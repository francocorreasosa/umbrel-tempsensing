#!/bin/sh
set -eu
image=${1:-tempsensing:test}
volume="tempsensing-test-$$"
docker volume create "$volume" >/dev/null
trap 'docker volume rm "$volume" >/dev/null' EXIT
docker run --rm --user 0:0 -v "$volume:/data" "$image" chown 1000:1000 /data
# The web process creates the DB with its real UID and dropped capabilities.
docker run --rm --cap-drop ALL --security-opt no-new-privileges -v "$volume:/data" "$image" \
  python -c 'from tempsensing import db; db.init(); db.discover("test", "LYWSD03MMC", -60)'
# The root BlueZ worker must be able to write through the shared GID.
docker run --rm --user 0:1000 --cap-drop ALL --security-opt no-new-privileges -v "$volume:/data" "$image" \
  python -c 'from tempsensing import db; db.init(); db.record("test", dict(temperature_c=23.45, humidity_percent=50, battery_voltage=3.0))'
# The web process must still read AND write after the worker's connection closes.
docker run --rm --cap-drop ALL --security-opt no-new-privileges -v "$volume:/data" "$image" \
  python -c 'from tempsensing.web import create_app; c=create_app().test_client(); assert c.get("/api/status").json["sensors"][0]["temperature_c"] == 23.45; assert c.post("/api/settings", json=dict(interval=60)).status_code == 200; print("Container ownership and persistence checks passed")'
