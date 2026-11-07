"""CLI entrypoint: load config, start Uvicorn + BLE scanner."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from gira_ble_api.config import load_config


def _default_config_path() -> Path:
    cwd = Path.cwd() / "config.yaml"
    if cwd.is_file():
        return cwd
    example = Path.cwd() / "config.example.yaml"
    return example


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gira-ble-api",
        description="REST API for Gira System 3000 Bluetooth thermostats",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="Path to config.yaml (default: ./config.yaml or config.example.yaml)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Override bind host from config",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override bind port from config",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging (includes raw hex ads/commands)",
    )
    parser.add_argument(
        "--no-ble",
        action="store_true",
        help="Start HTTP only (no scanner / no GATT) — for smoke tests",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    config_path = args.config or _default_config_path()
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        logging.error(
            "No config found at %s. Copy config.example.yaml to config.yaml "
            "and set thermostat MAC addresses.",
            config_path,
        )
        sys.exit(1)
    except Exception as exc:
        logging.error("Failed to load config %s: %s", config_path, exc)
        sys.exit(1)

    host = args.host or config.host
    port = args.port or config.port

    logging.info(
        "Loaded %s (%d thermostat(s)); binding %s:%d",
        config_path,
        len(config.thermostats),
        host,
        port,
    )
    if not args.no_ble and not config.thermostats:
        logging.warning("No thermostats configured — scanner will stay idle")

    # Import here so --help is fast and config errors are clear first.
    from gira_ble_api.api import create_app

    app = create_app(config, enable_ble=not args.no_ble)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
