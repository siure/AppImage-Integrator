from __future__ import annotations

from pathlib import Path

from appimage_integrator.models import AppImageInspection, ManagedAppRecord
from appimage_integrator.services.cancellation import OperationCancelled
from appimage_integrator.services.desktop_entry import parse_desktop_entry
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.inspection_cache import InspectionCache
from appimage_integrator.services import update_discovery as update_discovery_module
from appimage_integrator.services.update_discovery import UpdateCandidateEntry, UpdateDiscoveryService


class MappingInspector:
    def __init__(self, inspections: dict[Path, AppImageInspection]) -> None:
        self.inspections = {path.resolve(): inspection for path, inspection in inspections.items()}
        self.cleanup_calls = 0
        self.inspect_calls = 0

    def inspect(self, source_path: Path, should_cancel=None) -> AppImageInspection:
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        self.inspect_calls += 1
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


def test_discover_updates_uses_cached_inspection_when_file_stat_matches(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-cache"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector({candidate: make_inspection(candidate, extracted, version="2.0.0")})
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver(), InspectionCache(test_paths))
    record = make_record(test_paths, source)

    service.discover_updates(record)
    cleanup_calls = inspector.cleanup_calls
    result = service.discover_updates(record)

    assert result.higher_version_candidates[0].path == candidate
    assert inspector.inspect_calls == 1
    assert inspector.cleanup_calls == cleanup_calls


def test_discover_updates_invalidates_cache_when_mtime_changes(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-cache-mtime"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector({candidate: make_inspection(candidate, extracted, version="2.0.0")})
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver(), InspectionCache(test_paths))
    record = make_record(test_paths, source)

    service.discover_updates(record)
    candidate.write_text("changed-appimage", encoding="utf-8")
    service.discover_updates(record)

    assert inspector.inspect_calls == 2


def test_cached_candidate_matching_preserves_identity_scores(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-cache-score"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector({candidate: make_inspection(candidate, extracted, version="2.0.0")})
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver(), InspectionCache(test_paths))
    record = make_record(test_paths, source)

    uncached = service.discover_updates(record).higher_version_candidates[0]
    cached = service.discover_updates(record).higher_version_candidates[0]

    assert cached.match_kind == uncached.match_kind == "identity"
    assert cached.match_score == uncached.match_score


def test_corrupt_inspection_cache_is_ignored(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    test_paths.inspection_cache_path.parent.mkdir(parents=True)
    test_paths.inspection_cache_path.write_text("{bad json", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-cache-corrupt"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector({candidate: make_inspection(candidate, extracted, version="2.0.0")})
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver(), InspectionCache(test_paths))

    result = service.discover_updates(make_record(test_paths, source))

    assert result.higher_version_candidates[0].path == candidate
    assert inspector.inspect_calls == 1


def test_collect_candidate_entries_scans_shared_downloads_once(monkeypatch, test_paths) -> None:
    source_one = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source_two = test_paths.home / "Downloads" / "demo-copy-v1.AppImage"
    source_one.parent.mkdir(parents=True)
    source_one.write_text("appimage", encoding="utf-8")
    source_two.write_text("appimage", encoding="utf-8")
    candidate = source_one.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    service = UpdateDiscoveryService(test_paths, MappingInspector({}), IdResolver())
    scans: list[Path] = []

    def iter_appimages(directory: Path) -> list[Path]:
        scans.append(directory)
        return [candidate]

    monkeypatch.setattr(service, "_iter_appimages", iter_appimages)

    _searched, entries = service.collect_candidate_entries(
        [make_record(test_paths, source_one), make_record(test_paths, source_two)],
        prefer_error_recovery=False,
    )

    assert scans.count(source_one.parent.resolve(strict=False)) == 1
    assert [entry.path for entry in entries] == [candidate]


def test_discover_updates_from_shared_entries_skips_each_record_active_payload(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    payload = test_paths.managed_payloads_root / "org-demo-browser-b3029f72" / "demo-v2.AppImage"
    payload.parent.mkdir(parents=True)
    payload.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-shared-skip"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector({payload: make_inspection(payload, extracted, version="2.0.0")})
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "managed_payload_path": str(payload),
        }
    )
    other_record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "internal_id": "org-demo-browser-copy",
            "identity_fingerprint": "copy-fingerprint",
            "managed_payload_path": None,
        }
    )
    entries = [
        UpdateCandidateEntry(
            path=payload,
            source_dir_kind="managed_payload_dir",
            resolved_path=payload.resolve(strict=False),
            stat_size=payload.stat().st_size,
            stat_mtime_ns=payload.stat().st_mtime_ns,
        )
    ]

    skipped = service.discover_updates_from_entries(record, [payload.parent], entries)
    matched = service.discover_updates_from_entries(other_record, [payload.parent], entries)

    assert skipped.higher_version_candidates == []
    assert matched.higher_version_candidates[0].path == payload


