from __future__ import annotations

import os
from pathlib import Path

import pytest

from appimage_integrator.models import AppImageInspection, InstallRequest, ManagedAppRecord
from appimage_integrator.services.desktop_entry import parse_desktop_entry, DesktopEntryService
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.install_manager import InstallManager
from appimage_integrator.services.library_manager import LibraryManager
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.services.repair_manager import RepairManager
from appimage_integrator.storage.metadata_store import MetadataStore


class FakeInspector:
    def __init__(self, inspections: list[AppImageInspection]) -> None:
        self.inspections = inspections
        self.cleanup_calls = 0

    def inspect(self, _source_path: Path) -> AppImageInspection:
        return self.inspections.pop(0)

    def cleanup(self, _inspection: AppImageInspection) -> None:
        self.cleanup_calls += 1


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


class AppPathsLike:
    def __init__(self, extracted_dir: Path) -> None:
        self.icons_dir = extracted_dir.parent / "icons"


def build_manager(test_paths, tooling, inspections: list[AppImageInspection]):
    store = MetadataStore(test_paths)
    icon_resolver = IconResolver(test_paths)
    inspector = FakeInspector(inspections)
    desktop_service = DesktopEntryService(tooling)
    runtime_service = ManagedAppRuntimeService(
        test_paths,
        inspector,
        desktop_service,
        icon_resolver,
        IdResolver(),
    )
    manager = InstallManager(
        test_paths,
        inspector,
        desktop_service,
        icon_resolver,
        IdResolver(),
        runtime_service,
        store,
        tooling,
    )
    return manager, store, inspector, icon_resolver, desktop_service, runtime_service


