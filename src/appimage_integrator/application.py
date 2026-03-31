from __future__ import annotations
import shutil
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gtk

from appimage_integrator.assets import APP_ICON_PATH, ICON_THEME_ROOT
from appimage_integrator.bootstrap import build_service_container
from appimage_integrator.config import APP_ID, APP_NAME
from appimage_integrator.launcher import (
    build_app_desktop_text,
    current_appimage_path,
    install_self_appimage,
    install_self_command,
    resolve_launcher_command,
)
from appimage_integrator.paths import AppPaths
from appimage_integrator.self_integration import build_self_record, SELF_INTERNAL_ID
from appimage_integrator.ui.dialogs import CompatMessageDialog
from appimage_integrator.ui.application_window import ApplicationWindow


class AppImageIntegratorApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.paths = AppPaths.default()
        self.services = build_service_container(self.paths)
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app: Adw.Application) -> None:
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        self._load_css()
        self._configure_app_icon()
        window = self.props.active_window
        if window is None:
            window = ApplicationWindow(self, self.services)
        window.set_icon_name(APP_ID)
        window.set_startup_id(APP_ID)
        window.set_title(APP_NAME)
        window.present()
        self._ensure_desktop_integration(window)

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        css_path = (
            Path(__file__).resolve().parent / "ui" / "style.css"
        )
        provider.load_from_path(str(css_path))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _configure_app_icon(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        icon_theme = Gtk.IconTheme.get_for_display(display)
        icon_theme.add_search_path(str(ICON_THEME_ROOT))
        Gtk.Window.set_default_icon_name(APP_ID)

    def _ensure_desktop_integration(self, window: Gtk.Window) -> None:
        self.paths.ensure_directories()
        self._ensure_icon_integration()

        if self._should_offer_self_install():
            self._prompt_self_install(window)
            return

        if current_appimage_path() is None:
            launcher_command = resolve_launcher_command(self.paths)
            if launcher_command is None:
                self.services.logger.warning(
                    "Skipping desktop integration for %s because no concrete launcher path was resolved.",
                    APP_ID,
                )
                return
            self._write_app_desktop_entry(launcher_command)
            self._sync_self_library_record(launcher_command=launcher_command)
            self._refresh_desktop_metadata()
            return

        if self.paths.self_appimage_path.exists() and self.paths.self_command_path.exists():
            launcher_command = [str(self.paths.self_appimage_path)]
            self._write_app_desktop_entry(launcher_command)
            self._sync_self_library_record(
                source_path_last_seen=current_appimage_path(),
                launcher_command=launcher_command,
            )
            self._refresh_desktop_metadata()

    def _ensure_icon_integration(self) -> None:
        icon_target = self.paths.self_icon_path
        if APP_ICON_PATH.exists():
            icon_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(APP_ICON_PATH, icon_target)

    def _should_offer_self_install(self) -> bool:
        appimage_path = current_appimage_path()
        if appimage_path is None or not appimage_path.exists():
            return False
        if (
            self.paths.self_appimage_path.exists()
            and self.paths.self_command_path.exists()
            and (
                self.paths.self_desktop_entry_path.exists()
                or self.paths.legacy_self_desktop_entry_path.exists()
            )
        ):
            return False

        state = self._read_self_integration_state()
        return state != "dismissed"

    def _read_self_integration_state(self) -> str | None:
        if not self.paths.self_integration_state_path.exists():
            return None
        try:
            value = self.paths.self_integration_state_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None

    def _write_self_integration_state(self, value: str) -> None:
        self.paths.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.paths.self_integration_state_path.write_text(value + "\n", encoding="utf-8")

    def _prompt_self_install(self, window: Gtk.Window) -> None:
        dialog = CompatMessageDialog(
            window,
            "Install AppImage Integrator?",
            (
                "AppImage Integrator is running from an AppImage.\n\n"
                "Install a stable copy into your Applications folder, create a desktop launcher, "
                "and add a local command wrapper so managed launchers keep working even if this "
                "original AppImage is moved or deleted."
            ),
        )
        dialog.add_response("later", "Not Now")
        dialog.add_response("install", "Install")
        dialog.set_default_response("install")
        dialog.set_close_response("later")
        dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_self_install_response)
        dialog.present()

    def _on_self_install_response(self, dialog, response: str) -> None:
        if response != "install":
            self._write_self_integration_state("dismissed")
            return

        appimage_path = current_appimage_path()
        if appimage_path is None or not appimage_path.exists():
            self._show_self_install_result(
                "Install failed",
                "The current AppImage path could not be determined.",
            )
            return

        try:
            stable_appimage = install_self_appimage(self.paths, appimage_path)
            install_self_command(self.paths, stable_appimage)
            launcher_command = [str(stable_appimage)]
            self._write_app_desktop_entry(launcher_command)
            self._sync_self_library_record(
                source_path_last_seen=appimage_path,
                launcher_command=launcher_command,
            )
            self._refresh_desktop_metadata()
            self._write_self_integration_state("accepted")
        except OSError as exc:
            self._show_self_install_result(
                "Install failed",
                f"AppImage Integrator could not install itself.\n\n{exc}",
            )
            return

        self._show_self_install_result(
            "Installed",
            (
                "AppImage Integrator installed a stable AppImage copy, desktop launcher, and "
                "local command wrapper successfully."
            ),
        )

    def _show_self_install_result(self, title: str, body: str) -> None:
        dialog = CompatMessageDialog(self.props.active_window, title, body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present()

    def _write_app_desktop_entry(self, launcher_command: list[str]) -> None:
        desktop_target = self.paths.self_desktop_entry_path
        desktop_target.parent.mkdir(parents=True, exist_ok=True)
        desktop_target.write_text(build_app_desktop_text(launcher_command), encoding="utf-8")
        legacy_target = self.paths.legacy_self_desktop_entry_path
        if legacy_target != desktop_target:
            legacy_target.unlink(missing_ok=True)

    def _sync_self_library_record(
        self,
        *,
        source_path_last_seen: Path | None = None,
        launcher_command: list[str] | None = None,
    ) -> None:
        if not self.paths.self_appimage_path.exists():
            return

        existing = self.services.store.load(SELF_INTERNAL_ID)
        inspection = None
        try:
            inspection = self.services.install_manager.inspector.inspect(self.paths.self_appimage_path)
            record = build_self_record(
                self.paths,
                existing=existing,
                inspection=inspection,
                source_path_last_seen=source_path_last_seen,
                launcher_command=launcher_command,
            )
        except Exception as exc:  # noqa: BLE001
            self.services.logger.warning("Could not refresh self library record: %s", exc)
            record = build_self_record(
                self.paths,
                existing=existing,
                source_path_last_seen=source_path_last_seen,
                launcher_command=launcher_command,
            )
        finally:
            if inspection is not None:
                self.services.install_manager.inspector.cleanup(inspection)

        self.services.store.save(record)

    def _refresh_desktop_metadata(self) -> None:
        if self.services.tooling.tools.update_desktop_database:
            self.services.tooling.run(
                [self.services.tooling.tools.update_desktop_database, str(self.paths.desktop_entries_dir)]
            )
        if self.services.tooling.tools.gtk_update_icon_cache:
            icon_root = self.paths.icons_dir.parent.parent
            if icon_root.exists():
                self.services.tooling.run(
                    [self.services.tooling.tools.gtk_update_icon_cache, "-f", "-t", str(icon_root)]
                )
