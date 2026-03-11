from __future__ import annotations

import json

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from appimage_integrator.models import ManagedAppRecord


class DetailsDialog(Adw.Dialog):
    def __init__(self, parent: Gtk.Widget, record: ManagedAppRecord) -> None:
        super().__init__()
        self.set_title(record.display_name)
        self.set_content_width(700)
        self.set_content_height(520)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)

        if record.last_validation_messages:
            issue_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            issue_box.add_css_class("card")

            issue_title = Gtk.Label(label="Validation Issues", xalign=0)
            issue_title.add_css_class("title-5")
            issue_box.append(issue_title)

            issue_text = Gtk.Label(label="\n".join(record.last_validation_messages), xalign=0)
            issue_text.set_wrap(True)
            issue_text.set_selectable(True)
            issue_text.add_css_class("dim-label")

            issue_scroller = Gtk.ScrolledWindow(hexpand=True, min_content_height=140)
            issue_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            issue_scroller.set_child(issue_text)
            issue_box.append(issue_scroller)
            content.append(issue_box)

        summary = Gtk.Label(
            label=(
                f"Exec template: {record.desktop_exec_template}\n"
                f"Desktop file: {record.managed_desktop_path}\n"
                f"Icon path: {record.managed_icon_path or 'application-x-executable'}\n"
                f"Source last seen: {record.source_path_last_seen}"
            ),
            xalign=0,
        )
        summary.set_selectable(True)
        summary.add_css_class("monospace")
        content.append(summary)

        scrolled = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        text = Gtk.TextView(editable=False, monospace=True)
        text.get_buffer().set_text(json.dumps(record.to_dict(), indent=2, sort_keys=True))
        scrolled.set_child(text)
        content.append(scrolled)

        toolbar.set_content(content)
        self.set_child(toolbar)
