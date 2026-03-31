from __future__ import annotations

from pathlib import Path

from appimage_integrator.config import APP_ID, APP_NAME
from appimage_integrator.launcher import build_app_desktop_text
from appimage_integrator.models import AppImageInspection, InstallRequest
from appimage_integrator.self_integration import SELF_INTERNAL_ID, build_self_record
from appimage_integrator.services.desktop_entry import DesktopEntryService, parse_desktop_entry
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.install_manager import InstallManager
from appimage_integrator.services.library_manager import LibraryManager
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.storage.metadata_store import MetadataStore


class FakeInspector:
    def __init__(self, inspections: list[AppImageInspection]) -> None:
        self.inspections = inspections

    def inspect(self, _source_path: Path) -> AppImageInspection:
        return self.inspections.pop(0)

    def cleanup(self, _inspection: AppImageInspection) -> None:
        return None


def make_self_inspection(source_path: Path, extracted_dir: Path, version: str | None = "1.0.0") -> AppImageInspection:
    icon_candidate = IconResolver._candidate_from_path(
        IconResolver(type("Paths", (), {"icons_dir": extracted_dir.parent / "icons"})()),
        extracted_dir,
        extracted_dir / f"{APP_ID}.svg",
    )
    entry = parse_desktop_entry(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Install and manage AppImage desktop integrations\n"
        "Exec=AppRun\n"
        f"Icon={APP_ID}\n"
        f"X-AppImage-Version={version or ''}\n",
        f"{APP_ID}.desktop",
    )
    return AppImageInspection(
        source_path=source_path,
        is_appimage=True,
        appimage_type="type2",
        is_executable=True,
        detected_name=APP_NAME,
        detected_comment="Install and manage AppImage desktop integrations",
        detected_version=version,
        appstream_id=APP_ID,
        embedded_desktop_filename=f"{APP_ID}.desktop",
        desktop_entry=entry,
        chosen_icon_candidate=icon_candidate,
        startup_wm_class=APP_ID,
        mime_types=[],
        categories=["Utility"],
        terminal=False,
        startup_notify=True,
        exec_placeholders=[],
        warnings=[],
        errors=[],
        extracted_dir=extracted_dir,
    )


def test_build_self_record_uses_reserved_self_paths(test_paths) -> None:
    source = test_paths.home / "Downloads" / "AppImage-Integrator.AppImage"
    record = build_self_record(
        test_paths,
        source_path_last_seen=source,
        launcher_command=[str(test_paths.self_command_path)],
    )

    assert record.internal_id == SELF_INTERNAL_ID
    assert record.display_name == APP_NAME
    assert record.managed_appimage_path == str(test_paths.self_appimage_path)
    assert record.managed_desktop_path == str(test_paths.self_desktop_entry_path)
    assert record.source_path_last_seen == str(source)
    assert record.desktop_exec_template == str(test_paths.self_command_path)


def test_library_validation_keeps_self_record_on_reserved_appimage_path(test_paths, tooling) -> None:
    test_paths.self_appimage_path.parent.mkdir(parents=True, exist_ok=True)
    test_paths.self_appimage_path.write_text("appimage", encoding="utf-8")
    test_paths.self_appimage_path.chmod(0o755)
    test_paths.self_desktop_entry_path.parent.mkdir(parents=True, exist_ok=True)
    test_paths.self_desktop_entry_path.write_text(
        build_app_desktop_text([str(test_paths.self_appimage_path)]),
        encoding="utf-8",
    )

    desktop_service = DesktopEntryService(
        tooling,
        launcher_command_resolver=lambda: [str(test_paths.self_command_path)],
    )
    runtime_service = ManagedAppRuntimeService(
        test_paths,
        FakeInspector([]),
        desktop_service,
        IconResolver(test_paths),
        IdResolver(),
    )
    library_manager = LibraryManager(
        MetadataStore(test_paths),
        runtime_service,
        desktop_service,
    )

    record = build_self_record(test_paths)
    validated, status, messages = library_manager.validate_record(
        record,
        allow_reconcile_inspection=False,
    )

    assert validated.internal_id == SELF_INTERNAL_ID
    assert validated.managed_appimage_path == str(test_paths.self_appimage_path)
    assert Path(validated.managed_appimage_path).is_symlink()
    assert Path(validated.managed_payload_path).exists()
    assert status == "ok"
    assert messages == []


def test_install_manager_routes_self_app_to_reserved_paths(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "AppImage-Integrator.AppImage"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("appimage", encoding="utf-8")
    source.chmod(0o755)

    extracted = test_paths.cache_extract_dir / "extract-self"
    extracted.mkdir(parents=True, exist_ok=True)
    (extracted / f"{APP_ID}.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    inspector = FakeInspector([make_self_inspection(source, extracted)])
    store = MetadataStore(test_paths)
    desktop_service = DesktopEntryService(
        tooling,
        launcher_command_resolver=lambda: [str(test_paths.self_command_path)],
    )
    runtime_service = ManagedAppRuntimeService(
        test_paths,
        inspector,
        desktop_service,
        IconResolver(test_paths),
        IdResolver(),
    )
    install_manager = InstallManager(
        test_paths,
        inspector,
        desktop_service,
        IconResolver(test_paths),
        IdResolver(),
        runtime_service,
        store,
        tooling,
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

    assert result.record.internal_id == SELF_INTERNAL_ID
    assert result.record.managed_appimage_path == str(test_paths.self_appimage_path)
    assert result.record.managed_desktop_path == str(test_paths.self_desktop_entry_path)
    assert test_paths.self_appimage_path.is_symlink()
    assert test_paths.self_command_path.exists()
