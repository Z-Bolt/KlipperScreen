import logging
import os
import shutil
import subprocess
import datetime
import tarfile
import psutil
import re
import threading
import glob

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
from ks_includes.screen_panel import ScreenPanel
from gi.repository import Gdk


class Panel(ScreenPanel):
    def __init__(self, screen, title):
        title = title or _("System")
        super().__init__(screen, title)
        self._setup_dialog_style()
        self.current_row = 0
        self.mem_multiplier = None
        self.scales = {}
        self.labels = {}
        self.grid = Gtk.Grid(column_spacing=10, row_spacing=5)

        self.save_button = Gtk.Button(label=_("Export System Logs to External Storage"))
        self.save_button.connect("clicked", self.on_save_logs_clicked)
        self.grid.attach(self.save_button, 0, self.current_row, 2, 1)
        self.current_row += 1

        self.sysinfo = screen.printer.system_info
        if not self.sysinfo:
            logging.debug("Asking for info")
            self.sysinfo = screen.apiclient.send_request("machine/system_info")
            if 'system_info' in self.sysinfo:
                screen.printer.system_info = self.sysinfo['system_info']
                self.sysinfo = self.sysinfo['system_info']
        logging.debug(self.sysinfo)
        if self.sysinfo:
            self.content.add(self.create_layout())
        else:
            self.content.add(Gtk.Label(label=_("No info available"), vexpand=True))

    def _setup_dialog_style(self):
        css_provider = Gtk.CssProvider()
        css = b"""
        .log-dialog {
            background-color: #2F343F; /* RAL7016 Anthracite grey */
        }
        """
        css_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def get_serial_number(self):
        try:
            with open("/home/pi/printer_data/config/printer.cfg", "r") as f:
                for line in f:
                    if line.startswith("# S/N: ZBS"):
                        match = re.match(r'# S/N: (ZBS\d+)', line)
                        if match:
                            return match.group(1)
        except Exception as e:
            logging.error(f"Error reading printer.cfg: {str(e)}")
        return "UNKNOWN"

    def create_logs_folder(self, serial):
        timestamp = datetime.datetime.now().strftime("%d%m%Y_%H%M%S")
        safe_serial = re.sub(r'[^a-zA-Z0-9_-]', '_', serial)
        logs_dir = f"/home/pi/logs_{safe_serial}_{timestamp}"
        os.makedirs(logs_dir, exist_ok=True)
        return logs_dir

    def get_usb_mount_point(self):
        base_dir = "/home/pi/printer_data/gcodes/"
        for part in psutil.disk_partitions():
            if (part.device.startswith('/dev/sd')
                and part.mountpoint.startswith(base_dir)
                and 'rw' in part.opts.split(',')):
                return part.mountpoint
        return None

    def save_logs_thread(self):
        try:
            usb_mount_point = self.get_usb_mount_point()
            if not usb_mount_point:
                GLib.idle_add(self.show_error_dialog, _("USB device not mounted"))
                return

            test_file = os.path.join(usb_mount_point, "write_test.tmp")
            try:
                subprocess.run(['sudo', 'touch', test_file], check=True)
                subprocess.run(['sudo', 'rm', test_file], check=True)
            except subprocess.CalledProcessError:
                GLib.idle_add(self.show_error_dialog, _("No write permissions on USB"))
                return

            serial = self.get_serial_number()
            logs_dir = self.create_logs_folder(serial)

            log_files = [
                "/home/pi/printer_data/logs/moonraker.log",
                "/home/pi/printer_data/logs/KlipperScreen.log",
                "/home/pi/printer_data/logs/crowsnest.log"
            ]
                
            klippy_rotated = glob.glob("/home/pi/printer_data/logs/klippy.log.*")
            log_files.extend(klippy_rotated)

            for log_file in log_files:
                if os.path.exists(log_file):
                    shutil.copy2(log_file, logs_dir)
            
            if os.path.isfile("/home/pi/printer_data/logs/klippy.log"):
                shutil.copy2("/home/pi/printer_data/logs/klippy.log", logs_dir)

            dmesg_result = subprocess.run(
                ['dmesg'],
                capture_output=True,
                text=True,
                check=True
            )
            with open(os.path.join(logs_dir, "dmesg.log"), "w") as f:
                f.write(dmesg_result.stdout)

            debug_path = os.path.join(logs_dir, "debug.log")
            with open(debug_path, "w") as f:

                # date and time
                f.write(f"Date/time: {datetime.datetime.now()}\n\n")
                
                # serial
                f.write(f"Serial: {serial}\n\n")

                # uname -a
                uname_result = subprocess.run(
                    ['uname', '-a'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                f.write(f"Kernel: {uname_result.stdout.strip()}\n\n")

                # df -h
                df_result = subprocess.run(
                    ['df', '-h'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                f.write(f"df -h\n\n")
                f.write(f"{df_result.stdout}\n\n")

                # free -h
                free_result = subprocess.run(
                    ['free', '-h'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                f.write(f"free -h\n\n")
                f.write(f"{free_result.stdout}\n\n")

                # lsusb
                lsusb_result = subprocess.run(
                    ['lsusb'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                f.write(f"lsusb\n\n")
                f.write(f"{lsusb_result.stdout}\n\n")

                # lsblk
                lsblk_result = subprocess.run(
                    ['lsblk'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                f.write(f"lsblk\n\n")
                f.write(f"{lsblk_result.stdout}\n\n")

            archive_name = f"{logs_dir}.tar.gz"
            with tarfile.open(archive_name, "w:gz") as tar:
                tar.add(logs_dir, arcname=os.path.basename(logs_dir))

            if not os.path.exists(archive_name):
                raise FileNotFoundError("Archive creation failed")

            move_result = subprocess.run(
                ['sudo', 'mv', archive_name, usb_mount_point],
                capture_output=True,
                text=True,
                check=True
            )

            if move_result.returncode != 0:
                raise RuntimeError(f"Move failed: {move_result.stderr}")

            dest_path = os.path.join(usb_mount_point, os.path.basename(archive_name))
            if not os.path.exists(dest_path):
                raise FileNotFoundError(_("Archive not found after move"))

            shutil.rmtree(logs_dir)
            GLib.idle_add(self.show_success_dialog)

        except Exception as e:
            logging.error(f"Log save error: {str(e)}")
            GLib.idle_add(self.show_error_dialog, str(e))

    def on_save_logs_clicked(self, button):
        self.save_button.set_sensitive(False)
        self.save_button.set_label(_("Exporting..."))
        thread = threading.Thread(target=self.save_logs_thread)
        thread.daemon = True
        thread.start()

    def show_success_dialog(self):
        self.save_button.set_sensitive(True)
        self.save_button.set_label(_("Export System Logs to External Storage"))

        dialog = Gtk.MessageDialog(
            parent=self._screen,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=_("Logs exported successfully"),
        )

        dialog.get_style_context().add_class("log-dialog")

        content_area = dialog.get_content_area()
        for child in content_area.get_children():
            if isinstance(child, Gtk.Label):
                child.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))

        dialog.run()
        dialog.destroy()

    def show_error_dialog(self, message):
        self.save_button.set_sensitive(True)
        self.save_button.set_label(_("Export System Logs to External Storage"))

        dialog = Gtk.MessageDialog(
            parent=self._screen,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=_("Log export error"),
            secondary_text=message,
        )

        dialog.get_style_context().add_class("log-dialog")

        content_area = dialog.get_content_area()
        for child in content_area.get_children():
            if isinstance(child, Gtk.Label):
                child.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))

        dialog.run()
        dialog.destroy()

    def back(self):
        if not self.sysinfo:
            self._screen.panels_reinit.append("system")
        return False

    def create_layout(self):

        self.grid.attach(Gtk.Separator(), 0, self.current_row, 2, 1)
        self.current_row += 1

        self.cpu_count = int(self.sysinfo["cpu_info"]["cpu_count"])
        self.labels["cpu_usage"] = Gtk.Label(label="", xalign=0)
        self.grid.attach(self.labels["cpu_usage"], 0, self.current_row, 1, 1)
        self.scales["cpu_usage"] = Gtk.ProgressBar(
            hexpand=True, show_text=False, fraction=0
        )
        self.grid.attach(self.scales["cpu_usage"], 1, self.current_row, 1, 1)
        self.current_row += 1

        for i in range(self.cpu_count):
            self.labels[f"cpu_usage_{i}"] = Gtk.Label(label="", xalign=0)
            self.grid.attach(self.labels[f"cpu_usage_{i}"], 0, self.current_row, 1, 1)
            self.scales[f"cpu_usage_{i}"] = Gtk.ProgressBar(
                hexpand=True, show_text=False, fraction=0
            )
            self.grid.attach(self.scales[f"cpu_usage_{i}"], 1, self.current_row, 1, 1)
            self.current_row += 1

        self.labels["memory_usage"] = Gtk.Label(label="", xalign=0)
        self.grid.attach(self.labels["memory_usage"], 0, self.current_row, 1, 1)
        self.scales["memory_usage"] = Gtk.ProgressBar(
            hexpand=True, show_text=False, fraction=0
        )
        self.grid.attach(self.scales["memory_usage"], 1, self.current_row, 1, 1)
        self.current_row += 1

        self.grid.attach(Gtk.Separator(), 0, self.current_row, 2, 1)
        self.current_row += 1
        self.populate_info()

        scroll = self._gtk.ScrolledWindow()
        scroll.add(self.grid)
        return scroll

    def set_mem_multiplier(self, data):
        memory_units = data.get("memory_units", "kB").lower()
        units_mapping = {
            "kb": 1024,
            "mb": 1024**2,
            "gb": 1024**3,
            "tb": 1024**4,
            "pb": 1024**5,
        }
        self.mem_multiplier = units_mapping.get(memory_units, 1)

    def add_label_to_grid(self, text, column, bold=False):
        if bold:
            text = f"<b>{text}</b>"
        label = Gtk.Label(label=text, use_markup=True, xalign=0, wrap=True)
        self.grid.attach(label, column, self.current_row, 1, 1)
        self.current_row += 1

    def populate_info(self):
        for category, data in self.sysinfo.items():
            if category == "python":
                self.add_label_to_grid(self.prettify(category), 0, bold=True)
                self.current_row -= 1
                self.add_label_to_grid(
                    f'Version: {data["version_string"].split(" ")[0]}', 1
                )
                continue

            if (
                category
                in (
                    "virtualization",
                    "provider",
                    "available_services",
                    "service_state",
                    "instance_ids",
                )
                or not self.sysinfo[category]
            ):
                continue

            self.add_label_to_grid(self.prettify(category), 0, bold=True)

            if isinstance(data, dict):
                for key, value in data.items():
                    if key in ("version_parts", "memory_units") or not value:
                        continue
                    if key == "total_memory":
                        if not self.mem_multiplier:
                            self.set_mem_multiplier(data)
                        value = self.format_size(int(value) * self.mem_multiplier)
                    if isinstance(value, dict):
                        self.add_label_to_grid(self.prettify(key), 0)
                        self.current_row -= 1
                        for sub_key, sub_value in value.items():
                            if not sub_value:
                                continue
                            elif (
                                isinstance(sub_value, list)
                                and sub_key == "ip_addresses"
                            ):
                                for _ip in sub_value:
                                    self.add_label_to_grid(
                                        f"{self.prettify(sub_key)}: {_ip['address']}", 1
                                    )
                                continue
                            self.add_label_to_grid(
                                f"{self.prettify(sub_key)}: {sub_value}", 1
                            )
                    else:
                        self.add_label_to_grid(f"{self.prettify(key)}: {value}", 1)

    def process_update(self, action, data):
        if not self.sysinfo:
            return
        if action == "notify_proc_stat_update":
            self.labels["cpu_usage"].set_label(
                f'CPU: {data["system_cpu_usage"]["cpu"]:.0f}%'
            )
            self.scales["cpu_usage"].set_fraction(
                float(data["system_cpu_usage"]["cpu"]) / 100
            )
            for i in range(self.cpu_count):
                self.labels[f"cpu_usage_{i}"].set_label(
                    f'CPU {i}: {data["system_cpu_usage"][f"cpu{i}"]:.0f}%'
                )
                self.scales[f"cpu_usage_{i}"].set_fraction(
                    float(data["system_cpu_usage"][f"cpu{i}"]) / 100
                )

            self.labels["memory_usage"].set_label(
                _("Memory")
                + f': {(data["system_memory"]["used"] / data["system_memory"]["total"]) * 100:.0f}%'
            )
            self.scales["memory_usage"].set_fraction(
                float(data["system_memory"]["used"])
                / float(data["system_memory"]["total"])
            )