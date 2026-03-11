from __future__ import annotations

import subprocess
from pathlib import Path

from appimage_integrator.models import AppImageInspection
from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.icon_resolver import IconResolver


class FakeTooling:
    def __init__(self, result: subprocess.CompletedProcess[str]) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    def run(self, args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return self.result


def test_detect_type_treats_successful_version_probe_as_type2(test_paths) -> None:
    tooling = FakeTooling(
        subprocess.CompletedProcess(
            args=["demo.AppImage", "--appimage-version"],
            returncode=0,
            stdout="",
            stderr="Version: effcebc\n",
        )
    )
    inspector = AppImageInspector(test_paths, tooling, IconResolver(test_paths))

    appimage_type = inspector._detect_type(Path("/tmp/demo.AppImage"))

    assert appimage_type == "type2"
    assert tooling.calls == [["/tmp/demo.AppImage", "--appimage-version"]]


def test_find_appstream_id_prefers_component_matching_desktop_metadata(test_paths) -> None:
    tooling = FakeTooling(subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""))
    inspector = AppImageInspector(test_paths, tooling, IconResolver(test_paths))
    extracted_dir = test_paths.cache_extract_dir / "extract-appstream"
    extracted_dir.mkdir(parents=True)

    (extracted_dir / "writer.appdata.xml").write_text(
        "<?xml version='1.0'?>\n"
        "<component type='desktop'>\n"
        "  <id>libreoffice-writer.desktop</id>\n"
        "  <name>LibreOffice Writer</name>\n"
        "</component>\n",
        encoding="utf-8",
    )
    (extracted_dir / "base.appdata.xml").write_text(
        "<?xml version='1.0'?>\n"
        "<component type='desktop'>\n"
        "  <id>libreoffice-base.desktop</id>\n"
        "  <name>LibreOffice Base</name>\n"
        "</component>\n",
        encoding="utf-8",
    )

    appstream_id = inspector._find_appstream_id(
        extracted_dir,
        desktop_filename="base.desktop",
        detected_name="LibreOffice 26.2 Base",
    )

    assert appstream_id == "libreoffice-base.desktop"
