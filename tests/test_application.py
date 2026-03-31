from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from appimage_integrator.application import AppImageIntegratorApplication
from appimage_integrator.config import APP_ID
from appimage_integrator.launcher import build_app_desktop_text
from appimage_integrator.self_integration import SELF_INTERNAL_ID, build_self_record


class FakeInspector:
    def __init__(self) -> None:
        self.inspect_calls = 0
        self.cleanup_calls = 0

    def inspect(self, _path: Path):
        self.inspect_calls += 1
        raise AssertionError("inspect should not run")

    def cleanup(self, _inspection) -> None:
        self.cleanup_calls += 1


def test_write_app_desktop_entry_skips_unchanged_content(test_paths) -> None:
    fake_app = SimpleNamespace(paths=test_paths)
    launcher_command = [str(test_paths.self_command_path)]
    desktop_text = build_app_desktop_text(launcher_command)
    target = test_paths.self_desktop_entry_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(desktop_text, encoding="utf-8")

    changed = AppImageIntegratorApplication._write_app_desktop_entry(fake_app, launcher_command)

    assert changed is False
    assert target.read_text(encoding="utf-8") == desktop_text


def test_ensure_icon_integration_skips_identical_copy(test_paths, monkeypatch, tmp_path: Path) -> None:
    source_icon = tmp_path / f"{APP_ID}.png"
    source_icon.write_bytes(b"png-data")
    target = test_paths.self_icon_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"png-data")
    fake_app = SimpleNamespace(paths=test_paths)

    monkeypatch.setattr("appimage_integrator.application.APP_ICON_PATH", source_icon)

    changed = AppImageIntegratorApplication._ensure_icon_integration(fake_app)

    assert changed is False
    assert target.read_bytes() == b"png-data"


def test_sync_self_library_record_reuses_existing_record_without_inspection(test_paths) -> None:
    test_paths.self_appimage_path.parent.mkdir(parents=True, exist_ok=True)
    test_paths.self_appimage_path.write_text("appimage", encoding="utf-8")
    existing = build_self_record(
        test_paths,
        source_path_last_seen=test_paths.self_appimage_path,
        launcher_command=[str(test_paths.self_command_path)],
    )
    saved_records: list[object] = []
    inspector = FakeInspector()
    fake_app = SimpleNamespace(
        paths=test_paths,
        services=SimpleNamespace(
            store=SimpleNamespace(
                load=lambda internal_id: existing if internal_id == SELF_INTERNAL_ID else None,
                save=lambda record: saved_records.append(record),
            ),
            install_manager=SimpleNamespace(inspector=inspector),
            logger=logging.getLogger("tests.application"),
        ),
    )

    changed = AppImageIntegratorApplication._sync_self_library_record(
        fake_app,
        source_path_last_seen=test_paths.self_appimage_path,
        launcher_command=[str(test_paths.self_command_path)],
        force_inspect=False,
    )

    assert changed is False
    assert inspector.inspect_calls == 0
    assert inspector.cleanup_calls == 0
    assert saved_records == []
