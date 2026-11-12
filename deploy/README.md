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

## BLE watchdog (cron)

Recovers a dead BlueZ adapter (powered-off, Realtek `RTL: hw err`, HCI
`tx timeout` / `Resetting usb device`, etc.) and restarts `gira-ble-api`.
Runs every 15 minutes from `/etc/cron.d`. Journal hits alone trigger recovery
even when the adapter looks `Powered: yes` again after a USB reset.

```bash
sudo ln -sfn /usr/local/lib/gira-ble-api/deploy/gira-ble-bt-watchdog \
  /usr/local/bin/gira-ble-bt-watchdog
sudo cp /usr/local/lib/gira-ble-api/deploy/gira-ble-bt-watchdog.cron \
  /etc/cron.d/gira-ble-bt-watchdog
sudo chmod 644 /etc/cron.d/gira-ble-bt-watchdog

# optional WhatsApp (same simple_send API as tipp_game)
sudo -u gira-ble /usr/local/lib/gira-ble-api/.venv/bin/pip install wa_hack_cli
sudo edit /usr/local/etc/gira-ble-api/config.yaml   # notify.whatsapp.enabled: true
```

Config keys (ignored by the API process itself):

```yaml
watchdog:
  journal_lookback_min: 20
  rate_limit_min: 14
  adapter_wait_s: 20
notify:
  whatsapp:
    enabled: true
    server: "192.168.x.x"
    port: 9009
    to: "4917…"
```

Usage:

```bash
sudo gira-ble-bt-watchdog              # check; recover only if needed
sudo gira-ble-bt-watchdog --hard-reset # force recovery + notify
sudo gira-ble-bt-watchdog --dry-run -v
journalctl -t gira-ble-bt-watchdog -n 50   # if logger used; else cron mail / syslog
grep gira-ble-bt-watchdog /var/log/syslog | tail
```

`--hard-reset` always runs the recovery sequence (rfkill / power on /
`systemctl restart bluetooth` if still down / `systemctl restart gira-ble-api`)
and sends a WhatsApp message when notify is enabled. Cron runs are rate-limited
so a flapping adapter does not restart forever.

Also recommended on the Pi:

```bash
# persist journals across reboot (so RTL crash lines survive)
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
# set Storage=persistent in /etc/systemd/journald.conf, then:
sudo systemctl restart systemd-journald

# auto-power adapters after bluetoothd restart
sudo sed -i 's/^#AutoEnable=true/AutoEnable=true/' /etc/bluetooth/main.conf
sudo systemctl restart bluetooth
```

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
