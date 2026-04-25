from __future__ import annotations

from pathlib import Path

from appimage_integrator.models import AppImageInspection, ManagedAppRecord
from appimage_integrator.services.desktop_entry import parse_desktop_entry
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services import update_discovery as update_discovery_module
from appimage_integrator.services.update_discovery import UpdateDiscoveryService


class MappingInspector:
    def __init__(self, inspections: dict[Path, AppImageInspection]) -> None:
        self.inspections = {path.resolve(): inspection for path, inspection in inspections.items()}
        self.cleanup_calls = 0

    def inspect(self, source_path: Path) -> AppImageInspection:
        return self.inspections[source_path.resolve()]

    def cleanup(self, _inspection: AppImageInspection) -> None:
        self.cleanup_calls += 1


class AppPathsLike:
    def __init__(self, extracted_dir: Path) -> None:
        self.icons_dir = extracted_dir.parent / "icons"


def make_inspection(
    source_path: Path,
    extracted_dir: Path,
    *,
    version: str | None,
    name: str = "Demo Browser",
    appstream_id: str | None = "org.demo.Browser",
    desktop_filename: str = "demo.desktop",
    is_executable: bool = True,
) -> AppImageInspection:
    icon_candidate = IconResolver._candidate_from_path(
        IconResolver(AppPathsLike(extracted_dir)),
        extracted_dir,
        extracted_dir / "demo.svg",
    )
    entry = parse_desktop_entry(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        "Comment=Demo comment\n"
        "Exec=AppRun --existing %U\n"
        "Icon=demo\n"
        "StartupWMClass=DemoBrowser\n"
        f"X-AppImage-Version={version or ''}\n",
        desktop_filename,
    )
    return AppImageInspection(
        source_path=source_path,
        is_appimage=True,
        appimage_type="type2",
        is_executable=is_executable,
        detected_name=name,
        detected_comment="Demo comment",
        detected_version=version,
        appstream_id=appstream_id,
        embedded_desktop_filename=desktop_filename,
        desktop_entry=entry,
        chosen_icon_candidate=icon_candidate,
        startup_wm_class="DemoBrowser",
        mime_types=[],
        categories=[],
        terminal=False,
        startup_notify=True,
        exec_placeholders=["%U"],
        warnings=[],
        errors=[],
        extracted_dir=extracted_dir,
    )


def make_record(test_paths, source_path: Path) -> ManagedAppRecord:
    return ManagedAppRecord.from_dict(
        {
            "internal_id": "org-demo-browser-b3029f72",
            "display_name": "Demo Browser",
            "comment": "Demo comment",
            "version": "1.0.0",
            "appstream_id": "org.demo.Browser",
            "embedded_desktop_basename": "demo.desktop",
            "identity_fingerprint": "b3029f72",
            "managed_appimage_path": str(test_paths.applications_dir / "org-demo-browser-b3029f72.AppImage"),
            "managed_desktop_path": str(test_paths.desktop_entries_dir / "org-demo-browser-b3029f72.desktop"),
            "managed_icon_path": None,
            "source_file_name_at_install": source_path.name,
            "source_path_last_seen": str(source_path),
            "desktop_exec_template": str(test_paths.applications_dir / "org-demo-browser-b3029f72.AppImage"),
            "extra_args": [],
            "arg_preset_id": "none",
            "installed_at": "2026-03-09T00:00:00+00:00",
            "updated_at": "2026-03-09T00:00:00+00:00",
            "appimage_type": "type2",
            "icon_managed_by_app": False,
            "managed_files": [],
            "last_validation_status": "ok",
            "last_validation_messages": [],
            "managed_payload_path": None,
            "managed_payload_dir": str(test_paths.managed_payloads_root / "org-demo-browser-b3029f72"),
        }
    )


def test_update_discovery_finds_higher_version_in_source_directory(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            candidate: make_inspection(candidate, extracted, version="2.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())

    result = service.discover_updates(make_record(test_paths, source))

    assert [item.path for item in result.higher_version_candidates] == [candidate]
    assert result.higher_version_candidates[0].match_kind == "identity"
    assert result.same_or_unknown_candidates == []


def test_update_discovery_uses_downloads_and_ignores_current_and_managed_payload(test_paths) -> None:
    source = test_paths.home / "Apps" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    downloads_candidate = test_paths.home / "Downloads" / "demo-v2.AppImage"
    downloads_candidate.parent.mkdir(parents=True)
    downloads_candidate.write_text("appimage", encoding="utf-8")
    active_payload = test_paths.managed_payloads_root / "org-demo-browser-b3029f72" / "demo-v1.AppImage"
    active_payload.parent.mkdir(parents=True)
    active_payload.write_text("appimage", encoding="utf-8")
    managed_payload_candidate = test_paths.managed_payloads_root / "org-demo-browser-b3029f72" / "demo-v3.AppImage"
    managed_payload_candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-downloads"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            downloads_candidate: make_inspection(downloads_candidate, extracted, version="2.0.0"),
            managed_payload_candidate: make_inspection(managed_payload_candidate, extracted, version="3.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "managed_payload_path": str(active_payload),
        }
    )

    result = service.discover_updates(record)

    assert [item.path for item in result.higher_version_candidates] == [managed_payload_candidate, downloads_candidate]
    assert active_payload not in [item.path for item in result.higher_version_candidates]
    assert source not in [item.path for item in result.higher_version_candidates]
    assert test_paths.managed_payloads_root / "org-demo-browser-b3029f72" in result.searched_directories


def test_update_discovery_searches_managed_payload_dir_without_active_payload(test_paths) -> None:
    source = test_paths.home / "Apps" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    managed_payload_candidate = test_paths.managed_payloads_root / "org-demo-browser-b3029f72" / "demo-v2.AppImage"
    managed_payload_candidate.parent.mkdir(parents=True)
    managed_payload_candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-managed-dir"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            managed_payload_candidate: make_inspection(managed_payload_candidate, extracted, version="2.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())

    result = service.discover_updates(make_record(test_paths, source))

    assert [item.path for item in result.higher_version_candidates] == [managed_payload_candidate]
    assert test_paths.managed_payloads_root / "org-demo-browser-b3029f72" in result.searched_directories


