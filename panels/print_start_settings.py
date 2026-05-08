import logging

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from ks_includes.screen_panel import ScreenPanel


class Panel(ScreenPanel):
    temp_deltas = ["1", "5", "10", "25", "50"]
    temp_delta = temp_deltas[2]
    default_temp = 160

    def __init__(self, screen, title):
        title = title or _("Print Start Settings")
        super().__init__(screen, title)

        self.temp = float(self.default_temp)
        self.macros = self._printer.get_printer_status_data()["printer"]["gcode_macros"]["list"]
        self.toggle_macro = "CHANGE_T_STAB" if "CHANGE_T_STAB" in self.macros else None
        self.edit_macro = self.get_edit_macro_name()

        temp_delta_grid = Gtk.Grid()
        for idx, delta in enumerate(self.temp_deltas):
            self.labels[f"temp_delta_{delta}"] = self._gtk.Button(label=delta)
            self.labels[f"temp_delta_{delta}"].connect("clicked", self.change_temp_delta, delta)
            ctx = self.labels[f"temp_delta_{delta}"].get_style_context()
            ctx.add_class("horizontal_togglebuttons")
            ctx.add_class("horizontal_togglebuttons_smaller")
            if delta == self.temp_delta:
                ctx.add_class("horizontal_togglebuttons_active")
            temp_delta_grid.attach(self.labels[f"temp_delta_{delta}"], idx, 0, 1, 1)

        self.labels["temp_step_title"] = Gtk.Label(label=_("Temperature Step (deg)"))
        self.labels["tstab"] = self._gtk.Button("heat-up", _("Enable/Disable Thermal Stabilization"), "color4")
        self.labels["temp-"] = self._gtk.Button("arrow-down", _("Temp -"), "color2")
        self.labels["temp_value"] = self._gtk.Button(
            "refresh", f"  {self.default_temp}°C", "color2", self.bts, Gtk.PositionType.LEFT, 1
        )
        self.labels["temp+"] = self._gtk.Button("arrow-up", _("Temp +"), "color2")

        self.labels["tstab"].connect("clicked", self.toggle_thermal_stabilization)
        self.labels["temp-"].connect("clicked", self.change_temperature, -1)
        self.labels["temp+"].connect("clicked", self.change_temperature, 1)
        self.labels["temp_value"].connect("clicked", self.reset_temperature_confirm)

        has_tstab = self.toggle_macro is not None
        has_temp = self.edit_macro is not None
        self.labels["tstab"].set_sensitive(has_tstab)
        self.labels["temp-"].set_sensitive(has_temp)
        self.labels["temp_value"].set_sensitive(has_temp)
        self.labels["temp+"].set_sensitive(has_temp)
        for delta in self.temp_deltas:
            self.labels[f"temp_delta_{delta}"].set_sensitive(has_temp)

        main_button_height = int(self._gtk.font_size * 3.0)
        for key in ("temp-", "temp_value", "temp+"):
            self.labels[key].set_size_request(-1, main_button_height)

        grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=False, row_spacing=0)
        grid.attach(self.labels["tstab"], 0, 0, 3, 1)
        grid.attach(self.labels["temp-"], 0, 1, 1, 1)
        grid.attach(self.labels["temp_value"], 1, 1, 1, 1)
        grid.attach(self.labels["temp+"], 2, 1, 1, 1)
        grid.attach(self.labels["temp_step_title"], 0, 2, 3, 1)
        grid.attach(temp_delta_grid, 0, 3, 3, 1)
        self.content.add(grid)

        self.reload_temperature()

    def process_update(self, action, data):
        if action != "notify_status_update":
            return
        if "save_variables" not in data or "variables" not in data["save_variables"]:
            return
        self.apply_variables(data["save_variables"]["variables"])

    @staticmethod
    def parse_variable(variables, key, fallback):
        value = variables.get(key, fallback)
        try:
            return float(value)
        except (TypeError, ValueError):
            logging.warning(f"Invalid value for {key}: {value}")
            return float(fallback)

    def get_edit_macro_name(self):
        if "EDIT_T_CALIBTATE" in self.macros:
            return "EDIT_T_CALIBTATE"
        if "EDIT_T_CALIBRATE" in self.macros:
            return "EDIT_T_CALIBRATE"
        return None

    def reload_temperature(self):
        result = self._screen.apiclient.send_request("printer/objects/query?save_variables")
        if not result or "status" not in result:
            logging.warning("Unable to read save_variables from printer status")
            self.update_temp_label()
            return
        variables = result["status"].get("save_variables", {}).get("variables", {})
        self.apply_variables(variables)

    def apply_variables(self, variables):
        self.temp = self.parse_variable(variables, "t_calibrate", self.default_temp)
        self.update_temp_label()

    def update_temp_label(self):
        self.labels["temp_value"].set_label(f"  {self.temp:.0f}°C")

    def change_temp_delta(self, widget, delta):
        self.labels[f"temp_delta_{self.temp_delta}"].get_style_context().remove_class("horizontal_togglebuttons_active")
        self.temp_delta = delta
        widget.get_style_context().add_class("horizontal_togglebuttons_active")

    def change_temperature(self, widget, direction):
        if self.edit_macro is None:
            return
        step = int(self.temp_delta)
        self.temp = max(0, self.temp + (step * direction))
        self.update_temp_label()
        self._screen._send_action(
            widget,
            "printer.gcode.script",
            {"script": f"{self.edit_macro} T_CALIBRATE={int(self.temp)}"},
        )

    def reset_temperature_confirm(self, widget):
        if self.edit_macro is None:
            return
        self._screen._confirm_send_action(
            widget,
            _("Reset calibration temperature to 160C?"),
            "printer.gcode.script",
            {"script": f"{self.edit_macro} T_CALIBRATE={self.default_temp}"},
        )

    def toggle_thermal_stabilization(self, widget):
        if self.toggle_macro is None:
            return
        self._screen._confirm_send_action(
            widget,
            _("Toggle thermal stabilization?"),
            "printer.gcode.script",
            {"script": self.toggle_macro},
        )
