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

`AuthenticationCanceled` from Bleak usually means BlueZ had no pairing agent.
Bond each thermostat once while it is in **pairing mode**.

Helper script (MAC only):

```bash
sudo ln -sfn /usr/local/lib/gira-ble-api/deploy/gira-ble-pair \
  /usr/local/bin/gira-ble-pair

# 1) Thermostat: menu → Bluetooth → YES (icon blinks)
# 2) Pi:
sudo gira-ble-pair C7:F5:40:A6:81:66
```

Manual equivalent:

```bash
sudo bluetoothctl
power on
agent NoInputNoOutput
default-agent
scan on
pair C7:F5:40:A6:81:66
trust C7:F5:40:A6:81:66
connect C7:F5:40:A6:81:66
quit
```

Clear a bad bond: `sudo bluetoothctl remove C7:F5:40:A6:81:66`  
Then retry the API setpoint (pairing mode usually not needed after a successful bond).

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
