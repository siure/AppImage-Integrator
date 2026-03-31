from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from appimage_integrator.config import APP_ID, APP_NAME
from appimage_integrator.models import AppImageInspection, ManagedAppRecord
from appimage_integrator.paths import AppPaths
from appimage_integrator.services.desktop_entry import serialize_exec_tokens
from appimage_integrator.services.id_resolver import resolve_internal_id_from_appstream_id


SELF_INTERNAL_ID = resolve_internal_id_from_appstream_id(APP_ID)


def is_self_internal_id(internal_id: str) -> bool:
    return internal_id == SELF_INTERNAL_ID


def is_self_record(record: ManagedAppRecord) -> bool:
    return is_self_internal_id(record.internal_id)


def build_self_record(
    paths: AppPaths,
    *,
    existing: ManagedAppRecord | None = None,
    inspection: AppImageInspection | None = None,
    source_path_last_seen: Path | None = None,
    launcher_command: list[str] | None = None,
) -> ManagedAppRecord:
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    if source_path_last_seen is not None:
        source_path = source_path_last_seen
    elif existing is not None:
        source_path = Path(existing.source_path_last_seen)
    else:
        source_path = paths.self_appimage_path
    icon_path = paths.self_icon_path if paths.self_icon_path.exists() else None
    warnings = list(inspection.warnings) if inspection else list(existing.last_validation_messages if existing else [])
    status = "warning" if warnings else "ok"
    return ManagedAppRecord(
        internal_id=SELF_INTERNAL_ID,
        display_name=existing.display_name if existing else (inspection.detected_name if inspection else APP_NAME),
        comment=(
            existing.comment
            if existing and existing.comment is not None
            else (inspection.detected_comment if inspection else "Install and manage AppImage desktop integrations")
        ),
        version=inspection.detected_version if inspection else (existing.version if existing else None),
        appstream_id=APP_ID,
        embedded_desktop_basename=(
            inspection.embedded_desktop_filename
            if inspection and inspection.embedded_desktop_filename
            else f"{APP_ID}.desktop"
        ),
        identity_fingerprint=hashlib.sha256(APP_ID.encode("utf-8")).hexdigest(),
        managed_appimage_path=str(paths.self_appimage_path),
        managed_desktop_path=str(paths.self_desktop_entry_path),
        managed_icon_path=str(icon_path) if icon_path else None,
        source_file_name_at_install=source_path.name,
        source_path_last_seen=str(source_path),
        desktop_exec_template=serialize_exec_tokens(launcher_command or [str(paths.self_appimage_path)]),
        extra_args=list(existing.extra_args) if existing else [],
        arg_preset_id=existing.arg_preset_id if existing else "none",
        installed_at=existing.installed_at if existing else timestamp,
        updated_at=timestamp,
        appimage_type=inspection.appimage_type if inspection else (existing.appimage_type if existing else "unknown"),
        icon_managed_by_app=icon_path is not None,
        managed_files=[
            str(paths.self_appimage_path),
            str(paths.self_desktop_entry_path),
            str(paths.self_command_path),
            *([str(icon_path)] if icon_path else []),
        ],
        last_validation_status=status,
        last_validation_messages=warnings,
        managed_payload_path=existing.managed_payload_path if existing else None,
        managed_payload_dir=existing.managed_payload_dir if existing else str(paths.managed_payloads_root / SELF_INTERNAL_ID),
    )
