from __future__ import annotations

from appimage_integrator.models import ManagedAppRecord


def details_payload_location(record: ManagedAppRecord) -> tuple[str, str] | None:
    if record.managed_payload_path:
        return ("Payload Path", record.managed_payload_path)
    if record.managed_payload_dir:
        return ("Payload Directory", record.managed_payload_dir)
    return None
