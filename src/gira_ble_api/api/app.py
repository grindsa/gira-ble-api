"""FastAPI application factory and thermostat routes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from gira_ble_api.ble.client import BleClient, BleCommandError
from gira_ble_api.ble.scanner import BleScanner
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
    clients: dict[str, BleClient] = {
        t.id: BleClient(
            t.mac,
            timeout_s=config.ble_timeout_s,
            idle_disconnect_s=config.idle_disconnect_s,
        )
        for t in config.thermostats
    }
    scanner: BleScanner | None = None

    def on_ad(mac: str, update: Any, rssi: int | None) -> None:
        store.apply_advertisement(mac, update, rssi)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal scanner
        if enable_ble and config.thermostats:
            scanner = BleScanner(
                {t.mac for t in config.thermostats},
                on_advertisement=on_ad,
            )
            try:
                await scanner.start()
            except Exception:
                logger.exception(
                    "Failed to start BLE scanner — API will still serve "
                    "configured devices without live ads"
                )
                scanner = None
        yield
        if scanner is not None:
            await scanner.stop()
        for client in clients.values():
            await client.close()

    app = FastAPI(
        title="gira-ble-api",
        version="0.1.0",
        description="REST API for Gira System 3000 Bluetooth thermostats",
        lifespan=lifespan,
    )
    # Available before lifespan (TestClient / import-time) and during runtime.
    app.state.store = store
    app.state.config = config
    app.state.clients = clients

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/thermostats")
    async def list_thermostats(request: Request) -> list[dict]:
        return request.app.state.store.list()

    @app.get("/thermostats/{thermostat_id}")
    async def get_thermostat(thermostat_id: str, request: Request) -> dict:
        state = request.app.state.store.get(thermostat_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Unknown thermostat id: {thermostat_id}")
        return state

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
        clients_map: dict[str, BleClient] = request.app.state.clients

        if store.get(thermostat_id) is None:
            raise HTTPException(
                status_code=404,
                detail={"error": f"Unknown thermostat id: {thermostat_id}", "code": "not_found"},
            )

        temp_c = clamp_setpoint(body.celsius)
        if abs(temp_c - body.celsius) > 0.01:
            logger.info(
                "Clamped setpoint for %s from %.2f to %.2f",
                thermostat_id,
                body.celsius,
                temp_c,
            )

        client = clients_map[thermostat_id]
        command = build_setpoint_command(temp_c)
        logger.info(
            "Setpoint %s → %.1f°C cmd=%s",
            thermostat_id,
            temp_c,
            command.hex(),
        )

        try:
            await client.write(command)
        except BleCommandError as exc:
            store.set_error(thermostat_id, str(exc))
            status = 504 if exc.code == "ble_timeout" else 502
            if exc.code == "not_paired":
                status = 503
            raise HTTPException(
                status_code=status,
                detail={"error": str(exc), "code": exc.code},
            ) from exc

        store.set_setpoint_optimistic(thermostat_id, temp_c)
        state = store.get(thermostat_id)
        assert state is not None
        return state

    return app
