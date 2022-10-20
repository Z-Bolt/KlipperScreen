import gi
import logging
import os

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk, Pango
from datetime import datetime

from ks_includes.screen_panel import ScreenPanel

def create_panel(*args):
    return SystemPanel(*args)


ALLOWED_SERVICES = ["KlipperScreen", "MoonCord", "klipper", "moonraker"]

class SystemPanel(ScreenPanel):
    def initialize(self, panel_name):
        _ = self.lang.gettext

        grid = self._gtk.HomogeneousGrid()
        grid.set_row_homogeneous(True)

        restart = self._gtk.ButtonImage('refresh', "\n".join(_('Klipper Restart').split(' ')), 'color1')
        restart.connect("clicked", self.restart_klippy)
        restart.set_vexpand(False)
        firmrestart = self._gtk.ButtonImage('refresh', "\n".join(_('Firmware\nRestart').split(' ')), 'color2')
        firmrestart.connect("clicked", self.restart_klippy, "firmware")
        firmrestart.set_vexpand(False)

        reboot = self._gtk.ButtonImage('refresh', _('System\nRestart'), 'color3')
        reboot.connect("clicked", self._screen._confirm_send_action,
                       _("Are you sure you wish to reboot the system?"), "machine.reboot")
        reboot.set_vexpand(False)


        grid.attach(restart, 3, 2, 1, 1)
        grid.attach(firmrestart, 1, 2, 1, 1)
        grid.attach(reboot, 2, 2, 1, 1)
        self.content.add(grid)
        
    def restart_klippy(self, widget, type=None):
        if type == "firmware":
            self._screen._ws.klippy.restart_firmware()
        else:
            self._screen._ws.klippy.restart()

    def restart_ks(self, widget):
        os.system("sudo systemctl restart %s" % self._config.get_main_config_option('service'))