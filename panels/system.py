import logging
import os
import subprocess
import shutil
import zipfile
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from ks_includes.screen_panel import ScreenPanel


class Panel(ScreenPanel):
    def __init__(self, screen, title):
        title = title or _("System")
        super().__init__(screen, title)
        self.current_row = 0
        self.mem_multiplier = None
        self.scales = {}
        self.labels = {}
        self.grid = Gtk.Grid(column_spacing=10, row_spacing=5)

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

    def back(self):
        if not self.sysinfo:
            self._screen.panels_reinit.append("system")
        return False

    def create_layout(self):
        # Add Export Logs button at the top
        export_button = self._gtk.Button("refresh", _("Export Logs"), "color4")
        export_button.connect("clicked", self.export_logs)
        self.grid.attach(export_button, 0, self.current_row, 2, 1)
        self.current_row += 1

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

    def find_mounted_device(self):
        """Находит примонтированное устройство в /home/pi/printer_data/gcodes/"""
        gcodes_base = "/home/pi/printer_data/gcodes"

        if not os.path.exists(gcodes_base):
            return None

        # Проверяем все подкаталоги в gcodes
        try:
            for item in os.listdir(gcodes_base):
                item_path = os.path.join(gcodes_base, item)
                # Проверяем, является ли путь точкой монтирования
                if os.path.isdir(item_path) and os.path.ismount(item_path):
                    return item_path
        except OSError as e:
            logging.error(f"Error scanning gcodes directory: {e}")

        return None

    @staticmethod
    def _format_duration_seconds(value):
        try:
            total_seconds = int(float(value))
        except (TypeError, ValueError):
            return _("Unknown")

        if total_seconds < 0:
            total_seconds = 0

        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)

        if days > 0:
            return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _write_moonraker_history_totals(self, dest_path):
        """
        Saves Moonraker /server/history/totals into a text file.
        Moonraker reports time as seconds and filament as millimeters.
        """
        export_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            resp = self._screen.apiclient.send_request("server/history/totals")
        except Exception as e:
            logging.error(f"Error requesting Moonraker history totals: {e}")
            resp = None

        totals = None
        if isinstance(resp, dict):
            # Common shapes:
            # {"result": {"job_totals": {...}}}
            # {"job_totals": {...}}
            # {"result": {...}}
            result = resp.get("result")
            if isinstance(result, dict) and isinstance(result.get("job_totals"), dict):
                totals = result.get("job_totals")
            elif isinstance(resp.get("job_totals"), dict):
                totals = resp.get("job_totals")
            elif isinstance(result, dict):
                totals = result

        def _first_key(d, *keys, default=None):
            if not isinstance(d, dict):
                return default
            for k in keys:
                if k in d:
                    return d.get(k)
            return default

        total_jobs = _first_key(totals, "total_jobs", "job_total", "jobs", default=None)
        total_time_s = _first_key(
            totals, "total_time", "total_run_time", "total_time_seconds", default=None
        )
        total_print_time_s = _first_key(
            totals, "total_print_time", "total_print_time_seconds", "total_print_seconds", default=None
        )
        total_filament_mm = _first_key(
            totals, "total_filament_used", "total_filament", "total_filament_mm", default=None
        )

        # Filament: Moonraker reports millimeters (per docs). Convert to meters for readability.
        filament_mm_str = _("Unknown")
        filament_m_str = _("Unknown")
        try:
            if total_filament_mm is not None:
                filament_mm = float(total_filament_mm)
                if filament_mm < 0:
                    filament_mm = 0.0
                filament_mm_str = f"{filament_mm:,.0f} mm".replace(",", " ")
                filament_m_str = f"{(filament_mm / 1000.0):,.2f} m".replace(",", " ")
        except (TypeError, ValueError):
            pass

        with open(dest_path, "w", encoding="utf-8") as f:
            f.write("Moonraker history totals\n")
            f.write(f"Exported: {export_ts}\n")
            f.write("Endpoint: /server/history/totals\n\n")

            if totals is None:
                f.write("Status: failed to parse response\n")
                if resp is None:
                    f.write("Response: <none>\n")
                else:
                    f.write(f"Response keys: {list(resp.keys())}\n")
                return

            f.write("Totals:\n")
            f.write(f"- Prints: {total_jobs if total_jobs is not None else _('Unknown')}\n")
            f.write(f"- Total printer time: {self._format_duration_seconds(total_time_s)}\n")
            f.write(f"- Total print time: {self._format_duration_seconds(total_print_time_s)}\n")
            f.write(f"- Total filament used: {filament_mm_str} ({filament_m_str})\n")

    def export_logs(self, widget):
        """Экспортирует журналы на съемный носитель"""
        # Ищем примонтированное устройство
        mounted_device = self.find_mounted_device()

        home_dir = os.path.expanduser("~")
        temp_dir = os.path.join(home_dir, "printer_data", "logs_export_temp")
        logs_dir = os.path.join(home_dir, "printer_data", "logs")

        # Если съемный носитель не подключен, сохраняем архив в ~/printer_data/logs
        if mounted_device:
            export_dest_dir = mounted_device
        else:
            export_dest_dir = logs_dir
            self._screen.show_popup_message(
                _("No removable device found") + "\n" + _("Saving to logs folder"),
                level=2
            )
            logging.warning(
                "No mounted device found in /home/pi/printer_data/gcodes/. Saving to ~/printer_data/logs"
            )

        try:
            # Создаем временную директорию для файлов
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir)

            # Пути к файлам логов
            log_files = [
                ("klippy.log", os.path.join(logs_dir, "klippy.log")),
                ("moonraker.log", os.path.join(logs_dir, "moonraker.log")),
                ("crowsnest.log", os.path.join(logs_dir, "crowsnest.log")),
            ]

            # KlipperScreen.log может быть в разных местах
            klipperscreen_log_paths = [
                os.path.join(logs_dir, "KlipperScreen.log"),
                "/tmp/KlipperScreen.log",
            ]
            for log_path in klipperscreen_log_paths:
                if os.path.exists(log_path):
                    log_files.append(("KlipperScreen.log", log_path))
                    break

            # Копируем файлы логов, если они существуют
            for dest_name, source_path in log_files:
                if os.path.exists(source_path):
                    dest_path = os.path.join(temp_dir, dest_name)
                    shutil.copy2(source_path, dest_path)
                    logging.info(f"Copied {source_path} to {dest_path}")
                else:
                    logging.warning(f"Log file not found: {source_path}")

            # Выполняем команду dmesg и сохраняем вывод
            try:
                dmesg_result = subprocess.run(
                    ["dmesg"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if dmesg_result.returncode == 0:
                    dmesg_file = os.path.join(temp_dir, "dmesg.txt")
                    with open(dmesg_file, "w", encoding="utf-8") as f:
                        f.write(dmesg_result.stdout)
                    logging.info("Saved dmesg output")
            except Exception as e:
                logging.error(f"Error running dmesg: {e}")

            # Выполняем команду df -h и сохраняем вывод
            try:
                df_result = subprocess.run(
                    ["df", "-h"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if df_result.returncode == 0:
                    df_file = os.path.join(temp_dir, "df_h.txt")
                    with open(df_file, "w", encoding="utf-8") as f:
                        f.write(df_result.stdout)
                    logging.info("Saved df -h output")
            except Exception as e:
                logging.error(f"Error running df -h: {e}")

            # Добавляем историю печати Moonraker (totals) в отдельный файл
            try:
                history_file = os.path.join(temp_dir, "moonraker_history.txt")
                self._write_moonraker_history_totals(history_file)
                logging.info("Saved moonraker history totals")
            except Exception as e:
                logging.error(f"Error saving moonraker history totals: {e}")

            # Создаем ZIP архив
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"logs_export_{timestamp}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if file != zip_filename:  # Не добавляем сам архив
                            file_path = os.path.join(root, file)
                            arcname = os.path.basename(file_path)
                            zipf.write(file_path, arcname)

            # Копируем/сохраняем архив в целевую папку
            os.makedirs(export_dest_dir, exist_ok=True)
            dest_zip_path = os.path.join(export_dest_dir, zip_filename)
            shutil.copy2(zip_path, dest_zip_path)
            logging.info(f"Copied archive to {dest_zip_path}")

            # Удаляем временную директорию
            shutil.rmtree(temp_dir)

            # Показываем уведомление об успехе
            self._screen.show_popup_message(
                _("Logs saved successfully") + f"\n{dest_zip_path}",
                level=1
            )

            # Отмонтируем устройство
            if mounted_device:
                try:
                    result = subprocess.run(
                        ["sudo", "umount", mounted_device],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        logging.info(f"Successfully unmounted {mounted_device}")
                    else:
                        logging.warning(f"Failed to unmount {mounted_device}: {result.stderr}")
                except Exception as e:
                    logging.error(f"Error unmounting device: {e}")

        except Exception as e:
            logging.error(f"Error exporting logs: {e}")
            self._screen.show_popup_message(
                _("Error exporting logs") + f": {str(e)}",
                level=3
            )
            # Удаляем временную директорию в случае ошибки
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

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
