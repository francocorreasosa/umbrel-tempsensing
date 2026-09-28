import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from sensors import decode
from tempsensing import db
from tempsensing.collector import cycle
from tempsensing.web import create_app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, DATA_DIR=self.folder.name)
        self.env.start()
        self.client = create_app().test_client()
        db.discover('AA:BB:CC:DD:EE:FF', 'LYWSD03MMC', -60)
        self.address = 'AA:BB:CC:DD:EE:FF'
        db.set_settings(scan_requested=0)

    def tearDown(self):
        self.env.stop()
        self.folder.cleanup()

    def enable(self, name='Living'):
        return self.client.post('/api/sensors/'+self.address, json={'name':name,'enabled':True})

    def test_decoder_signed_temperature_and_invalid_packets(self):
        self.assertEqual(decode(bytes.fromhex('0cfe32b80b'))['temperature_c'], -5)
        self.assertEqual(decode(bytes.fromhex('290932b80b'))['humidity_percent'], 50)
        for packet in (b'', b'123456', bytes.fromhex('290965b80b')):
            with self.assertRaises(ValueError):
                decode(packet)

    def test_discovery_does_not_enable_or_overwrite_names(self):
        self.assertFalse(self.client.get('/api/status').json['sensors'][0]['enabled'])
        self.enable()
        db.discover(self.address, 'LYWSD03MMC', -70)
        sensor = self.client.get('/api/status').json['sensors'][0]
        self.assertEqual(sensor['name'], 'Living')
        self.assertEqual(sensor['rssi'], -70)

    def test_sampling_persists_and_respects_interval(self):
        self.enable()
        measurement = {'temperature_c':23.45,'humidity_percent':50,'battery_voltage':3.0}
        with patch('tempsensing.collector.sample', new_callable=AsyncMock, return_value=measurement) as sample:
            asyncio.run(cycle())
            asyncio.run(cycle())
            sample.assert_awaited_once_with(self.address)
        points = self.client.get('/api/history').json['points']
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]['temperature_c'], 23.45)
        self.assertEqual(create_app().test_client().get('/api/status').json['sensors'][0]['temperature_c'], 23.45)

    def test_failed_sensor_does_not_prevent_other_readings_and_recovers(self):
        self.enable()
        db.discover('second', 'LYWSD03MMC', -65)
        self.client.post('/api/sensors/second', json={'name':'Bedroom','enabled':True})
        measurement = {'temperature_c':20,'humidity_percent':55,'battery_voltage':2.9}
        with patch('tempsensing.collector.sample', new_callable=AsyncMock, side_effect=[TimeoutError(), measurement]):
            asyncio.run(cycle())
        sensors = {s['id']:s for s in self.client.get('/api/status').json['sensors']}
        self.assertIsNotNone(sensors[self.address]['error'])
        self.assertEqual(sensors['second']['temperature_c'], 20)
        with db.database() as conn:
            conn.execute('UPDATE sensors SET last_attempt=NULL WHERE id=?', (self.address,))
        with patch('tempsensing.collector.sample', new_callable=AsyncMock, return_value=measurement):
            asyncio.run(cycle())
        self.assertIsNone(next(s for s in self.client.get('/api/status').json['sensors'] if s['id']==self.address)['error'])

    def test_pause_keeps_history_and_skips_sampling(self):
        self.enable()
        db.record(self.address, {'temperature_c':20,'humidity_percent':55,'battery_voltage':2.9})
        self.client.post('/api/sensors/'+self.address, json={'name':'Living','enabled':False})
        with patch('tempsensing.collector.sample', new_callable=AsyncMock) as sample:
            asyncio.run(cycle())
            sample.assert_not_awaited()
        self.assertEqual(len(self.client.get('/api/history').json['points']), 1)

    def test_validation_and_cross_origin_mutations(self):
        for value in (0, 59, 3601, '300', True):
            self.assertEqual(self.client.post('/api/settings', json={'interval':value}).status_code,400)
        self.assertEqual(self.client.post('/api/settings',json={'interval':60}).status_code,200)
        self.assertEqual(self.client.post('/api/scan',json={},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/scan',data='{}').status_code,415)
        self.assertEqual(self.client.post('/api/settings',json=[]).status_code,400)
        self.assertEqual(self.client.get('/api/history?hours=999999').status_code,400)

    def test_export_and_time_range(self):
        self.enable('=FORMULA()')
        db.record(self.address, {'temperature_c':20,'humidity_percent':55,'battery_voltage':2.9})
        with db.database() as conn:
            conn.execute('INSERT INTO readings(sensor_id,timestamp,temperature_c,humidity_percent,battery_voltage) VALUES (?,?,?,?,?)',
                         (self.address,time.time()-90000,10,50,2.9))
        self.assertEqual(self.client.get('/api/history?hours=24').json['points'][0]['samples'],1)
        exported = self.client.get('/api/export?hours=24').text
        self.assertIn("'=FORMULA()",exported)
        self.assertEqual(len(exported.splitlines()),2)


if __name__ == '__main__':
    unittest.main()
