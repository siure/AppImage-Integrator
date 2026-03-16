from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from appimage_integrator.models import ManagedAppRecord, RepairReport
from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.desktop_entry import DesktopEntryService, partition_validation_messages
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.storage.metadata_store import MetadataStore


class RepairManager:
    def __init__(
        self,
        inspector: AppImageInspector,
        desktop_service: DesktopEntryService,
        icon_resolver: IconResolver,
        runtime_service: ManagedAppRuntimeService,
        store: MetadataStore,
    ) -> None:
        self.inspector = inspector
        self.desktop_service = desktop_service
        self.icon_resolver = icon_resolver
        self.runtime_service = runtime_service
        self.store = store

    def repair(self, record: ManagedAppRecord) -> tuple[ManagedAppRecord, RepairReport]:
        record = self.runtime_service.reconcile_record(record)
        issues: list[str] = []
        actions: list[str] = []
        validation_messages: list[str] = []
        appimage_path = Path(record.managed_appimage_path)
        desktop_path = Path(record.managed_desktop_path)
        icon_path = Path(record.managed_icon_path) if record.managed_icon_path else None

        if not appimage_path.exists():
            issues.append("Managed AppImage is missing and cannot be repaired automatically.")
            return record, RepairReport(record.internal_id, issues, actions, False)

        if not os.access(appimage_path, os.X_OK):
            os.chmod(appimage_path, 0o755)
            actions.append("Restored execute permission on the managed AppImage.")

        inspection = self.inspector.inspect(appimage_path)

        should_regenerate_desktop = not desktop_path.exists()
        if not should_regenerate_desktop:
            try:
                existing_desktop_text = desktop_path.read_text(encoding="utf-8", errors="replace")
                should_regenerate_desktop = bool(
                    partition_validation_messages(self.desktop_service.validate_text(existing_desktop_text))[1]
                )
            except OSError:
                should_regenerate_desktop = True

        if should_regenerate_desktop:
            try:
                desktop_text, validation_messages, exec_template = self.desktop_service.build_desktop_text(
                    internal_id=record.internal_id,
                    inspection=inspection,
                    appimage_path=appimage_path,
                    icon_value=record.managed_icon_path or "application-x-executable",
                    display_name=record.display_name,
                    comment=record.comment,
                    extra_args=record.extra_args,
                    arg_preset_id=record.arg_preset_id,
                )
            except ValueError as exc:
                issues.append(str(exc))
            else:
                desktop_path.write_text(desktop_text, encoding="utf-8")
                actions.append("Regenerated desktop launcher.")
                record = ManagedAppRecord.from_dict(
                    {
                        **record.to_dict(),
                        "desktop_exec_template": exec_template,
                        "last_validation_messages": validation_messages,
                    }
                )

        if record.icon_managed_by_app and (icon_path is None or not icon_path.exists()):
            icon_value, managed_icon_path, icon_managed = self.icon_resolver.install_icon(
                record.internal_id,
                inspection.chosen_icon_candidate,
            )
            if managed_icon_path:
                actions.append("Reinstalled managed icon.")
                record = ManagedAppRecord.from_dict(
                    {
                        **record.to_dict(),
                        "managed_icon_path": managed_icon_path,
                        "icon_managed_by_app": icon_managed,
                    }
                )
            else:
                issues.append(f"Could not restore icon. Using fallback icon {icon_value}.")

        remaining_messages = [*issues, *validation_messages]
        validation_warnings, validation_errors = partition_validation_messages(validation_messages)
        status = "error" if issues or validation_errors else ("warning" if validation_warnings else "ok")
        record = ManagedAppRecord.from_dict(
            {
                **record.to_dict(),
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                "last_validation_status": status,
                "last_validation_messages": remaining_messages,
            }
        )
        self.store.save(record)
        self.inspector.cleanup(inspection)
        return record, RepairReport(record.internal_id, issues, actions, not issues)
