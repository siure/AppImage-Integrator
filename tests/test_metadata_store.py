from __future__ import annotations

import json

from appimage_integrator.models import ManagedAppRecord
from appimage_integrator.storage.metadata_store import MetadataStore


def make_record(internal_id: str = "demo-1234") -> ManagedAppRecord:
    return ManagedAppRecord(
        internal_id=internal_id,
        display_name="Demo",
        comment="Test",
        version="1.0.0",
        appstream_id=None,
        embedded_desktop_basename="demo.desktop",
        identity_fingerprint="abc123",
        managed_appimage_path="/tmp/demo.AppImage",
        managed_desktop_path="/tmp/demo.desktop",
        managed_icon_path="/tmp/demo.svg",
        managed_payload_path="/tmp/payloads/demo.AppImage",
        managed_payload_dir="/tmp/payloads",
        source_file_name_at_install="demo.AppImage",
        source_path_last_seen="/tmp/demo.AppImage",
        desktop_exec_template="/tmp/demo.AppImage",
        extra_args=["--test"],
        arg_preset_id="none",
        installed_at="2026-03-09T00:00:00+00:00",
        updated_at="2026-03-09T00:00:00+00:00",
        appimage_type="type2",
        icon_managed_by_app=True,
        managed_files=["/tmp/demo.AppImage", "/tmp/demo.desktop", "/tmp/demo.svg"],
        last_validation_status="ok",
        last_validation_messages=[],
    )


def test_metadata_store_save_load_rebuild(test_paths) -> None:
    store = MetadataStore(test_paths)
    record = make_record()
    store.save(record)

    loaded = store.load(record.internal_id)
    assert loaded == record

    test_paths.metadata_index_path.write_text("{bad json", encoding="utf-8")
    rebuilt = store.load_index()
    assert rebuilt[record.internal_id]["display_name"] == "Demo"


def test_metadata_store_delete_updates_index(test_paths) -> None:
    store = MetadataStore(test_paths)
    record = make_record()
    store.save(record)
    store.delete(record.internal_id)
    assert store.load(record.internal_id) is None
    assert json.loads(test_paths.metadata_index_path.read_text(encoding="utf-8")) == {}
