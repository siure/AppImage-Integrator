from __future__ import annotations

import logging
from pathlib import Path

import pytest

from appimage_integrator.paths import AppPaths
from appimage_integrator.services.tooling import ToolAvailability, Tooling


@pytest.fixture
def test_paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        home=tmp_path,
        applications_dir=tmp_path / "Applications",
        managed_payloads_root=tmp_path / "Applications" / ".appimage-integrator",
        desktop_entries_dir=tmp_path / ".local" / "share" / "applications",
        icons_dir=tmp_path / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps",
        app_data_dir=tmp_path / ".local" / "share" / "appimage-integrator",
        metadata_apps_dir=tmp_path / ".local" / "share" / "appimage-integrator" / "apps",
        metadata_index_path=tmp_path / ".local" / "share" / "appimage-integrator" / "index.json",
        logs_dir=tmp_path / ".local" / "share" / "appimage-integrator" / "logs",
        log_file=tmp_path / ".local" / "share" / "appimage-integrator" / "logs" / "app.log",
        cache_extract_dir=tmp_path / ".cache" / "appimage-integrator" / "extract",
    )


@pytest.fixture
def tooling() -> Tooling:
    logger = logging.getLogger("tests")
    tool = Tooling(logger)
    tool.tools = ToolAvailability(
        desktop_file_validate=None,
        appstreamcli=None,
        update_desktop_database=None,
        gtk_update_icon_cache=None,
        unsquashfs=None,
        file_cmd=None,
        sha256sum=None,
    )
    return tool


@pytest.fixture
def launcher_command(test_paths: AppPaths) -> list[str]:
    return [str(test_paths.self_command_path)]
