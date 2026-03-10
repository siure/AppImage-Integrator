from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from appimage_integrator.models import AppImageInspection, ManagedAppRecord
from appimage_integrator.paths import AppPaths
from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.desktop_entry import DesktopEntryService
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.versioning import compare_versions


@dataclass(frozen=True)
class ManagedPlacement:
    stable_path: Path
    payload_dir: Path
    payload_path: Path


@dataclass(frozen=True)
class _ReplacementCandidate:
    path: Path
    version: str | None
    inspection: AppImageInspection


class ManagedAppRuntimeService:
    def __init__(
        self,
        paths: AppPaths,
        inspector: AppImageInspector,
        desktop_service: DesktopEntryService,
        icon_resolver: IconResolver,
        id_resolver: IdResolver,
    ) -> None:
        self.paths = paths
        self.inspector = inspector
        self.desktop_service = desktop_service
        self.icon_resolver = icon_resolver
        self.id_resolver = id_resolver

    def stable_path(self, internal_id: str) -> Path:
        return self.paths.applications_dir / f"{internal_id}.AppImage"

    def payload_dir(self, internal_id: str) -> Path:
        return self.paths.managed_payloads_root / internal_id

    def stage_install(self, internal_id: str, source_path: Path) -> ManagedPlacement:
        stable_path = self.stable_path(internal_id)
        payload_dir = self.payload_dir(internal_id)
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_path = payload_dir / source_path.name
        if source_path.resolve() != payload_path.resolve():
            shutil.copy2(source_path, payload_path)
        self._ensure_executable(payload_path)
        self._retarget_symlink(stable_path, payload_path)
        self.prune_inactive_payloads(payload_dir, payload_path)
        return ManagedPlacement(
            stable_path=stable_path,
            payload_dir=payload_dir,
            payload_path=payload_path,
        )

    def reconcile_record(self, record: ManagedAppRecord) -> ManagedAppRecord:
        record = self._ensure_runtime_fields(record)
        record = self._migrate_legacy_record(record)
        stable_path = Path(record.managed_appimage_path)
        payload_path = self._existing_payload_path(record)
        if stable_path.is_symlink():
            resolved = stable_path.resolve(strict=False)
            if resolved.exists():
                if payload_path is None or resolved != payload_path:
                    record = self._record_with_paths(record, payload_path=resolved)
                return self._record_with_managed_files(record)
        if payload_path and payload_path.exists():
            self._retarget_symlink(stable_path, payload_path)
            return self._record_with_managed_files(record)

        replacement = self._select_replacement_candidate(record)
        if replacement is None:
            return self._record_with_managed_files(record)

        try:
            self._retarget_symlink(stable_path, replacement.path)
            record = self._refresh_record_for_payload(record, replacement.inspection, replacement.path)
            self.prune_inactive_payloads(Path(record.managed_payload_dir), replacement.path)
            return self._record_with_managed_files(record)
        finally:
            self.inspector.cleanup(replacement.inspection)

    def remove_managed_artifacts(self, record: ManagedAppRecord) -> None:
        stable_path = Path(record.managed_appimage_path)
        if stable_path.exists() or stable_path.is_symlink():
            stable_path.unlink()

        desktop_path = Path(record.managed_desktop_path)
        if desktop_path.exists():
            desktop_path.unlink()

        if record.managed_icon_path:
            icon_path = Path(record.managed_icon_path)
            if icon_path.exists():
                icon_path.unlink()

        payload_dir = Path(record.managed_payload_dir) if record.managed_payload_dir else self.payload_dir(record.internal_id)
        if payload_dir.exists():
            shutil.rmtree(payload_dir, ignore_errors=True)

    def prune_inactive_payloads(self, payload_dir: Path, active_path: Path) -> None:
        if not payload_dir.exists():
            return
        for candidate in payload_dir.glob("*.AppImage"):
            if candidate == active_path:
                continue
            if candidate.exists() or candidate.is_symlink():
                candidate.unlink()

    def _ensure_runtime_fields(self, record: ManagedAppRecord) -> ManagedAppRecord:
        payload_dir = record.managed_payload_dir or str(self.payload_dir(record.internal_id))
        return self._record_with_managed_files(
            ManagedAppRecord.from_dict(
                {
                    **record.to_dict(),
                    "managed_appimage_path": str(self.stable_path(record.internal_id)),
                    "managed_payload_dir": payload_dir,
                }
            )
        )

    def _migrate_legacy_record(self, record: ManagedAppRecord) -> ManagedAppRecord:
        if record.managed_payload_path is not None:
            return self._record_with_managed_files(record)

        stable_path = Path(record.managed_appimage_path)
        payload_dir = Path(record.managed_payload_dir) if record.managed_payload_dir else self.payload_dir(record.internal_id)
        legacy_path = stable_path
        payload_path: Path | None = None

        if legacy_path.is_symlink():
            resolved = legacy_path.resolve(strict=False)
            if resolved.exists():
                payload_path = resolved
        elif legacy_path.exists():
            payload_dir.mkdir(parents=True, exist_ok=True)
            destination = payload_dir / legacy_path.name
            if destination.exists() or destination.is_symlink():
                destination.unlink()
            legacy_path.replace(destination)
            self._ensure_executable(destination)
            self._retarget_symlink(stable_path, destination)
            payload_path = destination

        return self._record_with_paths(record, payload_path=payload_path, payload_dir=payload_dir)

    def _record_with_paths(
        self,
        record: ManagedAppRecord,
        *,
        payload_path: Path | None = None,
        payload_dir: Path | None = None,
    ) -> ManagedAppRecord:
        data = record.to_dict()
        data["managed_appimage_path"] = str(self.stable_path(record.internal_id))
        data["managed_payload_dir"] = str(payload_dir or self.payload_dir(record.internal_id))
        data["managed_payload_path"] = str(payload_path) if payload_path is not None else None
        return self._record_with_managed_files(ManagedAppRecord.from_dict(data))

    def _record_with_managed_files(self, record: ManagedAppRecord) -> ManagedAppRecord:
        managed_files = [
            record.managed_appimage_path,
            record.managed_desktop_path,
            *( [record.managed_icon_path] if record.managed_icon_path else [] ),
            *( [record.managed_payload_path] if record.managed_payload_path else [] ),
        ]
        unique_files = list(dict.fromkeys(managed_files))
        return ManagedAppRecord.from_dict(
            {
                **record.to_dict(),
                "managed_files": unique_files,
            }
        )

    def _existing_payload_path(self, record: ManagedAppRecord) -> Path | None:
        if not record.managed_payload_path:
            return None
        payload_path = Path(record.managed_payload_path)
        return payload_path if payload_path.exists() else None

    def _select_replacement_candidate(self, record: ManagedAppRecord) -> _ReplacementCandidate | None:
        payload_dir = Path(record.managed_payload_dir) if record.managed_payload_dir else self.payload_dir(record.internal_id)
        if not payload_dir.exists():
            return None

        candidates: list[_ReplacementCandidate] = []
        for candidate_path in sorted(payload_dir.glob("*.AppImage")):
            if not candidate_path.is_file():
                continue
            inspection = self.inspector.inspect(candidate_path)
            identity = self.id_resolver.resolve(inspection)
            if identity.internal_id == record.internal_id or identity.identity_fingerprint == record.identity_fingerprint:
                candidates.append(
                    _ReplacementCandidate(
                        path=candidate_path,
                        version=inspection.detected_version,
                        inspection=inspection,
                    )
                )
                continue
            self.inspector.cleanup(inspection)

        if not candidates:
            return None

        chosen = candidates[0]
        for candidate in candidates[1:]:
            if self._candidate_is_better(candidate, chosen):
                self.inspector.cleanup(chosen.inspection)
                chosen = candidate
            else:
                self.inspector.cleanup(candidate.inspection)
        return chosen

    def _candidate_is_better(self, candidate: _ReplacementCandidate, current: _ReplacementCandidate) -> bool:
        version_cmp = compare_versions(candidate.version, current.version)
        if version_cmp != 0:
            return version_cmp > 0
        candidate_mtime = candidate.path.stat().st_mtime
        current_mtime = current.path.stat().st_mtime
        if candidate_mtime != current_mtime:
            return candidate_mtime > current_mtime
        return candidate.path.name > current.path.name

    def _refresh_record_for_payload(
        self,
        record: ManagedAppRecord,
        inspection: AppImageInspection,
        payload_path: Path,
    ) -> ManagedAppRecord:
        icon_value, managed_icon_path, icon_managed = self.icon_resolver.install_icon(
            record.internal_id,
            inspection.chosen_icon_candidate,
        )
        desktop_text, validation_messages, exec_template = self.desktop_service.build_desktop_text(
            inspection=inspection,
            appimage_path=Path(record.managed_appimage_path),
            icon_value=icon_value,
            display_name=record.display_name or inspection.detected_name or payload_path.stem,
            comment=record.comment if record.comment is not None else inspection.detected_comment,
            extra_args=record.extra_args,
            arg_preset_id=record.arg_preset_id,
        )
        Path(record.managed_desktop_path).write_text(desktop_text, encoding="utf-8")
        timestamp = datetime.now(tz=UTC).isoformat()
        updated = ManagedAppRecord.from_dict(
            {
                **record.to_dict(),
                "version": inspection.detected_version,
                "appstream_id": inspection.appstream_id,
                "embedded_desktop_basename": inspection.embedded_desktop_filename,
                "managed_payload_path": str(payload_path),
                "managed_payload_dir": str(self.payload_dir(record.internal_id)),
                "managed_icon_path": managed_icon_path,
                "desktop_exec_template": exec_template,
                "updated_at": timestamp,
                "appimage_type": inspection.appimage_type,
                "icon_managed_by_app": icon_managed,
                "last_validation_status": "warning" if validation_messages or inspection.warnings else "ok",
                "last_validation_messages": [*inspection.warnings, *validation_messages],
            }
        )
        return self._record_with_managed_files(updated)

    def _ensure_executable(self, path: Path) -> None:
        os.chmod(path, 0o755)

    def _retarget_symlink(self, stable_path: Path, payload_path: Path) -> None:
        stable_path.parent.mkdir(parents=True, exist_ok=True)
        temp_link = stable_path.with_name(f".{stable_path.name}.tmp")
        if temp_link.exists() or temp_link.is_symlink():
            temp_link.unlink()
        os.symlink(payload_path, temp_link)
        temp_link.replace(stable_path)
