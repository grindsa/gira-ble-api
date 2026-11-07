# gira-ble-api

Standalone Python service that talks to **Gira System 3000** Bluetooth devices
(especially the room temperature controller BT, article **5394xx** / e.g. **539403**)
and exposes a small REST API.

This is **not** a Home Assistant integration. It uses the host Bluetooth adapter
via [Bleak](https://github.com/hbldh/bleak) (macOS CoreBluetooth now; Linux BlueZ
on a Raspberry Pi later). Primary consumer: a separate Next.js dashboard.

```
Gira 539403  ←BLE→  gira-ble-api (Bleak)  ←HTTP REST→  clients (curl / dashboard)
```

## Features (v1)

- Passive scan of Gira manufacturer ads (company id **1412**) for live `temperature_c` / `setpoint_c`
- `POST .../setpoint` via short-lived GATT write (lazy pair, idle disconnect)
- YAML-configured thermostats; binds to `127.0.0.1:8787` by default
- Pure `protocol/` package (no Bleak/FastAPI) with unit tests — reusable as a
  reference for a future ESP32 firmware port

## Non-goals

- No Home Assistant / ESPHome bluetooth_proxy from this process
- No dashboard UI in this repo
- Shutters/sensors: protocol hooks only; not exposed in the REST API yet
- No auth (LAN-only / reverse-proxy later — see Security)

## Quick start (macOS)

```bash
cd gira-ble-api
# Python 3.11+ (Homebrew: brew install python@3.12)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp config.example.yaml config.yaml
# Edit config.yaml — set real MAC address(es)

gira-ble-api -c config.yaml
# or: python -m gira_ble_api.main -c config.yaml
```

Open another terminal:

```bash
curl -s http://127.0.0.1:8787/health
curl -s http://127.0.0.1:8787/thermostats | jq
```

**Bluetooth permission:** the first time you run the scanner, macOS may prompt
for Bluetooth access for Terminal / your IDE. Allow it, or grant Bluetooth under
*System Settings → Privacy & Security → Bluetooth*.

**Do not run this in Docker on Mac** — there is no BLE adapter passthrough.

### Finding the MAC address

1. Put the thermostat into advertising / pairing mode (see device instructions;
   usually a long-press of the pairing button on the front).
2. Scan with a phone app (**nRF Connect**, **LightBlue**) or a Mac BLE explorer.
3. Look for a Gira / System 3000 device; copy the Bluetooth address into
   `config.yaml` as `mac: "AA:BB:CC:DD:EE:FF"`.

On some macOS setups CoreBluetooth exposes a UUID-style identifier instead of a
classic MAC — paste whatever Bleak / the scanner shows; the service normalizes
colon-separated MACs when possible.

## Configuration

See [`config.example.yaml`](config.example.yaml):

```yaml
host: 127.0.0.1
port: 8787
online_timeout_s: 120
ble_timeout_s: 20
idle_disconnect_s: 5
thermostats:
  - id: living
    name: Wohnzimmer
    mac: "AA:BB:CC:DD:EE:FF"
```

| Key | Meaning |
| --- | --- |
| `online_timeout_s` | No ad within this window → `online: false` |
| `ble_timeout_s` | Connect/write timeout for setpoint |
| `idle_disconnect_s` | Drop GATT after a successful write |

## REST API

| Method | Path | Body | Result |
| --- | --- | --- | --- |
| `GET` | `/health` | — | `{ "ok": true }` |
| `GET` | `/thermostats` | — | List of configured devices + last known state |
| `GET` | `/thermostats/{id}` | — | One device |
| `POST` | `/thermostats/{id}/setpoint` | `{ "celsius": 21.0 }` | Updated state on success |

State fields: `id`, `name`, `mac`, `online`, `temperature_c`, `setpoint_c`,
`updated_at`, `rssi`, optional `error`.

### Setpoint / pairing

Temperature is read from **passive advertisements** (no pairing required).

Setting the setpoint requires a **GATT connection**. On **first use**, put the
thermostat into **pairing mode** while the API attempts the write (the service
retries within `ble_timeout_s`, default ~20s). After bonding, later setpoints
usually work without pairing mode.

```bash
# Put device in pairing mode first (first time only)
curl -s -X POST http://127.0.0.1:8787/thermostats/living/setpoint \
  -H 'Content-Type: application/json' \
  -d '{"celsius": 21.0}'
```

Failures return clear 4xx/5xx JSON (`detail.error`, `detail.code`) for timeout,
not paired, or other BLE errors. BLE is flaky — expect occasional retries.

Logging: `INFO` for commands; `-v` / `--verbose` enables `DEBUG` raw hex ads
and commands.

Smoke-test HTTP without BLE:

```bash
gira-ble-api -c config.yaml --no-ble
```

## Layout

```
src/gira_ble_api/
  protocol/   # parse ads, temp encode/decode, build commands (pure)
  ble/        # Bleak scanner + short-lived GATT client
  api/        # FastAPI routes
  config.py
  state.py
  main.py
tests/        # protocol (+ API) unit tests — no hardware required
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Raspberry Pi (follow-up)

Same code; Bleak uses BlueZ.

1. Enable Bluetooth (`sudo rfkill unblock bluetooth`), join the `bluetooth` group.
2. Use the same venv + `config.yaml`.
3. Optional systemd unit sketch:

```ini
[Unit]
Description=gira-ble-api
After=bluetooth.target network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/gira-ble-api
ExecStart=/home/pi/gira-ble-api/.venv/bin/gira-ble-api -c /home/pi/gira-ble-api/config.yaml
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Bind to LAN only behind a firewall/reverse proxy if you leave the Pi exposed.

## Security

v1 has **no authentication**. Default bind is localhost. For LAN access, put a
reverse proxy (or OS firewall) in front and add auth later.

## Protocol notes (thermostat)

- Manufacturer ID: **1412** (`0x0584`)
- Actual temp ad prefix: `F7 01 41 01 FE 10 01` + u16 (dual-scale decode)
- Setpoint ad prefix: `F7 00 65 01 FF 10 01` + u16
- Setpoint write: `F6 00 65 01 F5 10 01` + u16 with
  `raw = round((21 + °C) * 50 + 1000)`
- GATT write characteristic: `97696341-F77A-43AE-8C35-09F0C5245308`

## Attribution

Protocol knowledge is reverse-engineered and shared by the community (MIT /
public discussion). This service reimplements parsing and commands cleanly and
does **not** vendor Home Assistant entity or config-flow code.

- [stho/gira-3000-bt](https://github.com/stho/gira-3000-bt) — thermostat climate + dual-scale decode (preferred)
- [stho/girea-system-3000](https://github.com/stho/girea-system-3000) — shutters + `GIRA_SYSTEM_3000_BLUETOOTH.md`
- [HA community: Gira system 3000](https://community.home-assistant.io/t/gira-system-3000/490194) — advertisement layouts

## License

See [LICENSE](LICENSE). Protocol constants and encodings are independently
rewritten from public reverse-engineering notes.
