import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def database():
    path = Path(os.environ.get("DATA_DIR", "data"))
    path.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path / "sensors.sqlite3", timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init():
    # Both processes share GID 1000; SQLite's WAL/SHM inherit the database mode.
    os.umask(0o002)
    with database() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sensors (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, model TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0, rssi INTEGER,
                discovered_at REAL NOT NULL, last_attempt REAL, last_success REAL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY, sensor_id TEXT NOT NULL REFERENCES sensors(id),
                timestamp REAL NOT NULL, temperature_c REAL NOT NULL,
                humidity_percent REAL NOT NULL, battery_voltage REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS readings_sensor_time ON readings(sensor_id, timestamp);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO settings VALUES ('interval', '300');
            INSERT OR IGNORE INTO settings VALUES ('scan_requested', '1');
            INSERT OR IGNORE INTO settings VALUES ('scan_state', 'pending');
        """)


def get_settings():
    with database() as conn:
        return dict(conn.execute("SELECT key, value FROM settings"))


def set_settings(**values):
    with database() as conn:
        conn.executemany("INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         [(key, str(value)) for key, value in values.items()])


def discover(address, model, rssi):
    with database() as conn:
        conn.execute("""INSERT INTO sensors (id, name, model, rssi, discovered_at)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET
            model=excluded.model, rssi=excluded.rssi, discovered_at=excluded.discovered_at""",
                     (address, f"Sensor {address[-6:]}", model, rssi, time.time()))


def record(address, reading):
    now = time.time()
    with database() as conn:
        conn.execute("INSERT INTO readings(sensor_id, timestamp, temperature_c, humidity_percent, battery_voltage) VALUES (?, ?, ?, ?, ?)",
                     (address, now, reading["temperature_c"], reading["humidity_percent"], reading["battery_voltage"]))
        conn.execute("UPDATE sensors SET last_success=?, error=NULL WHERE id=?", (now, address))
