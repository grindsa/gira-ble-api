"""FastAPI application factory and device routes."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from gira_ble_api.api.auth import BearerTokenMiddleware
from gira_ble_api.ble.client import BleCommandError
from gira_ble_api.ble.controller import BleController
from gira_ble_api.ble.pairing import paired_map_async
from gira_ble_api.config import AppConfig
from gira_ble_api.protocol import (
    build_cover_move,
    build_cover_position,
    build_cover_stop,
    build_setpoint_command,
)
from gira_ble_api.protocol.cover import clamp_position_pct
from gira_ble_api.protocol.temp import clamp_setpoint
from gira_ble_api.state import DeviceStore

logger = logging.getLogger(__name__)


class SetpointBody(BaseModel):
    celsius: float = Field(..., description="Target temperature in °C")


class CoverCommandBody(BaseModel):
    action: Literal["up", "down", "stop"] | None = Field(
        default=None, description="Move up/down or stop"
    )
    position: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Absolute position percent open (0=closed, 100=open)",
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> CoverCommandBody:
        has_action = self.action is not None
        has_position = self.position is not None
        if has_action == has_position:
            raise ValueError("Provide exactly one of 'action' or 'position'")
        return self


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
        covers=config.covers,
        online_timeout_s=config.online_timeout_s,
    )
    controller: BleController | None = None
    watch_macs = {t.mac for t in config.thermostats} | {c.mac for c in config.covers}
    heating_poll_task: asyncio.Task[None] | None = None

    def on_ad(mac: str, update: Any, rssi: int | None) -> None:
        store.apply_advertisement(mac, update, rssi)

    async def _refresh_heating(thermostat_id: str) -> None:
        """One GATT status fetch for heating_active (may re-write known setpoint)."""
        assert controller is not None
        mac = store.get_mac(thermostat_id)
        if mac is None:
            raise BleCommandError(
                f"Unknown thermostat id: {thermostat_id}",
                code="not_found",
            )
        provoke = store.get_setpoint(thermostat_id)
        update = await controller.fetch_thermostat_status(
            mac, provoke_setpoint_c=provoke
        )
        store.apply_status_update(thermostat_id, update)

    async def _heating_poll_loop() -> None:
        interval = config.heating_poll_s
        gap_s = max(1.0, config.heating_poll_gap_s)
        settle_s = min(30.0, max(5.0, config.online_timeout_s / 4.0))
        logger.info(
            "Heating status background poll every %.0fs (%d thermostat(s)); "
            "settle %.0fs before first poll, %.0fs ad gap between devices",
            interval,
            len(config.thermostats),
            settle_s,
            gap_s,
        )
        # Let passive ads populate last_seen before the first scanner pause.
        await asyncio.sleep(settle_s)
        while True:
            if controller is not None:
                for thermo in config.thermostats:
                    try:
                        await _refresh_heating(thermo.id)
                        row = store.get(thermo.id)
                        heating = None if row is None else row.get("heating_active")
                        logger.info(
                            "Heating poll ok %s heating_active=%s",
                            thermo.id,
                            heating,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(
                            "Heating poll failed for %s: %s", thermo.id, exc
                        )
                    # Scanner is running again here — collect ads for siblings.
                    await asyncio.sleep(gap_s)
            await asyncio.sleep(interval)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal controller, heating_poll_task
        if enable_ble and watch_macs:
            controller = BleController(
                watch_macs,
                on_advertisement=on_ad,
                ble_timeout_s=max(config.ble_timeout_s, 30.0),
                heating_listen_s=config.heating_listen_s,
                on_scan_pause=store.begin_scan_pause,
                on_scan_resume=store.end_scan_pause,
            )
            app.state.controller = controller
            try:
                await controller.start()
            except Exception:
                logger.exception(
                    "Failed to start BLE scanner — API will still serve "
                    "configured devices; commands may still work"
                )
            if config.heating_poll_s > 0 and config.thermostats:
                heating_poll_task = asyncio.create_task(
                    _heating_poll_loop(), name="heating-poll"
                )
            else:
                logger.info(
                    "Heating background poll disabled "
                    "(set heating_poll_s > 0 in config to enable)"
                )
        yield
        if heating_poll_task is not None:
            heating_poll_task.cancel()
            try:
                await heating_poll_task
            except asyncio.CancelledError:
                pass
            heating_poll_task = None
        if controller is not None:
            await controller.stop()

    app = FastAPI(
        title="gira-ble-api",
        version="0.1.0",
        description="REST API for Gira System 3000 Bluetooth thermostats and covers",
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
        rows = store.list_thermostats()
        paired = await paired_map_async([row["mac"] for row in rows])
        return store.list_thermostats(paired_by_mac=paired)

    @app.get("/thermostats/{thermostat_id}")
    async def get_thermostat(
        thermostat_id: str,
        request: Request,
        refresh: bool = Query(
            False,
            description="If true, open a GATT session and refresh heating_active",
        ),
    ) -> dict:
        store: DeviceStore = request.app.state.store
        ctrl: BleController | None = request.app.state.controller
        state = store.get(thermostat_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Unknown thermostat id: {thermostat_id}")

        if refresh:
            if ctrl is None:
                raise HTTPException(
                    status_code=503,
                    detail={"error": "BLE not available", "code": "ble_disabled"},
                )
            try:
                await _refresh_heating(thermostat_id)
            except BleCommandError as exc:
                store.set_error(thermostat_id, str(exc))
                status = 504 if exc.code in {"ble_timeout", "not_found"} else 502
                if exc.code == "not_paired":
                    status = 503
                raise HTTPException(
                    status_code=status,
                    detail={"error": str(exc), "code": exc.code},
                ) from exc

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
            notify_update = await ctrl.write_command(state["mac"], command)
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
        store.apply_status_update(thermostat_id, notify_update)
        paired = await paired_map_async([state["mac"]])
        updated = store.get(thermostat_id, paired=paired.get(state["mac"]))
        assert updated is not None
        return updated

    @app.get("/covers")
    async def list_covers(request: Request) -> list[dict]:
        store: DeviceStore = request.app.state.store
        rows = store.list_covers()
        paired = await paired_map_async([row["mac"] for row in rows])
        return store.list_covers(paired_by_mac=paired)

    @app.get("/covers/{cover_id}")
    async def get_cover(cover_id: str, request: Request) -> dict:
        store: DeviceStore = request.app.state.store
        state = store.get_cover(cover_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Unknown cover id: {cover_id}")
        paired = await paired_map_async([state["mac"]])
        return store.get_cover(cover_id, paired=paired.get(state["mac"])) or state

    @app.post(
        "/covers/{cover_id}/command",
        responses={
            400: {"model": ErrorBody},
            404: {"model": ErrorBody},
            504: {"model": ErrorBody},
            502: {"model": ErrorBody},
        },
    )
    async def cover_command(
        cover_id: str,
        body: CoverCommandBody,
        request: Request,
    ) -> dict:
        store: DeviceStore = request.app.state.store
        ctrl: BleController | None = request.app.state.controller

        state = store.get_cover(cover_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail={"error": f"Unknown cover id: {cover_id}", "code": "not_found"},
            )
        if ctrl is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "BLE not available", "code": "ble_disabled"},
            )

        optimistic_position: int | None = None
        if body.action == "up":
            command = build_cover_move("up")
            optimistic_position = 100
            label = "up"
        elif body.action == "down":
            command = build_cover_move("down")
            optimistic_position = 0
            label = "down"
        elif body.action == "stop":
            command = build_cover_stop()
            label = "stop"
        else:
            assert body.position is not None
            optimistic_position = clamp_position_pct(body.position)
            command = build_cover_position(optimistic_position)
            label = f"position={optimistic_position}"

        logger.info("Cover %s → %s cmd=%s", cover_id, label, command.hex())
        if sys.platform == "darwin":
            logger.info(
                "macOS: if this is the first write, enable pairing mode on the "
                "device and accept the system Bluetooth pairing popup"
            )

        try:
            await ctrl.write_command(state["mac"], command)
        except BleCommandError as exc:
            store.set_cover_error(cover_id, str(exc))
            status = 504 if exc.code in {"ble_timeout", "not_found"} else 502
            if exc.code == "not_paired":
                status = 503
            raise HTTPException(
                status_code=status,
                detail={"error": str(exc), "code": exc.code},
            ) from exc

        if optimistic_position is not None:
            store.set_position_optimistic(cover_id, optimistic_position)
        paired = await paired_map_async([state["mac"]])
        updated = store.get_cover(cover_id, paired=paired.get(state["mac"]))
        assert updated is not None
        return updated

    return app
