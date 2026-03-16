from __future__ import annotations

import shlex
import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk, Pango

from appimage_integrator.config import PRESET_LABELS
from appimage_integrator.models import ManagedAppRecord, ManagedRecordUpdateRequest
from appimage_integrator.services.record_editor import RecordEditorService
from appimage_integrator.ui.dialogs import CompatMessageDialog, open_local_file_with_default_app
from appimage_integrator.ui.form_rows import CompatComboRow, CompatEntryRow, CompatExpanderRow


def details_payload_location(record: ManagedAppRecord) -> tuple[str, str] | None:
    if record.managed_payload_path:
        return ("Payload Path", record.managed_payload_path)
    if record.managed_payload_dir:
        return ("Payload Directory", record.managed_payload_dir)
    return None


class DetailsDialog(Gtk.Window):
    def __init__(
        self,
        parent: Gtk.Widget,
        record: ManagedAppRecord,
        record_editor: RecordEditorService,
        on_saved: Callable[[ManagedAppRecord], None],
    ) -> None:
        root = parent.get_root()
        super().__init__(transient_for=root if isinstance(root, Gtk.Window) else None, modal=True)
        self.add_css_class("integrator-dialog")
        self.set_modal(True)
        self.set_resizable(True)
        self.set_size_request(620, 480)
        self.set_default_size(820, 680)

        self._record = record
        self._record_editor = record_editor
        self._on_saved = on_saved
        self._saving = False
        self._preset_index_to_id = {index: preset_id for index, preset_id in enumerate(PRESET_LABELS)}
        self._preset_id_to_index = {
            preset_id: index for index, preset_id in self._preset_index_to_id.items()
        }
        self._initial_state = {
            "display_name": record.display_name,
            "comment": record.comment or "",
            "arg_preset_id": record.arg_preset_id or "none",
            "extra_args": shlex.join(record.extra_args) if record.extra_args else "",
        }

        self.set_title(record.display_name)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=record.display_name))
        self._save_button = Gtk.Button(label="Save")
        self._save_button.add_css_class("suggested-action")
        self._save_button.set_sensitive(False)
        self._save_button.connect("clicked", self._on_save_clicked)
        header.pack_end(self._save_button)
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
            content.append(self._build_validation_callout(record.last_validation_messages))

        content.append(self._build_overview_group(record))
        content.append(self._build_launch_group(record))
        content.append(self._build_files_group(record))
        content.append(self._build_advanced_group(record))

        self.set_child(scrolled)
        self._refresh_effective_command_preview()
        self._refresh_save_state()

    def _build_overview_group(self, record: ManagedAppRecord) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Overview")
        self._name_entry = CompatEntryRow("Name")
        self._name_entry.set_text(record.display_name)
        self._name_entry.connect_changed(self._on_fields_changed)
        group.add(self._name_entry.widget)

        self._comment_entry = CompatEntryRow("Comment")
        self._comment_entry.set_text(record.comment or "")
        self._comment_entry.connect_changed(self._on_fields_changed)
        group.add(self._comment_entry.widget)

        group.add(self._build_info_row("Version", record.version or "unknown"))
        group.add(self._build_info_row("Status", record.last_validation_status))
        return group

    def _build_launch_group(self, record: ManagedAppRecord) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Launch")
        preset_model = Gtk.StringList.new(list(PRESET_LABELS.values()))
        self._preset_combo = CompatComboRow("Preset", preset_model)
        self._preset_combo.set_selected(
            self._preset_id_to_index.get(record.arg_preset_id or "none", 0)
        )
        self._preset_combo.connect_changed(self._on_fields_changed)
        group.add(self._preset_combo.widget)

        self._args_entry = CompatEntryRow("Extra Arguments")
        self._args_entry.set_text(shlex.join(record.extra_args) if record.extra_args else "")
        self._args_entry.connect_changed(self._on_fields_changed)
        group.add(self._args_entry.widget)

        helper = Gtk.Label(
            label="This command is generated automatically from the selected launch options."
        )
        helper.add_css_class("dim-label")
        helper.set_wrap(True)
        helper.set_xalign(0)
        helper.set_margin_start(12)
        helper.set_margin_end(12)
        helper.set_margin_bottom(6)
        group.add(helper)

        command_row = Adw.ActionRow(title="Effective Command")
        command_row.set_activatable(False)
        self._effective_command_label = Gtk.Label()
        self._effective_command_label.set_selectable(True)
        self._effective_command_label.set_wrap(True)
        self._effective_command_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._effective_command_label.set_xalign(0)
        self._effective_command_label.set_hexpand(True)
        command_row.add_suffix(self._effective_command_label)
        group.add(command_row)
        return group

    def _build_files_group(self, record: ManagedAppRecord) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Files")
        group.add(self._build_info_row("Managed AppImage", record.managed_appimage_path))
        self._edit_desktop_button = Gtk.Button(label="Edit .desktop")
        self._edit_desktop_button.connect("clicked", self._open_desktop_file)
        self._edit_desktop_button.set_sensitive(self._desktop_file_exists(record.managed_desktop_path))
        group.add(
            self._build_info_row(
                "Desktop File",
                record.managed_desktop_path or "not available",
                suffix=self._edit_desktop_button,
            )
        )
        group.add(self._build_info_row("Source Last Seen", record.source_path_last_seen))
        payload_row = details_payload_location(record)
        if payload_row is not None:
            group.add(self._build_info_row(payload_row[0], payload_row[1]))
        return group

    def _build_advanced_group(self, record: ManagedAppRecord) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Advanced")
        expander = CompatExpanderRow("Technical Details")
        expander.set_enable_expansion(True)
        expander.set_expanded(False)
        expander.add_row(self._build_info_row("AppStream ID", record.appstream_id or "not found"))

        explanation = Gtk.Label(label="Used for app identity and update matching.")
        explanation.add_css_class("dim-label")
        explanation.set_wrap(True)
        explanation.set_xalign(0)
        explanation.set_margin_start(12)
        explanation.set_margin_end(12)
        explanation.set_margin_bottom(6)
        expander.add_row(explanation)

        expander.add_row(self._build_info_row("Internal ID", record.internal_id))
        expander.add_row(
            self._build_info_row("Desktop Basename", record.embedded_desktop_basename or "—")
        )
        expander.add_row(self._build_info_row("Installed At", record.installed_at))
        expander.add_row(self._build_info_row("Updated At", record.updated_at))
        group.add(expander.widget)
        return group

    def _build_validation_callout(self, messages: list[str]) -> Gtk.Box:
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        frame.add_css_class("details-section")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        header.append(icon)
        title = Gtk.Label(label="Validation Issues")
        title.add_css_class("title-5")
        title.set_xalign(0)
        header.append(title)
        frame.append(header)

        for message in messages:
            label = Gtk.Label(label=message)
            label.set_wrap(True)
            label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            label.set_xalign(0)
            label.set_selectable(True)
            frame.append(label)
        return frame

    def _build_info_row(
        self,
        title: str,
        value: str,
        *,
        suffix: Gtk.Widget | None = None,
    ) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        if hasattr(row, "set_use_markup"):
            row.set_use_markup(False)
        row.set_subtitle(value)
        if hasattr(row, "set_subtitle_selectable"):
            row.set_subtitle_selectable(True)
        if suffix is not None:
            row.add_suffix(suffix)
        row.set_activatable(False)
        return row

    def _desktop_file_exists(self, path: str | None) -> bool:
        return bool(path) and Path(path).exists()

    def _current_preset_id(self) -> str:
        return self._preset_index_to_id.get(self._preset_combo.get_selected(), "none")

    def _current_extra_args(self) -> list[str]:
        text = self._args_entry.get_text().strip()
        return shlex.split(text) if text else []

    def _current_state(self) -> dict[str, str]:
        return {
            "display_name": self._name_entry.get_text().strip(),
            "comment": self._comment_entry.get_text().strip(),
            "arg_preset_id": self._current_preset_id(),
            "extra_args": self._args_entry.get_text().strip(),
        }

    def _refresh_effective_command_preview(self) -> None:
        try:
            extra_args = self._current_extra_args()
            command = self._record_editor.build_effective_command(
                self._record,
                arg_preset_id=self._current_preset_id(),
                extra_args=extra_args,
            )
        except ValueError as exc:
            command = f"Could not build launch command: {exc}"
        self._effective_command_label.set_text(command)

    def _refresh_save_state(self) -> None:
        if self._saving:
            self._save_button.set_sensitive(False)
            return
        try:
            self._current_extra_args()
        except ValueError:
            self._save_button.set_sensitive(False)
            return
        self._save_button.set_sensitive(self._current_state() != self._initial_state)

    def _on_fields_changed(self, *_args) -> None:
        self._refresh_effective_command_preview()
        self._refresh_save_state()

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        try:
            extra_args = self._current_extra_args()
        except ValueError as exc:
            self._show_alert_dialog("Invalid arguments", f"Extra Arguments could not be parsed:\n\n{exc}")
            return

        request = ManagedRecordUpdateRequest(
            internal_id=self._record.internal_id,
            display_name=self._name_entry.get_text().strip() or self._record.display_name,
            comment=self._comment_entry.get_text(),
            arg_preset_id=self._current_preset_id(),
            extra_args=extra_args,
        )
        self._saving = True
        self._save_button.set_label("Saving…")
        self._refresh_save_state()

        def worker() -> None:
            try:
                updated_record = self._record_editor.update_record(request)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._apply_save_error, str(exc))
                return
            GLib.idle_add(self._apply_save_success, updated_record)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_save_success(self, updated_record: ManagedAppRecord) -> bool:
        self._saving = False
        self._on_saved(updated_record)
        self.destroy()
        return False

    def _apply_save_error(self, message: str) -> bool:
        self._saving = False
        self._save_button.set_label("Save")
        self._refresh_save_state()
        self._show_alert_dialog("Save failed", message)
        return False

    def _show_alert_dialog(self, title: str, body: str) -> None:
        dialog = CompatMessageDialog(self, title, body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present()

    def _open_desktop_file(self, _button: Gtk.Button) -> None:
        open_local_file_with_default_app(
            self,
            self._record.managed_desktop_path,
            label_for_errors="Desktop file",
        )
