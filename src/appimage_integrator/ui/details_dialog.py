from __future__ import annotations

import shlex

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from appimage_integrator.models import ManagedAppRecord


class DetailsDialog(Adw.Dialog):
    """Structured detail view using AdwPreferencesGroup sections."""

    def __init__(self, parent: Gtk.Widget, record: ManagedAppRecord) -> None:
        super().__init__()
        self.set_title(record.display_name)
        self.set_content_width(600)
        self.set_content_height(520)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(560)
        clamp.set_margin_top(18)
        clamp.set_margin_bottom(18)
        clamp.set_margin_start(12)
        clamp.set_margin_end(12)
        scrolled.set_child(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(content)

        # --- Validation Issues (if any) ---
        if record.last_validation_messages:
            issues_group = Adw.PreferencesGroup(title="Validation Issues")
            for msg in record.last_validation_messages:
                row = Adw.ActionRow()
                row.set_use_markup(False)
                row.set_title(msg)
                row.set_subtitle_selectable(True)
                row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
                issues_group.add(row)
            content.append(issues_group)

        # --- General ---
        general_group = Adw.PreferencesGroup(title="General")
        self._add_detail_row(general_group, "Name", record.display_name)
        self._add_detail_row(general_group, "Comment", record.comment or "—")
        self._add_detail_row(general_group, "Version", record.version or "unknown")
        self._add_detail_row(general_group, "AppStream ID", record.appstream_id or "—")
        self._add_detail_row(general_group, "AppImage Type", record.appimage_type)
        self._add_detail_row(general_group, "Validation Status", record.last_validation_status)
        content.append(general_group)

        # --- Paths ---
        paths_group = Adw.PreferencesGroup(title="Paths")
        self._add_detail_row(paths_group, "Managed AppImage", record.managed_appimage_path)
        self._add_detail_row(paths_group, "Desktop File", record.managed_desktop_path)
        self._add_detail_row(paths_group, "Icon", record.managed_icon_path or "application-x-executable")
        self._add_detail_row(paths_group, "Source Last Seen", record.source_path_last_seen)
        if record.managed_payload_path:
            self._add_detail_row(paths_group, "Payload Path", record.managed_payload_path)
        if record.managed_payload_dir:
            self._add_detail_row(paths_group, "Payload Directory", record.managed_payload_dir)
        content.append(paths_group)

        # --- Launch Configuration ---
        launch_group = Adw.PreferencesGroup(title="Launch Configuration")
        self._add_detail_row(launch_group, "Exec Template", record.desktop_exec_template)
        self._add_detail_row(launch_group, "Arg Preset", record.arg_preset_id or "none")
        self._add_detail_row(
            launch_group,
            "Extra Arguments",
            shlex.join(record.extra_args) if record.extra_args else "—",
        )
        content.append(launch_group)

        # --- Metadata ---
        meta_group = Adw.PreferencesGroup(title="Metadata")
        self._add_detail_row(meta_group, "Internal ID", record.internal_id)
        self._add_detail_row(meta_group, "Identity Fingerprint", record.identity_fingerprint)
        self._add_detail_row(meta_group, "Desktop Basename", record.embedded_desktop_basename or "—")
        self._add_detail_row(meta_group, "Source Filename at Install", record.source_file_name_at_install)
        self._add_detail_row(meta_group, "Installed At", record.installed_at)
        self._add_detail_row(meta_group, "Updated At", record.updated_at)
        self._add_detail_row(meta_group, "Icon Managed By App", "Yes" if record.icon_managed_by_app else "No")
        self._add_detail_row(meta_group, "Schema Version", str(record.schema_version))
        if record.managed_files:
            self._add_detail_row(meta_group, "Managed Files", str(len(record.managed_files)) + " files")
        content.append(meta_group)

        toolbar.set_content(scrolled)
        self.set_child(toolbar)

    @staticmethod
    def _add_detail_row(group: Adw.PreferencesGroup, title: str, value: str) -> None:
        row = Adw.ActionRow()
        row.set_use_markup(False)
        row.set_title(title)
        row.set_subtitle(value)
        row.set_subtitle_selectable(True)
        group.add(row)
