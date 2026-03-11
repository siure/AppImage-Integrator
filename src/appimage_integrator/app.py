from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gtk

from appimage_integrator.bootstrap import build_service_container
from appimage_integrator.config import APP_ID
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
        window = self.props.active_window
        if window is None:
            window = ApplicationWindow(self, self.services)
        window.present()

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        css_path = (
            __import__("pathlib").Path(__file__).resolve().parent / "ui" / "style.css"
        )
        provider.load_from_path(str(css_path))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