def test_update_discovery_matches_copy_base_identity(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-copy-update"
    extracted.mkdir(parents=True)
    inspection = make_inspection(candidate, extracted, version="2.0.0")
    base_identity = IdResolver().resolve(inspection)
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "internal_id": "demo-browser-copy-a1b2c3d4",
            "identity_fingerprint": "copy-fingerprint",
            "base_identity_fingerprint": base_identity.identity_fingerprint,
            "copy_index": 1,
        }
    )
    service = UpdateDiscoveryService(
        test_paths,
        MappingInspector({candidate: inspection}),
        IdResolver(),
    )

    match = service.evaluate_candidate(record, candidate)

    assert match is not None
    assert match.match_kind == "identity"
    assert match.match_score == 92


def test_update_discovery_detects_newer_nightly_for_nightly_channel(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-nightly-old.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-nightly-new.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-nightly-update"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "version": "v0.0.22-nightly.20260505.201",
        }
    )
    service = UpdateDiscoveryService(
        test_paths,
        MappingInspector(
            {
                candidate: make_inspection(
                    candidate,
                    extracted,
                    version="v0.0.22-nightly.20260506.201",
                ),
            }
        ),
        IdResolver(),
    )

    result = service.discover_updates(record)

    assert [item.path for item in result.higher_version_candidates] == [candidate]


def test_update_discovery_does_not_auto_promote_stable_to_nightly(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-stable.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-nightly.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-stable-nightly"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "version": "v0.0.22",
        }
    )
    service = UpdateDiscoveryService(
        test_paths,
        MappingInspector(
            {
                candidate: make_inspection(
                    candidate,
                    extracted,
                    version="v0.0.23-nightly.20260506.201",
                ),
            }
        ),
        IdResolver(),
    )

    result = service.discover_updates(record)

    assert result.higher_version_candidates == []
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


