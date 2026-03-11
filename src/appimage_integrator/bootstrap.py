from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

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
from appimage_integrator.services.update_discovery import UpdateDiscoveryService
from appimage_integrator.storage.metadata_store import MetadataStore


@dataclass(frozen=True)
class ServiceContainer:
    paths: AppPaths
    logger: Logger
    tooling: Tooling
    store: MetadataStore
    install_manager: InstallManager
    library_manager: LibraryManager
    runtime_service: ManagedAppRuntimeService
    repair_manager: RepairManager
    update_discovery: UpdateDiscoveryService


def build_service_container(
    paths: AppPaths | None = None,
    *,
    enable_console_logging: bool = True,
) -> ServiceContainer:
    paths = paths or AppPaths.default()
    paths.ensure_directories()
    logger = configure_logging(paths, enable_console=enable_console_logging)
    tooling = Tooling(logger)
    store = MetadataStore(paths)
    icon_resolver = IconResolver(paths)
    inspector = AppImageInspector(paths, tooling, icon_resolver)
    desktop_service = DesktopEntryService(tooling)
    id_resolver = IdResolver()
    runtime_service = ManagedAppRuntimeService(
        paths,
        inspector,
        desktop_service,
        icon_resolver,
        id_resolver,
    )
    install_manager = InstallManager(
        paths,
        inspector,
        desktop_service,
        icon_resolver,
        id_resolver,
        runtime_service,
        store,
        tooling,
    )
    library_manager = LibraryManager(
        store,
        runtime_service,
        desktop_service,
    )
    repair_manager = RepairManager(
        inspector,
        desktop_service,
        icon_resolver,
        runtime_service,
        store,
    )
    update_discovery = UpdateDiscoveryService(paths, inspector, id_resolver)
    return ServiceContainer(
        paths=paths,
        logger=logger,
        tooling=tooling,
        store=store,
        install_manager=install_manager,
        library_manager=library_manager,
        runtime_service=runtime_service,
        repair_manager=repair_manager,
        update_discovery=update_discovery,
    )
