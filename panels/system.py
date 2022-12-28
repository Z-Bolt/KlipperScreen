import gi
import logging
import os

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango, GLib

from ks_includes.screen_panel import ScreenPanel


def create_panel(*args):
    return SystemPanel(*args)

class SystemPanel(ScreenPanel):

    def initialize(self):
        
        grid = self._gtk.HomogeneousGrid()
        grid.set_row_homogeneous(False)
        
        restart = self._gtk.ButtonImage('refresh', _('Klipper Restart'), 'color1')
        restart.connect("clicked", self.restart_klippy)
        restart.set_vexpand(True)
        firmrestart = self._gtk.ButtonImage('refresh', _('Firmware\nRestart'), 'color2')
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