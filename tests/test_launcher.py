from __future__ import annotations

from pathlib import Path

from appimage_integrator.launcher import build_managed_app_launch_command
from appimage_integrator.launcher import (
    build_app_desktop_text,
    install_self_appimage,
    install_self_command,
    launch_tokens_from_exec_template,
    resolve_launcher_command,
)
from appimage_integrator.models import ManagedAppRecord


def test_resolve_launcher_command_prefers_wrapper(test_paths, monkeypatch) -> None:
    wrapper = test_paths.self_command_path
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(
        "appimage_integrator.launcher.resolve_current_launcher_executable",
        lambda: Path("/tmp/other-launcher"),
    )

    assert resolve_launcher_command(test_paths) == [str(wrapper)]


def test_resolve_launcher_command_falls_back_to_self_appimage(test_paths, monkeypatch) -> None:
    test_paths.self_appimage_path.parent.mkdir(parents=True, exist_ok=True)
    test_paths.self_appimage_path.write_text("appimage", encoding="utf-8")

    monkeypatch.setattr(
        "appimage_integrator.launcher.resolve_current_launcher_executable",
        lambda: Path("/tmp/other-launcher"),
    )

    assert resolve_launcher_command(test_paths) == [str(test_paths.self_appimage_path)]


def test_resolve_launcher_command_falls_back_to_current_executable(test_paths, monkeypatch) -> None:
    monkeypatch.setattr(
        "appimage_integrator.launcher.resolve_current_launcher_executable",
        lambda: Path("/tmp/current-launcher"),
    )

    assert resolve_launcher_command(test_paths) == ["/tmp/current-launcher"]


def test_resolve_launcher_command_returns_none_without_concrete_launcher(test_paths, monkeypatch) -> None:
    monkeypatch.setattr(
        "appimage_integrator.launcher.resolve_current_launcher_executable",
        lambda: None,
    )

    assert resolve_launcher_command(test_paths) is None


def test_build_app_desktop_text_rewrites_exec_and_tryexec() -> None:
    text = build_app_desktop_text(["/home/test/Applications/appimage-integrator.AppImage"])

    assert "Exec=/home/test/Applications/appimage-integrator.AppImage" in text
    assert "TryExec=/home/test/Applications/appimage-integrator.AppImage" in text
    assert "%U" not in text


def test_self_install_writes_stable_appimage_and_wrapper(test_paths) -> None:
    source = test_paths.home / "Downloads" / "AppImage-Integrator.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    source.chmod(0o755)

    stable = install_self_appimage(test_paths, source)
    install_self_command(test_paths, stable)

    assert stable == test_paths.self_appimage_path
    assert stable.exists()
    assert stable.stat().st_mode & 0o100
    assert test_paths.self_command_path.exists()
    assert test_paths.self_command_path.stat().st_mode & 0o100
    wrapper_text = test_paths.self_command_path.read_text(encoding="utf-8")
    assert f'exec "{stable}" "$@"' in wrapper_text


def test_launch_tokens_from_exec_template_drops_desktop_placeholders() -> None:
    tokens = launch_tokens_from_exec_template(
        "appimage-integrator launch demo --desktop -- --existing --flag %U %F"
    )

    assert tokens == ["--existing", "--flag"]


def test_build_managed_app_launch_command_reuses_saved_launch_args() -> None:
    record = ManagedAppRecord.from_dict(
        {
            "internal_id": "demo-1234",
            "display_name": "Demo",
            "comment": None,
            "version": "1.0.0",
            "appstream_id": None,
            "embedded_desktop_basename": None,
            "identity_fingerprint": "abc",
            "managed_appimage_path": "/apps/demo.AppImage",
            "managed_desktop_path": "/apps/demo.desktop",
            "managed_icon_path": None,
            "source_file_name_at_install": "demo.AppImage",
            "source_path_last_seen": "/tmp/demo.AppImage",
            "desktop_exec_template": "appimage-integrator launch demo-1234 --desktop -- --existing --flag %U",
            "extra_args": [],
            "arg_preset_id": "none",
            "installed_at": "2026-03-15T00:00:00+00:00",
            "updated_at": "2026-03-15T00:00:00+00:00",
            "appimage_type": "type2",
            "icon_managed_by_app": False,
            "managed_files": [],
            "last_validation_status": "ok",
            "last_validation_messages": [],
            "managed_payload_path": None,
            "managed_payload_dir": None,
        }
    )

    assert build_managed_app_launch_command(record, ["--sample"]) == [
        "/apps/demo.AppImage",
        "--existing",
        "--flag",
        "--sample",
    ]
