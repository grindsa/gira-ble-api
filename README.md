# gira-ble-api

Standalone Python service that talks to **Gira System 3000** Bluetooth devices
(room temperature controller BT **5394xx** / e.g. **539403**, and cover/timer BT
**5367xx** / e.g. **536727**) and exposes a small REST API.

This is **not** a Home Assistant integration. It uses the host Bluetooth adapter
via [Bleak](https://github.com/hbldh/bleak) (macOS CoreBluetooth now; Linux BlueZ
on a Raspberry Pi later). Primary consumer: a separate Next.js dashboard.

```
Gira 539403 / 536727  ←BLE→  gira-ble-api (Bleak)  ←HTTP REST→  clients (curl / dashboard)
```

## Features (v1)

- Passive scan of Gira manufacturer ads (company id **1412**) for live
  `temperature_c` / `setpoint_c` and cover `position_pct`
- `heating_active` via short GATT notify (property `0xF8`); optional background
  poll when `heating_poll_s > 0`, or on-demand with `GET ...?refresh=1`
- `POST .../setpoint` and `POST .../covers/{id}/command` via short-lived GATT
  write (lazy pair, idle disconnect)
- YAML-configured thermostats and covers; binds to `127.0.0.1:8787` by default
- Pure `protocol/` package (no Bleak/FastAPI) with unit tests — reusable as a
  reference for a future ESP32 firmware port

## Non-goals

- No Home Assistant / ESPHome bluetooth_proxy from this process
- No dashboard UI in this repo
- Cover timer/astro programs, slat tilt, dimming/switch inserts, sensors: not yet
- Auth is optional Bearer tokens (LAN-only / reverse-proxy later — see Security)

## Quick start (macOS)

```bash
cd gira-ble-api
# Python 3.11+ required. macOS system python3 is often 3.9 — use Homebrew:
#   brew install python@3.12
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
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
curl -s http://127.0.0.1:8787/covers | jq
```

**Bluetooth permission:** the first time you run the scanner, macOS may prompt
for Bluetooth access for Terminal / your IDE. Allow it, or grant Bluetooth under
*System Settings → Privacy & Security → Bluetooth*.

**Do not run this in Docker on Mac** — there is no BLE adapter passthrough.

### Finding the MAC address (built-in scan)

You do **not** need a phone app. Use the host adapter:

```bash
# Listen ~15s for Gira manufacturer ads (company id 1412)
gira-ble-api scan

# Longer window / machine-readable
gira-ble-api scan --seconds 30 --json
```

1. Stand near the thermostat (or briefly press pairing so it advertises).
2. Run `gira-ble-api scan` — copy the `ADDRESS` column into `config.yaml`
   as `mac: "…"`.
3. Thermostats that already broadcast temp/setpoint show those values and a
   `thermostat` hint; strongest RSSI is listed first.

**Which UUID is which room?** Easiest: set a distinctive setpoint on the
physical unit (e.g. **7.5 °C**), run `scan`, and match `SETPOINT°C`.
Alternatives: match `TEMP°C` to the display, or walk up and pick the
strongest RSSI.

While the API is running you can also call `GET /discover?seconds=10`
(blocks until the window ends). Prefer the CLI when possible — on macOS only
one process should drive discovery at a time.

On some macOS setups CoreBluetooth exposes a UUID-style identifier instead of a
classic MAC — paste whatever the scanner prints; the service normalizes
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
covers:
  - id: living_blind
    name: Wohnzimmer Jalousie
    mac: "11:22:33:44:55:66"
