import csv
import io
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, abort, jsonify, request

from tempsensing import db

STATIC = Path(__file__).parent / "static"


def create_app():
    db.init()
    app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 16384

    @app.before_request
    def same_origin():
        if request.method == "POST":
            if not request.is_json:
                abort(415)
            if not isinstance(request.get_json(), dict):
                abort(400, "Se esperaba un objeto JSON")
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc != request.host:
                abort(403)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/status")
    def status():
        settings = db.get_settings()
        with db.database() as conn:
            rows = conn.execute("""SELECT s.*, r.temperature_c, r.humidity_percent, r.battery_voltage,
                r.timestamp FROM sensors s LEFT JOIN readings r ON r.id=(
                    SELECT id FROM readings WHERE sensor_id=s.id ORDER BY timestamp DESC, id DESC LIMIT 1
                ) ORDER BY s.enabled DESC, s.name""").fetchall()
        return jsonify(sensors=[dict(row) for row in rows], interval=int(settings["interval"]),
                       collector_online=time.time()-float(settings.get("heartbeat", 0)) < 100,
                       scan_state=settings.get("scan_state"), scan_error=settings.get("scan_error", ""),
                       scan_count=int(settings.get("scan_count", 0)),
                       active_sensor=settings.get("active_sensor", ""), now=time.time())

    @app.post("/api/scan")
    def scan():
        db.set_settings(scan_requested="1", scan_state="pending", scan_error="")
        return jsonify(ok=True), 202

    @app.post("/api/settings")
    def settings():
        value = request.get_json().get("interval")
        if type(value) is not int or not 60 <= value <= 3600:
            abort(400, "El intervalo debe estar entre 60 y 3600 segundos")
        db.set_settings(interval=value)
        return jsonify(ok=True)

    @app.post("/api/sensors/<address>")
    def sensor(address):
        body = request.get_json()
        name, enabled = body.get("name"), body.get("enabled")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or type(enabled) is not bool:
            abort(400, "Nombre o estado inválido")
        with db.database() as conn:
            existing = conn.execute("SELECT enabled FROM sensors WHERE id=?", (address,)).fetchone()
            if existing is None:
                abort(404)
            conn.execute("UPDATE sensors SET name=?, enabled=?, last_attempt=CASE WHEN enabled=0 AND ?=1 THEN NULL ELSE last_attempt END WHERE id=?",
                         (name.strip(), int(enabled), int(enabled), address))
        return jsonify(ok=True)

    def range_args():
        hours = request.args.get("hours", 24, type=int)
        if hours not in (1, 6, 24, 168, 720, 8760):
            abort(400, "Rango inválido")
        return hours, time.time() - hours * 3600

    @app.get("/api/history")
    def history():
        hours, since = range_args()
        bucket = max(60, hours * 3600 // 720)
        with db.database() as conn:
            rows = conn.execute("""SELECT sensor_id, AVG(timestamp) timestamp,
                AVG(temperature_c) temperature_c, AVG(humidity_percent) humidity_percent,
                MIN(temperature_c) min_temperature, MAX(temperature_c) max_temperature,
                COUNT(*) samples FROM readings WHERE timestamp >= ?
                GROUP BY sensor_id, CAST(timestamp / ? AS INTEGER) ORDER BY timestamp""", (since, bucket)).fetchall()
        return jsonify(points=[dict(row) for row in rows], bucket_seconds=bucket)

    @app.get("/api/export")
    def export():
        _, since = range_args()

        def generate():
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["timestamp_utc", "sensor_id", "name", "temperature_c", "humidity_percent", "battery_voltage"])
            yield output.getvalue()
            with db.database() as conn:
                for row in conn.execute("""SELECT r.timestamp, r.sensor_id, s.name, r.temperature_c,
                    r.humidity_percent, r.battery_voltage FROM readings r JOIN sensors s ON s.id=r.sensor_id
                    WHERE timestamp >= ? ORDER BY r.timestamp""", (since,)):
                    output.seek(0)
                    output.truncate(0)
                    name = row["name"]
                    if name.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
                        name = "'" + name
                    writer.writerow([datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat(),
                                     row["sensor_id"], name, row["temperature_c"], row["humidity_percent"], row["battery_voltage"]])
                    yield output.getvalue()
        return Response(generate(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=tempsensing.csv"})

    return app
