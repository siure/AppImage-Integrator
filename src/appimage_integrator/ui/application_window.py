from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk

from appimage_integrator.assets import APP_BRAND_LOGO_PATH
from appimage_integrator.config import APP_NAME
from appimage_integrator.models import ManagedAppRecord
from appimage_integrator.ui.containers import CompatToolbarView
from appimage_integrator.ui.dialogs import CompatMessageDialog
from appimage_integrator.ui.details_dialog import DetailsDialog
from appimage_integrator.ui.install_view import InstallView
from appimage_integrator.ui.library_view import LibraryView


class ApplicationWindow(Adw.ApplicationWindow):
    def __init__(self, application, services) -> None:
        super().__init__(application=application)
        self.services = services
        self._update_progress_dialog: Gtk.Window | None = None
        self._update_progress_title: Gtk.Label | None = None
        self._update_progress_detail: Gtk.Label | None = None
        self._update_progress_bar: Gtk.ProgressBar | None = None
        self._update_progress_pulse_id: int | None = None
        self.add_css_class("integrator-window")
        self.set_title(APP_NAME)
        self.set_default_size(900, 650)

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar = CompatToolbarView(self)
        self.toast_overlay.set_child(toolbar.widget)

        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        brand.add_css_class("app-brand")

        if APP_BRAND_LOGO_PATH.exists():
            logo = Gtk.Image.new_from_file(str(APP_BRAND_LOGO_PATH))
            logo.set_pixel_size(18)
        else:
            logo = Gtk.Image.new_from_icon_name("application-x-executable")
            logo.set_pixel_size(18)
        logo.add_css_class("app-brand-logo")
        brand.append(logo)

        brand_label = Gtk.Label(label=APP_NAME, xalign=0)
        brand_label.add_css_class("app-brand-label")
        brand.append(brand_label)
        header.pack_start(brand)

        # Icon-only refresh button
        refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text("Refresh Library")
        refresh_button.add_css_class("flat")
        refresh_button.connect("clicked", lambda _btn: self.refresh_library())
        header.pack_end(refresh_button)

        # ViewSwitcher in center
        self.stack = Adw.ViewStack()
        self.view_switcher = Adw.ViewSwitcher()
        self.view_switcher.set_stack(self.stack)
        header.set_title_widget(self.view_switcher)

        self.library_view = LibraryView(
            on_launch=self.launch_record,
            on_update=self.update_record,
            on_show_details=self.show_details,
            on_repair=self.repair_record,
            on_uninstall=self.uninstall_record,
        )
        self.install_view = InstallView(
            install_manager=services.install_manager,
            on_installed=self.refresh_library,
            toast=self.show_toast,
        )

        self._add_stack_page(self.install_view, "install", "Install", "list-add-symbolic")
        self._add_stack_page(self.library_view, "library", "Library", "folder-symbolic")
        toolbar.set_content(self.stack)

        # Auto-refresh library when switching tabs
        self.stack.connect("notify::visible-child", self._on_tab_switched)

        self.refresh_library()

    def _add_stack_page(self, child: Gtk.Widget, name: str, title: str, icon_name: str) -> None:
        if hasattr(self.stack, "add_titled_with_icon"):
            self.stack.add_titled_with_icon(child, name, title, icon_name)
            return
        page = self.stack.add_titled(child, name, title)
        if hasattr(page, "set_icon_name"):
            page.set_icon_name(icon_name)

    def _on_tab_switched(self, stack: Adw.ViewStack, _pspec) -> None:
        if stack.get_visible_child() is self.library_view:
            self.refresh_library()

    def show_toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def refresh_library(self) -> None:
        records = []
        for record in self.services.library_manager.list_records():
            record = self._sync_record_validation(record)
            records.append(record)
        self.library_view.set_records(records)

    def launch_record(self, record: ManagedAppRecord) -> None:
        record = self._sync_record_validation(record)
        if record.last_validation_status == "error":
            self.refresh_library()
            self._prompt_issue_resolution(
                record,
                title="This AppImage needs attention",
                intro="The managed integration is not healthy enough to launch right now.",
            )
            return
        try:
            subprocess.Popen([record.managed_appimage_path])
        except OSError as exc:
            issue = self._format_launch_error(exc)
            record = self._update_record_validation(record, "error", [issue])
            self.refresh_library()
            self._prompt_issue_resolution(
                record,
                title="Launching failed",
                intro="AppImage Integrator could not start this managed AppImage.",
            )

    def show_details(self, record: ManagedAppRecord) -> None:
        dialog = DetailsDialog(self, record)
        dialog.present()

    def update_record(self, record: ManagedAppRecord) -> None:
        self._show_update_progress_dialog(record)

        def worker() -> None:
            try:
                discovery = self.services.update_discovery.discover_updates(
                    record,
                    progress_callback=lambda title, detail: GLib.idle_add(
                        self._set_update_progress_status,
                        title,
                        detail,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._finish_update_discovery, record, None, str(exc))
                return
            GLib.idle_add(self._finish_update_discovery, record, discovery, None)

        threading.Thread(target=worker, daemon=True).start()

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
        dialog = CompatMessageDialog(
            self,
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
        dialog.connect("response", self._on_failed_repair_reinstall_response, record)
        dialog.present()

    def _on_failed_repair_reinstall_response(
        self,
        dialog,
        response: str,
        record: ManagedAppRecord,
    ) -> None:
        if response != "reinstall":
            return
        self.reinstall_record(record)

    def _show_repair_result_dialog(self, title: str, body: str) -> None:
        dialog = CompatMessageDialog(self, title, body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present()

    def _sync_record_validation(self, record: ManagedAppRecord) -> ManagedAppRecord:
        validated_record, status, messages = self.services.library_manager.validate_record(record)
        if status == validated_record.last_validation_status and messages == validated_record.last_validation_messages:
            if validated_record != record:
                self.services.store.save(validated_record)
            return validated_record
        return self._update_record_validation(validated_record, status, messages)

    def _update_record_validation(
        self,
        record: ManagedAppRecord,
        status: str,
        messages: list[str],
    ) -> ManagedAppRecord:
        updated_record = ManagedAppRecord.from_dict(
            {
                **record.to_dict(),
                "last_validation_status": status,
                "last_validation_messages": messages,
            }
        )
        self.services.store.save(updated_record)
        return updated_record

    def _prompt_issue_resolution(
        self,
        record: ManagedAppRecord,
        title: str,
        intro: str,
    ) -> None:
        appimage_exists = Path(record.managed_appimage_path).exists()
        source_exists = Path(record.source_path_last_seen).exists()

        lines = [intro, "", *record.last_validation_messages]
        if appimage_exists:
            lines.extend(("", "Choose Repair to restore executable permissions and recreate launcher files."))
        elif source_exists:
            lines.extend(("", "Repair needs the managed AppImage. Reinstall from the original source instead."))
        else:
            lines.extend(("", "Automatic recovery is not possible because the original source file is unavailable."))

        dialog = CompatMessageDialog(self, title, "\n".join(lines))
        dialog.add_response("cancel", "Cancel")
        if appimage_exists:
            dialog.add_response("repair", "Repair")
            dialog.set_default_response("repair")
            dialog.set_response_appearance("repair", Adw.ResponseAppearance.SUGGESTED)
        if not appimage_exists and source_exists:
            dialog.add_response("reinstall", "Reinstall")
            dialog.set_default_response("reinstall")
            dialog.set_response_appearance("reinstall", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_issue_resolution_response, record)
        dialog.present()

    def _on_issue_resolution_response(
        self,
        dialog,
        response: str,
        record: ManagedAppRecord,
    ) -> None:
        if response == "repair":
            self.repair_record(record)
            return
        if response == "reinstall":
            self.reinstall_record(record)

    def _format_launch_error(self, exc: OSError) -> str:
        if isinstance(exc, FileNotFoundError):
            return "Managed AppImage is missing."
        if isinstance(exc, PermissionError):
            return "Managed AppImage is not executable."
        return f"Launching failed: {exc}"

    def _show_update_progress_dialog(self, record: ManagedAppRecord) -> None:
        self._close_update_progress_dialog()

        dialog = Gtk.Window(
            title="Searching for updates",
            transient_for=self,
            modal=True,
            resizable=False,
            decorated=False,
        )
        dialog.add_css_class("update-progress-dialog")
        dialog.set_default_size(420, -1)

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        frame.add_css_class("floating-panel")
        frame.set_margin_top(24)
        frame.set_margin_bottom(24)
        frame.set_margin_start(24)
        frame.set_margin_end(24)

        spinner = Gtk.Spinner(spinning=True)
        spinner.set_halign(Gtk.Align.CENTER)
        spinner.set_size_request(40, 40)
        frame.append(spinner)

        title = Gtk.Label(label=f"Searching for updates for {record.display_name}")
        title.add_css_class("title-4")
        title.set_wrap(True)
        title.set_justify(Gtk.Justification.CENTER)
        title.set_halign(Gtk.Align.CENTER)
        frame.append(title)

        detail = Gtk.Label(label="Preparing search…")
        detail.add_css_class("dim-label")
        detail.set_wrap(True)
        detail.set_justify(Gtk.Justification.CENTER)
        detail.set_halign(Gtk.Align.CENTER)
        frame.append(detail)

        progress = Gtk.ProgressBar()
        progress.set_hexpand(True)
        progress.pulse()
        frame.append(progress)

        dialog.set_child(frame)
        dialog.present()

        self._update_progress_dialog = dialog
        self._update_progress_title = title
        self._update_progress_detail = detail
        self._update_progress_bar = progress
        self._update_progress_pulse_id = GLib.timeout_add(120, self._pulse_update_progress)

    def _pulse_update_progress(self) -> bool:
        if self._update_progress_bar is None:
            return False
        self._update_progress_bar.pulse()
        return True

    def _set_update_progress_status(self, title: str, detail: str) -> bool:
        if self._update_progress_title is not None:
            self._update_progress_title.set_text(title)
        if self._update_progress_detail is not None:
            self._update_progress_detail.set_text(detail)
        return False

    def _close_update_progress_dialog(self) -> None:
        if self._update_progress_pulse_id is not None:
            GLib.source_remove(self._update_progress_pulse_id)
            self._update_progress_pulse_id = None
        if self._update_progress_dialog is not None:
            self._update_progress_dialog.close()
        self._update_progress_dialog = None
        self._update_progress_title = None
        self._update_progress_detail = None
        self._update_progress_bar = None

    def _finish_update_discovery(
        self,
        record: ManagedAppRecord,
        discovery,
        error_message: str | None,
    ) -> bool:
        self._close_update_progress_dialog()
        if error_message is not None:
            self._show_repair_result_dialog(
                "Update search failed",
                f"AppImage Integrator could not complete the update search.\n\n{error_message}",
            )
            return False
        assert discovery is not None
        return self._present_update_discovery(record, discovery)

    def _present_update_discovery(self, record: ManagedAppRecord, discovery) -> bool:
        if discovery.higher_version_candidates:
            candidate = discovery.higher_version_candidates[0]
            lines = [
                f"Current version: {record.version or 'unknown'}",
                f"Detected version: {candidate.detected_version or 'unknown'}",
                f"File: {candidate.path.name}",
                f"Location: {candidate.path.parent}",
                f"Match: {'identity-based' if candidate.match_kind == 'identity' else 'filename fallback'}",
            ]
            if len(discovery.higher_version_candidates) > 1:
                lines.extend(("", "Additional matching AppImages were also found."))
            dialog = CompatMessageDialog(self, "Update available", "\n".join(lines))
            dialog.add_response("cancel", "Do Nothing")
            dialog.add_response("choose", "Choose AppImage")
            dialog.add_response("update", "Update")
            dialog.set_default_response("update")
            dialog.set_close_response("cancel")
            dialog.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect(
                "response",
                self._on_update_discovery_response,
                record,
                candidate.path,
            )
            dialog.present()
            return False

        searched = "\n".join(str(path) for path in discovery.searched_directories) or "No searchable directories were available."
        dialog = CompatMessageDialog(
            self,
            "No newer AppImage found",
            "AppImage Integrator could not find a higher-version AppImage automatically.\n\n"
            f"Searched:\n{searched}\n\n"
            "Choose an AppImage manually if you want to update from a different file.",
        )
        dialog.add_response("cancel", "Do Nothing")
        dialog.add_response("choose", "Choose AppImage")
        dialog.set_default_response("choose")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("choose", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_no_update_found_response, record)
        dialog.present()
        return False

    def _on_update_discovery_response(
        self,
        dialog,
        response: str,
        record: ManagedAppRecord,
        candidate_path: Path,
    ) -> None:
        if response == "update":
            self._begin_update_install(record, candidate_path)
            return
        if response == "choose":
            self._open_update_file_chooser(record)

    def _on_no_update_found_response(
        self,
        dialog,
        response: str,
        record: ManagedAppRecord,
    ) -> None:
        if response == "choose":
            self._open_update_file_chooser(record)

    def _open_update_file_chooser(self, record: ManagedAppRecord) -> None:
        dialog = Gtk.FileChooserNative(
            title="Choose AppImage Update",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Update",
            cancel_label="Cancel",
        )
        dialog.connect("response", self._on_update_file_chosen, record)
        dialog.show()

    def _on_update_file_chosen(
        self,
        dialog: Gtk.FileChooserNative,
        response: int,
        record: ManagedAppRecord,
    ) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file and file.get_path():
                self._begin_manual_update_install(record, Path(file.get_path()))
        dialog.destroy()

    def _begin_update_install(self, record: ManagedAppRecord, source_path: Path) -> None:
        self.stack.set_visible_child(self.install_view)
        self.install_view.install_record_from_source(
            record,
            source_path,
            button_label="Update",
            require_trust_prompt=True,
        )

    def _begin_manual_update_install(self, record: ManagedAppRecord, source_path: Path) -> None:
        try:
            matched_candidate = self.services.update_discovery.evaluate_candidate(record, source_path)
        except OSError as exc:
            self._show_repair_result_dialog(
                "Update file could not be inspected",
                f"AppImage Integrator could not inspect the selected AppImage.\n\n{exc}",
            )
            return
        if matched_candidate is None:
            self._show_repair_result_dialog(
                "AppImage does not match",
                "The selected AppImage does not appear to be the same application as the managed integration.",
            )
            return
        self._begin_update_install(record, source_path)
