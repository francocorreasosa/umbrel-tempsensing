"""BLE discovery and live readings for compatible stock Xiaomi LYWSD03MMC sensors.

Run with .venv/bin/python sensors.py scan, then read DEVICE_ID [DEVICE_ID ...].
Readings are JSON lines; diagnostics go to stderr. Ctrl-C disconnects.
Newer authenticated firmware may require a different reader.
"""

import argparse
import asyncio
import json
import struct
import sys
from datetime import datetime, timezone

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

DATA_UUID = "ebe0ccc1-7a0a-4b0c-8a1a-6ff2997da3a6"


def decode(data):
    if len(data) != 5:
        raise ValueError(f"Expected 5 bytes, received {len(data)}")
    temperature, humidity, millivolts = struct.unpack("<hBH", data)
    if humidity > 100:
        raise ValueError(f"Invalid humidity: {humidity}")
    return dict(temperature_c=temperature / 100, humidity_percent=humidity,
                battery_voltage=millivolts / 1000)


async def scan(seconds):
    devices = await BleakScanner.discover(timeout=seconds, return_adv=True)
    for device, adv in sorted(devices.values(), key=lambda item: -item[1].rssi):
        print(json.dumps(dict(id=device.address, name=adv.local_name or device.name,
                              rssi=adv.rssi, services=adv.service_uuids)))
    if not devices:
        print("No BLE devices found. Check Bluetooth and move sensors closer.", file=sys.stderr)


async def read(address, seconds, inspect=False):
    disconnected = asyncio.Event()
    async with BleakClient(address, disconnected_callback=lambda _: disconnected.set(),
                           timeout=20) as client:
        if inspect:
            for service in client.services:
                print(service.uuid, service.description)
                for char in service.characteristics:
                    print("  ", char.uuid, ", ".join(char.properties))
            return
        char = client.services.get_characteristic(DATA_UUID)
        if char is None or "notify" not in char.properties:
            raise ValueError("Compatible LYWSD03MMC notification characteristic not found. "
                             "Use inspect to identify this model/firmware.")
        count = 0

        def notify(_, data):
            nonlocal count
            try:
                reading = decode(data)
            except ValueError as error:
                print(f"{address}: {error}", file=sys.stderr)
                return
            count += 1
            print(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),
                                  id=address, **reading)), flush=True)

        await client.start_notify(char, notify)
        print(f"Connected to {address}; waiting for readings...", file=sys.stderr)
        try:
            await asyncio.wait_for(disconnected.wait(), timeout=seconds)
        except TimeoutError:
            pass
        else:
            raise BleakError(f"{address} disconnected; rerun read to reconnect")
        if count == 0:
            raise ValueError("No readings received. Close Xiaomi Home, check range, "
                             "and confirm the sensor model and firmware.")


async def main(args):
    if args.command == "scan":
        await scan(args.seconds)
    elif args.command == "inspect":
        await read(args.id, args.seconds, inspect=True)
    else:
        results = await asyncio.gather(*(read(address, args.seconds) for address in args.ids),
                                       return_exceptions=True)
        errors = [(address, result) for address, result in zip(args.ids, results)
                  if isinstance(result, Exception)]
        for address, error in errors:
            print(f"{address}: {type(error).__name__}: {error or 'Operation timed out'}",
                  file=sys.stderr)
        return bool(errors)
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command, default in (("scan", 15), ("read", 60), ("inspect", 20)):
        sub = commands.add_parser(command)
        sub.add_argument("--seconds", type=float, default=default)
        if command == "read":
            sub.add_argument("ids", nargs="+", help="Device IDs from scan (UUIDs on macOS)")
        elif command == "inspect":
            sub.add_argument("id")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    try:
        sys.exit(int(asyncio.run(main(args))))
    except KeyboardInterrupt:
        pass
    except (BleakError, ValueError, TimeoutError) as error:
        print(f"Error: {error}", file=sys.stderr)
        print("On macOS, check System Settings > Privacy & Security > Bluetooth "
              "for the app running this command.", file=sys.stderr)
        sys.exit(1)
