"""One collector process per Bluetooth adapter; short, sequential connections."""
import asyncio
import logging
import signal
import time

from bleak import BleakClient, BleakScanner

from sensors import DATA_UUID, decode
from tempsensing import db

log = logging.getLogger(__name__)
_scanner = None
_observed = {}


def sensor_model(device, adv):
    name = adv.local_name or device.name or ""
    if name.upper() == "LYWSD03MMC":
        return "LYWSD03MMC"
    # BlueZ may receive MiBeacon frames without a local-name scan response.
    # Product ID is little endian after the two frame-control bytes.
    frame = adv.service_data.get("0000fe95-0000-1000-8000-00805f9b34fb", b"")
    if len(frame) >= 5 and int.from_bytes(frame[2:4], "little") == 0x055B:
        return "LYWSD03MMC"
    return None


async def scan():
    db.set_settings(scan_state="scanning", scan_error="", scan_requested="0")
    try:
        if _scanner is None:
            raise RuntimeError("El escáner Bluetooth no está disponible")
        await asyncio.sleep(30)
        count = 0
        for device, adv, seen_at in list(_observed.values()):
            if time.time() - seen_at > 60:
                continue
            model = sensor_model(device, adv)
            if model:
                db.discover(device.address, model, adv.rssi)
                count += 1
        db.set_settings(scan_state="done", scan_finished=time.time(), scan_count=count)
    except Exception as error:
        log.exception("Bluetooth discovery failed")
        db.set_settings(scan_state="error", scan_error=f"{type(error).__name__}: {error}")


async def sample(address):
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    def notified(_, packet):
        if result.done():
            return
        try:
            result.set_result(decode(packet))
        except ValueError as error:
            log.warning("Invalid packet from %s: %s", address, error)

    def disconnected(_):
        if not result.done():
            result.set_exception(ConnectionError("Sensor disconnected before sending a reading"))

    async with asyncio.timeout(45):
        if _scanner is None:
            raise RuntimeError("El escáner Bluetooth no está disponible")
        device = None
        for _ in range(20):
            device = next((d for d in _scanner.discovered_devices if d.address == address), None)
            if device is not None:
                break
            await asyncio.sleep(1)
        if device is None:
            raise TimeoutError("Sensor no visible por Bluetooth; se reintentará en el próximo ciclo")
        # Reuse the live scanner's device object. Restarting an implicit scan
        # between discovery and connection loses unpaired devices on BlueZ.
        async with BleakClient(device, timeout=20, disconnected_callback=disconnected) as client:
            char = client.services.get_characteristic(DATA_UUID)
            if char is None or "notify" not in char.properties:
                raise ValueError("Firmware incompatible: no se encontró la característica de medición")
            await client.start_notify(char, notified)
            return await result


async def cycle():
    settings = db.get_settings()
    db.set_settings(heartbeat=time.time())
    if settings.get("scan_requested") == "1":
        await scan()
    interval = int(settings["interval"])
    with db.database() as conn:
        sensors = conn.execute("SELECT id FROM sensors WHERE enabled=1 AND (last_attempt IS NULL OR last_attempt < ?) ORDER BY COALESCE(last_attempt, 0)",
                               (time.time() - interval,)).fetchall()
    for sensor in sensors:
        address = sensor["id"]
        with db.database() as conn:
            # A user can pause a sensor while another one is being read.
            if not conn.execute("SELECT enabled FROM sensors WHERE id=?", (address,)).fetchone()[0]:
                continue
            conn.execute("UPDATE sensors SET last_attempt=? WHERE id=?", (time.time(), address))
        db.set_settings(heartbeat=time.time(), active_sensor=address)
        try:
            reading = await sample(address)
            db.record(address, reading)
            log.info("%s: %s", address, reading)
        except Exception as error:
            message = str(error) or "Sin respuesta en 45 segundos; se reintentará en el próximo ciclo"
            log.warning("%s: %s", address, message)
            with db.database() as conn:
                conn.execute("UPDATE sensors SET error=? WHERE id=?", (message, address))
        finally:
            db.set_settings(active_sensor="", heartbeat=time.time())


async def main():
    global _scanner
    db.init()
    db.set_settings(scan_requested="1", active_sensor="")
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    last_cleanup = 0

    def observed(device, adv):
        if sensor_model(device, adv):
            _observed[device.address] = (device, adv, time.time())

    try:
        while True:
            try:
                async with BleakScanner(detection_callback=observed) as scanner:
                    _scanner = scanner
                    db.set_settings(scan_requested="1", scan_state="pending")
                    while True:
                        await cycle()
                        if time.time() - last_cleanup > 86400:
                            with db.database() as conn:
                                conn.execute("DELETE FROM readings WHERE timestamp < ?", (time.time() - 365 * 86400,))
                            last_cleanup = time.time()
                        await asyncio.sleep(2)
            except Exception:
                log.exception("Bluetooth session failed; retrying")
                db.set_settings(scan_state="error", scan_error="No se pudo iniciar Bluetooth; revisá el adaptador y BlueZ")
            finally:
                _scanner = None
                _observed.clear()
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        pass
    finally:
        db.set_settings(heartbeat="0", active_sensor="")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
