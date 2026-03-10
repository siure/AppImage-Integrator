from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from appimage_integrator.config import STEPPER_STEPS


class StatusStepper(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("status-stepper")
        self._rows: dict[str, tuple[Gtk.Label, Gtk.Label]] = {}
        for step in STEPPER_STEPS:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            name = Gtk.Label(label=step, xalign=0)
            name.add_css_class("heading")
            status = Gtk.Label(label="Pending", xalign=1)
            status.add_css_class("dim-label")
            row.append(name)
            row.append(status)
            self.append(row)
            self._rows[step] = (name, status)

    def reset(self) -> None:
        for _, status in self._rows.values():
            status.set_text("Pending")
            self._set_status_class(status, "pending")

    def set_step(self, step: str, state: str, detail: str | None = None) -> None:
        row = self._rows.get(step)
        if not row:
            return
        _, status = row
        text = state.capitalize()
        if detail:
            text = f"{text}: {detail}"
        status.set_text(text)
        self._set_status_class(status, state)

    def _set_status_class(self, label: Gtk.Label, state: str) -> None:
        for css_class in ("pending", "running", "success", "warning", "error"):
            label.remove_css_class(css_class)
        label.add_css_class(state)
