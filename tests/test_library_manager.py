from __future__ import annotations

from appimage_integrator.models import ManagedAppRecord
from appimage_integrator.services.library_manager import LibraryManager
from appimage_integrator.storage.metadata_store import MetadataStore


def make_record(
    internal_id: str,
    display_name: str,
    identity_fingerprint: str,
    *,
    base_identity_fingerprint: str | None = None,
    copy_index: int | None = None,
) -> ManagedAppRecord:
    return ManagedAppRecord.from_dict(
        {
            "internal_id": internal_id,
            "display_name": display_name,
            "comment": None,
            "version": "1.0.0",
            "appstream_id": "org.demo.App",
            "embedded_desktop_basename": "demo.desktop",
            "identity_fingerprint": identity_fingerprint,
            "managed_appimage_path": f"/apps/{internal_id}.AppImage",
            "managed_desktop_path": f"/desktop/{internal_id}.desktop",
            "managed_icon_path": None,
            "source_file_name_at_install": "demo.AppImage",
            "source_path_last_seen": "/tmp/demo.AppImage",
            "desktop_exec_template": "/apps/demo.AppImage",
            "extra_args": [],
            "arg_preset_id": "none",
            "installed_at": "2026-03-15T00:00:00+00:00",
            "updated_at": "2026-03-15T00:00:00+00:00",
            "appimage_type": "type2",
            "icon_managed_by_app": False,
            "managed_files": [],
            "last_validation_status": "ok",
            "last_validation_messages": [],
            "base_identity_fingerprint": base_identity_fingerprint,
            "copy_index": copy_index,
        }
    )


def test_related_records_groups_original_and_copies(test_paths) -> None:
    store = MetadataStore(test_paths)
    original = make_record("demo", "Demo", "base")
    copy_one = make_record("demo-copy-1", "Demo Copy", "copy-1", base_identity_fingerprint="base", copy_index=1)
    copy_two = make_record("demo-copy-2", "Demo Copy 2", "copy-2", base_identity_fingerprint="base", copy_index=2)
    unrelated = make_record("other", "Other", "other")
    for record in (copy_two, unrelated, original, copy_one):
        store.save(record)
    manager = LibraryManager(store, runtime_service=None)

    assert [record.internal_id for record in manager.related_records(original)] == [
        "demo",
        "demo-copy-1",
        "demo-copy-2",
    ]
    assert [record.internal_id for record in manager.related_records(copy_one)] == [
        "demo-copy-1",
        "demo",
        "demo-copy-2",
    ]
