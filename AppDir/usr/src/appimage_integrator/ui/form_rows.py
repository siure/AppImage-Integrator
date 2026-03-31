from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk


class CompatEntryRow:
    def __init__(self, title: str) -> None:
        if hasattr(Adw, "EntryRow"):
            self._widget = Adw.EntryRow(title=title)
            self._entry = None
            return

        row = Adw.ActionRow(title=title)
        entry = Gtk.Entry()
        entry.set_hexpand(True)
        entry.set_valign(Gtk.Align.CENTER)
        row.add_suffix(entry)
        row.set_activatable_widget(entry)
        self._widget = row
        self._entry = entry

    @property
    def widget(self) -> Gtk.Widget:
        return self._widget

    def set_text(self, value: str) -> None:
        if self._entry is None:
            self._widget.set_text(value)
            return
        self._entry.set_text(value)

    def get_text(self) -> str:
        if self._entry is None:
            return self._widget.get_text()
        return self._entry.get_text()

    def connect_changed(self, callback) -> None:
        if self._entry is None:
            self._widget.connect("notify::text", callback)
            return
        self._entry.connect("changed", callback)


class CompatComboRow:
    def __init__(self, title: str, model: Gtk.StringList) -> None:
        if hasattr(Adw, "ComboRow"):
            self._widget = Adw.ComboRow(title=title, model=model)
            self._dropdown = None
            return

        row = Adw.ActionRow(title=title)
        dropdown = Gtk.DropDown.new(model, None)
        dropdown.set_valign(Gtk.Align.CENTER)
        row.add_suffix(dropdown)
        row.set_activatable_widget(dropdown)
        self._widget = row
        self._dropdown = dropdown

    @property
    def widget(self) -> Gtk.Widget:
        return self._widget

    def get_selected(self) -> int:
        if self._dropdown is None:
            return self._widget.get_selected()
        return self._dropdown.get_selected()

    def set_selected(self, position: int) -> None:
        if self._dropdown is None:
            self._widget.set_selected(position)
            return
        self._dropdown.set_selected(position)

    def connect_changed(self, callback) -> None:
        if self._dropdown is None:
            self._widget.connect("notify::selected", callback)
            return
        self._dropdown.connect("notify::selected", callback)


class CompatExpanderRow:
    def __init__(self, title: str) -> None:
        if hasattr(Adw, "ExpanderRow"):
            self._widget = Adw.ExpanderRow(title=title)
            self._content = None
            return

        expander = Gtk.Expander(label=title)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        expander.set_child(content)
        self._widget = expander
        self._content = content

    @property
    def widget(self) -> Gtk.Widget:
        return self._widget

    def set_enable_expansion(self, enabled: bool) -> None:
        if self._content is None:
            self._widget.set_enable_expansion(enabled)
            return
        self._widget.set_sensitive(enabled)

    def set_expanded(self, expanded: bool) -> None:
        self._widget.set_expanded(expanded)

    def add_row(self, row: Gtk.Widget) -> None:
        if self._content is None:
            self._widget.add_row(row)
            return
        self._content.append(row)

    def remove(self, row: Gtk.Widget) -> None:
        if self._content is None:
            self._widget.remove(row)
            return
        self._content.remove(row)
