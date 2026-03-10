from __future__ import annotations

from pathlib import Path

from appimage_integrator.models import ManagedAppRecord
from appimage_integrator.storage.metadata_store import MetadataStore


class LibraryManager:
    def __init__(self, store: MetadataStore) -> None:
        self.store = store

    def list_records(self) -> list[ManagedAppRecord]:
        return sorted(self.store.load_all(), key=lambda record: record.display_name.lower())

    def validate_record(self, record: ManagedAppRecord) -> tuple[str, list[str]]:
        issues: list[str] = []
        if not Path(record.managed_appimage_path).exists():
            issues.append("Managed AppImage is missing.")
        if not Path(record.managed_desktop_path).exists():
            issues.append("Desktop launcher is missing.")
        if record.managed_icon_path and not Path(record.managed_icon_path).exists():
            issues.append("Managed icon is missing.")
        if issues:
            return ("error" if len(issues) > 1 else "warning", issues)
        return ("ok", [])
