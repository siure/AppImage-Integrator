from __future__ import annotations

import shlex

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk, Pango

from appimage_integrator.models import ManagedAppRecord


class DetailsDialog(Gtk.Window):
    """Structured detail view without libadwaita preference widgets."""

    def __init__(self, parent: Gtk.Widget, record: ManagedAppRecord) -> None:
        root = parent.get_root()
        super().__init__(transient_for=root if isinstance(root, Gtk.Window) else None, modal=True)
        self.add_css_class("integrator-dialog")
        self.set_modal(True)
        self.set_resizable(True)
        self.set_size_request(560, 440)
        self.set_title(record.display_name)
        self.set_default_size(760, 620)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=record.display_name))
        self.set_titlebar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_hexpand(True)
        content.set_vexpand(True)
        scrolled.set_child(content)

        if record.last_validation_messages:
            content.append(
                self._build_section(
                    "Validation Issues",
                    [("Issue", message) for message in record.last_validation_messages],
                    warning=True,
                )
            )

        content.append(
            self._build_section(
                "General",
                [
                    ("Name", record.display_name),
                    ("Comment", record.comment or "—"),
                    ("Version", record.version or "unknown"),
                    ("AppStream ID", record.appstream_id or "—"),
                    ("AppImage Type", record.appimage_type),
                    ("Validation Status", record.last_validation_status),
                ],
            )
        )

        path_rows = [
            ("Managed AppImage", record.managed_appimage_path),
            ("Desktop File", record.managed_desktop_path),
            ("Icon", record.managed_icon_path or "application-x-executable"),
            ("Source Last Seen", record.source_path_last_seen),
        ]
        if record.managed_payload_path:
            path_rows.append(("Payload Path", record.managed_payload_path))
        if record.managed_payload_dir:
            path_rows.append(("Payload Directory", record.managed_payload_dir))
        content.append(self._build_section("Paths", path_rows))

        content.append(
            self._build_section(
                "Launch Configuration",
                [
                    ("Exec Template", record.desktop_exec_template),
                    ("Arg Preset", record.arg_preset_id or "none"),
                    ("Extra Arguments", shlex.join(record.extra_args) if record.extra_args else "—"),
                ],
            )
        )

        metadata_rows = [
            ("Internal ID", record.internal_id),
            ("Identity Fingerprint", record.identity_fingerprint),
            ("Desktop Basename", record.embedded_desktop_basename or "—"),
            ("Source Filename at Install", record.source_file_name_at_install),
            ("Installed At", record.installed_at),
            ("Updated At", record.updated_at),
            ("Icon Managed By App", "Yes" if record.icon_managed_by_app else "No"),
            ("Schema Version", str(record.schema_version)),
        ]
        if record.managed_files:
            metadata_rows.append(("Managed Files", f"{len(record.managed_files)} files"))
        content.append(self._build_section("Metadata", metadata_rows))

        self.set_child(scrolled)

    def _build_section(
        self,
        title: str,
        rows: list[tuple[str, object]],
        *,
        warning: bool = False,
    ) -> Gtk.Box:
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        section.add_css_class("details-section")
        section.set_hexpand(True)
        section.set_margin_bottom(6)

        title_label = Gtk.Label(label=title)
        title_label.add_css_class("details-section-title")
        title_label.set_xalign(0)
        section.append(title_label)

        grid = Gtk.Grid()
        grid.add_css_class("details-grid")
        grid.set_column_spacing(18)
        grid.set_row_spacing(10)
        grid.set_hexpand(True)
        grid.set_column_homogeneous(False)

        for row_index, (key, value) in enumerate(rows):
            key_label = Gtk.Label(label=key)
            key_label.add_css_class("details-row-key")
            key_label.set_halign(Gtk.Align.START)
            key_label.set_valign(Gtk.Align.START)
            key_label.set_xalign(0)

            if warning:
                value_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                value_box.set_hexpand(True)
                value_box.set_valign(Gtk.Align.START)
                icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
                icon.set_valign(Gtk.Align.START)
                value_box.append(icon)
                value_box.append(self._build_value_label(value))
                value_widget = value_box
            else:
                value_widget = self._build_value_label(value)

            grid.attach(key_label, 0, row_index, 1, 1)
            grid.attach(value_widget, 1, row_index, 1, 1)

        section.append(grid)
        return section

    @staticmethod
    def _build_value_label(value: object) -> Gtk.Label:
        text = "—" if value is None else str(value)
        label = Gtk.Label(label=text)
        label.add_css_class("details-row-value")
        label.set_hexpand(True)
        label.set_halign(Gtk.Align.FILL)
        label.set_valign(Gtk.Align.START)
        label.set_xalign(0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_selectable(True)
        return label
