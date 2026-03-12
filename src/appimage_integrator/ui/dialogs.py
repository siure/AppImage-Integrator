from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk


def _resolve_parent(parent: Gtk.Widget | Gtk.Window | None) -> Gtk.Window | None:
    if parent is None:
        return None
    if isinstance(parent, Gtk.Window):
        return parent
    root = parent.get_root()
    return root if isinstance(root, Gtk.Window) else None


class CompatMessageDialog:
    def __init__(self, parent: Gtk.Widget | Gtk.Window | None, title: str, body: str) -> None:
        self._parent = _resolve_parent(parent)
        if hasattr(Adw, "AlertDialog"):
            self._dialog = Adw.AlertDialog.new(title, body)
            self._uses_parent_present = True
        else:
            self._dialog = Adw.MessageDialog.new(self._parent, title, body)
            self._uses_parent_present = False

    def add_response(self, response_id: str, label: str) -> None:
        self._dialog.add_response(response_id, label)

    def set_default_response(self, response_id: str) -> None:
        self._dialog.set_default_response(response_id)

    def set_close_response(self, response_id: str) -> None:
        if hasattr(self._dialog, "set_close_response"):
            self._dialog.set_close_response(response_id)

    def set_response_appearance(self, response_id: str, appearance) -> None:
        if hasattr(self._dialog, "set_response_appearance"):
            self._dialog.set_response_appearance(response_id, appearance)

    def connect(self, signal: str, callback, *args) -> None:
        self._dialog.connect(signal, callback, *args)

    def present(self) -> None:
        if self._uses_parent_present:
            self._dialog.present(self._parent)
            return
        self._dialog.present()

