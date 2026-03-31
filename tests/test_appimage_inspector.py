from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from appimage_integrator.services.appimage_inspector import AppImageInspector
from appimage_integrator.services.icon_resolver import IconResolver


class FakeTooling:
    def __init__(
        self,
        results: list[subprocess.CompletedProcess[str]] | None = None,
        *,
        unsquashfs: str | None = None,
        file_cmd: str | None = None,
    ) -> None:
        self.results = list(results or [])
        self.calls: list[list[str]] = []
        self.tools = SimpleNamespace(
            unsquashfs=unsquashfs,
            file_cmd=file_cmd,
        )

    def run(self, args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args and self.tools.unsquashfs and args[0] == self.tools.unsquashfs:
            destination = Path(args[3])
            destination.mkdir(parents=True, exist_ok=True)
        if self.results:
            return self.results.pop(0)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def test_detect_type_treats_successful_version_probe_as_type2(test_paths) -> None:
    tooling = FakeTooling(
        [
            subprocess.CompletedProcess(
                args=["demo.AppImage", "--appimage-version"],
                returncode=0,
                stdout="",
                stderr="Version: effcebc\n",
            )
        ]
    )
    inspector = AppImageInspector(test_paths, tooling, IconResolver(test_paths))

    appimage_type = inspector._detect_type(Path("/tmp/demo.AppImage"), True)

    assert appimage_type == "type2"
    assert tooling.calls == [["/tmp/demo.AppImage", "--appimage-version"]]


def test_detect_type_skips_version_probe_for_non_executable_sources(test_paths) -> None:
    tooling = FakeTooling()
    inspector = AppImageInspector(test_paths, tooling, IconResolver(test_paths))

    appimage_type = inspector._detect_type(Path("/tmp/demo.AppImage"), False)

    assert appimage_type == "unknown"
    assert tooling.calls == []


def test_extract_uses_unsquashfs_for_non_executable_sources(test_paths) -> None:
    source = test_paths.home / "Downloads" / "demo.AppImage"
    source.parent.mkdir(parents=True, exist_ok=True)
    test_paths.cache_extract_dir.mkdir(parents=True, exist_ok=True)
    source.write_text("appimage", encoding="utf-8")
    source.chmod(0o644)
    tooling = FakeTooling(
        [
            subprocess.CompletedProcess(
                args=["unsquashfs", "-f", "-d", "/tmp/out", str(source)],
                returncode=0,
                stdout="",
                stderr="",
            )
        ],
        unsquashfs="unsquashfs",
    )
    inspector = AppImageInspector(test_paths, tooling, IconResolver(test_paths))
    warnings: list[str] = []

    extracted_dir, extraction_failed = inspector._extract(source, "unknown", False, warnings)

    assert extraction_failed is False
    assert extracted_dir is not None
    assert extracted_dir.name == "squashfs-root"
    assert tooling.calls == [
        ["unsquashfs", "-f", "-d", str(extracted_dir), str(source)],
    ]
    inspector.cleanup(
        SimpleNamespace(extracted_dir=extracted_dir)
    )


def test_find_appstream_id_prefers_component_matching_desktop_metadata(test_paths) -> None:
    tooling = FakeTooling([subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")])
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
