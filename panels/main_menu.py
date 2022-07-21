import gi
import logging

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from panels.menu import MenuPanel

def create_panel(*args):
    return MainPanel(*args)

class MainPanel(MenuPanel):
    def __init__(self, screen, title, back=False):
        super().__init__(screen, title, False)

    def initialize(self, panel_name, items, extrudercount):
        print("### Making MainMenu")
        _ = self.lang.gettext

        grid = self._gtk.HomogeneousGrid()
        grid.set_hexpand(True)
        grid.set_vexpand(True)

        # Create Extruders and bed icons
        eq_grid = Gtk.Grid()
        eq_grid.set_hexpand(True)
        eq_grid.set_vexpand(True)

        self.heaters = []

        i = 0
        for x in self._printer.get_tools():
            self.labels[x] = self._gtk.ButtonImage("extruder-"+str(i), self._gtk.formatTemperatureString(0, 0))
            self.labels[x].connect("clicked", self.on_popover_clicked, "temperature", {
            "name":  _('Temperature'),
            "panel": "temperature"
            
            })
            self.heaters.append(x)
            i += 1

        add_heaters = self._printer.get_heaters()
        for h in add_heaters:
            if h == "heater_bed":
                self.labels[h] = self._gtk.ButtonImage("bed", self._gtk.formatTemperatureString(0, 0))
                self.labels[h].connect("clicked", self.on_popover_clicked, "temperature", {
                "name":  _('Temperature'),
                "panel": "temperature"
            
                })
            else:
                name = " ".join(h.split(" ")[1:])
                self.labels[h] = self._gtk.ButtonImage("heat-up", name)
            self.heaters.append(h)

        i = 0
        cols = 3 if len(self.heaters) > 4 else (1 if len(self.heaters) <= 2 else 2)
        for h in self.heaters:
            eq_grid.attach(self.labels[h], i % cols, int(i/cols), 1, 1)
            i += 1

        self.items = items
        self.create_menu_items()

        self.grid = Gtk.Grid()
        self.grid.set_row_homogeneous(True)
        self.grid.set_column_homogeneous(True)

        grid.attach(eq_grid, 0, 0, 1, 1)
        grid.attach(self.arrangeMenuItems(items, 2, True), 1, 0, 1, 1)

        self.grid = grid

        self.target_temps = {
            "heater_bed": 0,
            "extruder": 0
        }

        self.content.add(self.grid)
        self.layout.show_all()

    def activate(self):
        return


    def create_left_panel(self):

        self.labels['devices'] = Gtk.Grid()
        self.labels['devices'].get_style_context().add_class('heater-grid')
        self.labels['devices'].set_vexpand(False)

        name = Gtk.Label("")
        temp = Gtk.Label(_("Temp (°C)"))
        temp.set_size_request(round(self._gtk.get_font_size() * 7.7), 0)

        self.labels['devices'].attach(name, 0, 0, 1, 1)
        self.labels['devices'].attach(temp, 1, 0, 1, 1)

        da = HeaterGraph(self._printer, self._gtk.get_font_size())
        da.set_vexpand(True)
        self.labels['da'] = da

        scroll = self._gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.labels['devices'])

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_vexpand(True)
        box.add(scroll)
        box.add(self.labels['da'])

        self.labels['graph_settemp'] = self._gtk.Button(label=_("Set Temp"))
        self.labels['graph_settemp'].connect("clicked", self.show_numpad)
        self.labels['graph_hide'] = self._gtk.Button(label=_("Hide"))
        self.labels['graph_hide'].connect("clicked", self.graph_show_device, False)
        self.labels['graph_show'] = self._gtk.Button(label=_("Show"))
        self.labels['graph_show'].connect("clicked", self.graph_show_device)

        popover = Gtk.Popover()
        self.labels['popover_vbox'] = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        popover.add(self.labels['popover_vbox'])
        popover.set_position(Gtk.PositionType.BOTTOM)
        self.labels['popover'] = popover

        i = 0
        for d in self._printer.get_temp_store_devices():
            if self.add_device(d):
                i += 1
        graph_height = (self._gtk.get_content_height() / 2) - ((i + 2) * 4 * self._gtk.get_font_size())
        self.labels['da'].set_size_request(-1, graph_height)
        return box

    def graph_show_device(self, widget, show=True):
        logging.info("Graph show: %s %s" % (self.popover_device, show))
        self.labels['da'].set_showing(self.popover_device, show)
        if show:
            self.devices[self.popover_device]['name'].get_style_context().remove_class("graph_label_hidden")
            self.devices[self.popover_device]['name'].get_style_context().add_class(
                self.devices[self.popover_device]['class'])
        else:
            self.devices[self.popover_device]['name'].get_style_context().remove_class(
                self.devices[self.popover_device]['class'])
            self.devices[self.popover_device]['name'].get_style_context().add_class("graph_label_hidden")
        self.labels['da'].queue_draw()
        self.popover_populate_menu()
        self.labels['popover'].show_all()

    def hide_numpad(self, widget):
        self.devices[self.active_heater]['name'].get_style_context().remove_class("button_active")
        self.active_heater = None

        if self._screen.vertical_mode:
            self.grid.remove_row(1)
            self.grid.attach(self.labels['menu'], 0, 1, 1, 1)
        else:
            self.grid.remove_column(1)
            self.grid.attach(self.labels['menu'], 1, 0, 1, 1)
        self.grid.show_all()

    def on_popover_clicked(self, widget, device):
        self.popover_device = device
        po = self.labels['popover']
        po.set_relative_to(widget)
        self.popover_populate_menu()
        po.show_all()

    def popover_populate_menu(self):
        pobox = self.labels['popover_vbox']
        for child in pobox.get_children():
            pobox.remove(child)

        if self.labels['da'].is_showing(self.popover_device):
            pobox.pack_start(self.labels['graph_hide'], True, True, 5)
            if self.devices[self.popover_device]['type'] != "sensor":
                pobox.pack_start(self.labels['graph_settemp'], True, True, 5)
        else:
            pobox.pack_start(self.labels['graph_show'], True, True, 5)
            if self.devices[self.popover_device]['type'] != "sensor":
                pobox.pack_start(self.labels['graph_settemp'], True, True, 5)
    def show_numpad(self, widget):

        if self.active_heater is not None:
            self.devices[self.active_heater]['name'].get_style_context().remove_class("button_active")
        self.active_heater = self.popover_device
        self.devices[self.active_heater]['name'].get_style_context().add_class("button_active")

        if "keypad" not in self.labels:
            self.labels["keypad"] = Keypad(self._screen, self.change_target_temp, self.hide_numpad)
        self.labels["keypad"].clear()

        if self._screen.vertical_mode:
            self.grid.remove_row(1)
            self.grid.attach(self.labels["keypad"], 0, 1, 1, 1)
        else:
            self.grid.remove_column(1)
            self.grid.attach(self.labels["keypad"], 1, 0, 1, 1)
        self.grid.show_all()

        self.labels['popover'].popdown()
                

    def process_update(self, action, data):
        if action != "notify_status_update":
            return

        for x in self._printer.get_tools():
            self.update_temp(
                x,
                self._printer.get_dev_stat(x, "temperature"),
                self._printer.get_dev_stat(x, "target")
            )
        for h in self._printer.get_heaters():
            self.update_temp(
                h,
                self._printer.get_dev_stat(h, "temperature"),
                self._printer.get_dev_stat(h, "target"),
                None if h == "heater_bed" else " ".join(h.split(" ")[1:])
            )
        return