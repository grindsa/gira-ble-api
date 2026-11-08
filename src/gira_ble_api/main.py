"""CLI entrypoint: serve API, or scan for Gira BLE devices."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import uvicorn

from gira_ble_api.config import load_config

_SUBCOMMANDS = frozenset({"serve", "scan"})


def _default_config_path() -> Path:
    cwd = Path.cwd() / "config.yaml"
    if cwd.is_file():
        return cwd
    return Path.cwd() / "config.example.yaml"


def _with_default_serve(argv: list[str]) -> list[str]:
    """Insert `serve` when the user omitted the subcommand.

    Examples that should become serve:
      gira-ble-api
      gira-ble-api -c config.yaml
      gira-ble-api -v --no-ble

    Examples left alone:
      gira-ble-api scan
      gira-ble-api -v scan --seconds 20
      gira-ble-api serve -c config.yaml
    """
    if not argv:
        return ["serve"]
    if argv[0] in _SUBCOMMANDS or argv[0] in {"-h", "--help"}:
        return argv

    # Already has a subcommand after optional global flags.
    for token in argv:
        if token in _SUBCOMMANDS:
            return argv

    # Root parser currently only owns -v/--verbose; insert serve after those.
    i = 0
    while i < len(argv) and argv[i] in {"-v", "--verbose"}:
        i += 1
    return [*argv[:i], "serve", *argv[i:]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gira-ble-api",
        description="REST API / CLI for Gira System 3000 Bluetooth thermostats and covers",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging (includes raw hex ads/commands)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the REST API (default)")
    serve.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="Path to config.yaml (default: ./config.yaml or config.example.yaml)",
    )
    serve.add_argument("--host", default=None, help="Override bind host from config")
    serve.add_argument("--port", type=int, default=None, help="Override bind port")
    serve.add_argument(
        "--no-ble",
        action="store_true",
        help="Start HTTP only (no scanner / no GATT) — for smoke tests",
    )

    scan = sub.add_parser(
        "scan",
        help="Discover nearby Gira BLE devices (no config required)",
    )
    scan.add_argument(
        "-s",
        "--seconds",
        type=float,
        default=15.0,
        help="How long to listen for advertisements (default: 15)",
    )
    scan.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of a table",
    )

    return parser


def _cmd_scan(args: argparse.Namespace) -> int:
    from gira_ble_api.ble.discover import discover_gira_devices, format_discovery_table

    try:
        devices = asyncio.run(discover_gira_devices(seconds=args.seconds))
    except Exception as exc:
        logging.error("Scan failed: %s", exc)
        return 1

    if args.json:
        print(json.dumps([d.to_dict() for d in devices], indent=2))
    else:
        print(format_discovery_table(devices))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    config_path = args.config or _default_config_path()
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        logging.error(
            "No config found at %s. Copy config.example.yaml to config.yaml "
            "and set device MAC addresses. Tip: run `gira-ble-api scan` first.",
            config_path,
        )
        return 1
    except Exception as exc:
        logging.error("Failed to load config %s: %s", config_path, exc)
        return 1

    host = args.host or config.host
    port = args.port or config.port

    logging.info(
        "Loaded %s (%d thermostat(s), %d cover(s)); binding %s:%d",
        config_path,
        len(config.thermostats),
        len(config.covers),
        host,
        port,
    )
    if not args.no_ble and not config.thermostats and not config.covers:
        logging.warning("No devices configured — scanner will stay idle")

    from gira_ble_api.api import create_app

    app = create_app(config, enable_ble=not args.no_ble)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> None:
    raw = _with_default_serve(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(raw)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "scan":
        raise SystemExit(_cmd_scan(args))
    raise SystemExit(_cmd_serve(args))


if __name__ == "__main__":
    main()
