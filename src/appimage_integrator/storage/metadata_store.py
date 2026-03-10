from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from appimage_integrator.models import ManagedAppRecord
from appimage_integrator.paths import AppPaths


class MetadataStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure_directories()

    def _atomic_write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(path)

    def _record_path(self, internal_id: str) -> Path:
        return self.paths.metadata_apps_dir / f"{internal_id}.json"

    def save(self, record: ManagedAppRecord) -> None:
        self._atomic_write_json(self._record_path(record.internal_id), record.to_dict())
        index = self.load_index()
        index[record.internal_id] = {
            "display_name": record.display_name,
            "version": record.version,
            "managed_appimage_path": record.managed_appimage_path,
            "managed_desktop_path": record.managed_desktop_path,
            "managed_icon_path": record.managed_icon_path,
            "last_validation_status": record.last_validation_status,
        }
        self._atomic_write_json(self.paths.metadata_index_path, index)

    def load(self, internal_id: str) -> ManagedAppRecord | None:
        path = self._record_path(internal_id)
        if not path.exists():
            return None
        return ManagedAppRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def delete(self, internal_id: str) -> None:
        path = self._record_path(internal_id)
        if path.exists():
            path.unlink()
        index = self.load_index()
        if internal_id in index:
            del index[internal_id]
            self._atomic_write_json(self.paths.metadata_index_path, index)

    def load_all(self) -> list[ManagedAppRecord]:
        records: list[ManagedAppRecord] = []
        for path in sorted(self.paths.metadata_apps_dir.glob("*.json")):
            try:
                records.append(ManagedAppRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return records

    def load_index(self) -> dict[str, dict]:
        if not self.paths.metadata_index_path.exists():
            return self.rebuild_index()
        try:
            return json.loads(self.paths.metadata_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return self.rebuild_index()

    def rebuild_index(self) -> dict[str, dict]:
        index: dict[str, dict] = {}
        for record in self.load_all():
            index[record.internal_id] = {
                "display_name": record.display_name,
                "version": record.version,
                "managed_appimage_path": record.managed_appimage_path,
                "managed_desktop_path": record.managed_desktop_path,
                "managed_icon_path": record.managed_icon_path,
                "last_validation_status": record.last_validation_status,
            }
        self._atomic_write_json(self.paths.metadata_index_path, index)
        return index
