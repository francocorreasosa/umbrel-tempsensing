# Tempsensing for Umbrel

Local temperature and humidity history for Xiaomi LYWSD03MMC Bluetooth sensors.
Tested sensor protocol: the stock `ebe0ccc1` GATT notification, carrying temperature,
humidity and battery voltage. Authenticated firmware and other models are not yet supported.

## Install on Umbrel

Add this Community App Store in **App Store → Community App Stores**:

```
https://github.com/francocorreasosa/umbrel-tempsensing
```

Install **Tempsensing**, open it, and choose **Gestionar sensores → Buscar por Bluetooth**.
Activate the sensors you own and give them room names. The host needs a working
Bluetooth adapter, BlueZ and its system D-Bus socket at `/run/dbus/system_bus_socket`.
The app does not change sensor firmware or require a Xiaomi account.

The package's `hooks/pre-start` raises existing Bluetooth adapters' runtime LE
supervision timeout to at least 6 seconds. Umbrel Home's 420 ms default caused
`Connection Failed to be Established (0x3e)` with these sensors in hardware testing.
This host hook runs before the containers and is reapplied on app/system startup;
it does not change `/etc/bluetooth/main.conf`, reset the radio, or reduce a higher
timeout. It requires the host's `/sys/kernel/debug/bluetooth/hci*/supervision_timeout`
files. If you manually power-cycle the adapter, restart Tempsensing to reapply it.

The default polling interval is five minutes. Each sensor is connected briefly,
one at a time; a failed reading is retried at the next interval. Actual intervals
can be longer when sensors take time to respond. More frequent connections can
use more battery. Close Xiaomi Home if it keeps a sensor connected elsewhere.

The interface includes temperature/humidity charts, stale-reading indicators,
per-sensor pause, room names and CSV export. Chart points are averages; CSV retains
individual readings. Pausing keeps history. Data older than 365 days is deleted daily.
Voltage is reported directly, without estimating battery percentage.

## Architecture

- `web`: Flask/Gunicorn on Umbrel's app network, behind its authenticated proxy.
- `collector`: Bleak worker using the host's BlueZ over D-Bus, with no web listener.
- `init_data`: sets the data directory owner once during startup.
- `${APP_DATA_DIR}/data/sensors.sqlite3`: shared SQLite database in WAL mode.

Both the worker and web service run as UID/GID 1000, with all Linux capabilities
dropped and `no-new-privileges`. Umbrel's BlueZ policy allows non-root calls to
`org.bluez`. Only the worker gets the host D-Bus mount. No privileged container or
Docker socket is required. The D-Bus mount allows calls to host services; it is not a Bluetooth-only
authorization boundary. Keep this app limited to trusted users of your Umbrel.

App authentication is provided by Umbrel; do not expose the web container directly
to the Internet. Back up the entire persistent data directory while the app is stopped
or use SQLite's backup API. Do not copy just the main database file during collection.

## Development on macOS

```sh
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/gunicorn 'tempsensing.web:create_app()' --bind 127.0.0.1:8765
# In a second terminal, with Bluetooth permission:
.venv/bin/python -m tempsensing.collector
```

Open http://localhost:8765. Data is stored in `data/`, or the directory set by
`DATA_DIR`. macOS discovers UUIDs; Linux discovers MAC addresses. Discover sensors
again on each host. `sensors.py scan` and `sensors.py read DEVICE_ID` are also available
for diagnostics. Only run one collector against a given adapter/database.

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check tempsensing/static/app.js
```

## Releases

GitHub Actions tests pushes and publishes `edge` from `main`. A `v0.1.0` tag
publishes the `0.1.0` image for `linux/amd64` and `linux/arm64` to GHCR. The container
package must be public so Umbrel can pull anonymously. Release images referenced
by the store are pinned by digest after publishing. Update the manifest version,
release notes and image references together for subsequent releases.

Packaging follows the [Umbrel Community App Store template](https://github.com/getumbrel/umbrel-community-app-store).
