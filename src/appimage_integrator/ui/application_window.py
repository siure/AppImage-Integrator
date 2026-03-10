from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from appimage_integrator.models import ManagedAppRecord
from appimage_integrator.ui.details_dialog import DetailsDialog
from appimage_integrator.ui.install_view import InstallView
from appimage_integrator.ui.library_view import LibraryView


class ApplicationWindow(Adw.ApplicationWindow):
    def __init__(self, application, services) -> None:
        super().__init__(application=application)
        self.services = services
        self.set_title("AppImage Integrator")
        self.set_default_size(1120, 760)

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar)

        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        open_button = Gtk.Button(label="Open AppImage")
        open_button.connect("clicked", self._open_appimage)
        header.pack_start(open_button)

        refresh_button = Gtk.Button(label="Refresh Library")
        refresh_button.connect("clicked", lambda _btn: self.refresh_library())
        header.pack_end(refresh_button)

        stack = Adw.ViewStack()
        self.stack = stack
        self.view_switcher = Adw.ViewSwitcher()
        self.view_switcher.set_stack(stack)
        header.set_title_widget(self.view_switcher)

        self.library_view = LibraryView(
            on_show_details=self.show_details,
            on_repair=self.repair_record,
            on_uninstall=self.uninstall_record,
        )
        self.install_view = InstallView(
            install_manager=services.install_manager,
            on_installed=self.refresh_library,
            toast=self.show_toast,
        )

        stack.add_titled(self.install_view, "install", "Install")
        stack.add_titled(self.library_view, "library", "Library")
        toolbar.set_content(stack)

        self.refresh_library()

    def show_toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def refresh_library(self) -> None:
        records = []
        for record in self.services.library_manager.list_records():
            status, messages = self.services.library_manager.validate_record(record)
            if status != record.last_validation_status or messages != record.last_validation_messages:
                record = ManagedAppRecord.from_dict(
                    {
                        **record.to_dict(),
                        "last_validation_status": status,
                        "last_validation_messages": messages,
                    }
                )
                self.services.store.save(record)
            records.append(record)
        self.library_view.set_records(records)

    def show_details(self, record: ManagedAppRecord) -> None:
        dialog = DetailsDialog(self, record)
        dialog.present(self)

    def repair_record(self, record: ManagedAppRecord) -> None:
        _, report = self.services.repair_manager.repair(record)
        source_path = Path(record.source_path_last_seen)
        if report.success:
            self._show_repair_result_dialog(
                title="Repair completed",
                body="The integration was repaired successfully.",
            )
        elif source_path.exists():
            self._prompt_reinstall_after_failed_repair(record, report)
        else:
            issue_text = "\n".join(report.issues) if report.issues else "No additional details were reported."
            self._show_repair_result_dialog(
                title="Repair failed",
                body=(
                    "The integration could not be repaired automatically.\n\n"
                    f"{issue_text}\n\n"
                    "Reinstall is not possible because the original AppImage is not present."
                ),
            )
        self.refresh_library()

    def uninstall_record(self, record: ManagedAppRecord) -> None:
        self.services.install_manager.uninstall(record)
        self.show_toast(f"Removed {record.display_name}")
        self.refresh_library()

    def reinstall_record(self, record: ManagedAppRecord) -> None:
        path = Path(record.source_path_last_seen)
        if not path.exists():
            self.show_toast("Original source file is no longer available. Choose a new AppImage.")
            return
        self.stack.set_visible_child(self.install_view)
        self.install_view.reinstall_record(record)

    def _prompt_reinstall_after_failed_repair(
        self,
        record: ManagedAppRecord,
        report,
    ) -> None:
        issue_text = "\n".join(report.issues) if report.issues else "No additional details were reported."
        dialog = Adw.AlertDialog.new(
            "Repair failed",
            "Repairing this integration automatically may require replacing files or restoring executable permissions.\n\n"
            "Only continue if you trust the original AppImage source.\n\n"
            "The integration could not be repaired automatically.\n\n"
            f"{issue_text}\n\n"
            "Do you want to reinstall from the original AppImage?",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reinstall", "Reinstall")
        dialog.set_default_response("reinstall")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("reinstall", Adw.ResponseAppearance.SUGGESTED)
        dialog.choose(
            self,
            None,
            self._on_failed_repair_reinstall_response,
            record,
        )

    def _on_failed_repair_reinstall_response(
        self,
        dialog: Adw.AlertDialog,
        result,
        record: ManagedAppRecord,
    ) -> None:
        response = dialog.choose_finish(result)
        if response != "reinstall":
            return
        self.reinstall_record(record)

    def _show_repair_result_dialog(self, title: str, body: str) -> None:
        dialog = Adw.AlertDialog.new(title, body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present(self)

    def _open_appimage(self, _button: Gtk.Button) -> None:
        self.install_view._open_file_chooser(_button)
