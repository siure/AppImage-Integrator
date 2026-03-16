from __future__ import annotations

import re
import shutil
import struct
from pathlib import Path

from appimage_integrator.models import AppImageInspection, IconCandidate
from appimage_integrator.paths import AppPaths


class IconResolver:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def score_candidate(self, candidate: IconCandidate) -> int:
        if candidate.kind == "svg":
            return 1_000_000
        if candidate.kind == "png":
            return (candidate.width or 0) * (candidate.height or 0)
        if candidate.kind == "xpm":
            return 1
        return 0

    def collect_candidates(self, extracted_dir: Path, desktop_icon_key: str | None) -> list[IconCandidate]:
        preferred_candidates: list[IconCandidate] = []
        if desktop_icon_key:
            key_path = extracted_dir / desktop_icon_key
            for path in self._candidate_paths_for_key(extracted_dir, key_path, desktop_icon_key):
                icon = self._candidate_from_path(extracted_dir, path)
                if icon:
                    preferred_candidates.append(icon)
        fallback_candidates: list[IconCandidate] = []
        dir_icon = extracted_dir / ".DirIcon"
        if dir_icon.exists():
            icon = self._candidate_from_path(extracted_dir, dir_icon.resolve())
            if icon:
                preferred_candidates.append(icon)
        for path in extracted_dir.rglob("*"):
            icon = self._candidate_from_path(extracted_dir, path)
            if icon:
                fallback_candidates.append(icon)
        ordered_candidates: list[IconCandidate] = []
        seen_relpaths: set[str] = set()
        for group in (preferred_candidates, fallback_candidates):
            unique: dict[str, IconCandidate] = {}
            for candidate in group:
                current = unique.get(candidate.relpath)
                if current is None or self.score_candidate(candidate) > self.score_candidate(current):
                    unique[candidate.relpath] = candidate
            for candidate in sorted(unique.values(), key=self.score_candidate, reverse=True):
                if candidate.relpath in seen_relpaths:
                    continue
                seen_relpaths.add(candidate.relpath)
                ordered_candidates.append(candidate)
        return ordered_candidates

    def choose_for_inspection(self, inspection: AppImageInspection) -> IconCandidate | None:
        if inspection.extracted_dir is None:
            return None
        candidates = self.collect_candidates(
            inspection.extracted_dir,
            inspection.desktop_entry.icon_key if inspection.desktop_entry else None,
        )
        return candidates[0] if candidates else None

    def install_icon(self, internal_id: str, candidate: IconCandidate | None) -> tuple[str, str | None, bool]:
        if candidate is None:
            return "application-x-executable", None, False
        ext = candidate.source_path.suffix or ".png"
        destination = self.paths.icons_dir / f"{internal_id}{ext}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate.source_path, destination)
        return str(destination), str(destination), True

    def _candidate_paths_for_key(self, extracted_dir: Path, key_path: Path, key_name: str) -> list[Path]:
        paths = []
        if key_path.exists():
            paths.append(key_path)
        for ext in (".svg", ".png", ".xpm"):
            candidate = extracted_dir / f"{key_name}{ext}"
            if candidate.exists():
                paths.append(candidate)
            paths.extend(extracted_dir.rglob(f"{key_name}{ext}"))
        return paths

    def _candidate_from_path(self, extracted_dir: Path, path: Path) -> IconCandidate | None:
        if not path.is_file():
            return None
        extracted_root = extracted_dir.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        try:
            relpath = str(resolved_path.relative_to(extracted_root))
        except ValueError:
            return None
        suffix = path.suffix.lower()
        if suffix not in {".svg", ".png", ".xpm"} and path.name != ".DirIcon":
            return None
        if suffix == ".svg":
            kind = "svg"
            width = None
            height = None
        else:
            kind = "png" if suffix == ".png" or path.name == ".DirIcon" else "xpm"
            width, height = self._read_raster_dimensions(resolved_path, kind)
        candidate = IconCandidate(
            source_path=resolved_path,
            relpath=relpath,
            kind=kind,
            width=width,
            height=height,
            score=0,
        )
        return IconCandidate(
            source_path=candidate.source_path,
            relpath=candidate.relpath,
            kind=candidate.kind,
            width=candidate.width,
            height=candidate.height,
            score=self.score_candidate(candidate),
        )

    def _read_raster_dimensions(self, path: Path, kind: str) -> tuple[int | None, int | None]:
        if kind == "png":
            return self._read_png_dimensions(path)
        if kind == "xpm":
            return self._read_xpm_dimensions(path)
        return None, None

    def _read_png_dimensions(self, path: Path) -> tuple[int | None, int | None]:
        try:
            with path.open("rb") as handle:
                header = handle.read(24)
        except OSError:
            return None, None

        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            return None, None

        width, height = struct.unpack(">II", header[16:24])
        return width, height

    def _read_xpm_dimensions(self, path: Path) -> tuple[int | None, int | None]:
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    match = re.search(r'"(\d+)\s+(\d+)\s+\d+\s+\d+"', line)
                    if match:
                        return int(match.group(1)), int(match.group(2))
        except OSError:
            return None, None

        return None, None