```

Ids and MAC addresses must be unique across thermostats and covers.

| Key | Meaning |
| --- | --- |
| `api_tokens` | Optional Bearer tokens (comma-string or list). Empty → no auth |
| `online_timeout_s` | No ad within this window → `online: false` |
| `ble_timeout_s` | Connect/write timeout for setpoint |
| `idle_disconnect_s` | Drop GATT after a successful write |
| `heating_poll_s` | Background GATT poll for `heating_active` (seconds). `0` / omit = off |
| `heating_listen_s` | Seconds to wait for heating notify after connect/write (default 25) |

## REST API

| Method | Path | Body | Result |
| --- | --- | --- | --- |
| `GET` | `/health` | — | `{ "ok": true }` |
| `GET` | `/discover?seconds=10` | — | Nearby Gira devices (blocks for the scan window) |
| `GET` | `/thermostats` | — | List of configured thermostats + last known state |
| `GET` | `/thermostats/{id}` | — | One thermostat |
| `GET` | `/thermostats/{id}?refresh=1` | — | Same, after a GATT refresh of `heating_active` |
| `POST` | `/thermostats/{id}/setpoint` | `{ "celsius": 21.0 }` | Updated state on success |
| `GET` | `/covers` | — | List of configured covers + last known state |
| `GET` | `/covers/{id}` | — | One cover |
| `POST` | `/covers/{id}/command` | `{ "action": "up"\|"down"\|"stop" }` **or** `{ "position": 0..100 }` | Updated state on success |

### Example responses

Thermostat (`GET /thermostats/{id}`):

```json
{
  "id": "living",
  "name": "Wohnzimmer",
  "mac": "AA:BB:CC:DD:EE:FF",
  "online": true,
  "paired": true,
  "temperature_c": 21.5,
  "setpoint_c": 20.0,
  "heating_active": false,
  "last_seen_at": "2026-11-09T13:20:00.123456+00:00",
  "updated_at": "2026-11-09T13:20:05.123456+00:00",
  "rssi": -62,
  "error": null
}
```

| Field | Meaning |
| --- | --- |
| `temperature_c` / `setpoint_c` | From BLE ads (null until first ad) |
| `heating_active` | GATT-only: `true` / `false`, or `null` until a status poll / setpoint write |
| `online` | Ad seen within `online_timeout_s` |
| `paired` | Host OS bond status (`true`/`false`, or `null` if unknown) |
| `last_seen_at` | Last BLE advertisement (null until first ad) |
| `updated_at` | Last local state change (ad, optimistic write, status poll, or error) |
| `error` | Last command/poll error string, else `null` |

Cover (`GET /covers/{id}`):

```json
{
  "id": "living_blind",
  "name": "Wohnzimmer Jalousie",
  "mac": "11:22:33:44:55:66",
  "online": true,
  "paired": true,
  "position_pct": 75,
  "last_seen_at": "2026-11-09T13:20:00.123456+00:00",
  "updated_at": "2026-11-09T13:20:00.123456+00:00",
  "rssi": -70,
  "error": null
}
```

`position_pct` is percent open (`0` = closed … `100` = open).

`paired` is the host OS bond status: BlueZ (`bluetoothctl`) on Linux/Pi,
`system_profiler` / IOBluetooth on macOS.

### Setpoint / pairing

Temperature / cover position are read from **passive advertisements** (no
pairing required). Commands need a **GATT connection** and a one-time OS bond.

#### Raspberry Pi / Linux (recommended): `gira-ble-pair-agent`

Gira units often need User Confirm during bonding. Plain `bluetoothctl` /
`NoInputNoOutput` frequently fails with `AuthenticationCanceled`. Use the
D-Bus agent that discovers the MAC, auto-confirms, and calls `Pair()`:

```bash
sudo apt install -y python3-dbus python3-gi
sudo ln -sfn /usr/local/lib/gira-ble-api/deploy/gira-ble-pair-agent \
  /usr/local/bin/gira-ble-pair-agent

sudo systemctl stop gira-ble-api