def test_update_discovery_excludes_known_lower_version_candidate(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v2.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-legacy.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-lower-version"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            candidate: make_inspection(candidate, extracted, version="1.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict({**make_record(test_paths, source).to_dict(), "version": "2.0.0"})

    result = service.discover_updates(record)

    assert result.higher_version_candidates == []
    assert result.same_or_unknown_candidates == []


def test_update_discovery_keeps_same_version_as_fallback(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v2.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-same.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-same-version"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            candidate: make_inspection(candidate, extracted, version="2.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict({**make_record(test_paths, source).to_dict(), "version": "2.0.0"})

    result = service.discover_updates(record)

    assert result.higher_version_candidates == []
    assert [item.path for item in result.same_or_unknown_candidates] == [candidate]


def test_update_discovery_prefilters_obvious_older_filename_without_inspection(test_paths) -> None:
    source = test_paths.home / "Downloads" / "Demo-Browser-2.0.0.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    older_candidate = source.parent / "Demo-Browser-1.0.0.AppImage"
    older_candidate.write_text("appimage", encoding="utf-8")
    inspector = MappingInspector({})
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict({**make_record(test_paths, source).to_dict(), "version": "2.0.0"})

    result = service.discover_updates(record)

    assert result.higher_version_candidates == []
    assert result.same_or_unknown_candidates == []
    assert inspector.cleanup_calls == 0


def test_update_discovery_does_not_prefilter_unknown_filename_version(test_paths) -> None:
    source = test_paths.home / "Downloads" / "Demo-Browser-2.0.0.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "Demo-Browser-latest.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-latest-version"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            candidate: make_inspection(candidate, extracted, version="3.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict({**make_record(test_paths, source).to_dict(), "version": "2.0.0"})

    result = service.discover_updates(record)

    assert [item.path for item in result.higher_version_candidates] == [candidate]
    assert result.same_or_unknown_candidates == []


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


def test_update_discovery_prefers_missing_payload_parent_for_recovery(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    missing_payload = test_paths.managed_payloads_root / "org-demo-browser-b3029f72" / "demo-v1.AppImage"
    missing_payload.parent.mkdir(parents=True)
    recovery_candidate = missing_payload.parent / "demo-v2.AppImage"
    recovery_candidate.write_text("appimage", encoding="utf-8")
    downloads_candidate = source.parent / "demo-v3.AppImage"
    downloads_candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-recovery-parent"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            recovery_candidate: make_inspection(recovery_candidate, extracted, version="2.0.0"),
            downloads_candidate: make_inspection(downloads_candidate, extracted, version="3.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "managed_payload_path": str(missing_payload),
        }
    )

    result = service.discover_updates(record, prefer_error_recovery=True)

    assert result.searched_directories[0] == missing_payload.parent
    assert [item.path for item in result.higher_version_candidates] == [
        recovery_candidate,
        downloads_candidate,
    ]
    assert result.higher_version_candidates[0].source_dir_kind == "recovery_payload_dir"


def test_update_discovery_uses_legacy_stable_parent_for_recovery(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    stable_parent = test_paths.applications_dir
    stable_parent.mkdir(parents=True)
    recovery_candidate = stable_parent / "demo-v2.AppImage"
    recovery_candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-recovery-stable"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            recovery_candidate: make_inspection(recovery_candidate, extracted, version="2.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "managed_payload_path": None,
            "managed_payload_dir": None,
        }
    )

    result = service.discover_updates(record, prefer_error_recovery=True)

    assert result.searched_directories[0] == stable_parent
    assert [item.path for item in result.higher_version_candidates] == [recovery_candidate]
    assert result.higher_version_candidates[0].source_dir_kind == "recovery_stable_dir"


def test_update_discovery_stops_after_recovery_match(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    missing_payload = test_paths.managed_payloads_root / "org-demo-browser-b3029f72" / "demo-v1.AppImage"
    missing_payload.parent.mkdir(parents=True)
    recovery_candidate = missing_payload.parent / "demo-v2.AppImage"
    recovery_candidate.write_text("appimage", encoding="utf-8")
    downloads_candidate = source.parent / "demo-v3.AppImage"
    downloads_candidate.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-discovery-stop"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    inspector = MappingInspector(
        {
            recovery_candidate: make_inspection(recovery_candidate, extracted, version="2.0.0"),
            downloads_candidate: make_inspection(downloads_candidate, extracted, version="3.0.0"),
        }
    )
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    record = ManagedAppRecord.from_dict(
        {
            **make_record(test_paths, source).to_dict(),
            "managed_payload_path": str(missing_payload),
        }
    )

    result = service.discover_updates(
        record,
        prefer_error_recovery=True,
        stop_after_first_recovery_match=True,
    )

    assert result.stopped_after_priority_match is True
    assert [item.path for item in result.higher_version_candidates] == [recovery_candidate]
    assert inspector.cleanup_calls == 1


def test_update_discovery_cancels_before_candidate_inspection(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    service = UpdateDiscoveryService(test_paths, MappingInspector({}), IdResolver())

    try:
        service.discover_updates(make_record(test_paths, source), should_cancel=lambda: True)
    except OperationCancelled:
        cancelled = True
    else:
        cancelled = False

    assert cancelled is True


def test_update_discovery_cancels_during_candidate_inspection(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    candidate = source.parent / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    inspector = MappingInspector({})
    service = UpdateDiscoveryService(test_paths, inspector, IdResolver())
    checks = iter([False, False, True])

    try:
        service.discover_updates(
            make_record(test_paths, source),
            should_cancel=lambda: next(checks, True),
        )
    except OperationCancelled:
        cancelled = True
    else:
        cancelled = False

    assert cancelled is True
