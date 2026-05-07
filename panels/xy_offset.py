import logging

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from ks_includes.screen_panel import ScreenPanel


class Panel(ScreenPanel):
    deltas = ["0.01", "0.05", "0.1"]
    delta = deltas[0]

    def __init__(self, screen, title):
        title = title or _("XY Offset")
        super().__init__(screen, title)

        self.offsets = {
            "x": 0.0,
            "y": 0.0,
        }
        self.variables = {
            "x": "t1_x_offset",
            "y": "t1_y_offset",
        }

        delta_grid = Gtk.Grid()
        for idx, delta in enumerate(self.deltas):
            self.labels[f"delta_{delta}"] = self._gtk.Button(label=delta)
            self.labels[f"delta_{delta}"].connect("clicked", self.change_delta, delta)
            ctx = self.labels[f"delta_{delta}"].get_style_context()
            ctx.add_class("horizontal_togglebuttons")
            ctx.add_class("horizontal_togglebuttons_smaller")
            if delta == self.delta:
                ctx.add_class("horizontal_togglebuttons_active")
            delta_grid.attach(self.labels[f"delta_{delta}"], idx, 0, 1, 1)

        self.labels["step_title"] = Gtk.Label(label=_("Offset Step (mm)"))

        self.labels["x-"] = self._gtk.Button("arrow-left", "X-", "color1")
        self.labels["x_value"] = self._gtk.Button("refresh", "  0.000mm", "color1", self.bts, Gtk.PositionType.LEFT, 1)
        self.labels["x+"] = self._gtk.Button("arrow-right", "X+", "color1")

        self.labels["y-"] = self._gtk.Button("arrow-down", "Y-", "color2")
        self.labels["y_value"] = self._gtk.Button("refresh", "  0.000mm", "color2", self.bts, Gtk.PositionType.LEFT, 1)
        self.labels["y+"] = self._gtk.Button("arrow-up", "Y+", "color2")

        main_button_height = int(self._gtk.font_size * 4)
        for key in ("x-", "x_value", "x+", "y-", "y_value", "y+"):
            self.labels[key].set_size_request(-1, main_button_height)

        self.labels["x-"].connect("clicked", self.change_offset, "x", -1)
        self.labels["x+"].connect("clicked", self.change_offset, "x", 1)
        self.labels["y-"].connect("clicked", self.change_offset, "y", -1)
        self.labels["y+"].connect("clicked", self.change_offset, "y", 1)
        self.labels["x_value"].connect("clicked", self.reset_offset_confirm, "x")
        self.labels["y_value"].connect("clicked", self.reset_offset_confirm, "y")

        grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True)
        grid.attach(self.labels["x-"], 0, 0, 1, 1)
        grid.attach(self.labels["x_value"], 1, 0, 1, 1)
        grid.attach(self.labels["x+"], 2, 0, 1, 1)
        grid.attach(self.labels["y-"], 0, 1, 1, 1)
        grid.attach(self.labels["y_value"], 1, 1, 1, 1)
        grid.attach(self.labels["y+"], 2, 1, 1, 1)
        grid.attach(self.labels["step_title"], 0, 2, 3, 1)
        grid.attach(delta_grid, 0, 3, 3, 1)

        self.content.add(grid)
        self.reload_offsets()

    def process_update(self, action, data):
        if action != "notify_status_update":
            return
        if "save_variables" not in data or "variables" not in data["save_variables"]:
            return
        self.apply_variables(data["save_variables"]["variables"])

    def reload_offsets(self, widget=None):
        result = self._screen.apiclient.send_request("printer/objects/query?save_variables")
        if not result or "status" not in result:
            logging.warning("Unable to read save_variables from printer status")
            return
        variables = result["status"].get("save_variables", {}).get("variables", {})
        self.apply_variables(variables)

    def apply_variables(self, variables):
        self.offsets["x"] = self.parse_variable(variables, self.variables["x"])
        self.offsets["y"] = self.parse_variable(variables, self.variables["y"])
        self.update_labels()

    @staticmethod
    def parse_variable(variables, key):
        value = variables.get(key, 0.0)
        try:
            return float(value)
        except (TypeError, ValueError):
            logging.warning(f"Invalid value for {key}: {value}")
            return 0.0

    def update_labels(self):
        self.labels["x_value"].set_label(f"  {self.offsets['x']:.3f}mm")
        self.labels["y_value"].set_label(f"  {self.offsets['y']:.3f}mm")

    def change_delta(self, widget, delta):
        self.labels[f"delta_{self.delta}"].get_style_context().remove_class("horizontal_togglebuttons_active")
        self.delta = delta
        widget.get_style_context().add_class("horizontal_togglebuttons_active")

    def change_offset(self, widget, axis, direction):
        step = float(self.delta)
        value = self.offsets[axis] + (step * direction)
        self.offsets[axis] = value
        self.update_labels()
        variable = self.variables[axis]
        self._screen._send_action(
            widget,
            "printer.gcode.script",
            {"script": f"SAVE_VARIABLE VARIABLE={variable} VALUE={value:.3f}"},
        )

    def reset_offset_confirm(self, widget, axis):
        variable = self.variables[axis]
        axis_name = axis.upper()
        self._screen._confirm_send_action(
            widget,
            _("Reset offset to 0?"),
            "printer.gcode.script",
            {"script": f"SAVE_VARIABLE VARIABLE={variable} VALUE=0.000"},
        )
