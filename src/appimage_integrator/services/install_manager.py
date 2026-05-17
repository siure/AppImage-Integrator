from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from appimage_integrator.models import (
    AppImageInspection,
    IdentityResolution,
    InstallRequest,
    InstallResult,
    ManagedAppRecord,
)
from appimage_integrator.paths import AppPaths
from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.desktop_entry import DesktopEntryService, partition_validation_messages
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.self_integration import is_self_internal_id
from appimage_integrator.services.cancellation import CancelCallback, OperationCancelled, raise_if_cancelled
from appimage_integrator.services.tooling import Tooling
from appimage_integrator.services.versioning import compare_versions
from appimage_integrator.storage.metadata_store import MetadataStore
from appimage_integrator.launcher import install_self_command


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

    def inspect(
        self,
        source_path: Path,
        should_cancel: CancelCallback | None = None,
    ) -> tuple[AppImageInspection, ManagedAppRecord | None, str]:
        raise_if_cancelled(should_cancel)
        inspection = (
            self.inspector.inspect(source_path)
            if should_cancel is None
            else self.inspector.inspect(source_path, should_cancel=should_cancel)
        )
        identity = self.id_resolver.resolve(inspection)
        try:
            raise_if_cancelled(should_cancel)
        except Exception:
            self.inspector.cleanup(inspection)
            raise
        existing = self.store.load(identity.internal_id)
        if existing:
            existing = self.runtime_service.reconcile_record(existing)
        return inspection, existing, self._install_mode(existing, inspection.detected_version)

    def related_records_for_inspection(self, inspection: AppImageInspection) -> list[ManagedAppRecord]:
        identity = self.id_resolver.resolve(inspection)
        related = [
            self.runtime_service.reconcile_record(record, allow_payload_inspection=False)
            for record in self.store.load_all()
            if (
                record.identity_fingerprint == identity.identity_fingerprint
                or record.base_identity_fingerprint == identity.identity_fingerprint
            )
        ]
        return sorted(
            related,
            key=lambda record: (
                0 if record.identity_fingerprint == identity.identity_fingerprint else 1,
                record.copy_index or 0,
                record.display_name.lower(),
                record.internal_id,
            ),
        )

    def install(
        self,
        request: InstallRequest,
        should_cancel: CancelCallback | None = None,
    ) -> InstallResult:
        raise_if_cancelled(should_cancel)
        if request.target_internal_id is not None and request.install_action == "copy":
            raise ValueError("Cannot install a copy into an explicit update target.")
        inspection = (
            self.inspector.inspect(request.source_path)
            if should_cancel is None
            else self.inspector.inspect(request.source_path, should_cancel=should_cancel)
        )
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

        try:
            identity, base_identity, existing, mode, display_name, copy_index = self._resolve_install_target(
                inspection,
                request,
            )
        except OperationCancelled:
            self.inspector.cleanup(inspection)
            raise

        try:
            raise_if_cancelled(should_cancel)
        except OperationCancelled:
            self.inspector.cleanup(inspection)
            raise
        placement = self.runtime_service.stage_install(identity.internal_id, request.source_path)
        if is_self_internal_id(identity.internal_id):
            install_self_command(self.paths, placement.stable_path)

        try:
            raise_if_cancelled(should_cancel)
        except OperationCancelled:
            self.inspector.cleanup(inspection)
            raise
        icon_value, managed_icon_path, icon_managed = self.icon_resolver.install_icon(
            identity.internal_id,
            inspection.chosen_icon_candidate,
        )
        comment = (
            request.comment_override
            if request.comment_override is not None
            else (existing.comment if request.target_internal_id and existing else inspection.detected_comment)
        )
        extra_args = request.extra_args
        arg_preset_id = request.arg_preset_id
        desktop_text, validation_messages, exec_template = self.desktop_service.build_desktop_text(
            internal_id=identity.internal_id,
            inspection=inspection,
            appimage_path=placement.stable_path,
            icon_value=icon_value,
            display_name=display_name,
            comment=comment,
            extra_args=extra_args,
            arg_preset_id=arg_preset_id,
        )
        desktop_path = (
            self.paths.self_desktop_entry_path
            if is_self_internal_id(identity.internal_id)
            else self.paths.desktop_entries_dir / f"{identity.internal_id}.desktop"
        )
        desktop_path.write_text(desktop_text, encoding="utf-8")

        try:
            raise_if_cancelled(should_cancel)
        except OperationCancelled:
            self.inspector.cleanup(inspection)
            raise
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        validation_warnings, validation_errors = partition_validation_messages(validation_messages)
        record = ManagedAppRecord(
            internal_id=identity.internal_id,
            display_name=display_name,
            comment=comment,
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
            extra_args=extra_args,
            arg_preset_id=arg_preset_id,
            installed_at=existing.installed_at if existing else timestamp,
            updated_at=timestamp,
            appimage_type=inspection.appimage_type,
            icon_managed_by_app=icon_managed,
            managed_payload_path=str(placement.payload_path),
            managed_payload_dir=str(placement.payload_dir),
            base_identity_fingerprint=(
                existing.base_identity_fingerprint
                if existing
                else (base_identity.identity_fingerprint if request.install_action == "copy" else None)
            ),
            copy_index=existing.copy_index if existing else (copy_index if request.install_action == "copy" else None),
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

    def _resolve_install_target(
        self,
        inspection: AppImageInspection,
        request: InstallRequest,
    ) -> tuple[IdentityResolution, IdentityResolution, ManagedAppRecord | None, str, str, int | None]:
        base_identity = self.id_resolver.resolve(inspection)
        if request.target_internal_id is not None:
            existing = self.store.load(request.target_internal_id)
            if existing is None:
                raise ValueError("The selected update target could not be found.")
            existing = self.runtime_service.reconcile_record(existing)
            mode = self._install_mode(existing, inspection.detected_version)
            if request.source_path.resolve(strict=False) != Path(
                existing.source_path_last_seen
            ).expanduser().resolve(strict=False):
                mode = "update"
            identity = IdentityResolution(
                internal_id=existing.internal_id,
                identity_fingerprint=existing.identity_fingerprint,
                basis=existing.internal_id,
            )
            return (
                identity,
                base_identity,
                existing,
                mode,
                request.display_name_override or existing.display_name,
                existing.copy_index,
            )

        base_display_name = (
            request.display_name_override or inspection.detected_name or request.source_path.stem
        )

        if request.install_action != "copy":
            existing = self.store.load(base_identity.internal_id)
            if existing:
                existing = self.runtime_service.reconcile_record(existing)
            return (
                base_identity,
                base_identity,
                existing,
                self._install_mode(existing, inspection.detected_version),
                base_display_name,
                None,
            )

        copy_index = self._next_copy_index(base_identity)
        display_name = self._copy_display_name(
            base_display_name,
            copy_index,
            custom_name=request.display_name_override,
        )
        identity = self.id_resolver.resolve_copy(base_identity, display_name, copy_index)
        while self.store.load(identity.internal_id) is not None:
            copy_index += 1
            display_name = self._copy_display_name(
                base_display_name,
                copy_index,
                custom_name=request.display_name_override,
            )
            identity = self.id_resolver.resolve_copy(base_identity, display_name, copy_index)
        return identity, base_identity, None, "copy", display_name, copy_index

    def _next_copy_index(self, base_identity: IdentityResolution) -> int:
        indexes = [0]
        for record in self.store.load_all():
            if record.identity_fingerprint == base_identity.identity_fingerprint:
                indexes.append(0)
            if record.base_identity_fingerprint == base_identity.identity_fingerprint:
                indexes.append(record.copy_index or 1)
        return max(indexes) + 1

    def _copy_display_name(
        self,
        base_display_name: str,
        copy_index: int,
        *,
        custom_name: str | None,
    ) -> str:
        existing_names = {record.display_name.casefold() for record in self.store.load_all()}
        if custom_name and custom_name.casefold() not in existing_names:
            return custom_name

        root_name = custom_name or base_display_name
        suffix_index = 1 if custom_name else copy_index
        candidate = self._copy_name_for_index(root_name, suffix_index)
        while candidate.casefold() in existing_names:
            suffix_index += 1
            candidate = self._copy_name_for_index(root_name, suffix_index)
        return candidate

    def _copy_name_for_index(self, display_name: str, copy_index: int) -> str:
        if copy_index <= 1:
            return f"{display_name} Copy"
        return f"{display_name} Copy {copy_index}"

    def _install_mode(self, existing: ManagedAppRecord | None, detected_version: str | None) -> str:
        if existing is None:
            return "install"
        return "update" if compare_versions(detected_version, existing.version) > 0 else "reinstall"