def test_update_discovery_limits_candidates_per_directory(test_paths, monkeypatch) -> None:
    monkeypatch.setattr(update_discovery_module, "MAX_APPIMAGE_CANDIDATES_PER_DIRECTORY", 3)
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate_a = source.parent / "demo-v2-a.AppImage"
    candidate_b = source.parent / "demo-v2-b.AppImage"
    candidate_c = source.parent / "demo-v2-c.AppImage"
    for candidate in (candidate_a, candidate_b, candidate_c):
        candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-limit"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            candidate_a: make_inspection(candidate_a, extracted, version="2.0.0"),
            candidate_b: make_inspection(candidate_b, extracted, version="2.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())

    result = service.discover_updates(make_record(test_paths, source))

    discovered_paths = [item.path for item in result.higher_version_candidates]
    assert discovered_paths == [candidate_b, candidate_a]
    assert candidate_c not in discovered_paths


def test_update_discovery_uses_filename_fallback_and_same_version_bucket(test_paths) -> None:
    source = test_paths.home / "Downloads" / "Demo-Browser-1.0.0.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    same_version = source.parent / "Demo_Browser_1.0.0_build2.AppImage"
    same_version.write_text("appimage", encoding="utf-8")
    higher_version = source.parent / "Demo_Browser_2.0.0.AppImage"
    higher_version.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-filename"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            same_version: make_inspection(
                same_version,
                extracted,
                version="1.0.0",
                name="Demo Browser",
                appstream_id=None,
                desktop_filename="other.desktop",
            ),
            higher_version: make_inspection(
                higher_version,
                extracted,
                version="2.0.0",
                name="Demo Browser",
                appstream_id=None,
                desktop_filename="other.desktop",
            ),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = make_record(test_paths, source)

    result = service.discover_updates(record)

    assert [item.path for item in result.higher_version_candidates] == [higher_version]
    assert [item.path for item in result.same_or_unknown_candidates] == [same_version]
    assert result.higher_version_candidates[0].match_kind == "filename"


def test_update_discovery_sorts_identity_before_filename(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    identity_candidate = source.parent / "demo-v2.AppImage"
    identity_candidate.write_text("appimage", encoding="utf-8")
    filename_candidate = source.parent / "Demo_Browser_3.0.0.AppImage"
    filename_candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-sort"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            identity_candidate: make_inspection(identity_candidate, extracted, version="2.0.0"),
            filename_candidate: make_inspection(
                filename_candidate,
                extracted,
                version="3.0.0",
                name="Demo Browser",
                appstream_id=None,
                desktop_filename="other.desktop",
            ),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = make_record(test_paths, source)

    result = service.discover_updates(record)

    assert [item.path for item in result.higher_version_candidates] == [identity_candidate, filename_candidate]


def test_update_discovery_skips_unrelated_filenames_when_likely_match_exists(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    likely_candidate = source.parent / "demo-v2.AppImage"
    likely_candidate.write_text("appimage", encoding="utf-8")
    unrelated_candidate = source.parent / "totally-unrelated.AppImage"
    unrelated_candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-prefilter"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            likely_candidate: make_inspection(likely_candidate, extracted, version="2.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = make_record(test_paths, source)

    result = service.discover_updates(record)

    assert [item.path for item in result.higher_version_candidates] == [likely_candidate]


def test_update_discovery_falls_back_to_full_scan_when_no_likely_name_matches(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    fallback_candidate = source.parent / "release-latest.AppImage"
    fallback_candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-fallback"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            fallback_candidate: make_inspection(
                fallback_candidate,
                extracted,
                version="2.0.0",
            ),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = make_record(test_paths, source)

    result = service.discover_updates(record)

    assert [item.path for item in result.higher_version_candidates] == [fallback_candidate]


def test_update_discovery_does_not_promote_known_version_when_current_version_is_unknown(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-unknown-current"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            candidate: make_inspection(candidate, extracted, version="2.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "version": None,
        }
    )

    result = service.discover_updates(record)

    assert result.higher_version_candidates == []
    assert [item.path for item in result.same_or_unknown_candidates] == [candidate]


def test_update_discovery_keeps_non_executable_candidates(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-nonexec"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            candidate: make_inspection(candidate, extracted, version="2.0.0", is_executable=False),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())

    result = service.discover_updates(make_record(test_paths, source))

    assert [item.path for item in result.higher_version_candidates] == [candidate]
    assert result.higher_version_candidates[0].is_executable is False


def test_update_discovery_skips_active_payload_but_discovers_renamed_payload_sibling(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    active_payload = test_paths.managed_payloads_root / "org-demo-browser-b3029f72" / "demo-v1.AppImage"
    active_payload.parent.mkdir(parents=True)
    active_payload.write_text("appimage", encoding="utf-8")
    renamed_payload = test_paths.managed_payloads_root / "org-demo-browser-b3029f72" / "demo-v2.AppImage"
    renamed_payload.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-managed-payload"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    inspector = MappingInspector(
        {
            renamed_payload: make_inspection(renamed_payload, extracted, version="2.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "managed_payload_path": str(active_payload),
        }
    )

    result = service.discover_updates(record)

    assert [item.path for item in result.higher_version_candidates] == [renamed_payload]
    assert active_payload not in [item.path for item in result.higher_version_candidates]
