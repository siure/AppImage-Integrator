from __future__ import annotations

from collections.abc import Callable
import re
from pathlib import Path

from appimage_integrator.models import (
    AppImageInspection,
    IdentityResolution,
    ManagedAppRecord,
    UpdateCandidate,
    UpdateDiscoveryResult,
)
from appimage_integrator.paths import AppPaths
from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.versioning import compare_versions

_ARCH_TOKENS = {
    "x86",
    "x64",
    "x86_64",
    "amd64",
    "arm64",
    "aarch64",
    "linux",
    "appimage",
}
_VERSION_RE = re.compile(r"\b\d+(?:[._-]\d+)*(?:[._-]?(?:alpha|beta|rc)\d*)?\b", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"[-_.()\[\]]+")
_WHITESPACE_RE = re.compile(r"\s+")
UpdateProgressCallback = Callable[[str, str], None]


class UpdateDiscoveryService:
    def __init__(self, paths: AppPaths, inspector: AppImageInspector, id_resolver: IdResolver) -> None:
        self.paths = paths
        self.inspector = inspector
        self.id_resolver = id_resolver

    def discover_updates(
        self,
        record: ManagedAppRecord,
        progress_callback: UpdateProgressCallback | None = None,
    ) -> UpdateDiscoveryResult:
        self._emit_progress(
            progress_callback,
            "Preparing search",
            f"Resolving where to search for updates to {record.display_name}.",
        )
        searched_directories = self._search_directories(record)
        higher_version_candidates: list[UpdateCandidate] = []
        same_or_unknown_candidates: list[UpdateCandidate] = []
        skipped_paths: list[str] = []
        candidate_entries: list[tuple[Path, str]] = []

        for directory, source_dir_kind in searched_directories:
            self._emit_progress(
                progress_callback,
                "Scanning directories",
                f"Looking for AppImages in {directory}.",
            )
            for candidate_path in self._iter_appimages(directory):
                if self._should_skip_candidate(record, candidate_path):
                    continue
                candidate_entries.append((candidate_path, source_dir_kind))

        likely_candidates, fallback_candidates = self._partition_candidates(record, candidate_entries)
        self._inspect_candidates(
            record,
            likely_candidates,
            higher_version_candidates,
            same_or_unknown_candidates,
            skipped_paths,
            progress_callback,
            stage_title="Checking likely matches",
        )
        if not higher_version_candidates and not same_or_unknown_candidates and fallback_candidates:
            self._inspect_candidates(
                record,
                fallback_candidates,
                higher_version_candidates,
                same_or_unknown_candidates,
                skipped_paths,
                progress_callback,
                stage_title="Checking remaining files",
            )

        self._emit_progress(
            progress_callback,
            "Ranking results",
            f"Sorting {len(higher_version_candidates) + len(same_or_unknown_candidates)} matching candidates.",
        )

        return UpdateDiscoveryResult(
            record=record,
            searched_directories=[directory for directory, _kind in searched_directories],
            higher_version_candidates=self._sort_candidates(higher_version_candidates, record),
            same_or_unknown_candidates=self._sort_candidates(same_or_unknown_candidates, record),
            skipped_paths=sorted(skipped_paths),
        )

    def evaluate_candidate(
        self,
        record: ManagedAppRecord,
        candidate_path: Path,
        source_dir_kind: str = "source_dir",
    ) -> UpdateCandidate | None:
        inspection = self.inspector.inspect(candidate_path)
        try:
            identity = self.id_resolver.resolve(inspection)
            return self._match_candidate(record, candidate_path, inspection, identity, source_dir_kind)
        finally:
            self.inspector.cleanup(inspection)

    def _search_directories(self, record: ManagedAppRecord) -> list[tuple[Path, str]]:
        source_parent = Path(record.source_path_last_seen).expanduser().resolve(strict=False).parent
        downloads = (self.paths.home / "Downloads").resolve(strict=False)
        candidates = [
            (source_parent, "source_dir"),
            (downloads, "downloads"),
        ]
        directories: list[tuple[Path, str]] = []
        seen: set[Path] = set()
        for directory, kind in candidates:
            if directory in seen or not directory.exists() or not directory.is_dir():
                continue
            seen.add(directory)
            directories.append((directory, kind))
        return directories

    def _iter_appimages(self, directory: Path) -> list[Path]:
        return sorted(
            (
                path
                for path in directory.rglob("*")
                if path.is_file() and path.suffix.lower() == ".appimage"
            ),
            key=lambda path: str(path).lower(),
        )

    def _should_skip_candidate(self, record: ManagedAppRecord, candidate_path: Path) -> bool:
        resolved_candidate = candidate_path.resolve(strict=False)
        managed_paths = {
            Path(record.managed_appimage_path).resolve(strict=False),
            Path(record.source_path_last_seen).expanduser().resolve(strict=False),
        }
        if resolved_candidate in managed_paths:
            return True
        if record.managed_payload_dir:
            payload_dir = Path(record.managed_payload_dir).resolve(strict=False)
            try:
                resolved_candidate.relative_to(payload_dir)
                return True
            except ValueError:
                return False
        return False

    def _match_candidate(
        self,
        record: ManagedAppRecord,
        candidate_path: Path,
        inspection: AppImageInspection,
        identity: IdentityResolution,
        source_dir_kind: str,
    ) -> UpdateCandidate | None:
        identity_score = self._identity_match_score(record, inspection, identity)
        if identity_score is not None:
            return UpdateCandidate(
                path=candidate_path,
                detected_version=inspection.detected_version,
                match_kind="identity",
                match_score=identity_score,
                identity_internal_id=identity.internal_id,
                identity_fingerprint=identity.identity_fingerprint,
                detected_name=inspection.detected_name,
                source_dir_kind=source_dir_kind,
                warnings=list(inspection.warnings),
            )

        filename_score = self._filename_match_score(record, candidate_path, inspection)
        if filename_score is None:
            return None
        return UpdateCandidate(
            path=candidate_path,
            detected_version=inspection.detected_version,
            match_kind="filename",
            match_score=filename_score,
            identity_internal_id=identity.internal_id,
            identity_fingerprint=identity.identity_fingerprint,
            detected_name=inspection.detected_name,
            source_dir_kind=source_dir_kind,
            warnings=list(inspection.warnings),
        )

    def _identity_match_score(
        self,
        record: ManagedAppRecord,
        inspection: AppImageInspection,
        identity: IdentityResolution,
    ) -> int | None:
        if identity.internal_id == record.internal_id:
            return 100
        if identity.identity_fingerprint == record.identity_fingerprint:
            return 95
        if inspection.appstream_id and record.appstream_id and inspection.appstream_id == record.appstream_id:
            return 90
        if (
            inspection.embedded_desktop_filename
            and record.embedded_desktop_basename
            and inspection.embedded_desktop_filename == record.embedded_desktop_basename
        ):
            return 85
        return None

    def _inspect_candidates(
        self,
        record: ManagedAppRecord,
        candidate_entries: list[tuple[Path, str]],
        higher_version_candidates: list[UpdateCandidate],
        same_or_unknown_candidates: list[UpdateCandidate],
        skipped_paths: list[str],
        progress_callback: UpdateProgressCallback | None,
        *,
        stage_title: str,
    ) -> None:
        total = len(candidate_entries)
        if total == 0:
            return

        for index, (candidate_path, source_dir_kind) in enumerate(candidate_entries, start=1):
            self._emit_progress(
                progress_callback,
                stage_title,
                f"Inspecting {candidate_path.name} ({index}/{total}).",
            )
            try:
                match = self.evaluate_candidate(record, candidate_path, source_dir_kind)
            except OSError as exc:
                skipped_paths.append(f"{candidate_path}: {exc}")
                continue
            if match is None:
                continue
            version_cmp = compare_versions(match.detected_version, record.version)
            if match.detected_version and record.version and version_cmp > 0:
                higher_version_candidates.append(match)
            else:
                same_or_unknown_candidates.append(match)

    def _partition_candidates(
        self,
        record: ManagedAppRecord,
        candidate_entries: list[tuple[Path, str]],
    ) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
        likely_candidates: list[tuple[Path, str]] = []
        fallback_candidates: list[tuple[Path, str]] = []
        for candidate_path, source_dir_kind in candidate_entries:
            if self._candidate_name_might_match(record, candidate_path):
                likely_candidates.append((candidate_path, source_dir_kind))
            else:
                fallback_candidates.append((candidate_path, source_dir_kind))
        return likely_candidates, fallback_candidates

    def _candidate_name_might_match(self, record: ManagedAppRecord, candidate_path: Path) -> bool:
        candidate_name = self._normalize_name(candidate_path.stem)
        if not candidate_name:
            return False
        hints = [
            self._normalize_name(Path(record.source_path_last_seen).stem),
            self._normalize_name(record.display_name),
            self._normalize_name(Path(record.embedded_desktop_basename).stem)
            if record.embedded_desktop_basename
            else "",
            self._normalize_name(record.appstream_id.rsplit(".", 1)[0])
            if record.appstream_id
            else "",
        ]
        return any(self._names_match(candidate_name, hint) for hint in hints if hint)

    def _emit_progress(
        self,
        progress_callback: UpdateProgressCallback | None,
        title: str,
        detail: str,
    ) -> None:
        if progress_callback is not None:
            progress_callback(title, detail)

    def _filename_match_score(
        self,
        record: ManagedAppRecord,
        candidate_path: Path,
        inspection: AppImageInspection,
    ) -> int | None:
        candidate_name = self._normalize_name(candidate_path.stem)
        original_source = self._normalize_name(Path(record.source_path_last_seen).stem)
        display_name = self._normalize_name(record.display_name)
        detected_name = self._normalize_name(inspection.detected_name or "")

        source_match = self._names_match(candidate_name, original_source) or self._names_match(candidate_name, display_name)
        if not source_match:
            return None

        if detected_name and not self._names_match(detected_name, display_name):
            return None

        if candidate_name == original_source or candidate_name == display_name:
            return 70
        if detected_name and detected_name == display_name:
            return 65
        return 60

    def _sort_candidates(
        self,
        candidates: list[UpdateCandidate],
        record: ManagedAppRecord,
    ) -> list[UpdateCandidate]:
        return sorted(
            candidates,
            key=lambda candidate: (
                0 if candidate.match_kind == "identity" else 1,
                -candidate.match_score,
                -self._version_rank(candidate.detected_version, record.version),
                -candidate.path.stat().st_mtime,
                candidate.path.name.lower(),
            ),
        )

    def _version_rank(self, candidate_version: str | None, current_version: str | None) -> int:
        return compare_versions(candidate_version, current_version)

    def _normalize_name(self, value: str) -> str:
        lowered = value.lower().strip()
        lowered = _VERSION_RE.sub(" ", lowered)
        lowered = _SEPARATOR_RE.sub(" ", lowered)
        tokens = [token for token in _WHITESPACE_RE.split(lowered) if token and token not in _ARCH_TOKENS]
        return " ".join(tokens)

    def _names_match(self, left: str, right: str) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return False
        smaller, larger = sorted((left_tokens, right_tokens), key=len)
        return smaller.issubset(larger)
