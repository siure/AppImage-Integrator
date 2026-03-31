from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk


class DropTargetFrame(Gtk.Frame):
    __gtype_name__ = "DropTargetFrame"

    def __init__(self, on_path_dropped) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(False)
        self.add_css_class("drop-zone")
        self._on_path_dropped = on_path_dropped

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        title = Gtk.Label(label="Drop an AppImage here")
        title.add_css_class("title-3")
        subtitle = Gtk.Label(label="or use the file picker to inspect metadata before installing")
        subtitle.add_css_class("dim-label")
        box.append(title)
        box.append(subtitle)
        self.set_child(box)

        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.connect("drop", self._on_drop)
        self.add_controller(target)

    def _on_drop(self, _target: Gtk.DropTarget, value: Gdk.FileList, _x: float, _y: float) -> bool:
        files = value.get_files() if value else []
        if not files:
            return False
        path = files[0].get_path()
        if not path:
            return False
        self._on_path_dropped(Path(path))
        return True
