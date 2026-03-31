from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from appimage_integrator.models import AppImageInspection, ManagedAppRecord, ManagedRecordUpdateRequest
from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.desktop_entry import DesktopEntryService, partition_validation_messages
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.storage.metadata_store import MetadataStore


class RecordEditorService:
    def __init__(
        self,
        store: MetadataStore,
        runtime_service: ManagedAppRuntimeService,
        desktop_service: DesktopEntryService,
        inspector: AppImageInspector,
    ) -> None:
        self.store = store
        self.runtime_service = runtime_service
        self.desktop_service = desktop_service
        self.inspector = inspector

    def build_effective_command(
        self,
        record: ManagedAppRecord,
        *,
        arg_preset_id: str | None,
        extra_args: list[str],
    ) -> str:
        return self.desktop_service.build_exec_template_from_record(
            record,
            arg_preset_id=arg_preset_id,
            extra_args=extra_args,
        )

    def update_record(self, request: ManagedRecordUpdateRequest) -> ManagedAppRecord:
        record = self.store.load(request.internal_id)
        if record is None:
            raise ValueError("The selected AppImage could not be found.")

        record = self.runtime_service.reconcile_record(record, allow_payload_inspection=False)
        updated_display_name = request.display_name.strip() or record.display_name
        updated_comment = request.comment.strip() if request.comment is not None else None
        if updated_comment == "":
            updated_comment = None
        updated_args = list(request.extra_args)
        updated_preset_id = request.arg_preset_id or "none"

        desktop_path = Path(record.managed_desktop_path)
        if desktop_path.exists():
            try:
                existing_text = desktop_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                desktop_text, validation_messages, exec_template = self._rebuild_desktop_text_from_payload(
                    record,
                    display_name=updated_display_name,
                    comment=updated_comment,
                    arg_preset_id=updated_preset_id,
                    extra_args=updated_args,
                )
            else:
                desktop_text, validation_messages, exec_template = self.desktop_service.rewrite_managed_desktop_text(
                    record,
                    existing_text,
                    display_name=updated_display_name,
                    comment=updated_comment,
                    arg_preset_id=updated_preset_id,
                    extra_args=updated_args,
                )
        else:
            desktop_text, validation_messages, exec_template = self._rebuild_desktop_text_from_payload(
                record,
                display_name=updated_display_name,
                comment=updated_comment,
                arg_preset_id=updated_preset_id,
                extra_args=updated_args,
            )

        try:
            desktop_path.write_text(desktop_text, encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Could not update the managed desktop file: {exc}") from exc

        validation_warnings, validation_errors = partition_validation_messages(validation_messages)
        status = "error" if validation_errors else ("warning" if validation_warnings else "ok")
        updated_record = ManagedAppRecord.from_dict(
            {
                **record.to_dict(),
                "display_name": updated_display_name,
                "comment": updated_comment,
                "arg_preset_id": updated_preset_id,
                "extra_args": updated_args,
                "desktop_exec_template": exec_template,
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                "last_validation_status": status,
                "last_validation_messages": validation_messages,
            }
        )
        self.store.save(updated_record)
        return updated_record

    def _rebuild_desktop_text_from_payload(
        self,
        record: ManagedAppRecord,
        *,
        display_name: str,
        comment: str | None,
        arg_preset_id: str | None,
        extra_args: list[str],
    ) -> tuple[str, list[str], str]:
        appimage_path = Path(record.managed_appimage_path)
        if not appimage_path.exists():
            raise ValueError(
                "The managed desktop file is missing and the managed AppImage is not available for regeneration."
            )

        inspection: AppImageInspection = self.inspector.inspect(appimage_path)
        try:
            desktop_text, validation_messages, exec_template = self.desktop_service.build_desktop_text(
                internal_id=record.internal_id,
                inspection=inspection,
                appimage_path=appimage_path,
                icon_value=record.managed_icon_path or "application-x-executable",
                display_name=display_name,
                comment=comment,
                extra_args=extra_args,
                arg_preset_id=arg_preset_id,
            )
        finally:
            self.inspector.cleanup(inspection)
        return desktop_text, validation_messages, exec_template
