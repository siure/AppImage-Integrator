from __future__ import annotations

from pathlib import Path

from appimage_integrator.models import AppImageInspection, EmbeddedDesktopEntry
from appimage_integrator.services.id_resolver import IdResolver


def make_inspection(**overrides):
    payload = {
        "source_path": Path("/tmp/demo.AppImage"),
        "is_appimage": True,
        "appimage_type": "type2",
        "is_executable": True,
        "detected_name": "Demo App",
        "detected_comment": None,
        "detected_version": "1.0.0",
        "appstream_id": None,
        "embedded_desktop_filename": None,
        "desktop_entry": EmbeddedDesktopEntry(
            source_relpath="demo.desktop",
            raw_text="[Desktop Entry]\nName=Demo\nExec=AppRun\n",
            parsed_fields={"Name": "Demo", "Exec": "AppRun", "Icon": "demo"},
            exec_tokens=["AppRun"],
            icon_key="demo",
            is_valid=True,
            validation_messages=[],
        ),
        "chosen_icon_candidate": None,
        "startup_wm_class": "DemoClass",
        "mime_types": [],
        "categories": [],
        "terminal": False,
        "startup_notify": True,
        "exec_placeholders": [],
        "warnings": [],
        "errors": [],
        "extracted_dir": None,
    }
    payload.update(overrides)
    return AppImageInspection(**payload)


def test_id_resolver_prefers_appstream_id() -> None:
    inspection = make_inspection(appstream_id="org.demo.App")
    resolved = IdResolver().resolve(inspection)
    assert resolved.internal_id.startswith("org-demo-app-")


def test_id_resolver_uses_desktop_basename_when_no_appstream() -> None:
    inspection = make_inspection(
        appstream_id=None,
        embedded_desktop_filename="demo-browser.desktop",
    )
    resolved = IdResolver().resolve(inspection)
    assert resolved.internal_id.startswith("demo-browser-")


def test_id_resolver_falls_back_to_metadata_tuple_stably() -> None:
    inspection = make_inspection(appstream_id=None, embedded_desktop_filename=None)
    first = IdResolver().resolve(inspection)
    second = IdResolver().resolve(inspection)
    assert first.internal_id == second.internal_id
    assert first.identity_fingerprint == second.identity_fingerprint
