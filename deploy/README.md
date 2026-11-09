# Deploy on Raspberry Pi (`/usr/local`)

## Layout

```text
/usr/local/lib/gira-ble-api/           # git checkout / released tree
/usr/local/lib/gira-ble-api/.venv/     # python3 -m venv && pip install -e .
/usr/local/etc/gira-ble-api/config.yaml
/etc/systemd/system/gira-ble-api.service
```

## One-time setup

```bash
sudo mkdir -p /usr/local/lib /usr/local/etc/gira-ble-api
sudo useradd --system --home /usr/local/lib/gira-ble-api --shell /usr/sbin/nologin gira-ble
sudo usermod -aG bluetooth gira-ble

# prefer git clone so gira-ble-api-update can fetch later
sudo git clone https://github.com/grindsa/gira-ble-api.git /usr/local/lib/gira-ble-api
sudo chown -R gira-ble:gira-ble /usr/local/lib/gira-ble-api /usr/local/etc/gira-ble-api
sudo ln -sfn /usr/local/lib/gira-ble-api/deploy/gira-ble-api-update \
  /usr/local/bin/gira-ble-api-update

sudo -u gira-ble -H bash -lc '
  cd /usr/local/lib/gira-ble-api
  python3 -m venv .venv
  .venv/bin/pip install -U pip setuptools wheel
  .venv/bin/pip install -e .
'

# config: re-scan on the Pi for classic MACs (Mac UUIDs will not work)
sudo -u gira-ble /usr/local/lib/gira-ble-api/.venv/bin/gira-ble-api scan
sudo cp config.example.yaml /usr/local/etc/gira-ble-api/config.yaml
sudo edit /usr/local/etc/gira-ble-api/config.yaml

sudo cp deploy/gira-ble-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gira-ble-api
sudo systemctl status gira-ble-api
journalctl -u gira-ble-api -f
```

## First-time BLE pairing (BlueZ / Pi)

**Recommended:** [`gira-ble-pair-agent`](gira-ble-pair-agent) — registers a BlueZ
`DisplayYesNo` agent, removes any stale device cache entry, discovers the MAC,
auto-confirms User Confirm / passkey, and calls async `Pair()`.

Plain `bluetoothctl` with `agent NoInputNoOutput` often fails with
`AuthenticationCanceled`. Many Pi BlueZ builds also lack
`btmgmt user-confirm-reply`. Do **not** run two `bluetoothctl` sessions
(scan in one, pair in another) — that frequently cancels auth.

### One-shot (reliable)

```bash
sudo apt install -y python3-dbus python3-gi
sudo ln -sfn /usr/local/lib/gira-ble-api/deploy/gira-ble-pair-agent \
  /usr/local/bin/gira-ble-pair-agent

sudo systemctl stop gira-ble-api

# Device in pairing mode (thermostat BT icon / cover blue LED blinking).
# Stand close — RSSI should be better than about -80 (worse than -90 is flaky).
sudo gira-ble-pair-agent -s 40 AA:BB:CC:DD:EE:FF
```

Success looks like:

```text
Found AA:BB:CC:DD:EE:FF … RSSI=-65
Calling async Pair() …
AUTO-CONFIRM …          # optional; some units bond without this line
Pair() completed
Result: Paired=True Bonded=True …
OK: …
```

Verify and restart:

```bash
bluetoothctl info AA:BB:CC:DD:EE:FF   # Paired: yes
sudo systemctl start gira-ble-api
# then POST /thermostats/…/setpoint or /covers/…/command
```

Clear a bad bond before retrying:

```bash
sudo bluetoothctl remove AA:BB:CC:DD:EE:FF
```

### Manual fallback

Prefer `gira-ble-pair-agent`. If you must use `bluetoothctl`, use **one**
session only (do not run a second `bluetoothctl` for scanning).

```bash
sudo systemctl stop gira-ble-api
sudo bluetoothctl remove AA:BB:CC:DD:EE:FF   # optional; clear bad bond
sudo bluetoothctl
```

Inside `bluetoothctl` (device already in pairing mode, stay close):

```text
power on
pairable on
agent off
agent DisplayYesNo
default-agent
scan on
devices
pair AA:BB:CC:DD:EE:FF
```

Wait for a line like `[agent] Confirm passkey 000000 (yes/no):`, then type
`yes` **there** (not at the normal `[bluetoothctl]>` prompt — that prints
`Invalid command in menu main: yes`). Then:

```text
trust AA:BB:CC:DD:EE:FF
info AA:BB:CC:DD:EE:FF
scan off
quit
```

Confirm `Paired: yes` / `Bonded: yes`, then `sudo systemctl start gira-ble-api`.

## Updates

Prefer a git checkout at `/usr/local/lib/gira-ble-api` (not a plain rsync copy):

```bash
sudo git clone https://github.com/grindsa/gira-ble-api.git /usr/local/lib/gira-ble-api
# then create venv / config / enable unit as above
```

Link the update helper:

```bash
sudo ln -sfn /usr/local/lib/gira-ble-api/deploy/gira-ble-api-update \
  /usr/local/bin/gira-ble-api-update
```

Then anytime:

```bash
sudo gira-ble-api-update              # fetch origin/main, reinstall, restart
sudo gira-ble-api-update --branch main
sudo gira-ble-api-update --dry-run
```

The script:

1. `git fetch` from `https://github.com/grindsa/gira-ble-api`
2. Hard-resets the deploy tree to `origin/<branch>` (keeps `.venv`; does **not** touch `/usr/local/etc/gira-ble-api/config.yaml`)
3. `pip install -e .` in the venv
4. Refreshes the systemd unit if `deploy/gira-ble-api.service` changed
5. `systemctl restart gira-ble-api`
