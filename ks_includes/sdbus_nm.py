# This is the backend of the UI panel that communicates to sdbus-networkmanager
# TODO device selection/swtichability
# Alfredo Monclus (alfrix) 2024
import logging
import re
import subprocess
import socket
from uuid import uuid4

import sdbus
from sdbus_block.networkmanager import (
    NetworkManager,
    NetworkDeviceGeneric,
    NetworkDeviceWireless,
    NetworkConnectionSettings,
    NetworkManagerSettings,
    AccessPoint,
    NetworkManagerConnectionProperties,
    IPv4Config,
    ActiveConnection,
    enums,
    exceptions,
)

NONE = 0  # The access point has no special security requirements.
PAIR_WEP40 = 1  # 40/64-bit WEP is supported for pairwise/unicast encryption.
PAIR_WEP104 = 2  # 104/128-bit WEP is supported for pairwise/unicast encryption.
PAIR_TKIP = 4  # TKIP is supported for pairwise/unicast encryption.
PAIR_CCMP = 8  # AES/CCMP is supported for pairwise/unicast encryption.
GROUP_WEP40 = 16  # 40/64-bit WEP is supported for group/broadcast encryption.
GROUP_WEP104 = 32  # 104/128-bit WEP is supported for group/broadcast encryption.
GROUP_TKIP = 64  # TKIP is supported for group/broadcast encryption.
GROUP_CCMP = 128  # AES/CCMP is supported for group/broadcast encryption.
KEY_MGMT_PSK = 256  # WPA/RSN Pre-Shared Key encryption
KEY_MGMT_802_1X = 512  # 802.1x authentication and key management
KEY_MGMT_SAE = 1024  # WPA/RSN Simultaneous Authentication of Equals
KEY_MGMT_OWE = 2048  # WPA/RSN Opportunistic Wireless Encryption
KEY_MGMT_OWE_TM = 4096  # WPA/RSN Opportunistic Wireless Encryption transition mode
KEY_MGMT_EAP_SUITE_B_192 = 8192  # WPA3 Enterprise Suite-B 192


def get_encryption(flags):
    if flags == 0:
        return "Open"

    encryption_mapping = {
        PAIR_WEP40: "WEP",
        PAIR_WEP104: "WEP",
        PAIR_TKIP: "TKIP",
        PAIR_CCMP: "AES",
        GROUP_WEP40: "WEP",
        GROUP_WEP104: "WEP",
        GROUP_TKIP: "TKIP",
        GROUP_CCMP: "AES",
        KEY_MGMT_PSK: "WPA-PSK",
        KEY_MGMT_802_1X: "802.1x",
        KEY_MGMT_SAE: "WPA-SAE",
        KEY_MGMT_OWE: "OWE",
        KEY_MGMT_OWE_TM: "OWE-TM",
        KEY_MGMT_EAP_SUITE_B_192: "WPA3-B192",
    }

    encryption_methods = []
    for flag, method_name in encryption_mapping.items():
        if flags & flag and method_name not in encryption_methods:
            encryption_methods.append(method_name)
    return " ".join(encryption_methods)


def WifiChannels(freq: str):
    if freq == "2484":
        return "2.4", "14"
    try:
        freq = float(freq)
    except ValueError:
        return "?", "?"
    if 2412 <= freq <= 2472:
        return "2.4", str(int((freq - 2407) / 5))
    elif 3657.5 <= freq <= 3692.5:
        return "3", str(int((freq - 3000) / 5))
    elif 4915 <= freq <= 4980:
        return "5", str(int((freq - 4000) / 5))
    elif 5035 <= freq <= 5885:
        return "5", str(int((freq - 5000) / 5))
    elif 6455 <= freq <= 7115:
        return "6", str(int((freq - 5950) / 5))
    else:
        return "?", "?"


