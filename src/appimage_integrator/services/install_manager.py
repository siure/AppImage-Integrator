from __future__ import annotations

import os
import stat
import shutil
from datetime import UTC, datetime
from pathlib import Path

from appimage_integrator.models import AppImageInspection, InstallRequest, InstallResult, ManagedAppRecord
from appimage_integrator.paths import AppPaths
from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.desktop_entry import DesktopEntryService
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
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
        store: MetadataStore,
        tooling: Tooling,
    ) -> None:
        self.paths = paths
        self.inspector = inspector
        self.desktop_service = desktop_service
        self.icon_resolver = icon_resolver
        self.id_resolver = id_resolver
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
        mode = "install"
        if existing:
            if compare_versions(inspection.detected_version, existing.version) != 0:
                mode = "update"
            else:
                mode = "reinstall"
        return inspection, existing, mode

    def install(self, request: InstallRequest) -> InstallResult:
        inspection = self.inspector.inspect(request.source_path)
        identity = self.id_resolver.resolve(inspection)
        existing = self.store.load(identity.internal_id)
        mode = "install"
        if existing:
            if compare_versions(inspection.detected_version, existing.version) != 0:
                mode = "update"
            else:
                mode = "reinstall"

        managed_appimage = self.paths.applications_dir / f"{identity.internal_id}.AppImage"
        managed_appimage.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(request.source_path, managed_appimage)
        os.chmod(managed_appimage, 0o755)

        icon_value, managed_icon_path, icon_managed = self.icon_resolver.install_icon(
            identity.internal_id,
            inspection.chosen_icon_candidate,
        )
        desktop_text, validation_messages, exec_template = self.desktop_service.build_desktop_text(
            inspection=inspection,
            appimage_path=managed_appimage,
            icon_value=icon_value,
            display_name=request.display_name_override or inspection.detected_name or request.source_path.stem,
            comment=request.comment_override if request.comment_override is not None else inspection.detected_comment,
            extra_args=request.extra_args,
            arg_preset_id=request.arg_preset_id,
        )
        desktop_path = self.paths.desktop_entries_dir / f"{identity.internal_id}.desktop"
        desktop_path.write_text(desktop_text, encoding="utf-8")

        timestamp = datetime.now(tz=UTC).isoformat()
        record = ManagedAppRecord(
            internal_id=identity.internal_id,
            display_name=request.display_name_override or inspection.detected_name or request.source_path.stem,
            comment=request.comment_override if request.comment_override is not None else inspection.detected_comment,
            version=inspection.detected_version,
            appstream_id=inspection.appstream_id,
            embedded_desktop_basename=inspection.embedded_desktop_filename,
            identity_fingerprint=identity.identity_fingerprint,
            managed_appimage_path=str(managed_appimage),
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
            managed_files=[
                str(managed_appimage),
                str(desktop_path),
                *( [managed_icon_path] if managed_icon_path else [] ),
            ],
            last_validation_status="warning" if validation_messages or inspection.warnings else "ok",
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
        for file_path in record.managed_files:
            path = Path(file_path)
            if path.exists():
                path.unlink()
        self.store.delete(record.internal_id)
        self._refresh_desktop_databases()

    def _refresh_desktop_databases(self) -> None:
        if self.tooling.tools.update_desktop_database:
            self.tooling.run(
                [self.tooling.tools.update_desktop_database, str(self.paths.desktop_entries_dir)]
            )
