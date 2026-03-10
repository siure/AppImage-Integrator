from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gtk

from appimage_integrator.config import APP_ID
from appimage_integrator.logging_utils import configure_logging
from appimage_integrator.paths import AppPaths
from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.desktop_entry import DesktopEntryService
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.install_manager import InstallManager
from appimage_integrator.services.library_manager import LibraryManager
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.services.repair_manager import RepairManager
from appimage_integrator.services.tooling import Tooling
from appimage_integrator.storage.metadata_store import MetadataStore
from appimage_integrator.ui.application_window import ApplicationWindow


@dataclass
class ServiceContainer:
    paths: AppPaths
    logger: object
    tooling: Tooling
    store: MetadataStore
    install_manager: InstallManager
    library_manager: LibraryManager
    runtime_service: ManagedAppRuntimeService
    repair_manager: RepairManager


class AppImageIntegratorApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.paths = AppPaths.default()
        self.paths.ensure_directories()
        self.logger = configure_logging(self.paths)
        self.tooling = Tooling(self.logger)
        self.store = MetadataStore(self.paths)
        self.icon_resolver = IconResolver(self.paths)
        self.inspector = AppImageInspector(self.paths, self.tooling, self.icon_resolver)
        self.desktop_service = DesktopEntryService(self.tooling)
        self.id_resolver = IdResolver()
        self.runtime_service = ManagedAppRuntimeService(
            self.paths,
            self.inspector,
            self.desktop_service,
            self.icon_resolver,
            self.id_resolver,
        )
        self.install_manager = InstallManager(
            self.paths,
            self.inspector,
            self.desktop_service,
            self.icon_resolver,
            self.id_resolver,
            self.runtime_service,
            self.store,
            self.tooling,
        )
        self.library_manager = LibraryManager(
            self.store,
            self.runtime_service,
            self.desktop_service,
        )
        self.repair_manager = RepairManager(
            self.inspector,
            self.desktop_service,
            self.icon_resolver,
            self.runtime_service,
            self.store,
        )
        self.services = ServiceContainer(
            paths=self.paths,
            logger=self.logger,
            tooling=self.tooling,
            store=self.store,
            install_manager=self.install_manager,
            library_manager=self.library_manager,
            runtime_service=self.runtime_service,
            repair_manager=self.repair_manager,
        )
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