class SdbusNm:

    def __init__(self, popup_callback):
        self.ensure_nm_running()
        self.system_bus = sdbus.sd_bus_open_system()  # We need system bus
        if self.system_bus is None:
            return None
        sdbus.set_default_bus(self.system_bus)
        self.nm = NetworkManager()
        self.wlan_device = (
            self.get_wireless_interfaces()[0]
            if self.get_wireless_interfaces()
            else None
        )
        self.wifi = self.wlan_device is not None
        self.monitor_connection = False
        self.wifi_state = -1
        self.popup = popup_callback

    def ensure_nm_running(self):
        try:
            status = subprocess.run(
                ["systemctl", "is-active", "--quiet", "NetworkManager"]
            )
            if status.returncode != 0:
                raise RuntimeError("Failed to detect NetworkManager service")
        except FileNotFoundError as e:
            logging.exception(f"{e}")
            raise RuntimeError(f"{e}") from e

    def is_wifi_enabled(self):
        return self.nm.wireless_enabled

    def get_interfaces(self):
        return [
            NetworkDeviceGeneric(device).interface for device in self.nm.get_devices()
        ]

    def get_wireless_interfaces(self):
        devices = {path: NetworkDeviceGeneric(path) for path in self.nm.get_devices()}
        return [
            NetworkDeviceWireless(path)
            for path, device in devices.items()
            if device.device_type == enums.DeviceType.WIFI
        ]

    def get_ethernet_interfaces(self):
        devices = {path: NetworkDeviceGeneric(path) for path in self.nm.get_devices()}
        ethernet_type = getattr(enums.DeviceType, "ETHERNET", 1)
        return [
            device.interface
            for device in devices.values()
            if device.device_type == ethernet_type
        ]

    def get_ap_mode_ips(self):
        """Return WiFi AP IP and ethernet shared IPs for display."""
        wifi_ip = "?"
        ethernet_ips = []
        if self.wlan_device:
            wifi_ip = self.get_interface_ip_address(self.wlan_device.interface)
        for interface in self.get_ethernet_interfaces():
            ip = self.get_interface_ip_address(interface)
            if ip != "?":
                ethernet_ips.append(ip)
        return {"wifi": wifi_ip, "ethernet": ethernet_ips}

    def get_primary_interface(self):
        if self.nm.primary_connection == "/":
            if self.wlan_device:
                return self.wlan_device.interface
            return next(
                (interface for interface in self.get_interfaces() if interface != "lo"),
                None,
            )
        gateway = ActiveConnection(self.nm.primary_connection).devices[0]
        return NetworkDeviceGeneric(gateway).interface

    @staticmethod
    def get_known_networks():
        known_networks = []
        saved_network_paths = NetworkManagerSettings().list_connections()
        for netpath in saved_network_paths:
            saved_con = NetworkConnectionSettings(netpath)
            con_settings = saved_con.get_settings()
            if con_settings["connection"]["type"][1] == "802-11-wireless":
                known_networks.append(
                    {
                        "SSID": con_settings["802-11-wireless"]["ssid"][1].decode(),
                        "UUID": con_settings["connection"]["uuid"][1],
                    }
                )
        return known_networks

    def is_known(self, ssid):
        return any(net["SSID"] == ssid for net in self.get_known_networks())

    def get_ip_address(self):
        # In AP mode we want to display the WiFi AP address, not the primary
        # connection chosen by NM (which may become ethernet shared).
        if self.is_access_point_mode() and self.wlan_device:
            ap_ip = self.get_interface_ip_address(self.wlan_device.interface)
            if ap_ip != "?":
                return ap_ip

        active_connection_path = self.nm.primary_connection
        if not active_connection_path or active_connection_path == "/":
            # Try to get IP address directly from interface
            return self.get_interface_ip_address()
        try:
            active_connection = ActiveConnection(active_connection_path)
            ip_info = IPv4Config(active_connection.ip4_config)
            return ip_info.address_data[0]["address"][1]
        except Exception as e:
            logging.debug(f"Failed to get IP from active connection: {e}")
            return self.get_interface_ip_address()

    def get_networks(self):
        networks = []
        if self.wlan_device:
            all_aps = [AccessPoint(result) for result in self.wlan_device.access_points]
            networks.extend(
                {
                    "SSID": ap.ssid.decode("utf-8"),
                    "known": self.is_known(ap.ssid.decode("utf-8")),
                    "security": get_encryption(
                        ap.rsn_flags or ap.wpa_flags or ap.flags
                    ),
                    "frequency": WifiChannels(ap.frequency)[0],
                    "channel": WifiChannels(ap.frequency)[1],
                    "signal_level": ap.strength,
                    "max_bitrate": ap.max_bitrate,
                    "BSSID": ap.hw_address,
                }
                for ap in all_aps
                if ap.ssid
            )
            return sorted(networks, key=lambda i: i["signal_level"], reverse=True)
        return networks

    def get_bssid_from_ssid(self, ssid):
        return next(net["BSSID"] for net in self.get_networks() if ssid == net["SSID"])

    def get_connected_ap(self):
        if self.wlan_device.active_access_point == "/":
            return None
        return AccessPoint(self.wlan_device.active_access_point)

    def get_connected_bssid(self):
        return (
            self.get_connected_ap().hw_address
            if self.get_connected_ap() is not None
            else None
        )

    def get_security_type(self, ssid):
        return next(
            (
                network["security"]
                for network in self.get_networks()
                if network["SSID"] == ssid
            ),
            None,
        )

    def add_network(self, ssid, psk, eap_method, identity="", phase2=None):
        security_type = self.get_security_type(ssid)
        logging.debug(f"Adding network of type: {security_type}")
        if security_type is None:
            return {"error": "network_not_found", "message": _("Network not found")}

        if self.is_known(ssid):
            self.delete_network(ssid)

        properties: NetworkManagerConnectionProperties = {
            "connection": {
                "id": ("s", ssid),
                "uuid": ("s", str(uuid4())),
                "type": ("s", "802-11-wireless"),
                "interface-name": ("s", self.wlan_device.interface),
            },
            "802-11-wireless": {
                "mode": ("s", "infrastructure"),
                "ssid": ("ay", ssid.encode("utf-8")),
                "security": ("s", "802-11-wireless-security"),
            },
            "ipv4": {"method": ("s", "auto")},
            "ipv6": {"method": ("s", "auto")},
        }

        if security_type == "Open":
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "none"),
            }
        elif "WPA-PSK" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "wpa-psk"),
                "psk": ("s", psk),
            }
        elif "SAE" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "sae"),
                "psk": ("s", psk),
            }
        elif "WPA3-B192" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "wpa-eap-suite-b-192"),
                "psk": ("s", psk),
            }
        elif "OWE" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "owe"),
            }
        elif "802.1x" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "wpa-eap"),
                "eap": ("as", [eap_method]),
                "identity": ("s", identity),
                "password": ("s", psk.encode("utf-8")),
            }
            if phase2:
                if eap_method == "ttls":
                    properties["802-11-wireless-security"]["phase2_autheap"] = ("s", phase2)
                else:
                    properties["802-11-wireless-security"]["phase2_auth"] = ("s", phase2)
        elif "WEP" in security_type:
            properties["802-11-wireless-security"] = {
                "key-mgmt": ("s", "none"),
                "wep-key-type": ("u", 2),
                "wep-key0": ("s", psk),
                "auth-alg": ("s", "shared"),
            }
        else:
            return {
                "error": "unknown_security_type",
                "message": _("Unknown security type"),
            }

        try:
            NetworkManagerSettings().add_connection(properties)
            return {"status": "success"}
        except exceptions.NmSettingsPermissionDeniedError:
            logging.exception("Insufficient privileges")
            return {
                "error": "insufficient_privileges",
                "message": _("Insufficient privileges"),
            }
        except exceptions.NmConnectionInvalidPropertyError:
            logging.exception("Invalid property")
            return {"error": "psk_invalid", "message": _("Invalid password")}
        except Exception as e:
            logging.exception("Couldn't add network")
            return {"error": "unknown", "message": _("Couldn't add network") + f"\n{e}"}

    def disconnect_network(self):
        self.wlan_device.disconnect()

    def delete_network(self, ssid):
        if path := self.get_connection_path_by_ssid(ssid):
            self.delete_connection_path(path)
        else:
            logging.debug(f"SSID '{ssid}' not found among saved connections")

    def delete_connection_path(self, path):
        try:
            NetworkConnectionSettings(path).delete()
            logging.info(f"Deleted connection path: {path}")
        except Exception as e:
            logging.exception(f"Failed to delete connection path: {path} - {e}")
            return {
                "error": "deletion_failed",
                "message": _("Failed to delete connection") + f"\n{e}",
            }

    def rescan(self):
        try:
            return self.wlan_device.request_scan({})
        except Exception as e:
            self.popup(f"Unexpected error: {e}")

    def get_connection_path_by_ssid(self, ssid):
        existing_networks = NetworkManagerSettings().list_connections()
        for connection_path in existing_networks:
            connection_settings = NetworkConnectionSettings(
                connection_path
            ).get_settings()
            if (
                connection_settings.get("802-11-wireless")
                and connection_settings["802-11-wireless"].get("ssid")
                and connection_settings["802-11-wireless"]["ssid"][1].decode() == ssid
            ):
                return connection_path
        return None

    def connect(self, ssid):
        if target_connection := self.get_connection_path_by_ssid(ssid):
            self.popup(f"{ssid}\n{_('Starting WiFi Association')}", 1)
            try:
                active_connection = self.nm.activate_connection(target_connection)
                return target_connection
            except Exception as e:
                logging.exception("Unexpected error")
                self.popup(f"Unexpected error: {e}")
        else:
            self.popup(f"SSID '{ssid}' not found among saved connections")

    def toggle_wifi(self, enable):
        self.nm.wireless_enabled = enable

    def monitor_connection_status(self):
        state = self.wlan_device.state
        if self.wifi_state != state:
            logging.debug(f"State changed: {state} {self.wlan_device.state_reason}")
            if self.wifi_state == -1:
                logging.debug("Starting to monitor state")
            elif state in [
                enums.DeviceState.PREPARE,
                enums.DeviceState.CONFIG,
            ]:
                self.popup(_("Connecting"), 1)
            elif state in [
                enums.DeviceState.IP_CONFIG,
                enums.DeviceState.IP_CHECK,
                enums.DeviceState.SECONDARIES,
            ]:
                self.popup(_("Getting IP address"), 1)
            elif state in [
                enums.DeviceState.ACTIVATED,
            ]:
                self.popup(_("Network connected"), 1)
            elif state in [
                enums.DeviceState.DISCONNECTED,
                enums.DeviceState.DEACTIVATING,
            ]:
                self.popup(_("Network disconnected"))
            elif state == enums.DeviceState.FAILED:
                self.popup(_("Connection failed"))
            self.wifi_state = state
        return self.monitor_connection

    def enable_monitoring(self, enable):
        self.monitor_connection = enable

    def get_interface_ip_address(self, interface=None):
        """Get IP address directly from network interface"""
        try:
            explicit_interface = interface is not None
            interface = interface or self.get_primary_interface()
            if not interface:
                return "?"
            # When interface is explicitly requested, do not use socket-based
            # route lookup because it can return another interface IP.
            if not explicit_interface:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    ip = s.getsockname()[0]
                    s.close()
                    return ip
                except Exception:
                    pass
            # Fallback to ip command
            result = subprocess.run(
                ["ip", "-4", "addr", "show", interface],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', result.stdout)
                if match:
                    return match.group(1)
        except Exception as e:
            logging.debug(f"Failed to get interface IP: {e}")
        return "?"

    def is_access_point_mode(self):
        """Check if wireless device is in AP mode"""
        if not self.wlan_device:
            return False
        try:
            # Check active connection type
            active_connection_path = self.wlan_device.active_connection
            if active_connection_path and active_connection_path != "/":
                active_connection = ActiveConnection(active_connection_path)
                connection_path = active_connection.connection
                if connection_path and connection_path != "/":
                    connection_settings = NetworkConnectionSettings(connection_path)
                    settings = connection_settings.get_settings()
                    if "802-11-wireless" in settings:
                        mode = settings["802-11-wireless"].get("mode", [None, None])[1]
                        return mode == "ap"
        except Exception as e:
            logging.debug(f"Failed to check AP mode: {e}")
        return False

    def get_access_point_connection_path(self):
        """Get connection path for access point if exists"""
        try:
            saved_network_paths = NetworkManagerSettings().list_connections()
            for netpath in saved_network_paths:
                saved_con = NetworkConnectionSettings(netpath)
                con_settings = saved_con.get_settings()
                if (
                    con_settings["connection"]["type"][1] == "802-11-wireless"
                    and con_settings.get("802-11-wireless", {}).get("mode", [None, None])[1] == "ap"
                ):
                    return netpath
        except Exception as e:
            logging.debug(f"Failed to get AP connection path: {e}")
        return None

    @staticmethod
    def get_ethernet_sharing_connection_id(interface):
        return f"KlipperScreen-AP-ETH-{interface}"

    def get_ethernet_sharing_connection_paths(self):
        """Get saved ethernet sharing connection paths created by AP mode"""
        paths = []
        try:
            saved_network_paths = NetworkManagerSettings().list_connections()
            for netpath in saved_network_paths:
                saved_con = NetworkConnectionSettings(netpath)
                con_settings = saved_con.get_settings()
                conn_type = con_settings.get("connection", {}).get("type", [None, None])[1]
                conn_id = con_settings.get("connection", {}).get("id", [None, None])[1]
                if conn_type == "802-3-ethernet" and conn_id and conn_id.startswith("KlipperScreen-AP-ETH-"):
                    paths.append(netpath)
        except Exception as e:
            logging.debug(f"Failed to get ethernet sharing connection paths: {e}")
        return paths

    def create_ethernet_sharing(self):
        """Create and activate ethernet shared mode for AP use"""
        ethernet_interfaces = self.get_ethernet_interfaces()
        if not ethernet_interfaces:
            logging.info("No ethernet interfaces found, skipping ethernet sharing setup")
            return {"status": "success"}

        # Remove stale KlipperScreen ethernet sharing profiles first
        for path in self.get_ethernet_sharing_connection_paths():
            try:
                NetworkConnectionSettings(path).delete()
            except Exception as e:
                logging.debug(f"Failed to delete stale ethernet sharing profile {path}: {e}")

        for interface in ethernet_interfaces:
            try:
                properties: NetworkManagerConnectionProperties = {
                    "connection": {
                        "id": ("s", self.get_ethernet_sharing_connection_id(interface)),
                        "uuid": ("s", str(uuid4())),
                        "type": ("s", "802-3-ethernet"),
                        "interface-name": ("s", interface),
                        "autoconnect": ("b", True),
                    },
                    "ipv4": {
                        "method": ("s", "shared"),
                    },
                    "ipv6": {
                        "method": ("s", "ignore"),
                    },
                }
                connection_path = NetworkManagerSettings().add_connection(properties)
                self.nm.activate_connection(connection_path)
                logging.info(f"Enabled ethernet sharing on {interface}")
            except Exception as e:
                logging.exception(f"Failed to enable ethernet sharing on {interface}: {e}")
                return {
                    "error": "ethernet_sharing_failed",
                    "message": f"Couldn't enable ethernet sharing on {interface}\n{e}",
                }
        return {"status": "success"}

    def remove_ethernet_sharing(self):
        """Remove ethernet shared mode profiles created by AP mode"""
        for path in self.get_ethernet_sharing_connection_paths():
            try:
                NetworkConnectionSettings(path).delete()
                logging.info(f"Removed ethernet sharing profile: {path}")
            except Exception as e:
                logging.exception(f"Failed to remove ethernet sharing profile {path}: {e}")
                return {
                    "error": "ethernet_sharing_remove_failed",
                    "message": f"Couldn't remove ethernet sharing profile\n{e}",
                }
        return {"status": "success"}

    def create_access_point(self, ssid, password):
        """Create and activate access point"""
        try:
            # Delete existing AP connection if exists
            ap_path = self.get_access_point_connection_path()
            if ap_path:
                NetworkConnectionSettings(ap_path).delete()

            # Disconnect current connection
            if self.wlan_device.active_connection and self.wlan_device.active_connection != "/":
                self.wlan_device.disconnect()

            properties: NetworkManagerConnectionProperties = {
                "connection": {
                    "id": ("s", "KlipperScreen-AP"),
                    "uuid": ("s", str(uuid4())),
                    "type": ("s", "802-11-wireless"),
                    "interface-name": ("s", self.wlan_device.interface),
                    "autoconnect": ("b", True),
                },
                "802-11-wireless": {
                    "mode": ("s", "ap"),
                    "ssid": ("ay", ssid.encode("utf-8")),
                    "security": ("s", "802-11-wireless-security"),
                },
                "802-11-wireless-security": {
                    "key-mgmt": ("s", "wpa-psk"),
                    "psk": ("s", password),
                },
                "ipv4": {
                    "method": ("s", "shared"),
                },
                "ipv6": {
                    "method": ("s", "ignore"),
                },
            }

            connection_path = NetworkManagerSettings().add_connection(properties)
            logging.info(f"Created AP connection: {connection_path}")

            # Activate the connection
            self.popup(f"{ssid}\nStarting Access Point", 1)
            self.nm.activate_connection(connection_path)
            ethernet_result = self.create_ethernet_sharing()
            if "error" in ethernet_result:
                # Roll back AP if ethernet sharing setup fails.
                try:
                    if self.wlan_device.active_connection and self.wlan_device.active_connection != "/":
                        self.wlan_device.disconnect()
                    NetworkConnectionSettings(connection_path).delete()
                except Exception as rollback_error:
                    logging.debug(f"Failed to roll back AP after ethernet sharing error: {rollback_error}")
                return ethernet_result
            return {"status": "success"}
        except exceptions.NmSettingsPermissionDeniedError:
            logging.exception("Insufficient privileges")
            return {
                "error": "insufficient_privileges",
                "message": "Insufficient privileges",
            }
        except Exception as e:
            logging.exception("Couldn't create access point")
            return {"error": "unknown", "message": "Couldn't create access point" + f"\n{e}"}

    def remove_access_point(self):
        """Remove access point and return to normal mode"""
        try:
            # Disconnect current connection
            if self.wlan_device.active_connection and self.wlan_device.active_connection != "/":
                self.wlan_device.disconnect()

            # Delete AP connection
            ap_path = self.get_access_point_connection_path()
            if ap_path:
                NetworkConnectionSettings(ap_path).delete()
                logging.info("Removed AP connection")
            ethernet_result = self.remove_ethernet_sharing()
            if "error" in ethernet_result:
                return ethernet_result
            return {"status": "success"}
        except Exception as e:
            logging.exception("Couldn't remove access point")
            return {"error": "unknown", "message": "Couldn't remove access point" + f"\n{e}"}
        return {"status": "success"}
