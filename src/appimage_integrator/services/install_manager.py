from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from appimage_integrator.models import AppImageInspection, InstallRequest, InstallResult, ManagedAppRecord
from appimage_integrator.paths import AppPaths
from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.desktop_entry import DesktopEntryService, partition_validation_messages
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.services.tooling import Tooling
from appimage_integrator.services.versioning import compare_versions
from appimage_integrator.storage.metadata_store import MetadataStore


class InstallManager:
    def __init__(
        self,
        paths: AppPaths,
        inspector: AppImageInspector,
        desktop_service: DesktopEntryService,
        icon_resolver: IconResolver,
        id_resolver: IdResolver,
        runtime_service: ManagedAppRuntimeService,
        store: MetadataStore,
        tooling: Tooling,
    ) -> None:
        self.paths = paths
        self.inspector = inspector
        self.desktop_service = desktop_service
        self.icon_resolver = icon_resolver
        self.id_resolver = id_resolver
        self.runtime_service = runtime_service
        self.store = store
        self.tooling = tooling

    def ensure_source_executable(self, source_path: Path) -> None:
        current_mode = source_path.stat().st_mode
        executable_mode = current_mode | stat.S_IXUSR
        if current_mode & stat.S_IRGRP:
            executable_mode |= stat.S_IXGRP
        if current_mode & stat.S_IROTH:
            executable_mode |= stat.S_IXOTH
        os.chmod(source_path, executable_mode)

    def inspect(self, source_path: Path) -> tuple[AppImageInspection, ManagedAppRecord | None, str]:
        inspection = self.inspector.inspect(source_path)
        identity = self.id_resolver.resolve(inspection)
        existing = self.store.load(identity.internal_id)
        if existing:
            existing = self.runtime_service.reconcile_record(existing)
        return inspection, existing, self._install_mode(existing, inspection.detected_version)

    def install(self, request: InstallRequest) -> InstallResult:
        inspection = self.inspector.inspect(request.source_path)
        fatal_errors = [
            message
            for message in inspection.errors
            if message != "Could not extract AppImage contents."
        ]
        if not inspection.is_appimage:
            self.inspector.cleanup(inspection)
            raise ValueError("Selected file is not a valid AppImage.")
        if fatal_errors:
            message = fatal_errors[0]
            self.inspector.cleanup(inspection)
            raise ValueError(f"Could not install AppImage: {message}")

        identity = self.id_resolver.resolve(inspection)
        existing = self.store.load(identity.internal_id)
        if existing:
            existing = self.runtime_service.reconcile_record(existing)
        mode = self._install_mode(existing, inspection.detected_version)

        placement = self.runtime_service.stage_install(identity.internal_id, request.source_path)

        icon_value, managed_icon_path, icon_managed = self.icon_resolver.install_icon(
            identity.internal_id,
            inspection.chosen_icon_candidate,
        )
        desktop_text, validation_messages, exec_template = self.desktop_service.build_desktop_text(
            internal_id=identity.internal_id,
            inspection=inspection,
            appimage_path=placement.stable_path,
            icon_value=icon_value,
            display_name=request.display_name_override or inspection.detected_name or request.source_path.stem,
            comment=request.comment_override if request.comment_override is not None else inspection.detected_comment,
            extra_args=request.extra_args,
            arg_preset_id=request.arg_preset_id,
        )
        desktop_path = self.paths.desktop_entries_dir / f"{identity.internal_id}.desktop"
        desktop_path.write_text(desktop_text, encoding="utf-8")

        timestamp = datetime.now(tz=timezone.utc).isoformat()
        validation_warnings, validation_errors = partition_validation_messages(validation_messages)
        record = ManagedAppRecord(
            internal_id=identity.internal_id,
            display_name=request.display_name_override or inspection.detected_name or request.source_path.stem,
            comment=request.comment_override if request.comment_override is not None else inspection.detected_comment,
            version=inspection.detected_version,
            appstream_id=inspection.appstream_id,
            embedded_desktop_basename=inspection.embedded_desktop_filename,
            identity_fingerprint=identity.identity_fingerprint,
            managed_appimage_path=str(placement.stable_path),
            managed_desktop_path=str(desktop_path),
            managed_icon_path=managed_icon_path,
            source_file_name_at_install=request.source_path.name,
            source_path_last_seen=str(request.source_path),
            desktop_exec_template=exec_template,
            extra_args=request.extra_args,
            arg_preset_id=request.arg_preset_id,
            installed_at=existing.installed_at if existing else timestamp,
            updated_at=timestamp,
            appimage_type=inspection.appimage_type,
            icon_managed_by_app=icon_managed,
            managed_payload_path=str(placement.payload_path),
            managed_payload_dir=str(placement.payload_dir),
            managed_files=[
                str(placement.stable_path),
                str(desktop_path),
                str(placement.payload_path),
                *( [managed_icon_path] if managed_icon_path else [] ),
            ],
            last_validation_status=(
                "error"
                if validation_errors
                else ("warning" if validation_warnings or inspection.warnings else "ok")
            ),
            last_validation_messages=[*inspection.warnings, *validation_messages],
        )
        self.store.save(record)
        self._refresh_desktop_databases()
        self.inspector.cleanup(inspection)
        return InstallResult(
            mode=mode,
            record=record,
            warnings=inspection.warnings,
            validation_messages=validation_messages,
        )

    def uninstall(self, record: ManagedAppRecord) -> None:
        record = self.runtime_service.reconcile_record(record)
        self.runtime_service.remove_managed_artifacts(record)
        self.store.delete(record.internal_id)
        self._refresh_desktop_databases()

    def _refresh_desktop_databases(self) -> None:
        if self.tooling.tools.update_desktop_database:
            self.tooling.run(
                [self.tooling.tools.update_desktop_database, str(self.paths.desktop_entries_dir)]
            )

    def _install_mode(self, existing: ManagedAppRecord | None, detected_version: str | None) -> str:
        if existing is None:
            return "install"
        return "update" if compare_versions(detected_version, existing.version) > 0 else "reinstall"
