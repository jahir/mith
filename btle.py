"Bluetooth LE methods for MiTH. Based on https://github.com/colin-guyon/py-bluetooth-utils"

import socket
import struct
import fcntl
import array
from errno import EALREADY
from collections.abc import Callable

import bluetooth._bluetooth as bluez


LE_META_EVENT = 0x3E
LE_PUBLIC_ADDRESS = 0x00
SCAN_TYPE_PASSIVE = 0x00
SCAN_FILTER_DUPLICATES = 0x01
SCAN_DISABLE = 0x00
SCAN_ENABLE = 0x01

# Allow Scan Request from Any, Connect Request from Any
FILTER_POLICY_NO_WHITELIST = 0x00

OGF_LE_CTL = 0x08
OCF_LE_SET_SCAN_PARAMETERS = 0x000B
OCF_LE_SET_SCAN_ENABLE = 0x000C

EVT_LE_ADVERTISING_REPORT = 0x02


class BtLe:
    @staticmethod
    def _toggle_device(dev_id: int, code: int) -> None:
        hci_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
        req_str = struct.pack("H", dev_id)
        request = array.array("b", req_str)
        try:
            fcntl.ioctl(hci_sock.fileno(), code, request[0])
        except IOError as e:
            if e.errno != EALREADY:
                raise
        finally:
            hci_sock.close()

    @staticmethod
    def device_enable(dev_id: int=0) -> None:
        BtLe._toggle_device(dev_id, bluez.HCIDEVUP)

    @staticmethod
    def device_disable(dev_id: int=0) -> None:
        BtLe._toggle_device(dev_id, bluez.HCIDEVDOWN)

    @staticmethod
    def open(device_id: int=0) -> int:
        sock = bluez.hci_open_dev(device_id)
        return sock

    @staticmethod
    def le_scan_enable(sock: int) -> None:
        own_bdaddr_type = LE_PUBLIC_ADDRESS  # does not work with LE_RANDOM_ADDRESS
        interval=0x0800
        window=0x0800
        filter_policy=FILTER_POLICY_NO_WHITELIST
        cmd_pkt = struct.pack("<BHHBB", SCAN_TYPE_PASSIVE, interval, window,
                            own_bdaddr_type, filter_policy)
        bluez.hci_send_cmd(sock, OGF_LE_CTL, OCF_LE_SET_SCAN_PARAMETERS, cmd_pkt)
        filter_duplicates = False
        cmd_pkt = struct.pack("<BB", SCAN_ENABLE, SCAN_FILTER_DUPLICATES if filter_duplicates else 0x00)
        bluez.hci_send_cmd(sock, OGF_LE_CTL, OCF_LE_SET_SCAN_ENABLE, cmd_pkt)

    @staticmethod
    def le_scan_disable(sock: int) -> None:
        cmd_pkt = struct.pack("<BB", SCAN_DISABLE, 0x00)
        bluez.hci_send_cmd(sock, OGF_LE_CTL, OCF_LE_SET_SCAN_ENABLE, cmd_pkt)

    @staticmethod
    def parse_le_advertising_events(sock: int, handler: Callable[[str, int, bytes, int], None]) -> None:
        old_filter = sock.getsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, 16)

        new_filter = bluez.hci_filter_new()
        bluez.hci_filter_set_ptype(new_filter, bluez.HCI_EVENT_PKT)
        bluez.hci_filter_set_event(new_filter, LE_META_EVENT)
        sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, new_filter)

        try:
            while True:
                pkt = full_pkt = sock.recv(255)
                ptype, event, plen = struct.unpack("BBB", pkt[:3])

                # Should never occur because we filtered with this type of event
                if event != LE_META_EVENT:
                    continue

                # filter sub_event
                if struct.unpack("B", pkt[3:4])[0] != EVT_LE_ADVERTISING_REPORT:
                    continue

                pkt = pkt[4:]
                adv_type = struct.unpack("b", pkt[1:2])[0]
                mac_addr_str = bluez.ba2str(pkt[3:9])

                data = pkt[9:-1]
                rssi = struct.unpack("b", full_pkt[len(full_pkt)-1:len(full_pkt)])[0]

                try:
                    handler(mac_addr_str, adv_type, data, rssi)
                except Exception as e:
                    print('Exception when calling handler with a BLE advertising event: %r' % (e,))
                    import traceback
                    traceback.print_exc()

        except KeyboardInterrupt:
            try:
                sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, old_filter)
            except bluez.error as e:
                print(f'failed setting filter {old_filter}: {e}')
            raise

    @staticmethod
    def handle_le_advertising_events(device_id: int, handler: Callable[[str, int, bytes, int], None]) -> None:
        BtLe.device_enable(device_id)

        try:
            sock = BtLe.open(device_id)
        except Exception as e:
            # print(f"Error: cannot open bluetooth device {self.device_id}")
            raise Exception(f"Error: cannot open bluetooth device {device_id}", e)

        BtLe.le_scan_enable(sock)
        try:
            BtLe.parse_le_advertising_events(sock, handler=handler)
        except KeyboardInterrupt:
            BtLe.le_scan_disable(sock)
