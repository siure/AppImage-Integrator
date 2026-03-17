from __future__ import annotations

from pathlib import Path

import pytest

gi = pytest.importorskip("gi")

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from appimage_integrator.models import ManagedAppRecord
from appimage_integrator.ui import dialogs as dialog_module
from appimage_integrator.ui.details_dialog import DetailsDialog


class StubRecordEditor:
    def build_effective_command(
        self,
        record: ManagedAppRecord,
        *,
        arg_preset_id: str,
        extra_args: list[str],
    ) -> str:
        tokens = [record.managed_appimage_path, arg_preset_id, *extra_args]
        return " ".join(token for token in tokens if token)


class FakeMessageDialog:
    instances: list["FakeMessageDialog"] = []

    def __init__(self, parent, title: str, body: str) -> None:
        self.parent = parent
        self.title = title
        self.body = body
        self.responses: list[tuple[str, str]] = []
        self.default_response: str | None = None
        self.close_response: str | None = None
        self.presented = False
        type(self).instances.append(self)

    def add_response(self, response_id: str, label: str) -> None:
        self.responses.append((response_id, label))

    def set_default_response(self, response_id: str) -> None:
        self.default_response = response_id

    def set_close_response(self, response_id: str) -> None:
        self.close_response = response_id

    def present(self) -> None:
        self.presented = True


