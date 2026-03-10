from __future__ import annotations

import shutil
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

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
        candidates: list[IconCandidate] = []
        if desktop_icon_key:
            key_path = extracted_dir / desktop_icon_key
            for path in self._candidate_paths_for_key(extracted_dir, key_path, desktop_icon_key):
                icon = self._candidate_from_path(extracted_dir, path)
                if icon:
                    candidates.append(icon)
        dir_icon = extracted_dir / ".DirIcon"
        if dir_icon.exists():
            icon = self._candidate_from_path(extracted_dir, dir_icon.resolve())
            if icon:
                candidates.append(icon)
        for path in extracted_dir.rglob("*"):
            icon = self._candidate_from_path(extracted_dir, path)
            if icon:
                candidates.append(icon)
        unique: dict[str, IconCandidate] = {}
        for candidate in candidates:
            current = unique.get(candidate.relpath)
            if current is None or self.score_candidate(candidate) > self.score_candidate(current):
                unique[candidate.relpath] = candidate
        return sorted(unique.values(), key=self.score_candidate, reverse=True)

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
        return paths

    def _candidate_from_path(self, extracted_dir: Path, path: Path) -> IconCandidate | None:
        if not path.is_file():
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
            info = GdkPixbuf.Pixbuf.get_file_info(str(path))
            width = info.width if info else None
            height = info.height if info else None
        relpath = str(path.relative_to(extracted_dir))
        candidate = IconCandidate(
            source_path=path,
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
