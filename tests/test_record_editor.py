from __future__ import annotations

from pathlib import Path

import pytest

from appimage_integrator.models import (
    AppImageInspection,
    InstallRequest,
    ManagedAppRecord,
    ManagedRecordUpdateRequest,
)
from appimage_integrator.services.desktop_entry import DesktopEntryService, parse_desktop_entry
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.install_manager import InstallManager
from appimage_integrator.services.library_manager import LibraryManager
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.services.record_editor import RecordEditorService
from appimage_integrator.storage.metadata_store import MetadataStore
from appimage_integrator.ui.details_dialog import details_payload_location


class FakeInspector:
    def __init__(self, inspections: list[AppImageInspection]) -> None:
        self.inspections = inspections
        self.cleanup_calls = 0

    def inspect(self, _source_path: Path) -> AppImageInspection:
        return self.inspections.pop(0)

    def cleanup(self, _inspection: AppImageInspection) -> None:
        self.cleanup_calls += 1


class AppPathsLike:
    def __init__(self, extracted_dir: Path) -> None:
        self.icons_dir = extracted_dir.parent / "icons"


def make_inspection(source_path: Path, extracted_dir: Path, version: str | None) -> AppImageInspection:
    icon_candidate = IconResolver._candidate_from_path(
        IconResolver(AppPathsLike(extracted_dir)),
        extracted_dir,
        extracted_dir / "demo.svg",
    )
    entry = parse_desktop_entry(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Demo Browser\n"
        "Comment=Demo comment\n"
        "Exec=AppRun --existing %U\n"
        "Icon=demo\n"
        "StartupWMClass=DemoBrowser\n"
        "X-AppImage-Version="
        + (version or "")
        + "\n",
        "demo.desktop",
    )
    return AppImageInspection(
        source_path=source_path,
        is_appimage=True,
        appimage_type="type2",
        is_executable=True,
        detected_name="Demo Browser",
        detected_comment="Demo comment",
        detected_version=version,
        appstream_id="org.demo.Browser",
        embedded_desktop_filename="demo.desktop",
        desktop_entry=entry,
        chosen_icon_candidate=icon_candidate,
        startup_wm_class="DemoBrowser",
        mime_types=["x-scheme-handler/http"],
        categories=["Network"],
        terminal=False,
        startup_notify=True,
        exec_placeholders=["%U"],
        warnings=[],
        errors=[],
        extracted_dir=extracted_dir,
    )


def _default_launcher_command(test_paths) -> list[str]:
    return [str(test_paths.self_command_path)]


def build_editor(test_paths, tooling, inspections: list[AppImageInspection]):
    store = MetadataStore(test_paths)
    icon_resolver = IconResolver(test_paths)
    inspector = FakeInspector(inspections)
    desktop_service = DesktopEntryService(
        tooling,
        launcher_command_resolver=lambda: _default_launcher_command(test_paths),
    )
    runtime_service = ManagedAppRuntimeService(
        test_paths,
        inspector,
        desktop_service,
        icon_resolver,
        IdResolver(),
    )
    install_manager = InstallManager(
        test_paths,
        inspector,
        desktop_service,
        icon_resolver,
        IdResolver(),
        runtime_service,
        store,
        tooling,
    )
    editor = RecordEditorService(store, runtime_service, desktop_service, inspector)
    library = LibraryManager(store, runtime_service, desktop_service)
    return install_manager, editor, library, store, inspector


def test_record_editor_updates_name_comment_and_exec_template(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-edit.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-edit"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    install_manager, editor, _, store, _ = build_editor(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    result = install_manager.install(
        InstallRequest(
            source_path=source,
            display_name_override=None,
            comment_override=None,
            extra_args=[],
            arg_preset_id="none",
            allow_update=True,
            allow_reinstall=True,
        )
    )

    updated = editor.update_record(
        ManagedRecordUpdateRequest(
            internal_id=result.record.internal_id,
            display_name="Renamed Browser",
            comment="Updated comment",
            arg_preset_id="disable_gpu",
            extra_args=["--user-flag"],
        )
    )

    assert updated.display_name == "Renamed Browser"
    assert updated.comment == "Updated comment"
    assert updated.arg_preset_id == "disable_gpu"
    assert updated.extra_args == ["--user-flag"]
    assert (
        f"{test_paths.self_command_path} launch {updated.internal_id} --desktop -- --existing --disable-gpu --user-flag %U"
        == updated.desktop_exec_template
    )
    desktop_text = Path(updated.managed_desktop_path).read_text(encoding="utf-8")
    assert "Name=Renamed Browser" in desktop_text
    assert "Comment=Updated comment" in desktop_text
    assert updated == store.load(updated.internal_id)
    assert store.load_index()[updated.internal_id]["display_name"] == "Renamed Browser"