def test_install_update_and_uninstall_flow(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract1"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, store, inspector, _, _, _ = build_manager(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0"), make_inspection(source, extracted, "2.0.0")],
    )

    first = manager.install(
        InstallRequest(
            source_path=source,
            display_name_override=None,
            comment_override=None,
            extra_args=["--user-flag"],
            arg_preset_id="disable_gpu",
            allow_update=True,
            allow_reinstall=True,
        )
    )
    assert first.mode == "install"
    assert Path(first.record.managed_appimage_path).exists()
    assert Path(first.record.managed_appimage_path).is_symlink()
    assert Path(first.record.managed_payload_path).exists()
    assert Path(first.record.managed_payload_dir).is_dir()
    assert Path(first.record.managed_desktop_path).exists()
    assert first.record.managed_appimage_path in Path(first.record.managed_desktop_path).read_text(encoding="utf-8")
    assert inspector.cleanup_calls == 1

    updated = manager.install(
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
    assert updated.mode == "update"
    assert store.load(updated.record.internal_id).version == "2.0.0"

    manager.uninstall(updated.record)
    assert store.load(updated.record.internal_id) is None
    assert not Path(updated.record.managed_appimage_path).exists()
    assert not Path(updated.record.managed_payload_dir).exists()


def test_ensure_source_executable_adds_execute_bit(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "needs-trust.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    source.chmod(0o644)

    extracted = test_paths.cache_extract_dir / "extract-trust"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, _, _, _, _, _ = build_manager(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    manager.ensure_source_executable(source)

    assert os.access(source, os.X_OK)
    assert source.stat().st_mode & 0o100


def test_install_rejects_non_appimage_sources(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "not-appimage.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("plain text", encoding="utf-8")
    source.chmod(0o755)

    manager, _, inspector, _, _, _ = build_manager(
        test_paths,
        tooling,
        [
            AppImageInspection(
                source_path=source,
                is_appimage=False,
                appimage_type="unknown",
                is_executable=True,
                detected_name=source.stem,
                detected_comment=None,
                detected_version=None,
                appstream_id=None,
                embedded_desktop_filename=None,
                desktop_entry=None,
                chosen_icon_candidate=None,
                startup_wm_class=None,
                mime_types=[],
                categories=[],
                terminal=None,
                startup_notify=None,
                exec_placeholders=[],
                warnings=["The file does not strongly identify itself as an AppImage."],
                errors=["Could not extract AppImage contents."],
                extracted_dir=None,
            )
        ],
    )

    with pytest.raises(ValueError, match="not a valid AppImage"):
        manager.install(
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

    assert inspector.cleanup_calls == 1


def test_library_validation_and_repair(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract2"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, store, _, icon_resolver, desktop_service, runtime_service = build_manager(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0"), make_inspection(source, extracted, "1.0.0")],
    )
    result = manager.install(
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
    record = result.record
    os.unlink(record.managed_desktop_path)

    library = LibraryManager(store, runtime_service, desktop_service)
    _, status, messages = library.validate_record(record)
    assert status in {"warning", "error"}
    assert messages

    repair = RepairManager(
        FakeInspector([make_inspection(Path(record.managed_appimage_path), extracted, "1.0.0")]),
        desktop_service,
        icon_resolver,
        runtime_service,
        store,
    )
    repaired, report = repair.repair(record)
    assert report.actions_taken
    assert Path(repaired.managed_desktop_path).exists()


def test_library_validation_reports_non_executable_appimage(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-nonexec.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-nonexec"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, store, _, _, desktop_service, runtime_service = build_manager(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    result = manager.install(
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
    Path(result.record.managed_appimage_path).chmod(0o644)

    library = LibraryManager(store, runtime_service, desktop_service)
    _, status, messages = library.validate_record(result.record)

    assert status == "error"
    assert "Managed AppImage is not executable." in messages


def test_library_validation_treats_desktop_warnings_as_non_blocking(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-warning.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-warning"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, store, _, _, desktop_service, runtime_service = build_manager(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    result = manager.install(
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

    desktop_service.validate_text = lambda _text: ["demo.desktop: warning: comment matches name"]
    library = LibraryManager(store, runtime_service, desktop_service)
    _, status, messages = library.validate_record(result.record)

    assert status == "warning"
    assert messages == ["Desktop launcher warning: demo.desktop: warning: comment matches name"]


def test_repair_regenerates_invalid_desktop(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-invalid-desktop.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-invalid-desktop"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, store, _, icon_resolver, desktop_service, runtime_service = build_manager(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0"), make_inspection(source, extracted, "1.0.0")],
    )
    result = manager.install(
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
    Path(result.record.managed_desktop_path).write_text("BROKEN\n", encoding="utf-8")
    desktop_service.validate_text = lambda text: ["desktop is broken"] if text == "BROKEN\n" else []

    repair = RepairManager(
        FakeInspector([make_inspection(Path(result.record.managed_appimage_path), extracted, "1.0.0")]),
        desktop_service,
        icon_resolver,
        runtime_service,
        store,
    )
    repaired, report = repair.repair(result.record)

    assert report.success
    assert "Regenerated desktop launcher." in report.actions_taken
    assert Path(repaired.managed_desktop_path).read_text(encoding="utf-8").startswith("[Desktop Entry]\n")


def test_library_validation_adopts_managed_replacement(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-adopt"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, store, inspector, _, desktop_service, runtime_service = build_manager(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0"), make_inspection(source, extracted, "2.0.0")],
    )
    result = manager.install(
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
    record = result.record
    old_payload = Path(record.managed_payload_path)
    old_payload.unlink()
    replacement = Path(record.managed_payload_dir) / "demo-v2.AppImage"
    replacement.write_text("appimage", encoding="utf-8")
    replacement.chmod(0o755)

    library = LibraryManager(store, runtime_service, desktop_service)
    updated_record, status, messages = library.validate_record(record)

    assert status == "ok"
    assert messages == []
    assert updated_record.version == "2.0.0"
    assert Path(updated_record.managed_appimage_path).is_symlink()
    assert Path(updated_record.managed_appimage_path).resolve() == replacement.resolve()
    assert inspector.cleanup_calls == 2


def test_library_validation_does_not_scan_source_directory_for_replacement(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-source-scan"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, store, _, _, desktop_service, runtime_service = build_manager(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    result = manager.install(
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
    record = result.record
    Path(record.managed_payload_path).unlink()
    downloads_replacement = source.parent / "demo-v2.AppImage"
    downloads_replacement.write_text("appimage", encoding="utf-8")
    downloads_replacement.chmod(0o755)

    library = LibraryManager(store, runtime_service, desktop_service)
    _, status, messages = library.validate_record(record)

    assert status == "error"
    assert "Managed AppImage is missing." in messages


def test_library_validation_migrates_legacy_record_to_symlink_layout(test_paths, tooling) -> None:
    legacy_path = test_paths.applications_dir / "legacy-demo-1234.AppImage"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("appimage", encoding="utf-8")
    legacy_path.chmod(0o755)
    desktop_path = test_paths.desktop_entries_dir / "legacy-demo-1234.desktop"
    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    desktop_path.write_text("[Desktop Entry]\nType=Application\nName=Legacy\nExec=/tmp/legacy\n", encoding="utf-8")

    record = ManagedAppRecord.from_dict(
        {
            "internal_id": "legacy-demo-1234",
            "display_name": "Legacy Demo",
            "comment": None,
            "version": "1.0.0",
            "appstream_id": None,
            "embedded_desktop_basename": "legacy.desktop",
            "identity_fingerprint": "legacy-demo-1234",
            "managed_appimage_path": str(legacy_path),
            "managed_desktop_path": str(desktop_path),
            "managed_icon_path": None,
            "source_file_name_at_install": "legacy.AppImage",
            "source_path_last_seen": str(test_paths.home / "Downloads" / "legacy.AppImage"),
            "desktop_exec_template": str(legacy_path),
            "extra_args": [],
            "arg_preset_id": "none",
            "installed_at": "2026-03-09T00:00:00+00:00",
            "updated_at": "2026-03-09T00:00:00+00:00",
            "appimage_type": "type2",
            "icon_managed_by_app": False,
            "managed_files": [str(legacy_path), str(desktop_path)],
            "last_validation_status": "ok",
            "last_validation_messages": [],
        }
    )

    store = MetadataStore(test_paths)
    store.save(record)
    inspector = FakeInspector([])
    icon_resolver = IconResolver(test_paths)
    desktop_service = DesktopEntryService(tooling)
    runtime_service = ManagedAppRuntimeService(
        test_paths,
        inspector,
        desktop_service,
        icon_resolver,
        IdResolver(),
    )
    library = LibraryManager(store, runtime_service, desktop_service)

    updated_record, status, messages = library.validate_record(record)

    assert status == "ok"
    assert messages == []
    assert Path(updated_record.managed_appimage_path).is_symlink()
    assert updated_record.managed_payload_path is not None
    assert Path(updated_record.managed_payload_path).exists()
