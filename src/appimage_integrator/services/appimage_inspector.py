from __future__ import annotations

import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from appimage_integrator.models import AppImageInspection
from appimage_integrator.paths import AppPaths
from appimage_integrator.services.desktop_entry import parse_desktop_entry
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.tooling import Tooling


class AppImageInspector:
    def __init__(self, paths: AppPaths, tooling: Tooling, icon_resolver: IconResolver) -> None:
        self.paths = paths
        self.tooling = tooling
        self.icon_resolver = icon_resolver

    def inspect(self, source_path: Path) -> AppImageInspection:
        warnings: list[str] = []
        errors: list[str] = []
        source_path = source_path.expanduser().resolve()
        is_executable = os.access(source_path, os.X_OK)
        if not source_path.exists():
            return AppImageInspection(
                source_path=source_path,
                is_appimage=False,
                appimage_type="unknown",
                is_executable=False,
                detected_name=None,
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
                warnings=[],
                errors=["The selected file does not exist."],
            )

        file_description = self._file_description(source_path)
        appimage_type = self._detect_type(source_path, is_executable)
        is_appimage = "appimage" in file_description.lower() or appimage_type != "unknown"
        if not is_appimage:
            warnings.append("The file does not strongly identify itself as an AppImage.")
        extracted_dir, extraction_failed = self._extract(
            source_path,
            appimage_type,
            is_executable,
            warnings,
        )

        desktop_entry = None
        desktop_filename = None
        appstream_id = None
        name = source_path.stem
        comment = None
        version = None
        startup_wm_class = None
        mime_types: list[str] = []
        categories: list[str] = []
        terminal = None
        startup_notify = None
        exec_placeholders: list[str] = []

        if extracted_dir:
            desktop_path = self._find_desktop_file(extracted_dir)
            if desktop_path:
                desktop_filename = desktop_path.name
                desktop_entry = parse_desktop_entry(
                    desktop_path.read_text(encoding="utf-8", errors="replace"),
                    str(desktop_path.relative_to(extracted_dir)),
                )
                name = desktop_entry.parsed_fields.get("Name", name)
                comment = desktop_entry.parsed_fields.get("Comment")
                version = desktop_entry.parsed_fields.get("X-AppImage-Version")
                startup_wm_class = desktop_entry.parsed_fields.get("StartupWMClass")
                mime_types = self._split_semi_colon_field(desktop_entry.parsed_fields.get("MimeType"))
                categories = self._split_semi_colon_field(desktop_entry.parsed_fields.get("Categories"))
                terminal = self._bool_field(desktop_entry.parsed_fields.get("Terminal"))
                startup_notify = self._bool_field(desktop_entry.parsed_fields.get("StartupNotify"))
                exec_placeholders = [
                    token for token in desktop_entry.exec_tokens if token.startswith("%")
                ]
                warnings.extend(desktop_entry.validation_messages)
            else:
                warnings.append("No embedded desktop file was found. A fallback launcher will be generated.")

            appstream_id = self._find_appstream_id(extracted_dir, desktop_filename, name)

        if extraction_failed:
            errors.append("Could not extract AppImage contents.")
        if not is_executable:
            warnings.append("The source AppImage is not executable. The managed copy will be fixed during install.")

        inspection = AppImageInspection(
            source_path=source_path,
            is_appimage=is_appimage,
            appimage_type=appimage_type,
            is_executable=is_executable,
            detected_name=name,
            detected_comment=comment,
            detected_version=version,
            appstream_id=appstream_id,
            embedded_desktop_filename=desktop_filename,
            desktop_entry=desktop_entry,
            chosen_icon_candidate=None,
            startup_wm_class=startup_wm_class,
            mime_types=mime_types,
            categories=categories,
            terminal=terminal,
            startup_notify=startup_notify,
            exec_placeholders=exec_placeholders,
            warnings=warnings,
            errors=errors,
            extracted_dir=extracted_dir,
        )
        chosen_icon = self.icon_resolver.choose_for_inspection(inspection)
        return AppImageInspection(
            **{
                **inspection.__dict__,
                "chosen_icon_candidate": chosen_icon,
            }
        )

    def cleanup(self, inspection: AppImageInspection) -> None:
        if inspection.extracted_dir and inspection.extracted_dir.exists():
            shutil.rmtree(inspection.extracted_dir, ignore_errors=True)

    def _file_description(self, source_path: Path) -> str:
        if not self.tooling.tools.file_cmd:
            return ""
        result = self.tooling.run([self.tooling.tools.file_cmd, "-b", str(source_path)])
        return result.stdout.strip()

    def _detect_type(self, source_path: Path, is_executable: bool) -> str:
        if not is_executable:
            return "unknown"
        result = self.tooling.run([str(source_path), "--appimage-version"])
        output = f"{result.stdout} {result.stderr}".lower()
        if "type 1" in output:
            return "type1"
        if result.returncode == 0 and output.strip():
            return "type2"
        if "type 2" in output or "appimage version" in output:
            return "type2"
        return "unknown"

    def _extract(
        self,
        source_path: Path,
        appimage_type: str,
        is_executable: bool,
        warnings: list[str],
    ) -> tuple[Path | None, bool]:
        extract_dir = Path(
            tempfile.mkdtemp(prefix="extract-", dir=self.paths.cache_extract_dir)
        )
        if is_executable and (appimage_type == "type2" or appimage_type == "unknown"):
            result = self.tooling.run(
                [str(source_path), "--appimage-extract"],
                cwd=extract_dir,
            )
            squashed = extract_dir / "squashfs-root"
            if result.returncode == 0 and squashed.exists():
                return squashed, False
        if self.tooling.tools.unsquashfs:
            result = self.tooling.run(
                [self.tooling.tools.unsquashfs, "-f", "-d", str(extract_dir / "squashfs-root"), str(source_path)]
            )
            squashed = extract_dir / "squashfs-root"
            if result.returncode == 0 and squashed.exists():
                return squashed, False
        elif not is_executable:
            warnings.append(
                "Extraction was skipped because the AppImage is not executable and unsquashfs is unavailable."
            )
            shutil.rmtree(extract_dir, ignore_errors=True)
            return None, False
        if appimage_type == "type1":
            warnings.append("Type 1 AppImage support is best-effort and metadata may be incomplete.")
        warnings.append("Extraction failed; install may continue with a fallback launcher.")
        shutil.rmtree(extract_dir, ignore_errors=True)
        return None, True

    def _find_desktop_file(self, extracted_dir: Path) -> Path | None:
        desktop_files = sorted(extracted_dir.rglob("*.desktop"))
        return desktop_files[0] if desktop_files else None

    def _find_appstream_id(
        self,
        extracted_dir: Path,
        desktop_filename: str | None,
        detected_name: str | None,
    ) -> str | None:
        candidates: list[tuple[int, str]] = []
        xml_files = list(extracted_dir.rglob("*.appdata.xml")) + list(extracted_dir.rglob("*.metainfo.xml"))
        desktop_stem = desktop_filename.rsplit(".", 1)[0].casefold() if desktop_filename else ""
        normalized_name = self._normalize_token_string(detected_name)

        for path in xml_files:
            try:
                root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
            except ET.ParseError:
                continue
            component_id = self._first_child_text(root, "id")
            if not component_id:
                continue

            score = 0
            component_type = root.attrib.get("type", "").casefold()
            if component_type == "desktop":
                score += 10

            launchables = self._child_texts(root, "launchable")
            if desktop_filename and desktop_filename in launchables:
                score += 100
            if desktop_filename and component_id == desktop_filename:
                score += 95

            component_stem = component_id.rsplit(".", 1)[0].casefold()
            path_stem = self._normalize_token_string(path.name)
            if desktop_stem and desktop_stem == component_stem:
                score += 90
            if desktop_stem and desktop_stem and desktop_stem in path_stem.split():
                score += 70

            component_name = self._normalize_token_string(self._first_child_text(root, "name"))
            if normalized_name and component_name:
                if component_name == normalized_name:
                    score += 85
                elif self._token_sets_overlap(component_name, normalized_name):
                    score += 60

            if score > 0:
                candidates.append((score, component_id.strip()))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][1]

    def _bool_field(self, value: str | None) -> bool | None:
        if value is None:
            return None
        lowered = value.lower()
        if lowered in {"true", "1"}:
            return True
        if lowered in {"false", "0"}:
            return False
        return None

    def _split_semi_colon_field(self, value: str | None) -> list[str]:
        if not value:
            return []
        return [item for item in value.split(";") if item]

    def _first_child_text(self, root: ET.Element, local_name: str) -> str | None:
        for child in root:
            if child.tag.rsplit("}", 1)[-1] != local_name:
                continue
            text = child.text.strip() if child.text else ""
            if text:
                return text
        return None

    def _child_texts(self, root: ET.Element, local_name: str) -> list[str]:
        values: list[str] = []
        for child in root:
            if child.tag.rsplit("}", 1)[-1] != local_name:
                continue
            text = child.text.strip() if child.text else ""
            if text:
                values.append(text)
        return values

    def _normalize_token_string(self, value: str | None) -> str:
        if not value:
            return ""
        collapsed = "".join(char.lower() if char.isalnum() else " " for char in value)
        return " ".join(part for part in collapsed.split() if part)

    def _token_sets_overlap(self, left: str, right: str) -> bool:
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        return bool(
            left_tokens
            and right_tokens
            and (left_tokens <= right_tokens or right_tokens <= left_tokens)
        )
