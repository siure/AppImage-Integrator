from __future__ import annotations

import os
import shlex
import threading
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk, Pango

from appimage_integrator.config import PRESET_LABELS
from appimage_integrator.models import AppImageInspection, InstallRequest, ManagedAppRecord
from appimage_integrator.ui.dialogs import (
    CompatFileChooserDialog,
    CompatMessageDialog,
    prompt_for_appimage_trust,
)
from appimage_integrator.ui.form_rows import CompatComboRow, CompatEntryRow, CompatExpanderRow


def inspection_can_install(inspection: AppImageInspection) -> bool:
    fatal_errors = [
        message
        for message in inspection.errors
        if message != "Could not extract AppImage contents."
    ]
    return inspection.is_appimage and not fatal_errors


class InstallView(Gtk.Box):
    def __init__(self, install_manager, on_installed, toast) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_hexpand(True)
        self.add_css_class("install-view")
        self.install_manager = install_manager
        self.on_installed = on_installed
        self.toast = toast
        self.current_source_path: Path | None = None
        self.current_inspection: AppImageInspection | None = None
        self.current_existing: ManagedAppRecord | None = None
        self.current_mode = "install"
        self._busy = False
        self._tech_rows: list[Gtk.Widget] = []

        self._build_compact_bar()
        self._build_editor_panel()
        self.reset()

    def _build_compact_bar(self) -> None:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.set_hexpand(True)
        bar.add_css_class("install-compact-bar")
        self.compact_bar = bar

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)

        title = Gtk.Label(label="Add AppImage", xalign=0)
        title.add_css_class("title-5")
        title.add_css_class("install-compact-title")
        text_box.append(title)

        hint = Gtk.Label(label="Browse or drop anywhere in the window", xalign=0)
        hint.add_css_class("dim-label")
        hint.add_css_class("install-compact-hint")
        text_box.append(hint)

        bar.append(text_box)

        self.source_label = Gtk.Label(label="No file selected", xalign=1)
        self.source_label.add_css_class("dim-label")
        self.source_label.add_css_class("install-source-label")
        self.source_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.source_label.set_max_width_chars(36)
        bar.append(self.source_label)

        browse_btn = Gtk.Button(label="Browse")
        browse_btn.add_css_class("suggested-action")
        browse_btn.add_css_class("install-browse-button")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.set_size_request(64, -1)
        browse_btn.connect("clicked", self._open_file_chooser)
        self.browse_button = browse_btn
        bar.append(browse_btn)

        self.append(bar)

    def _build_editor_panel(self) -> None:
        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_transition_duration(180)
        self.editor_revealer = revealer
        self.append(revealer)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.add_css_class("install-editor-card")
        card.set_hexpand(True)
        self.editor_card = card
        revealer.set_child(card)

        busy_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        busy_box.add_css_class("install-busy-row")
        busy_box.set_visible(False)
        self.busy_box = busy_box

        spinner = Gtk.Spinner()
        spinner.set_spinning(False)
        spinner.set_size_request(18, 18)
        self.busy_spinner = spinner
        busy_box.append(spinner)

        busy_label = Gtk.Label(label="", xalign=0)
        busy_label.add_css_class("dim-label")
        busy_label.set_hexpand(True)
        self.busy_label = busy_label
        busy_box.append(busy_label)

        card.append(busy_box)

        form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.form_box = form_box
        card.append(form_box)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.preview_icon = Gtk.Image.new_from_icon_name("application-x-executable")
        self.preview_icon.set_pixel_size(64)
        header.append(self.preview_icon)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        labels.set_hexpand(True)
        labels.set_valign(Gtk.Align.CENTER)

        self.name_label = Gtk.Label(label="", xalign=0)
        self.name_label.add_css_class("title-3")
        labels.append(self.name_label)

        self.comment_label = Gtk.Label(label="", xalign=0)
        self.comment_label.add_css_class("dim-label")
        self.comment_label.set_wrap(True)
        labels.append(self.comment_label)
        header.append(labels)

        form_box.append(header)

        display_group = Adw.PreferencesGroup(title="Display")
        self.name_entry = CompatEntryRow("Name")
        self.comment_entry = CompatEntryRow("Comment")
        display_group.add(self.name_entry.widget)
        display_group.add(self.comment_entry.widget)
        form_box.append(display_group)

        launch_group = Adw.PreferencesGroup(title="Launch Options")
        preset_labels = list(PRESET_LABELS.values())
        preset_model = Gtk.StringList.new(preset_labels)
        self.preset_combo = CompatComboRow("Preset", preset_model)
        labels_map = {value: key for key, value in PRESET_LABELS.items()}
        self._preset_index_to_id = {
            index: labels_map[label] for index, label in enumerate(preset_labels)
        }
        self._preset_id_to_index = {
            preset_id: index for index, preset_id in self._preset_index_to_id.items()
        }
        launch_group.add(self.preset_combo.widget)

        self.args_entry = CompatEntryRow("Extra Arguments")
        launch_group.add(self.args_entry.widget)
        form_box.append(launch_group)

        tech_group = Adw.PreferencesGroup(title="Technical Details")
        self.tech_expander = CompatExpanderRow("Detected Metadata")
        self.tech_expander.set_enable_expansion(True)
        self.tech_expander.set_expanded(False)
        tech_group.add(self.tech_expander.widget)
        form_box.append(tech_group)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_halign(Gtk.Align.END)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("pill")
        cancel_btn.connect("clicked", lambda _btn: self.reset())
        self.cancel_button = cancel_btn
        footer.append(cancel_btn)

        install_btn = Gtk.Button(label="Install")
        install_btn.add_css_class("pill")
        install_btn.add_css_class("suggested-action")
        install_btn.connect("clicked", self._on_install_clicked)
        self.install_button = install_btn
        footer.append(install_btn)

        form_box.append(footer)

        self._editable_widgets = [
            self.name_entry.widget,
            self.comment_entry.widget,
            self.preset_combo.widget,
            self.args_entry.widget,
            self.tech_expander.widget,
            self.cancel_button,
            self.install_button,
        ]

    def _show_editor(self, visible: bool) -> None:
        self.editor_revealer.set_reveal_child(visible)

    def _set_busy_state(self, message: str | None) -> None:
        busy = bool(message)
        self._busy = busy
        self.busy_box.set_visible(busy)
        self.busy_spinner.set_spinning(busy)
        self.busy_label.set_text(message or "")
        self._update_action_sensitivity()

    def _update_action_sensitivity(self) -> None:
        sensitive = not self._busy
        for widget in self._editable_widgets:
            widget.set_sensitive(sensitive)

        if self._busy:
            return

        if self.current_inspection is not None:
            self.install_button.set_sensitive(inspection_can_install(self.current_inspection))
            return

        if self.current_source_path is not None:
            self.install_button.set_sensitive(True)
            return

        self.install_button.set_sensitive(False)

    def _set_source_label(self, label: str | None = None) -> None:
        if label is not None:
            self.source_label.set_text(label)
            return
        if self.current_source_path is None:
            self.source_label.set_text("No file selected")
            return
        self.source_label.set_text(self.current_source_path.name)

    def _set_preview_icon(
        self,
        inspection: AppImageInspection | None = None,
        record: ManagedAppRecord | None = None,
    ) -> None:
        if inspection and inspection.chosen_icon_candidate:
            self.preview_icon.set_from_file(str(inspection.chosen_icon_candidate.source_path))
            return
        if record and record.managed_icon_path:
            self.preview_icon.set_from_file(record.managed_icon_path)
            return
        self.preview_icon.set_from_icon_name("application-x-executable")

    def _clear_tech_rows(self) -> None:
        for row in self._tech_rows:
            self.tech_expander.remove(row)
        self._tech_rows = []

    def _add_tech_row(self, title: str, value: str) -> None:
        row = Adw.ActionRow(title=title)
        if hasattr(row, "set_use_markup"):
            row.set_use_markup(False)
        row.set_subtitle(value)
        row.set_subtitle_selectable(True)
        self.tech_expander.add_row(row)
        self._tech_rows.append(row)

    def _show_alert_dialog(self, title: str, body: str) -> None:
        dialog = CompatMessageDialog(self, title, body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present()

    def _open_file_chooser(self, _button: Gtk.Button) -> None:
        dialog = CompatFileChooserDialog(
            self,
            title="Choose AppImage",
            accept_label="Inspect",
        )
        dialog.connect("response", self._on_file_chosen)
        dialog.present()

    def _on_file_chosen(self, dialog: CompatFileChooserDialog, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file and file.get_path():
                self.load_path(Path(file.get_path()))
        dialog.destroy()

    def load_path(self, path: Path) -> None:
        self.reset(clear_selection=False)
        self.current_source_path = path
        self._set_source_label()
        if not path.exists():
            self._show_alert_dialog(
                "AppImage not found",
                "The selected AppImage does not exist.",
            )
            self.reset()
            return
        if not os.access(path, os.X_OK):
            prompt_for_appimage_trust(
                self,
                path,
                self.install_manager.ensure_source_executable,
                title="Trust this AppImage before inspecting it?",
                body=(
                    "This AppImage is not executable yet. AppImage Integrator needs to mark it as executable "
                    "to extract metadata and inspect its embedded launcher.\n\n"
                    "Only continue if you trust the source of this AppImage. Running untrusted AppImages can be dangerous."
                ),
                on_trusted=lambda: self._on_source_trust_success(
                    "Executable permission updated",
                    "Marked the AppImage as executable. Review the metadata before installing.",
                    lambda: self._begin_inspection(path),
                ),
                on_cancel=lambda: self._on_source_trust_cancel(
                    "Inspection cancelled",
                    "The AppImage was left unchanged.",
                ),
                on_error=self._on_source_trust_error,
            )
            return
        self._begin_inspection(path)

    def reinstall_record(self, record: ManagedAppRecord) -> None:
        source_path = Path(record.source_path_last_seen)
        self.install_record_from_source(
            record,
            source_path,
            button_label="Reinstall",
            require_trust_prompt=False,
        )

    def install_record_from_source(
        self,
        record: ManagedAppRecord,
        source_path: Path,
        *,
        button_label: str,
        require_trust_prompt: bool,
    ) -> None:
        self.reset(clear_selection=False)
        self.current_source_path = source_path
        self._set_source_label()
        self._populate_record_fields(record, button_label)
        self._show_editor(True)

        if not source_path.exists():
            self._show_alert_dialog(
                "Original AppImage not found",
                "The original source file is no longer available.",
            )
            self.reset()
            return

        if not os.access(source_path, os.X_OK):
            if require_trust_prompt:
                prompt_for_appimage_trust(
                    self,
                    source_path,
                    self.install_manager.ensure_source_executable,
                    title="Trust this AppImage before updating it?",
                    body=(
                        "The selected AppImage is not executable yet. AppImage Integrator needs to mark it as executable "
                        "before updating this integration.\n\n"
                        "Only continue if you trust the source of this AppImage. Running untrusted AppImages can be dangerous."
                    ),
                    on_trusted=lambda: self._on_source_trust_success(
                        "Executable permission updated",
                        "Marked the selected AppImage as executable and continued with the update.",
                        lambda: self._submit_record_install(record, source_path),
                    ),
                    on_cancel=lambda: self._on_source_trust_cancel(
                        "Update cancelled",
                        "The selected AppImage was left unchanged.",
                    ),
                    on_error=self._on_source_trust_error,
                )
                return
            try:
                self.install_manager.ensure_source_executable(source_path)
            except OSError as exc:
                self._show_alert_dialog(
                    "Reinstall failed",
                    f"Could not mark the AppImage as executable:\n\n{exc}",
                )
                self.reset()
                return
            self._show_alert_dialog(
                "Executable permission updated",
                "Marked the original AppImage as executable for reinstall.",
            )

        self._submit_record_install(record, source_path)

    def _begin_inspection(self, path: Path) -> None:
        self.current_source_path = path
        self._show_editor(True)
        self._set_source_label()
        self._set_busy_state("Inspecting AppImage…")

        def worker() -> None:
            try:
                inspection, existing, mode = self.install_manager.inspect(path)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._apply_inspection_error, str(exc))
                return
            GLib.idle_add(self._apply_inspection, inspection, existing, mode)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_inspection(
        self,
        inspection: AppImageInspection,
        existing: ManagedAppRecord | None,
        mode: str,
    ) -> bool:
        self.current_inspection = inspection
        self.current_existing = existing
        self.current_mode = mode

        name = inspection.detected_name or (
            self.current_source_path.stem if self.current_source_path is not None else "AppImage"
        )
        comment = inspection.detected_comment or ""

        self.name_label.set_text(name)
        self.comment_label.set_text(comment or "Embedded metadata will be reused when possible.")
        self.name_entry.set_text(name)
        self.comment_entry.set_text(comment)
        self.install_button.set_label(mode.capitalize())
        self._set_preview_icon(inspection=inspection)
        self._populate_tech_details(inspection, existing)
        self._set_busy_state(None)
        self._show_editor(True)
        return False

    def _apply_inspection_error(self, message: str) -> bool:
        self._show_alert_dialog("Inspection failed", message)
        self.reset()
        return False

    def _populate_tech_details(
        self,
        inspection: AppImageInspection,
        existing: ManagedAppRecord | None,
    ) -> None:
        self._clear_tech_rows()

        details = [
            ("Source", str(inspection.source_path)),
            ("AppImage type", inspection.appimage_type),
            ("Desktop file", inspection.embedded_desktop_filename or "fallback"),
            ("AppStream ID", inspection.appstream_id or "not found"),
            ("Version", inspection.detected_version or "unknown"),
        ]
        if inspection.warnings:
            details.append(("Warnings", "; ".join(inspection.warnings)))
        if inspection.errors:
            details.append(("Errors", "; ".join(inspection.errors)))
        if existing:
            details.append(
                ("Existing", f"{existing.display_name} ({existing.version or 'unknown'})")
            )

        for title, value in details:
            self._add_tech_row(title, value)

    def _populate_record_fields(self, record: ManagedAppRecord, button_label: str) -> None:
        self.current_existing = record
        self.current_mode = button_label.lower()
        self.current_inspection = None
        self.name_label.set_text(record.display_name)
        self.comment_label.set_text(record.comment or "Reuse the current managed metadata.")
        self.name_entry.set_text(record.display_name)
        self.comment_entry.set_text(record.comment or "")
        self.args_entry.set_text(shlex.join(record.extra_args))
        self.preset_combo.set_selected(
            self._preset_id_to_index.get(record.arg_preset_id or "none", 0)
        )
        self.install_button.set_label(button_label)
        self._set_preview_icon(record=record)
        self._clear_tech_rows()
        self._add_tech_row(
            "Source",
            str(self.current_source_path) if self.current_source_path else "unknown",
        )
        self._add_tech_row("Existing", f"{record.display_name} ({record.version or 'unknown'})")
        self._add_tech_row("Desktop file", record.managed_desktop_path)
        self._set_busy_state(None)

    def _on_source_trust_cancel(self, title: str, body: str) -> None:
        self._show_alert_dialog(title, body)
        self.reset()

    def _on_source_trust_success(self, title: str, body: str, on_trusted) -> None:
        self._show_alert_dialog(title, body)
        on_trusted()

    def _on_source_trust_error(self, exc: OSError) -> None:
        self._show_alert_dialog(
            "Inspection failed",
            f"Could not mark the AppImage as executable:\n\n{exc}",
        )
        self.reset()

    def _on_install_clicked(self, _button: Gtk.Button) -> None:
        if self.current_source_path is None:
            return
        self._submit_install_request(
            InstallRequest(
                source_path=self.current_source_path,
                display_name_override=self.name_entry.get_text().strip() or None,
                comment_override=self.comment_entry.get_text().strip() or None,
                extra_args=shlex.split(self.args_entry.get_text().strip())
                if self.args_entry.get_text().strip()
                else [],
                arg_preset_id=self._preset_index_to_id.get(
                    self.preset_combo.get_selected(), "none"
                ),
                allow_update=True,
                allow_reinstall=True,
            )
        )

    def _submit_record_install(self, record: ManagedAppRecord, source_path: Path) -> None:
        self._submit_install_request(
            InstallRequest(
                source_path=source_path,
                display_name_override=record.display_name,
                comment_override=record.comment,
                extra_args=record.extra_args,
                arg_preset_id=record.arg_preset_id,
                allow_update=True,
                allow_reinstall=True,
            )
        )

    def _submit_install_request(self, request: InstallRequest) -> None:
        self._show_editor(True)
        self._set_busy_state("Installing…")

        def worker() -> None:
            try:
                result = self.install_manager.install(request)
                GLib.idle_add(self._apply_install_result, result)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._apply_install_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_install_result(self, result) -> bool:
        messages = [*result.warnings, *result.validation_messages]
        body = f"{result.record.display_name} was processed successfully."
        if messages:
            body += "\n\nWarnings:\n" + "\n".join(messages)
        self._show_alert_dialog(
            f"{result.mode.capitalize()} completed",
            body,
        )
        self.on_installed()
        self.reset(clear_selection=True)
        return False

    def _apply_install_error(self, message: str) -> bool:
        self._show_alert_dialog("Install failed", message)
        self._set_busy_state(None)
        self._show_editor(self.current_source_path is not None)
        return False

    def reset(self, clear_selection: bool = True) -> None:
        self.name_label.set_text("")
        self.comment_label.set_text("")
        self.name_entry.set_text("")
        self.comment_entry.set_text("")
        self.args_entry.set_text("")
        self.preset_combo.set_selected(0)
        self.install_button.set_label("Install")
        self.tech_expander.set_expanded(False)
        self.current_inspection = None
        self.current_existing = None
        self.current_mode = "install"
        self._clear_tech_rows()
        self._set_preview_icon()
        self._set_busy_state(None)
        if clear_selection:
            self.current_source_path = None
        self._set_source_label()
        self._show_editor(False)
        self._update_action_sensitivity()
