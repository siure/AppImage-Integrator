from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk


class CompatToolbarView:
    def __init__(self, window: Gtk.Window | None = None) -> None:
        self._window = window
        if hasattr(Adw, "ToolbarView"):
            self._widget = Adw.ToolbarView()
            self._fallback = False
        else:
            container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            container.set_vexpand(True)
            self._widget = container
            self._fallback = True

    @property
    def widget(self) -> Gtk.Widget:
        return self._widget

    def add_top_bar(self, bar: Gtk.Widget) -> None:
        if self._fallback:
            handle = Gtk.WindowHandle()
            handle.set_child(bar)
            self._widget.append(handle)
            return
        self._widget.add_top_bar(bar)

    def set_content(self, child: Gtk.Widget) -> None:
        child.set_vexpand(True)
        if self._fallback:
            self._widget.append(child)
            return
        self._widget.set_content(child)
