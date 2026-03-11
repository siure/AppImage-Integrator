from __future__ import annotations

import subprocess
from pathlib import Path

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