# Thermostat: menu → Bluetooth → YES (icon blinks)
# Cover: hold ↑+↓ until blue LED blinks
# Stand close (aim for RSSI better than about -80), then:
sudo gira-ble-pair-agent -s 40 AA:BB:CC:DD:EE:FF
```

Success looks like `Paired=True` / `Bonded=True` (optional `AUTO-CONFIRM` line).
Verify with `bluetoothctl info AA:BB:CC:DD:EE:FF`, then:

```bash
sudo systemctl start gira-ble-api
```

Weak RSSI (e.g. -95 or worse) makes bonding and later GATT writes unreliable —
move the Pi / dongle closer. Full notes: [`deploy/README.md`](deploy/README.md).

#### macOS

1. Put the device into **pairing mode**.
2. Send a command immediately (setpoint or cover command).
3. Accept the **system Bluetooth pairing popup** — Bleak cannot pair
   programmatically; the first encrypted GATT write triggers it.
4. Stay near the device; expect up to ~30–60s with retries.

After bonding, later commands usually work without pairing mode.

```bash
# Put device in pairing mode first (first time only)
# Add -H "Authorization: Bearer <token>" when api_tokens is configured
curl -s -X POST http://127.0.0.1:8787/thermostats/living/setpoint \
  -H 'Content-Type: application/json' \
  -d '{"celsius": 21.0}'

curl -s -X POST http://127.0.0.1:8787/covers/living_blind/command \
  -H 'Content-Type: application/json' \
  -d '{"action": "up"}'

curl -s -X POST http://127.0.0.1:8787/covers/living_blind/command \
  -H 'Content-Type: application/json' \
  -d '{"position": 50}'
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

Same code; Bleak uses BlueZ. Re-scan on the Pi for classic MACs (Mac UUIDs
do not transfer). Ready-made unit + `/usr/local` layout:

- [`deploy/gira-ble-api.service`](deploy/gira-ble-api.service)
- [`deploy/README.md`](deploy/README.md)

Bind to LAN only behind a firewall/reverse proxy if you leave the Pi exposed
(`host: 0.0.0.0` in config).

## Security

Optional Bearer tokens via `api_tokens` in config (omit/empty = open access):

```yaml
api_tokens: "dashboard-secret, laptop-curl"
```

```bash
curl -s -H "Authorization: Bearer dashboard-secret" http://127.0.0.1:8787/thermostats
```

`GET /health` stays open. Tokens are plaintext in config — use file mode `600`.
Still HTTP (sniffable on LAN); add HTTPS / reverse proxy / Tailscale when needed.

## Protocol notes

Shared:

- Manufacturer ID: **1412** (`0x0584`)
- GATT write characteristic: `97696341-F77A-43AE-8C35-09F0C5245308`

Thermostat:

- Actual temp ad prefix: `F7 01 41 01 FE 10 01` + u16 (dual-scale decode)
- Setpoint ad prefix: `F7 00 65 01 FF 10 01` + u16
- Heating active (GATT notify only): `F7 00 65 01 F8 10 01` + `00`/`01`
- Setpoint write: `F6 00 65 01 F5 10 01` + u16 with
  `raw = round((21 + °C) * 50 + 1000)`
- `heating_active` is not in advertisements; a GATT connect is required. Status
  polls re-write the known setpoint to provoke the `0xF8` notify.

Cover (object `0x0320`):

- Position ad prefix: `F7 03 20 01 F6 10 01` + PDT_SCALING byte
  (`0x00` = open / 100%, `0xFF` = closed / 0%; API exposes percent open)
- Move: `F6 03 20 01 FF 10 01` + `00` (up) / `01` (down)
- Stop: `F6 03 20 01 FD 10 01 00`
- Set position: `F6 03 20 01 FC 10 01` + raw byte

## Attribution

Protocol knowledge is reverse-engineered and shared by the community (MIT /
public discussion). This service reimplements parsing and commands cleanly and
does **not** vendor Home Assistant entity or config-flow code.

- [stho/gira-3000-bt](https://github.com/stho/gira-3000-bt) — thermostat climate + dual-scale decode (preferred)
- [stho/girea-system-3000](https://github.com/stho/girea-system-3000) — covers/shutters + `GIRA_SYSTEM_3000_BLUETOOTH.md`
- [HA community: Gira system 3000](https://community.home-assistant.io/t/gira-system-3000/490194) — advertisement layouts

## License

See [LICENSE](LICENSE). Protocol constants and encodings are independently
rewritten from public reverse-engineering notes.
