from __future__ import annotations

import shutil
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gtk

from appimage_integrator.assets import APP_DESKTOP_ENTRY_PATH, APP_ICON_PATH, ICON_THEME_ROOT
from appimage_integrator.bootstrap import build_service_container
from appimage_integrator.config import APP_ID, APP_NAME
from appimage_integrator.paths import AppPaths
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
        self._ensure_desktop_integration()
        self._configure_app_icon()
        window = self.props.active_window
        if window is None:
            window = ApplicationWindow(self, self.services)
        window.set_icon_name(APP_ID)
        window.set_startup_id(APP_ID)
        window.set_title(APP_NAME)
        window.present()

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

    def _ensure_desktop_integration(self) -> None:
        self.paths.ensure_directories()

        desktop_target = self.paths.desktop_entries_dir / f"{APP_ID}.desktop"
        if APP_DESKTOP_ENTRY_PATH.exists():
            desktop_target.write_text(APP_DESKTOP_ENTRY_PATH.read_text(encoding="utf-8"), encoding="utf-8")

        icon_target = (
            Path.home()
            / ".local"
            / "share"
            / "icons"
            / "hicolor"
            / "512x512"
            / "apps"
            / f"{APP_ID}.png"
        )
        if APP_ICON_PATH.exists():
            icon_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(APP_ICON_PATH, icon_target)
