from __future__ import annotations

import os
from pathlib import Path

from appimage_integrator.models import AppImageInspection, InstallRequest
from appimage_integrator.services.desktop_entry import parse_desktop_entry, DesktopEntryService
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.install_manager import InstallManager
from appimage_integrator.services.library_manager import LibraryManager
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
    manager = InstallManager(
        test_paths,
        inspector,
        desktop_service,
        icon_resolver,
        IdResolver(),
        store,
        tooling,
    )
    return manager, store, inspector, icon_resolver, desktop_service


def test_install_update_and_uninstall_flow(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract1"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, store, inspector, _, _ = build_manager(
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
    assert Path(first.record.managed_desktop_path).exists()
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


def test_ensure_source_executable_adds_execute_bit(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "needs-trust.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    source.chmod(0o644)

    extracted = test_paths.cache_extract_dir / "extract-trust"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, _, _, _, _ = build_manager(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    manager.ensure_source_executable(source)

    assert os.access(source, os.X_OK)
    assert source.stat().st_mode & 0o100


def test_library_validation_and_repair(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract2"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager, store, _, icon_resolver, desktop_service = build_manager(
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

    library = LibraryManager(store)
    status, messages = library.validate_record(record)
    assert status in {"warning", "error"}
    assert messages

    repair = RepairManager(FakeInspector([make_inspection(Path(record.managed_appimage_path), extracted, "1.0.0")]), desktop_service, icon_resolver, store)
    repaired, report = repair.repair(record)
    assert report.actions_taken
    assert Path(repaired.managed_desktop_path).exists()
