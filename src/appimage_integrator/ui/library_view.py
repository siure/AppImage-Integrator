from __future__ import annotations

import subprocess

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from appimage_integrator.models import ManagedAppRecord


class LibraryView(Gtk.Box):
    def __init__(self, on_show_details, on_repair, on_uninstall) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)
        self._on_show_details = on_show_details
        self._on_repair = on_repair
        self._on_uninstall = on_uninstall

        self.search = Gtk.SearchEntry(placeholder_text="Search managed AppImages")
        self.search.connect("search-changed", self._filter_rows)
        self.append(self.search)

        self.empty_state = Gtk.Label(label="No managed AppImages yet.")
        self.empty_state.add_css_class("dim-label")
        self.append(self.empty_state)

        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        self.append(self.list_box)

    def set_records(self, records: list[ManagedAppRecord]) -> None:
        while child := self.list_box.get_first_child():
            self.list_box.remove(child)
        self._records = records
        self.empty_state.set_visible(not records)
        for record in records:
            self.list_box.append(self._build_row(record))
        self._filter_rows()

    def _build_row(self, record: ManagedAppRecord) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        image = Gtk.Image.new_from_file(record.managed_icon_path) if record.managed_icon_path else Gtk.Image.new_from_icon_name("application-x-executable")
        image.set_pixel_size(48)
        box.append(image)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        title = Gtk.Label(label=record.display_name, xalign=0)
        title.add_css_class("title-4")
        labels.append(title)
        subtitle = Gtk.Label(
            label=f"{record.version or 'version unknown'}   {record.last_validation_status}",
            xalign=0,
        )
        subtitle.add_css_class("dim-label")
        labels.append(subtitle)
        box.append(labels)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, callback in (
            ("Launch", lambda _btn: subprocess.Popen([record.managed_appimage_path])),
            ("Details", lambda _btn: self._on_show_details(record)),
            ("Repair", lambda _btn: self._on_repair(record)),
            ("Uninstall", lambda _btn: self._on_uninstall(record)),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            actions.append(button)
        box.append(actions)
        row.set_child(box)
        row._record = record
        return row

    def _filter_rows(self, *_args) -> None:
        query = self.search.get_text().strip().lower()
        row = self.list_box.get_first_child()
        while row:
            record = getattr(row, "_record", None)
            visible = not query or (
                query in record.display_name.lower()
                or (record.version or "").lower().find(query) >= 0
            )
            row.set_visible(visible)
            row = row.get_next_sibling()
