from __future__ import annotations

from pathlib import Path

import pytest

gi = pytest.importorskip("gi")

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from appimage_integrator.models import AppImageInspection, InstallResult, ManagedAppRecord
from appimage_integrator.ui import install_view as install_view_module
from appimage_integrator.ui.install_view import InstallView


class DummyInstallManager:
    def inspect(self, _path: Path):
        raise AssertionError("inspect should not run in this test")

    def install(self, _request):
        raise AssertionError("install should not run in this test")

    def ensure_source_executable(self, _path: Path) -> None:
        return None


class CleanupTrackingInspector:
    def __init__(self) -> None:
        self.cleaned: list[AppImageInspection] = []

    def cleanup(self, inspection: AppImageInspection) -> None:
        self.cleaned.append(inspection)


class CleanupTrackingInstallManager(DummyInstallManager):
    def __init__(self) -> None:
        self.inspector = CleanupTrackingInspector()


class FakeMessageDialog:
    instances: list["FakeMessageDialog"] = []

    def __init__(self, parent, title: str, body: str) -> None:
        self.parent = parent
        self.title = title
        self.body = body
        self.presented = False
        type(self).instances.append(self)

    def add_response(self, _response_id: str, _label: str) -> None:
        return None

    def set_default_response(self, _response_id: str) -> None:
        return None

    def set_close_response(self, _response_id: str) -> None:
        return None

    def set_response_appearance(self, _response_id: str, _appearance) -> None:
        return None

    def connect(self, *_args) -> None:
        return None

    def present(self) -> None:
        self.presented = True


class FakeThread:
    def __init__(self, target, args=(), kwargs=None, daemon=False) -> None:
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True


def _make_record(tmp_path: Path) -> ManagedAppRecord:
    return ManagedAppRecord.from_dict(
        {
            "internal_id": "demo",
            "display_name": "Demo",
            "comment": "Demo comment",
            "version": "1.0.0",
            "appstream_id": "org.demo.App",
            "embedded_desktop_basename": "demo.desktop",
            "identity_fingerprint": "abc",
            "managed_appimage_path": str(tmp_path / "Applications" / "demo.AppImage"),
            "managed_desktop_path": str(tmp_path / ".local" / "share" / "applications" / "demo.desktop"),
            "managed_icon_path": None,
            "source_file_name_at_install": "demo.AppImage",
            "source_path_last_seen": str(tmp_path / "Downloads" / "demo.AppImage"),
            "desktop_exec_template": str(tmp_path / "Applications" / "demo.AppImage"),
            "extra_args": ["--demo"],
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


def _make_inspection(source_path: Path) -> AppImageInspection:
    return AppImageInspection(
        source_path=source_path,
        is_appimage=True,
        appimage_type="type2",
        is_executable=True,
        detected_name="Demo Browser",
        detected_comment="A demo app",
        detected_version="2.0.0",
        appstream_id="org.demo.App",
        embedded_desktop_filename="demo.desktop",
        desktop_entry=None,
        chosen_icon_candidate=None,
        startup_wm_class=None,
        mime_types=[],
        categories=[],
        terminal=False,
        startup_notify=True,
        exec_placeholders=[],
        warnings=[],
        errors=[],
        extracted_dir=None,
    )


def test_install_view_starts_with_compact_bar_and_hidden_editor() -> None:
    Gtk.init()
    view = InstallView(DummyInstallManager(), lambda: None, lambda _message: None)

    assert view.compact_bar.get_visible() is True
    assert view.editor_revealer.get_reveal_child() is False
    assert view.source_label.get_text() == "No file selected"
    assert view.install_button.get_label() == "Install"


def test_load_path_enters_busy_state_and_apply_inspection_reveals_editor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    Gtk.init()
    appimage_path = tmp_path / "demo.AppImage"
    appimage_path.write_text("demo", encoding="utf-8")
    appimage_path.chmod(0o755)

    monkeypatch.setattr(install_view_module.threading, "Thread", FakeThread)

    view = InstallView(DummyInstallManager(), lambda: None, lambda _message: None)
    view.load_path(appimage_path)

    assert view.editor_revealer.get_reveal_child() is True
    assert view.busy_box.get_visible() is True
    assert view.busy_label.get_text() == "Inspecting AppImage…"
    assert view.install_button.get_sensitive() is False
    assert view.source_label.get_text() == "demo.AppImage"

    record = _make_record(tmp_path)
    result = view._apply_inspection(_make_inspection(appimage_path), record, "update")

    assert result is False
    assert view.editor_revealer.get_reveal_child() is True
    assert view.busy_box.get_visible() is False
    assert view.name_entry.get_text() == "Demo Browser"
    assert view.comment_entry.get_text() == "A demo app"
    assert view.install_button.get_label() == "Update"
    assert view.install_button.get_sensitive() is True


def test_reset_cleans_current_inspection(tmp_path: Path) -> None:
    Gtk.init()
    manager = CleanupTrackingInstallManager()
    view = InstallView(manager, lambda: None, lambda _message: None)
    inspection = _make_inspection(tmp_path / "demo.AppImage")

    view._apply_inspection(inspection, _make_record(tmp_path), "install")
    view.reset()

    assert manager.inspector.cleaned == [inspection]
    assert view.current_inspection is None


def test_apply_install_result_hides_editor_and_resets_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    Gtk.init()
    FakeMessageDialog.instances = []
    monkeypatch.setattr(install_view_module, "CompatMessageDialog", FakeMessageDialog)

    installed_calls: list[bool] = []
    view = InstallView(DummyInstallManager(), lambda: installed_calls.append(True), lambda _message: None)
    view.current_source_path = tmp_path / "demo.AppImage"
    view._show_editor(True)
    view._set_source_label()

    result = InstallResult(
        mode="install",
        record=_make_record(tmp_path),
        warnings=[],
        validation_messages=[],
    )

    returned = view._apply_install_result(result)

    assert returned is False
    assert installed_calls == [True]
    assert view.editor_revealer.get_reveal_child() is False
    assert view.source_label.get_text() == "No file selected"
    assert FakeMessageDialog.instances
    assert FakeMessageDialog.instances[-1].title == "Install completed"


def test_load_path_uses_shared_trust_prompt_for_non_executable_sources(
    monkeypatch,
    tmp_path: Path,
) -> None:
    Gtk.init()
    appimage_path = tmp_path / "demo.AppImage"
    appimage_path.write_text("demo", encoding="utf-8")
    appimage_path.chmod(0o644)

    trust_calls: list[Path] = []
    monkeypatch.setattr(
        install_view_module,
        "prompt_for_appimage_trust",
        lambda _parent, path, _ensure, **_kwargs: trust_calls.append(path),
    )

    view = InstallView(DummyInstallManager(), lambda: None, lambda _message: None)
    view.load_path(appimage_path)

    assert trust_calls == [appimage_path]


def test_install_record_from_source_uses_shared_trust_prompt_for_non_executable_updates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    Gtk.init()
    appimage_path = tmp_path / "demo.AppImage"
    appimage_path.write_text("demo", encoding="utf-8")
    appimage_path.chmod(0o644)

    trust_calls: list[Path] = []
    monkeypatch.setattr(
        install_view_module,
        "prompt_for_appimage_trust",
        lambda _parent, path, _ensure, **_kwargs: trust_calls.append(path),
    )

    view = InstallView(DummyInstallManager(), lambda: None, lambda _message: None)
    view.install_record_from_source(
        _make_record(tmp_path),
        appimage_path,
        button_label="Update",
        require_trust_prompt=True,
    )

    assert trust_calls == [appimage_path]
