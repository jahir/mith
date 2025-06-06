#!/usr/bin/python3
# vim: set et ts=4 sw=4
#
"""
read ATC1441/pvvx temperature/humidity sensors (based on Telink chipset)
https://github.com/pvvx/ATC_MiThermometer
"""

import time
from datetime import datetime
from dataclasses import dataclass
import struct
from enum import Enum
import re

from btle import BtLe


# config ##############################################################
sensors = {
    'A4:C1:38:xx:xx:xx': 'living room',
    'A4:C1:38:xx:xx:xx': 'kitchen',
}

VERBOSE = False
DEBUG = False

# internals ###########################################################
_sensors_max_name_length = max(map(len, sensors.values()))

class DeviceType(Enum):
    ATC1441 = 1
    PVVX = 2

_devicetype_max_lenght = max(map(len, DeviceType._member_names_))


def log(msg: str, ts: datetime|None = None) -> None:
    if not ts:
        ts = datetime.now()
    ts_str = ts.isoformat(sep=' ', timespec='milliseconds')
    print(f'{ts_str}  {msg}')

def vlog(msg: str) -> None:
    if VERBOSE:
        log(msg)

def dlog(msg: str) -> None:
    if DEBUG:
        log(msg)


@dataclass
class Measurement:
    "Measurement data"
    device_type: DeviceType
    adv_number: int
    adv_missed: int
    timestamp: datetime
    temperature: float
    humidity: float
    battery_voltage: int
    battery_percentage: int
    sensor_name: str = ""

    def __repr__(self):
        dev_str = f'[{self.sensor_name:{_sensors_max_name_length}}] ({self.device_type.name:{_devicetype_max_lenght}} {self.adv_number:3})'
        return f'{dev_str:32}  {self.temperature:6.2f} °C   {self.humidity:6.1f} % rH   Bat {self.battery_percentage:3}% ({self.battery_voltage:4} mV)'


class MiTH:
    "read pvvx bluetooth LE device"

    # internal stuff
    _adv_counter = dict()
    _latest_measurement_time = dict()

    # the bluetooth device is hci0
    def __init__(self, device_id: int = 0):
        self.device_id = device_id

    def event_loop_passive(self) -> None:
        """passive read"""
        BtLe.handle_le_advertising_events(self.device_id, self.le_advertise_packet_handler)

    # def le_advertise_packet_handler(mac, adv_type, data, rssi):
    def le_advertise_packet_handler(self, mac: str, _: int, data: bytes, rssi: int):
        "handler for le advertising events"
        if measurement := self.decode_data_atc(mac, data):
            measurement.sensor_name = self.sensor_name(mac)

            now = time.perf_counter()
            elapsed = now - previous if (previous := self._latest_measurement_time.get(mac)) else None
            elapsed_str = f'{elapsed:6.3f} s' if elapsed else ''
            self._latest_measurement_time[mac] = now

            if measurement.adv_missed:
                elapsed_str += f', missed {measurement.adv_missed}'

            log(f'{measurement}  RSSI {rssi} dBm  ({elapsed_str})')

    def decode_data_atc(self, mac: str, packet: bytes) -> Measurement | None:
        """decode ATC data"""
        preamble = b'\x16\x1a\x18'
        packet_start = packet.find(preamble)
        if (packet_start == -1):
            dlog(f'{mac} unknown packet ({len(packet)}): {packet.hex(" ")}')
            return
        offset = packet_start + len(preamble)
        data = packet[offset:]

        device_type: DeviceType
        data_len = len(data)
        if data_len == 13: # ATC1441 format
            device_type = DeviceType.ATC1441
            adv_number_offset = -1 # last data in packet is adv number
        elif data_len == 15: # pvvx (custom) format
            device_type = DeviceType.PVVX
            adv_number_offset = -2 # next-to-last ist adv number
        else:
            dlog(f'mac {mac} unknown device type, data length {data_len}')
            return

        adv_number = data[adv_number_offset]
        adv_number_prev = self._adv_counter.get(mac)
        if adv_number == adv_number_prev:
            vlog(f'[{self.sensor_name(mac):{_sensors_max_name_length}}] adv_number {adv_number:3} unchanged')
            return
        adv_missed = (adv_number - adv_number_prev - 1) if adv_number_prev else 0
        self._adv_counter[mac] = adv_number

        if device_type == DeviceType.ATC1441:
            temperature = int.from_bytes(data[6:8], byteorder='big', signed=True) / 10.
            humidity = int(data[8])
            battery_percentage = int(data[9])
            battery_voltage = int.from_bytes(data[10:12])
        elif device_type == DeviceType.PVVX:
            temperature = int.from_bytes(data[6:8], byteorder='little', signed=True) / 100.
            humidity = int.from_bytes(data[8:10], byteorder='little', signed=False) / 100
            battery_voltage = int.from_bytes(data[10:12], byteorder='little', signed=False)
            battery_percentage = int(data[12])
        else:
            return

        now = datetime.now()
        measurement = Measurement(device_type, adv_number, adv_missed, now, temperature, humidity, battery_voltage, battery_percentage)

        return measurement

    def sensor_name(self, mac: str) -> str:
        name = sensors.get(mac)
        if not name:
            if m := re.match('A4:C1:38:(..):(..):(..)', mac):
                name = ''.join(m.groups())
            else:
                name = mac
        return name


if __name__ == "__main__":
    MiTH().event_loop_passive()