def test_record_editor_preview_uses_structured_launch_inputs(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-preview.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-preview"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    install_manager, editor, _, _, _ = build_editor(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    result = install_manager.install(
        InstallRequest(
            source_path=source,
            display_name_override=None,
            comment_override=None,
            extra_args=[],
            arg_preset_id="none",
            allow_update=True,
            allow_reinstall=True,
        )
    )

    preview = editor.build_effective_command(
        result.record,
        arg_preset_id="disable_gpu",
        extra_args=["--user-flag"],
    )

    assert preview == (
        f"{test_paths.self_command_path} launch {result.record.internal_id} --desktop -- --existing --disable-gpu --user-flag %U"
    )


def test_record_editor_rebuilds_when_desktop_file_is_missing(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-missing-desktop.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-missing-desktop"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    install_manager, editor, _, _, inspector = build_editor(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0"), make_inspection(source, extracted, "1.0.0")],
    )
    result = install_manager.install(
        InstallRequest(
            source_path=source,
            display_name_override=None,
            comment_override=None,
            extra_args=[],
            arg_preset_id="none",
            allow_update=True,
            allow_reinstall=True,
        )
    )
    Path(result.record.managed_desktop_path).unlink()

    updated = editor.update_record(
        ManagedRecordUpdateRequest(
            internal_id=result.record.internal_id,
            display_name="Fallback Save",
            comment=None,
            arg_preset_id="none",
            extra_args=[],
        )
    )

    assert Path(updated.managed_desktop_path).exists()
    assert "Name=Fallback Save" in Path(updated.managed_desktop_path).read_text(encoding="utf-8")
    assert inspector.cleanup_calls == 2


def test_record_editor_fails_when_launcher_path_is_unresolved(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-unresolved-launcher.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-unresolved-launcher"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    install_manager, _, _, store, inspector = build_editor(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    result = install_manager.install(
        InstallRequest(
            source_path=source,
            display_name_override=None,
            comment_override=None,
            extra_args=[],
            arg_preset_id="none",
            allow_update=True,
            allow_reinstall=True,
        )
    )
    unresolved_desktop_service = DesktopEntryService(tooling, launcher_command_resolver=lambda: None)
    unresolved_runtime_service = ManagedAppRuntimeService(
        test_paths,
        inspector,
        unresolved_desktop_service,
        IconResolver(test_paths),
        IdResolver(),
    )
    editor = RecordEditorService(store, unresolved_runtime_service, unresolved_desktop_service, inspector)

    with pytest.raises(ValueError, match="Could not resolve a concrete launcher path"):
        editor.update_record(
            ManagedRecordUpdateRequest(
                internal_id=result.record.internal_id,
                display_name=result.record.display_name,
                comment=result.record.comment,
                arg_preset_id="none",
                extra_args=[],
            )
        )


def test_details_payload_location_prefers_payload_path(test_paths) -> None:
    record = ManagedAppRecord.from_dict(
        {
            "internal_id": "demo",
            "display_name": "Demo",
            "comment": None,
            "version": "1.0.0",
            "appstream_id": "org.demo.App",
            "embedded_desktop_basename": "demo.desktop",
            "identity_fingerprint": "abc",
            "managed_appimage_path": "/apps/demo.AppImage",
            "managed_desktop_path": "/apps/demo.desktop",
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
            "managed_payload_path": "/payload/demo.AppImage",
            "managed_payload_dir": "/payload",
        }
    )

    assert details_payload_location(record) == ("Payload Path", "/payload/demo.AppImage")


def test_details_payload_location_falls_back_to_payload_directory(test_paths) -> None:
    record = ManagedAppRecord.from_dict(
        {
            "internal_id": "demo",
            "display_name": "Demo",
            "comment": None,
            "version": "1.0.0",
            "appstream_id": "org.demo.App",
            "embedded_desktop_basename": "demo.desktop",
            "identity_fingerprint": "abc",
            "managed_appimage_path": "/apps/demo.AppImage",
            "managed_desktop_path": "/apps/demo.desktop",
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
            "managed_payload_path": None,
            "managed_payload_dir": "/payload",
        }
    )

    assert details_payload_location(record) == ("Payload Directory", "/payload")
