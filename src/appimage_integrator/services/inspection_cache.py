from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from appimage_integrator.models import (
    AppImageInspection,
    AppImageInspectionCacheKey,
    CachedAppImageInspection,
    IdentityResolution,
)
from appimage_integrator.paths import AppPaths

SCHEMA_VERSION = 1


class InspectionCache:
    def __init__(self, paths: AppPaths, *, max_entries: int = 512) -> None:
        self.paths = paths
        self.max_entries = max_entries
        self._entries: dict[str, dict[str, Any]] | None = None

    def get(self, path: Path) -> CachedAppImageInspection | None:
        try:
            key = self._key_for_path(path)
        except OSError:
            return None
        entry = self._load_entries().get(key.resolved_path)
        if not isinstance(entry, dict):
            return None
        if entry.get("size") != key.size or entry.get("mtime_ns") != key.mtime_ns:
            return None
        inspection_payload = entry.get("inspection")
        if not isinstance(inspection_payload, dict):
            return None
        try:
            return CachedAppImageInspection.from_dict(inspection_payload)
        except (TypeError, KeyError):
            return None

    def put(
        self,
        path: Path,
        inspection: AppImageInspection,
        identity: IdentityResolution,
    ) -> None:
        try:
            key = self._key_for_path(path)
        except OSError:
            return
        cached = CachedAppImageInspection(
            source_path=str(inspection.source_path),
            is_appimage=inspection.is_appimage,
            appimage_type=inspection.appimage_type,
            is_executable=inspection.is_executable,
            detected_name=inspection.detected_name,
            detected_comment=inspection.detected_comment,
            detected_version=inspection.detected_version,
            appstream_id=inspection.appstream_id,
            embedded_desktop_filename=inspection.embedded_desktop_filename,
            startup_wm_class=inspection.startup_wm_class,
            mime_types=list(inspection.mime_types),
            categories=list(inspection.categories),
            terminal=inspection.terminal,
            startup_notify=inspection.startup_notify,
            exec_placeholders=list(inspection.exec_placeholders),
            warnings=list(inspection.warnings),
            errors=list(inspection.errors),
            identity_internal_id=identity.internal_id,
            identity_fingerprint=identity.identity_fingerprint,
            identity_basis=identity.basis,
        )
        entries = self._load_entries()
        entries[key.resolved_path] = {
            "size": key.size,
            "mtime_ns": key.mtime_ns,
            "inspection": cached.to_dict(),
        }
        self._prune_entries(entries)
        self._write_entries(entries)

    def delete(self, path: Path) -> None:
        try:
            resolved_path = str(path.expanduser().resolve(strict=False))
        except OSError:
            return
        entries = self._load_entries()
        if entries.pop(resolved_path, None) is not None:
            self._write_entries(entries)

    def prune_missing(self) -> None:
        entries = self._load_entries()
        changed = False
        for resolved_path in list(entries):
            if not Path(resolved_path).exists():
                del entries[resolved_path]
                changed = True
        if changed:
            self._write_entries(entries)

    def _key_for_path(self, path: Path) -> AppImageInspectionCacheKey:
        resolved = path.expanduser().resolve(strict=False)
        stat = resolved.stat()
        return AppImageInspectionCacheKey(
            resolved_path=str(resolved),
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )

    def _load_entries(self) -> dict[str, dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        try:
            payload = json.loads(self.paths.inspection_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._entries = {}
            return self._entries
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            self._entries = {}
            return self._entries
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            self._entries = {}
            return self._entries
        self._entries = {
            str(path): entry for path, entry in entries.items() if isinstance(entry, dict)
        }
        return self._entries

    def _write_entries(self, entries: dict[str, dict[str, Any]]) -> None:
        self._entries = entries
        payload = {
            "schema_version": SCHEMA_VERSION,
            "entries": entries,
        }
        try:
            self.paths.inspection_cache_path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.paths.inspection_cache_path.parent,
                delete=False,
            ) as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                temp_path = Path(handle.name)
            temp_path.replace(self.paths.inspection_cache_path)
        except OSError:
            return

    def _prune_entries(self, entries: dict[str, dict[str, Any]]) -> None:
        for resolved_path in list(entries):
            if not Path(resolved_path).exists():
                del entries[resolved_path]
        if len(entries) <= self.max_entries:
            return
        ordered = sorted(
            entries.items(),
            key=lambda item: (
                item[1].get("mtime_ns", 0) if isinstance(item[1], dict) else 0,
                item[0],
            ),
        )
        for resolved_path, _entry in ordered[: max(0, len(entries) - self.max_entries)]:
            entries.pop(resolved_path, None)
