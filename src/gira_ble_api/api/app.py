"""FastAPI application factory and thermostat routes."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from gira_ble_api.api.auth import BearerTokenMiddleware
from gira_ble_api.ble.client import BleCommandError
from gira_ble_api.ble.controller import BleController
from gira_ble_api.ble.pairing import paired_map_async
from gira_ble_api.config import AppConfig
from gira_ble_api.protocol import build_setpoint_command
from gira_ble_api.protocol.temp import clamp_setpoint
from gira_ble_api.state import DeviceStore

logger = logging.getLogger(__name__)


class SetpointBody(BaseModel):
    celsius: float = Field(..., description="Target temperature in °C")


class ErrorBody(BaseModel):
    error: str
    code: str | None = None


def create_app(
    config: AppConfig,
    *,
    enable_ble: bool = True,
) -> FastAPI:
    """Build the API. enable_ble=False is useful for unit tests without hardware."""
    store = DeviceStore.from_config(
        config.thermostats,
        online_timeout_s=config.online_timeout_s,
    )
    controller: BleController | None = None

    def on_ad(mac: str, update: Any, rssi: int | None) -> None:
        store.apply_advertisement(mac, update, rssi)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal controller
        if enable_ble and config.thermostats:
            controller = BleController(
                {t.mac for t in config.thermostats},
                on_advertisement=on_ad,
                ble_timeout_s=max(config.ble_timeout_s, 30.0),
            )
            app.state.controller = controller
            try:
                await controller.start()
            except Exception:
                logger.exception(
                    "Failed to start BLE scanner — API will still serve "
                    "configured devices; setpoint may still work"
                )
        yield
        if controller is not None:
            await controller.stop()

    app = FastAPI(
        title="gira-ble-api",
        version="0.1.0",
        description="REST API for Gira System 3000 Bluetooth thermostats",
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.config = config
    app.state.controller = controller

    if config.api_tokens:
        app.add_middleware(BearerTokenMiddleware, tokens=config.api_tokens)
        logger.info(
            "API auth enabled (%d token(s)); /health remains open",
            len(config.api_tokens),
        )
    else:
        logger.info("API auth disabled (no api_tokens in config)")

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/discover")
    async def discover(seconds: float = 10.0) -> dict:
        """Listen for nearby Gira ads and return addresses for config."""
        if not enable_ble:
            raise HTTPException(
                status_code=503,
                detail={"error": "BLE disabled (--no-ble)", "code": "ble_disabled"},
            )
        secs = max(1.0, min(float(seconds), 60.0))
        from gira_ble_api.ble.discover import discover_gira_devices

        ctrl: BleController | None = app.state.controller
        try:
            # Avoid fighting the background scanner on macOS.
            if ctrl is not None:
                await ctrl.stop()
            devices = await discover_gira_devices(seconds=secs)
        except Exception as exc:
            logger.exception("discover failed")
            raise HTTPException(
                status_code=502,
                detail={"error": str(exc), "code": "ble_error"},
            ) from exc
        finally:
            if ctrl is not None:
                try:
                    await ctrl.start()
                except Exception:
                    logger.exception("failed to resume scanner after discover")
        return {
            "seconds": secs,
            "devices": [d.to_dict() for d in devices],
        }

    @app.get("/thermostats")
    async def list_thermostats(request: Request) -> list[dict]:
        store: DeviceStore = request.app.state.store
        rows = store.list()
        paired = await paired_map_async([row["mac"] for row in rows])
        return store.list(paired_by_mac=paired)

    @app.get("/thermostats/{thermostat_id}")
    async def get_thermostat(thermostat_id: str, request: Request) -> dict:
        store: DeviceStore = request.app.state.store
        state = store.get(thermostat_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Unknown thermostat id: {thermostat_id}")
        paired = await paired_map_async([state["mac"]])
        return store.get(thermostat_id, paired=paired.get(state["mac"])) or state

    @app.post(
        "/thermostats/{thermostat_id}/setpoint",
        responses={
            400: {"model": ErrorBody},
            404: {"model": ErrorBody},
            504: {"model": ErrorBody},
            502: {"model": ErrorBody},
        },
    )
    async def set_setpoint(
        thermostat_id: str,
        body: SetpointBody,
        request: Request,
    ) -> dict:
        store: DeviceStore = request.app.state.store
        ctrl: BleController | None = request.app.state.controller

        state = store.get(thermostat_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail={"error": f"Unknown thermostat id: {thermostat_id}", "code": "not_found"},
            )
        if ctrl is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "BLE not available", "code": "ble_disabled"},
            )

        temp_c = clamp_setpoint(body.celsius)
        if abs(temp_c - body.celsius) > 0.01:
            logger.info(
                "Clamped setpoint for %s from %.2f to %.2f",
                thermostat_id,
                body.celsius,
                temp_c,
            )

        command = build_setpoint_command(temp_c)
        logger.info(
            "Setpoint %s → %.1f°C cmd=%s",
            thermostat_id,
            temp_c,
            command.hex(),
        )
        if sys.platform == "darwin":
            logger.info(
                "macOS: if this is the first write, enable pairing mode on the "
                "device and accept the system Bluetooth pairing popup"
            )

        try:
            await ctrl.write_command(state["mac"], command)
        except BleCommandError as exc:
            store.set_error(thermostat_id, str(exc))
            status = 504 if exc.code in {"ble_timeout", "not_found"} else 502
            if exc.code == "not_paired":
                status = 503
            raise HTTPException(
                status_code=status,
                detail={"error": str(exc), "code": exc.code},
            ) from exc

        store.set_setpoint_optimistic(thermostat_id, temp_c)
        paired = await paired_map_async([state["mac"]])
        updated = store.get(thermostat_id, paired=paired.get(state["mac"]))
        assert updated is not None
        return updated

    return app
