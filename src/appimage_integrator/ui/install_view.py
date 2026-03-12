from __future__ import annotations

import os
import shlex
import threading
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from appimage_integrator.config import PRESET_LABELS
from appimage_integrator.models import AppImageInspection, InstallRequest, ManagedAppRecord
from appimage_integrator.ui.dialogs import CompatFileChooserDialog, CompatMessageDialog
from appimage_integrator.ui.form_rows import CompatComboRow, CompatEntryRow, CompatExpanderRow


class InstallView(Gtk.Box):
    """Four-page stack: empty → loading → form → progress."""

    def __init__(self, install_manager, on_installed, toast) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.add_css_class("install-view")
        self.install_manager = install_manager
        self.on_installed = on_installed
        self.toast = toast
        self.current_source_path: Path | None = None
        self.current_inspection: AppImageInspection | None = None
        self.current_existing: ManagedAppRecord | None = None
        self.current_mode = "install"

        # --- Drag-drop on the entire view ---
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_drop)
        drop_target.connect("enter", self._on_drag_enter)
        drop_target.connect("leave", self._on_drag_leave)
        self.add_controller(drop_target)

        # --- Stack pages ---
        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(200)
        self.append(self.stack)

        # Page: empty
        self._build_empty_page()
        # Page: loading
        self._build_loading_page()
        # Page: form
        self._build_form_page()
        # Page: progress
        self._build_progress_page()

        self.stack.set_visible_child_name("empty")

    # ------------------------------------------------------------------
    # Empty page
    # ------------------------------------------------------------------
    def _build_empty_page(self) -> None:
        browse_btn = Gtk.Button(label="Browse Files")
        browse_btn.add_css_class("pill")
        browse_btn.add_css_class("suggested-action")
        browse_btn.set_halign(Gtk.Align.CENTER)
        browse_btn.connect("clicked", self._open_file_chooser)
        self.stack.add_named(
            self._build_centered_status_page(
                icon_name="list-add-symbolic",
                title="Add an AppImage",
                description="Drop an AppImage here or browse for one",
                child=browse_btn,
            ),
            "empty",
        )

    # ------------------------------------------------------------------
    # Loading page
    # ------------------------------------------------------------------
    def _build_loading_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)

        spinner = Gtk.Spinner(spinning=True)
        spinner.set_size_request(48, 48)
        box.append(spinner)

        label = Gtk.Label(label="Inspecting AppImage…")
        label.add_css_class("title-4")
        box.append(label)

        self.stack.add_named(self._wrap_page(box), "loading")

    # ------------------------------------------------------------------
    # Form page
    # ------------------------------------------------------------------
    def _build_form_page(self) -> None:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_hexpand(True)
        page.set_vexpand(True)
        page.set_margin_top(24)
        page.set_margin_bottom(24)
        page.set_margin_start(12)
        page.set_margin_end(12)
        scrolled.set_child(page)

        form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        form_box.set_hexpand(True)
        page.append(form_box)

        # Icon + Name header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.set_margin_bottom(6)
        self.preview_icon = Gtk.Image.new_from_icon_name("application-x-executable")
        self.preview_icon.set_pixel_size(64)
        header.append(self.preview_icon)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        labels.set_valign(Gtk.Align.CENTER)
        self.name_label = Gtk.Label(label="", xalign=0)
        self.name_label.add_css_class("title-2")
        self.comment_label = Gtk.Label(label="", xalign=0)
        self.comment_label.add_css_class("dim-label")
        labels.append(self.name_label)
        labels.append(self.comment_label)
        header.append(labels)
        form_box.append(header)

        # --- Display group ---
        display_group = Adw.PreferencesGroup(title="Display")
        self.name_entry = CompatEntryRow("Name")
        self.comment_entry = CompatEntryRow("Comment")
        display_group.add(self.name_entry.widget)
        display_group.add(self.comment_entry.widget)
        form_box.append(display_group)

        # --- Launch Options group ---
        launch_group = Adw.PreferencesGroup(title="Launch Options")

        # Preset combo
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

        # --- Technical Details (collapsible) ---
        tech_group = Adw.PreferencesGroup(title="Technical Details")
        self.tech_expander = CompatExpanderRow("Detected Metadata")
        self.tech_expander.set_enable_expansion(True)
        self.tech_expander.set_expanded(False)
        tech_group.add(self.tech_expander.widget)
        form_box.append(tech_group)

        # --- Footer buttons ---
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_halign(Gtk.Align.END)
        footer.set_margin_top(6)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("pill")
        cancel_btn.connect("clicked", lambda _btn: self.reset())
        footer.append(cancel_btn)

        self.install_button = Gtk.Button(label="Install")
        self.install_button.add_css_class("pill")
        self.install_button.add_css_class("suggested-action")
        self.install_button.connect("clicked", self._on_install_clicked)
        self.install_button.set_sensitive(False)
        footer.append(self.install_button)

        form_box.append(footer)

        self.stack.add_named(scrolled, "form")

    # ------------------------------------------------------------------
    # Progress page
    # ------------------------------------------------------------------
    def _build_progress_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)

        spinner = Gtk.Spinner(spinning=True)
        spinner.set_size_request(48, 48)
        box.append(spinner)

        label = Gtk.Label(label="Installing…")
        label.add_css_class("title-4")
        self._progress_label = label
        box.append(label)

        self.stack.add_named(self._wrap_page(box), "progress")

    def _wrap_page(self, child: Gtk.Widget) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_hexpand(True)
        page.set_vexpand(True)
        page.append(child)
        return page

    def _build_centered_status_page(
        self,
        icon_name: str,
        title: str,
        description: str,
        child: Gtk.Widget | None = None,
    ) -> Gtk.Box:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_halign(Gtk.Align.CENTER)
        content.set_valign(Gtk.Align.CENTER)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(96)
        content.append(icon)

        title_label = Gtk.Label(label=title)
        title_label.add_css_class("title-1")
        content.append(title_label)

        description_label = Gtk.Label(label=description)
        description_label.add_css_class("dim-label")
        description_label.set_wrap(True)
        description_label.set_justify(Gtk.Justification.CENTER)
        content.append(description_label)

        if child is not None:
            content.append(child)

        return self._wrap_page(content)

    # ------------------------------------------------------------------
    # Drag-drop handlers
    # ------------------------------------------------------------------
    def _on_drop(self, _target: Gtk.DropTarget, value: Gdk.FileList, _x: float, _y: float) -> bool:
        self.remove_css_class("drop-highlight")
        files = value.get_files() if value else []
        if not files:
            return False
        path = files[0].get_path()
        if not path:
            return False
        self.load_path(Path(path))
        return True

    def _on_drag_enter(self, *_args) -> Gdk.DragAction:
        self.add_css_class("drop-highlight")
        return Gdk.DragAction.COPY

    def _on_drag_leave(self, *_args) -> None:
        self.remove_css_class("drop-highlight")

    # ------------------------------------------------------------------
    # File chooser
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    def load_path(self, path: Path) -> None:
        self.reset(clear_selection=False)
        self.current_source_path = path
        if not path.exists():
            self._show_alert_dialog(
                "AppImage not found",
                "The selected AppImage does not exist.",
            )
            self.reset()
            return
        if not os.access(path, os.X_OK):
            self._prompt_for_source_trust(
                path,
                on_trusted=lambda: self._begin_inspection(path),
                title="Trust this AppImage before inspecting it?",
                body=(
                    "This AppImage is not executable yet. AppImage Integrator needs to mark it as executable "
                    "to extract metadata and inspect its embedded launcher.\n\n"
                    "Only continue if you trust the source of this AppImage. Running untrusted AppImages can be dangerous."
                ),
                cancel_title="Inspection cancelled",
                cancel_body="The AppImage was left unchanged.",
                success_title="Executable permission updated",
                success_body="Marked the AppImage as executable. Review the metadata before installing.",
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
        self._populate_record_fields(record, button_label)

        if not source_path.exists():
            self._show_alert_dialog(
                "Original AppImage not found",
                "The original source file is no longer available.",
            )
            self.reset()
            return

        if not os.access(source_path, os.X_OK):
            if require_trust_prompt:
                self._prompt_for_source_trust(
                    source_path,
                    on_trusted=lambda: self._submit_record_install(record, source_path),
                    title="Trust this AppImage before updating it?",
                    body=(
                        "The selected AppImage is not executable yet. AppImage Integrator needs to mark it as executable "
                        "before updating this integration.\n\n"
                        "Only continue if you trust the source of this AppImage. Running untrusted AppImages can be dangerous."
                    ),
                    cancel_title="Update cancelled",
                    cancel_body="The selected AppImage was left unchanged.",
                    success_title="Executable permission updated",
                    success_body="Marked the selected AppImage as executable and continued with the update.",
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

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    def _begin_inspection(self, path: Path) -> None:
        self.current_source_path = path
        self.stack.set_visible_child_name("loading")

        def worker() -> None:
            inspection, existing, mode = self.install_manager.inspect(path)
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

        name = inspection.detected_name or self.current_source_path.stem
        comment = inspection.detected_comment or ""

        self.name_label.set_text(name)
        self.comment_label.set_text(comment or "Embedded metadata will be reused when possible.")
        self.name_entry.set_text(name)
        self.comment_entry.set_text(comment)
        self.install_button.set_label(mode.capitalize())
        self.install_button.set_sensitive(not inspection.errors or inspection.is_executable)

        if inspection.chosen_icon_candidate:
            self.preview_icon.set_from_file(str(inspection.chosen_icon_candidate.source_path))
        else:
            self.preview_icon.set_from_icon_name("application-x-executable")

        # Populate technical details expander
        self._populate_tech_details(inspection, existing)

        self.stack.set_visible_child_name("form")
        return False

    def _populate_tech_details(
        self,
        inspection: AppImageInspection,
        existing: ManagedAppRecord | None,
    ) -> None:
        # Clear previous rows
        # ExpanderRow does not expose a clear method for rows added with add_row.
        # Keep track of the rows we add and remove only those on refresh.

        # Remove previously added rows
        if hasattr(self, "_tech_rows"):
            for row in self._tech_rows:
                self.tech_expander.remove(row)
        self._tech_rows = []

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
            details.append(("Existing", f"{existing.display_name} ({existing.version or 'unknown'})"))

        for title, value in details:
            row = Adw.ActionRow(title=title)
            if hasattr(row, "set_use_markup"):
                row.set_use_markup(False)
            row.set_subtitle(value)
            row.set_subtitle_selectable(True)
            self.tech_expander.add_row(row)
            self._tech_rows.append(row)

    # ------------------------------------------------------------------
    # Trust prompt
    # ------------------------------------------------------------------
    def _prompt_for_source_trust(
        self,
        path: Path,
        *,
        on_trusted,
        title: str,
        body: str,
        cancel_title: str,
        cancel_body: str,
        success_title: str,
        success_body: str,
    ) -> None:
        dialog = CompatMessageDialog(self, title, body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("trust", "Trust and Continue")
        dialog.set_default_response("trust")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("trust", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect(
            "response",
            self._on_source_trust_response,
            path,
            on_trusted,
            cancel_title,
            cancel_body,
            success_title,
            success_body,
        )
        dialog.present()

    def _on_source_trust_response(
        self,
        dialog,
        response: str,
        path: Path,
        on_trusted,
        cancel_title: str,
        cancel_body: str,
        success_title: str,
        success_body: str,
    ) -> None:
        if response != "trust":
            self._show_alert_dialog(cancel_title, cancel_body)
            self.reset()
            return
        try:
            self.install_manager.ensure_source_executable(path)
        except OSError as exc:
            self._show_alert_dialog(
                "Inspection failed",
                f"Could not mark the AppImage as executable:\n\n{exc}",
            )
            self.reset()
            return
        self._show_alert_dialog(success_title, success_body)
        on_trusted()

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------
    def _on_install_clicked(self, _button: Gtk.Button) -> None:
        if self.current_source_path is None:
            return
        self._submit_install_request(
            InstallRequest(
                source_path=self.current_source_path,
                display_name_override=self.name_entry.get_text().strip() or None,
                comment_override=self.comment_entry.get_text().strip() or None,
                extra_args=shlex.split(self.args_entry.get_text().strip()) if self.args_entry.get_text().strip() else [],
                arg_preset_id=self._preset_index_to_id.get(self.preset_combo.get_selected(), "none"),
                allow_update=True,
                allow_reinstall=True,
            )
        )

    def _populate_record_fields(self, record: ManagedAppRecord, button_label: str) -> None:
        self.name_entry.set_text(record.display_name)
        self.comment_entry.set_text(record.comment or "")
        self.args_entry.set_text(shlex.join(record.extra_args))
        self.preset_combo.set_selected(
            self._preset_id_to_index.get(record.arg_preset_id or "none", 0)
        )
        self.install_button.set_label(button_label)
        self.stack.set_visible_child_name("form")

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
        self._progress_label.set_text("Installing…")
        self.stack.set_visible_child_name("progress")

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
        self.stack.set_visible_child_name("form")
        self.install_button.set_sensitive(True)
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _show_alert_dialog(self, title: str, body: str) -> None:
        dialog = CompatMessageDialog(self, title, body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present()

    def reset(self, clear_selection: bool = True) -> None:
        self.name_label.set_text("")
        self.comment_label.set_text("")
        self.name_entry.set_text("")
        self.comment_entry.set_text("")
        self.args_entry.set_text("")
        self.preset_combo.set_selected(0)
        self.install_button.set_sensitive(False)
        self.install_button.set_label("Install")
        self.preview_icon.set_from_icon_name("application-x-executable")
        if hasattr(self, "_tech_rows"):
            for row in self._tech_rows:
                self.tech_expander.remove(row)
            self._tech_rows = []
        self.tech_expander.set_expanded(False)
        self.current_inspection = None
        self.current_existing = None
        self.current_mode = "install"
        if clear_selection:
            self.current_source_path = None
        self.stack.set_visible_child_name("empty")
