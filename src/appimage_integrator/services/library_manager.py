from __future__ import annotations

import os
from pathlib import Path

from appimage_integrator.models import ManagedAppRecord
from appimage_integrator.services.desktop_entry import DesktopEntryService
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.storage.metadata_store import MetadataStore


class LibraryManager:
    def __init__(
        self,
        store: MetadataStore,
        runtime_service: ManagedAppRuntimeService,
        desktop_service: DesktopEntryService | None = None,
    ) -> None:
        self.store = store
        self.runtime_service = runtime_service
        self.desktop_service = desktop_service

    def list_records(self) -> list[ManagedAppRecord]:
        return sorted(self.store.load_all(), key=lambda record: record.display_name.lower())

    def validate_record(self, record: ManagedAppRecord) -> tuple[ManagedAppRecord, str, list[str]]:
        record = self.runtime_service.reconcile_record(record)
        issues: list[str] = []
        launch_blocked = False
        appimage_path = Path(record.managed_appimage_path)
        desktop_path = Path(record.managed_desktop_path)

        if not appimage_path.exists():
            issues.append("Managed AppImage is missing.")
            launch_blocked = True
        elif not os.access(appimage_path, os.X_OK):
            issues.append("Managed AppImage is not executable.")
            launch_blocked = True

        if not desktop_path.exists():
            issues.append("Desktop launcher is missing.")
            launch_blocked = True
        elif self.desktop_service:
            try:
                desktop_messages = self.desktop_service.validate_text(
                    desktop_path.read_text(encoding="utf-8", errors="replace")
                )
            except OSError as exc:
                desktop_messages = [f"Desktop launcher could not be read: {exc}"]
            if desktop_messages:
                issues.extend(f"Desktop launcher is invalid: {message}" for message in desktop_messages)
                launch_blocked = True

        if record.managed_icon_path and not Path(record.managed_icon_path).exists():
            issues.append("Managed icon is missing.")
        if issues:
            return (record, "error" if launch_blocked else "warning", issues)
        return (record, "ok", [])
