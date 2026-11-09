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

Gira thermostats/covers request **User Confirm** (often passkey `000000`).
`agent NoInputNoOutput` → `AuthenticationCanceled`. Prefer the helper script
(drives `bluetoothctl` + `expect` and auto-sends `yes`).

Many Pi BlueZ builds **do not** have `btmgmt user-confirm-reply`
(`Invalid command in menu mgmt`) — do not use that one-liner.

```bash
sudo apt install -y expect   # once
sudo ln -sfn /usr/local/lib/gira-ble-api/deploy/gira-ble-pair \
  /usr/local/bin/gira-ble-pair

# 1) Device: pairing mode (thermostat BT icon / cover blue LED blinking)
# 2) Pi (press Enter as soon as the LED blinks):
sudo gira-ble-pair C7:F5:40:A6:81:66
sudo gira-ble-pair -s 30 C7:F5:40:A6:81:66   # longer scan window
```

If `bluetoothctl` fails with `AuthenticationCanceled` and never shows
`[agent] Confirm passkey`, use the D-Bus auto-confirm agent (recommended on
Pi). **Do not** run two `bluetoothctl` sessions (scan+pair) — that often
cancels auth.

```bash
sudo apt install -y python3-dbus python3-gi
sudo ln -sfn /usr/local/lib/gira-ble-api/deploy/gira-ble-pair-agent \
  /usr/local/bin/gira-ble-pair-agent

# Terminal 1:
sudo systemctl stop gira-ble-api
sudo gira-ble-pair-agent
# leave running — should print "Agent registered"

# Terminal 2 (device LED blinking):
sudo bluetoothctl remove C7:F5:40:A6:81:66
sudo bluetoothctl
power on
pairable on
scan on
# wait until `devices` shows the MAC, then:
pair C7:F5:40:A6:81:66
trust C7:F5:40:A6:81:66
info C7:F5:40:A6:81:66
# expect Paired: yes — Terminal 1 should log AUTO-CONFIRM
quit
```

To watch for a MAC without a second `bluetoothctl scan` (poll only):

```bash
MAC=C7:F5:40:A6:81:66
watch -n1 "bluetoothctl devices | grep -i $MAC || true"
```

Clear a bad bond: `sudo bluetoothctl remove C7:F5:40:A6:81:66`  
Then retry the API command (pairing mode usually not needed after a successful bond).

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