def _walk_widgets(widget: Gtk.Widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk_widgets(child)
        child = child.get_next_sibling()


def _button_labels(widget: Gtk.Widget) -> set[str]:
    return {
        child.get_label()
        for child in _walk_widgets(widget)
        if isinstance(child, Gtk.Button) and child.get_label() is not None
    }


def _make_record(tmp_path: Path, *, desktop_exists: bool) -> ManagedAppRecord:
    managed_appimage = tmp_path / "Applications" / "demo.AppImage"
    managed_appimage.parent.mkdir(parents=True, exist_ok=True)
    managed_appimage.write_text("appimage", encoding="utf-8")

    desktop_path = tmp_path / ".local" / "share" / "applications" / "demo.desktop"
    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    if desktop_exists:
        desktop_path.write_text("[Desktop Entry]\nName=Demo\n", encoding="utf-8")

    return ManagedAppRecord.from_dict(
        {
            "internal_id": "demo",
            "display_name": "Demo",
            "comment": "Demo comment",
            "version": "1.0.0",
            "appstream_id": "org.demo.App",
            "embedded_desktop_basename": "demo.desktop",
            "identity_fingerprint": "abc",
            "managed_appimage_path": str(managed_appimage),
            "managed_desktop_path": str(desktop_path),
            "managed_icon_path": None,
            "source_file_name_at_install": "demo.AppImage",
            "source_path_last_seen": str(tmp_path / "Downloads" / "demo.AppImage"),
            "desktop_exec_template": str(managed_appimage),
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


def test_open_local_file_with_default_app_launches_existing_file(monkeypatch, tmp_path: Path) -> None:
    desktop_path = tmp_path / "demo.desktop"
    desktop_path.write_text("[Desktop Entry]\nName=Demo\n", encoding="utf-8")
    launched_uris: list[str] = []
    monkeypatch.setattr(dialog_module, "CompatMessageDialog", FakeMessageDialog)
    monkeypatch.setattr(
        dialog_module.Gio.AppInfo,
        "launch_default_for_uri",
        lambda uri, _context: launched_uris.append(uri),
    )

    assert (
        dialog_module.open_local_file_with_default_app(
            None,
            desktop_path,
            label_for_errors="Desktop file",
        )
        is True
    )
    assert launched_uris == [desktop_path.resolve().as_uri()]
    assert FakeMessageDialog.instances == []


def test_open_local_file_with_default_app_shows_error_for_missing_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.desktop"
    launch_calls: list[str] = []
    FakeMessageDialog.instances = []
    monkeypatch.setattr(dialog_module, "CompatMessageDialog", FakeMessageDialog)
    monkeypatch.setattr(
        dialog_module.Gio.AppInfo,
        "launch_default_for_uri",
        lambda uri, _context: launch_calls.append(uri),
    )

    assert (
        dialog_module.open_local_file_with_default_app(
            None,
            missing_path,
            label_for_errors="Desktop file",
        )
        is False
    )
    assert launch_calls == []
    assert FakeMessageDialog.instances
    assert "does not exist" in FakeMessageDialog.instances[-1].body


def test_open_local_file_with_default_app_shows_error_when_launch_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    desktop_path = tmp_path / "demo.desktop"
    desktop_path.write_text("[Desktop Entry]\nName=Demo\n", encoding="utf-8")
    FakeMessageDialog.instances = []
    monkeypatch.setattr(dialog_module, "CompatMessageDialog", FakeMessageDialog)

    def raise_error(_uri, _context) -> None:
        raise ValueError("No application is registered")

    monkeypatch.setattr(dialog_module.Gio.AppInfo, "launch_default_for_uri", raise_error)

    assert (
        dialog_module.open_local_file_with_default_app(
            None,
            desktop_path,
            label_for_errors="Desktop file",
        )
        is False
    )
    assert FakeMessageDialog.instances
    assert "system default application" in FakeMessageDialog.instances[-1].body
    assert "No application is registered" in FakeMessageDialog.instances[-1].body


def test_details_dialog_exposes_save_and_edit_desktop_actions(tmp_path: Path) -> None:
    Gtk.init()
    parent = Gtk.Window()
    dialog = DetailsDialog(parent, _make_record(tmp_path, desktop_exists=True), StubRecordEditor(), lambda _record: None)

    labels = _button_labels(dialog)
    assert "Save" in labels
    assert "Edit .desktop" in labels
    assert "Cancel" not in labels
    assert dialog._edit_desktop_button.get_sensitive() is True

    dialog.destroy()
    parent.destroy()


def test_details_dialog_disables_edit_button_when_desktop_file_is_missing(tmp_path: Path) -> None:
    Gtk.init()
    parent = Gtk.Window()
    dialog = DetailsDialog(parent, _make_record(tmp_path, desktop_exists=False), StubRecordEditor(), lambda _record: None)

    assert dialog._edit_desktop_button.get_sensitive() is False

    dialog.destroy()
    parent.destroy()


def test_edit_desktop_action_does_not_mark_clean_dialog_dirty(monkeypatch, tmp_path: Path) -> None:
    Gtk.init()
    parent = Gtk.Window()
    dialog = DetailsDialog(parent, _make_record(tmp_path, desktop_exists=True), StubRecordEditor(), lambda _record: None)
    opened_paths: list[str | None] = []
    monkeypatch.setattr(
        "appimage_integrator.ui.details_dialog.open_local_file_with_default_app",
        lambda _parent, path, *, label_for_errors: opened_paths.append(path) or True,
    )

    assert dialog._save_button.get_sensitive() is False

    dialog._open_desktop_file(dialog._edit_desktop_button)

    assert opened_paths == [dialog._record.managed_desktop_path]
    assert dialog._save_button.get_sensitive() is False
    assert dialog._name_entry.get_text() == "Demo"

    dialog.destroy()
    parent.destroy()


def test_edit_desktop_action_preserves_unsaved_fields(monkeypatch, tmp_path: Path) -> None:
    Gtk.init()
    parent = Gtk.Window()
    dialog = DetailsDialog(parent, _make_record(tmp_path, desktop_exists=True), StubRecordEditor(), lambda _record: None)
    monkeypatch.setattr(
        "appimage_integrator.ui.details_dialog.open_local_file_with_default_app",
        lambda _parent, _path, *, label_for_errors: True,
    )

    dialog._name_entry.set_text("Changed Demo")
    dialog._on_fields_changed()
    assert dialog._save_button.get_sensitive() is True

    dialog._open_desktop_file(dialog._edit_desktop_button)

    assert dialog._name_entry.get_text() == "Changed Demo"
    assert dialog._save_button.get_sensitive() is True

    dialog.destroy()
    parent.destroy()
