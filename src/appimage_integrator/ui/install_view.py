from __future__ import annotations

import os
import shlex
import threading
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk

from appimage_integrator.config import PRESET_LABELS, STEPPER_STEPS
from appimage_integrator.models import AppImageInspection, InstallRequest, ManagedAppRecord
from appimage_integrator.ui.widgets.drop_target import DropTargetFrame
from appimage_integrator.ui.widgets.status_stepper import StatusStepper


class InstallView(Gtk.Box):
    def __init__(self, install_manager, on_installed, toast) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)
        self.install_manager = install_manager
        self.on_installed = on_installed
        self.toast = toast
        self.current_source_path: Path | None = None
        self.current_inspection: AppImageInspection | None = None
        self.current_existing: ManagedAppRecord | None = None
        self.current_mode = "install"

        self.drop_target = DropTargetFrame(self.load_path)
        self.append(self.drop_target)

        choose_button = Gtk.Button(label="Choose AppImage")
        choose_button.add_css_class("suggested-action")
        choose_button.connect("clicked", self._open_file_chooser)
        self.append(choose_button)

        self.status_stepper = StatusStepper()
        self.append(self.status_stepper)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("card")
        card.set_margin_top(8)
        card.set_margin_bottom(8)
        card.set_margin_start(8)
        card.set_margin_end(8)
        self.append(card)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.preview_icon = Gtk.Image.new_from_icon_name("application-x-executable")
        self.preview_icon.set_pixel_size(72)
        header.append(self.preview_icon)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.name_label = Gtk.Label(label="No AppImage selected", xalign=0)
        self.name_label.add_css_class("title-3")
        self.comment_label = Gtk.Label(label="Select an AppImage to inspect embedded metadata.", xalign=0)
        self.comment_label.add_css_class("dim-label")
        labels.append(self.name_label)
        labels.append(self.comment_label)
        header.append(labels)
        card.append(header)

        details_expander = Gtk.Expander(label="Detected Metadata")
        self.metadata_label = Gtk.Label(xalign=0, selectable=True, wrap=True)
        self.metadata_label.add_css_class("monospace")
        details_expander.set_child(self.metadata_label)
        card.append(details_expander)

        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        card.append(grid)
        self.name_entry = Gtk.Entry(placeholder_text="Display name")
        self.comment_entry = Gtk.Entry(placeholder_text="Comment")
        self.args_entry = Gtk.Entry(placeholder_text="Extra launch arguments")
        self.preset_combo = Gtk.DropDown.new_from_strings(list(PRESET_LABELS.values()))
        labels_map = {value: key for key, value in PRESET_LABELS.items()}
        self._preset_index_to_id = {
            index: labels_map[label] for index, label in enumerate(PRESET_LABELS.values())
        }
        self._preset_id_to_index = {
            preset_id: index for index, preset_id in self._preset_index_to_id.items()
        }

        for row, (label_text, widget) in enumerate(
            (
                ("Name", self.name_entry),
                ("Comment", self.comment_entry),
                ("Extra args", self.args_entry),
                ("Preset", self.preset_combo),
            )
        ):
            label = Gtk.Label(label=label_text, xalign=0)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)

        self.install_button = Gtk.Button(label="Install")
        self.install_button.add_css_class("suggested-action")
        self.install_button.connect("clicked", self._on_install_clicked)
        self.install_button.set_sensitive(False)
        cancel_button = Gtk.Button(label="Clear")
        cancel_button.connect("clicked", lambda _btn: self.reset())
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.append(self.install_button)
        footer.append(cancel_button)
        card.append(footer)

    def _open_file_chooser(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative(
            title="Choose AppImage",
            transient_for=self.get_root(),
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Inspect",
            cancel_label="Cancel",
        )
        dialog.connect("response", self._on_file_chosen)
        dialog.show()

    def _on_file_chosen(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file and file.get_path():
                self.load_path(Path(file.get_path()))
        dialog.destroy()

    def load_path(self, path: Path) -> None:
        self.reset(clear_selection=False)
        self.current_source_path = path
        if not path.exists():
            self.toast("The selected AppImage does not exist.")
            self.reset()
            return
        if not os.access(path, os.X_OK):
            self._prompt_for_executable_trust(path)
            return
        self._begin_inspection(path)

    def reinstall_record(self, record: ManagedAppRecord) -> None:
        source_path = Path(record.source_path_last_seen)
        self.reset(clear_selection=False)
        self.current_source_path = source_path
        self.name_entry.set_text(record.display_name)
        self.comment_entry.set_text(record.comment or "")
        self.args_entry.set_text(shlex.join(record.extra_args))
        self.preset_combo.set_selected(
            self._preset_id_to_index.get(record.arg_preset_id or "none", 0)
        )
        self.install_button.set_label("Reinstall")

        if not source_path.exists():
            self.toast("Original source file is no longer available.")
            self.reset()
            return
        if not os.access(source_path, os.X_OK):
            try:
                self.install_manager.ensure_source_executable(source_path)
            except OSError as exc:
                self.toast(f"Could not mark the AppImage as executable: {exc}")
                self.reset()
                return
            self.toast("Marked the original AppImage as executable for reinstall.")

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

    def _begin_inspection(self, path: Path) -> None:
        self.current_source_path = path
        self.status_stepper.reset()
        self.status_stepper.set_step(STEPPER_STEPS[0], "running", "Checking file")
        self.install_button.set_sensitive(False)

        def worker() -> None:
            inspection, existing, mode = self.install_manager.inspect(path)
            GLib.idle_add(self._apply_inspection, inspection, existing, mode)

        threading.Thread(target=worker, daemon=True).start()

    def _prompt_for_executable_trust(self, path: Path) -> None:
        dialog = Adw.AlertDialog.new(
            "Trust this AppImage before inspecting it?",
            "This AppImage is not executable yet. AppImage Integrator needs to mark it as executable "
            "to extract metadata and inspect its embedded launcher.\n\n"
            "Only continue if you trust the source of this AppImage. Running untrusted AppImages can be dangerous.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("trust", "Trust and Continue")
        dialog.set_default_response("trust")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("trust", Adw.ResponseAppearance.SUGGESTED)
        dialog.choose(self.get_root(), None, self._on_trust_response, path)

    def _on_trust_response(
        self,
        dialog: Adw.AlertDialog,
        result,
        path: Path,
    ) -> None:
        response = dialog.choose_finish(result)
        if response != "trust":
            self.toast("Inspection cancelled. The AppImage was left unchanged.")
            self.reset()
            return
        try:
            self.install_manager.ensure_source_executable(path)
        except OSError as exc:
            self.toast(f"Could not mark the AppImage as executable: {exc}")
            self.reset()
            return
        self.toast("Marked the AppImage as executable. Review the metadata before installing.")
        self._begin_inspection(path)

    def _apply_inspection(
        self,
        inspection: AppImageInspection,
        existing: ManagedAppRecord | None,
        mode: str,
    ) -> bool:
        self.current_inspection = inspection
        self.current_existing = existing
        self.current_mode = mode
        self.status_stepper.set_step(STEPPER_STEPS[0], "success" if inspection.is_appimage else "warning")
        self.status_stepper.set_step(
            STEPPER_STEPS[1],
            "success" if inspection.extracted_dir else "warning",
            "metadata ready" if inspection.extracted_dir else "fallback only",
        )
        self.name_label.set_text(inspection.detected_name or self.current_source_path.stem)
        self.comment_label.set_text(inspection.detected_comment or "Embedded metadata will be reused when possible.")
        self.name_entry.set_text(inspection.detected_name or self.current_source_path.stem)
        self.comment_entry.set_text(inspection.detected_comment or "")
        self.install_button.set_label(mode.capitalize())
        self.install_button.set_sensitive(not inspection.errors or inspection.is_executable)
        if inspection.chosen_icon_candidate:
            self.preview_icon.set_from_file(str(inspection.chosen_icon_candidate.source_path))
        else:
            self.preview_icon.set_from_icon_name("application-x-executable")

        details = [
            f"Source: {inspection.source_path}",
            f"AppImage type: {inspection.appimage_type}",
            f"Desktop: {inspection.embedded_desktop_filename or 'fallback'}",
            f"AppStream ID: {inspection.appstream_id or 'not found'}",
            f"Version: {inspection.detected_version or 'unknown'}",
            f"Warnings: {'; '.join(inspection.warnings) if inspection.warnings else 'none'}",
            f"Errors: {'; '.join(inspection.errors) if inspection.errors else 'none'}",
        ]
        if existing:
            details.append(f"Existing integration: {existing.display_name} ({existing.version or 'unknown'})")
        self.metadata_label.set_text("\n".join(details))
        return False

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

    def _submit_install_request(self, request: InstallRequest) -> None:
        self.status_stepper.set_step(STEPPER_STEPS[2], "running", "Copying AppImage")
        self.status_stepper.set_step(STEPPER_STEPS[3], "running", "Resolving icon")
        self.status_stepper.set_step(STEPPER_STEPS[4], "running", "Writing launcher")
        self.status_stepper.set_step(STEPPER_STEPS[5], "running", "Saving metadata")
        self.install_button.set_sensitive(False)

        def worker() -> None:
            try:
                result = self.install_manager.install(request)
                GLib.idle_add(self._apply_install_result, result)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._apply_install_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_install_result(self, result) -> bool:
        for step in STEPPER_STEPS[2:]:
            self.status_stepper.set_step(step, "success")
        self.toast(f"{result.mode.capitalize()} completed for {result.record.display_name}")
        if result.warnings or result.validation_messages:
            self.toast("Install completed with warnings. Review the metadata panel for details.")
        self.on_installed()
        self.reset(clear_selection=True)
        return False

    def _apply_install_error(self, message: str) -> bool:
        for step in STEPPER_STEPS[2:]:
            self.status_stepper.set_step(step, "error")
        self.toast(f"Install failed: {message}")
        self.install_button.set_sensitive(True)
        return False

    def reset(self, clear_selection: bool = True) -> None:
        self.status_stepper.reset()
        self.name_label.set_text("No AppImage selected")
        self.comment_label.set_text("Select an AppImage to inspect embedded metadata.")
        self.metadata_label.set_text("")
        self.preview_icon.set_from_icon_name("application-x-executable")
        self.name_entry.set_text("")
        self.comment_entry.set_text("")
        self.args_entry.set_text("")
        self.preset_combo.set_selected(0)
        self.install_button.set_sensitive(False)
        self.install_button.set_label("Install")
        self.current_inspection = None
        self.current_existing = None
        self.current_mode = "install"
        if clear_selection:
            self.current_source_path = None
