from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

gi = pytest.importorskip("gi")

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from appimage_integrator.models import ManagedAppRecord, UpdateCandidate, UpdateDiscoveryResult
from appimage_integrator.ui import application_window as application_window_module
from appimage_integrator.ui.application_window import ApplicationWindow
from appimage_integrator.ui.update_source_dialog import UpdateSourceDialog


def _walk_widgets(widget: Gtk.Widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk_widgets(child)
        child = child.get_next_sibling()


class DummyLibraryManager:
    def list_records(self):
        return []

    def validate_record(self, record, allow_reconcile_inspection=False):
        return record, record.last_validation_status, record.last_validation_messages


class DummyStore:
    def load(self, _internal_id):
        return None

    def save(self, _record) -> None:
        return None


def _make_services():
    return SimpleNamespace(
        install_manager=SimpleNamespace(ensure_source_executable=lambda _path: None),
        library_manager=DummyLibraryManager(),
        record_editor=SimpleNamespace(),
        repair_manager=SimpleNamespace(),
        update_discovery=SimpleNamespace(evaluate_candidate=lambda _record, _path: None),
        store=DummyStore(),
    )


def _make_record(tmp_path: Path) -> ManagedAppRecord:
    return ManagedAppRecord.from_dict(
        {
            "internal_id": "demo-browser",
            "display_name": "Demo Browser",
            "comment": "Demo comment",
            "version": "1.0.0",
            "appstream_id": "org.demo.Browser",
            "embedded_desktop_basename": "demo.desktop",
            "identity_fingerprint": "abc123",
            "managed_appimage_path": str(tmp_path / "Applications" / "demo-browser.AppImage"),
            "managed_desktop_path": str(tmp_path / ".local" / "share" / "applications" / "demo-browser.desktop"),
            "managed_icon_path": None,
            "source_file_name_at_install": "demo-browser-v1.AppImage",
            "source_path_last_seen": str(tmp_path / "Downloads" / "demo-browser-v1.AppImage"),
            "desktop_exec_template": str(tmp_path / "Applications" / "demo-browser.AppImage"),
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


def _make_candidate(
    path: Path,
    *,
    version: str | None,
    is_executable: bool,
    match_kind: str = "identity",
) -> UpdateCandidate:
    return UpdateCandidate(
        path=path,
        detected_version=version,
        is_executable=is_executable,
        match_kind=match_kind,
        match_score=100,
        identity_internal_id="demo-browser",
        identity_fingerprint="abc123",
        detected_name="Demo Browser",
        source_dir_kind="downloads",
        warnings=[],
    )


def test_application_window_uses_single_page_layout() -> None:
    Gtk.init()
    app = Adw.Application(application_id="io.github.appimageintegrator.tests")
    window = ApplicationWindow(app, _make_services())

    widgets = list(_walk_widgets(window))
    assert not any(isinstance(widget, Adw.ViewSwitcher) for widget in widgets)
    assert not any(isinstance(widget, Adw.ViewStack) for widget in widgets)

    first_child = window.content_root.get_first_child()
    assert first_child is window.install_view
    assert first_child.get_next_sibling() is window.library_view

    window.destroy()


def test_application_window_delegates_root_drop_to_install_view(monkeypatch, tmp_path: Path) -> None:
    Gtk.init()
    app = Adw.Application(application_id="io.github.appimageintegrator.tests.drop")
    window = ApplicationWindow(app, _make_services())

    dropped_paths: list[Path] = []
    monkeypatch.setattr(window.install_view, "load_path", lambda path: dropped_paths.append(path))

    candidate = tmp_path / "demo.AppImage"
    window._handle_dropped_path(candidate)

    assert dropped_paths == [candidate]

    window.destroy()


def test_update_source_dialog_lists_candidates_and_defaults_to_first_higher(tmp_path: Path) -> None:
    Gtk.init()
    parent = Gtk.Window()
    candidate_one = _make_candidate(tmp_path / "demo-v2.AppImage", version="2.0.0", is_executable=True)
    candidate_two = _make_candidate(tmp_path / "demo-v1-build2.AppImage", version=None, is_executable=False)
    dialog = UpdateSourceDialog(parent, _make_record(tmp_path), [candidate_one, candidate_two])

    rows: list[Gtk.ListBoxRow] = []
    row = dialog.list_box.get_first_child()
    while row is not None:
        rows.append(row)
        row = row.get_next_sibling()

    assert len(rows) == 2
    assert dialog._window.get_resizable() is True
    assert dialog.get_selected_candidate() == candidate_one
    assert dialog.use_button.get_sensitive() is True
    assert rows[0].has_css_class("selected") is True
    assert rows[1].has_css_class("selected") is False

    dialog._window.close()
    parent.close()


def test_application_window_uses_update_source_dialog_for_all_matches(monkeypatch, tmp_path: Path) -> None:
    Gtk.init()
    app = Adw.Application(application_id="io.github.appimageintegrator.tests.update-dialog")
    window = ApplicationWindow(app, _make_services())
    record = _make_record(tmp_path)
    higher = _make_candidate(tmp_path / "demo-v2.AppImage", version="2.0.0", is_executable=True)
    same = _make_candidate(
        tmp_path / "demo-v1-build2.AppImage",
        version=None,
        is_executable=False,
        match_kind="filename",
    )
    discovery = UpdateDiscoveryResult(
        record=record,
        searched_directories=[tmp_path],
        higher_version_candidates=[higher],
        same_or_unknown_candidates=[same],
        skipped_paths=[],
    )
    presented: list[list[UpdateCandidate]] = []

    class FakeUpdateSourceDialog:
        def __init__(self, _parent, _record, candidates) -> None:
            presented.append(list(candidates))

        def connect(self, *_args) -> None:
            return None

        def present(self) -> None:
            return None

    monkeypatch.setattr(application_window_module, "UpdateSourceDialog", FakeUpdateSourceDialog)

    window._present_update_discovery(record, discovery)

    assert presented == [[higher, same]]
    window.destroy()


def test_application_window_browse_response_opens_file_chooser(monkeypatch, tmp_path: Path) -> None:
    Gtk.init()
    app = Adw.Application(application_id="io.github.appimageintegrator.tests.update-browse")
    window = ApplicationWindow(app, _make_services())
    record = _make_record(tmp_path)
    opened: list[ManagedAppRecord] = []
    monkeypatch.setattr(window, "_open_update_file_chooser", lambda candidate_record: opened.append(candidate_record))

    window._on_update_source_dialog_response(None, "browse", None, record)

    assert opened == [record]
    window.destroy()


def test_application_window_non_executable_automatic_candidate_prompts_trust_and_updates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    Gtk.init()
    app = Adw.Application(application_id="io.github.appimageintegrator.tests.update-auto-trust")
    services = _make_services()
    chmod_calls: list[Path] = []
    services.install_manager.ensure_source_executable = lambda path: (
        chmod_calls.append(path),
        path.chmod(path.stat().st_mode | 0o100),
    )
    window = ApplicationWindow(app, services)
    record = _make_record(tmp_path)
    candidate = tmp_path / "demo-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    candidate.chmod(0o644)
    install_calls: list[tuple[ManagedAppRecord, Path, str, bool]] = []
    monkeypatch.setattr(
        window.install_view,
        "install_record_from_source",
        lambda selected_record, path, *, button_label, require_trust_prompt: install_calls.append(
            (selected_record, path, button_label, require_trust_prompt)
        ),
    )

    def fake_prompt(_parent, path, ensure_source_executable, **kwargs) -> None:
        ensure_source_executable(path)
        kwargs["on_trusted"]()

    monkeypatch.setattr(application_window_module, "prompt_for_appimage_trust", fake_prompt)

    window._prepare_update_source(record, candidate, validate_selection=False)

    assert chmod_calls == [candidate]
    assert os.access(candidate, os.X_OK)
    assert install_calls == [(record, candidate, "Update", False)]
    window.destroy()


def test_application_window_manual_non_executable_candidate_is_validated_after_trust(
    monkeypatch,
    tmp_path: Path,
) -> None:
    Gtk.init()
    app = Adw.Application(application_id="io.github.appimageintegrator.tests.update-manual-trust")
    services = _make_services()
    services.install_manager.ensure_source_executable = lambda path: path.chmod(path.stat().st_mode | 0o100)
    validated: list[Path] = []
    manual_candidate = _make_candidate(tmp_path / "manual-v2.AppImage", version="2.0.0", is_executable=True)
    services.update_discovery.evaluate_candidate = lambda _record, path: (
        validated.append(path),
        manual_candidate if os.access(path, os.X_OK) else None,
    )[1]
    window = ApplicationWindow(app, services)
    record = _make_record(tmp_path)
    candidate = tmp_path / "manual-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    candidate.chmod(0o644)
    install_calls: list[tuple[ManagedAppRecord, Path, str, bool]] = []
    monkeypatch.setattr(
        window.install_view,
        "install_record_from_source",
        lambda selected_record, path, *, button_label, require_trust_prompt: install_calls.append(
            (selected_record, path, button_label, require_trust_prompt)
        ),
    )

    def fake_prompt(_parent, path, ensure_source_executable, **kwargs) -> None:
        ensure_source_executable(path)
        kwargs["on_trusted"]()

    monkeypatch.setattr(application_window_module, "prompt_for_appimage_trust", fake_prompt)

    window._prepare_update_source(record, candidate, validate_selection=True)

    assert validated == [candidate]
    assert install_calls == [(record, candidate, "Update", False)]
    window.destroy()


def test_application_window_manual_non_executable_cancel_leaves_file_unchanged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    Gtk.init()
    app = Adw.Application(application_id="io.github.appimageintegrator.tests.update-cancel")
    window = ApplicationWindow(app, _make_services())
    record = _make_record(tmp_path)
    candidate = tmp_path / "manual-v2.AppImage"
    candidate.write_text("appimage", encoding="utf-8")
    candidate.chmod(0o644)
    install_calls: list[Path] = []
    monkeypatch.setattr(
        window.install_view,
        "install_record_from_source",
        lambda _record, path, *, button_label, require_trust_prompt: install_calls.append(path),
    )
    monkeypatch.setattr(
        application_window_module,
        "prompt_for_appimage_trust",
        lambda _parent, _path, _ensure, **_kwargs: None,
    )

    window._prepare_update_source(record, candidate, validate_selection=True)

    assert install_calls == []
    assert os.access(candidate, os.X_OK) is False
    window.destroy()


def test_application_window_no_automatic_candidates_keeps_manual_choose_flow(monkeypatch, tmp_path: Path) -> None:
    Gtk.init()
    app = Adw.Application(application_id="io.github.appimageintegrator.tests.update-none")
    window = ApplicationWindow(app, _make_services())
    record = _make_record(tmp_path)
    discovery = UpdateDiscoveryResult(
        record=record,
        searched_directories=[tmp_path / "Downloads"],
        higher_version_candidates=[],
        same_or_unknown_candidates=[],
        skipped_paths=[],
    )
    shown: list[tuple[str, str]] = []
    opened: list[ManagedAppRecord] = []

    class FakeMessageDialog:
        def __init__(self, _parent, title: str, body: str) -> None:
            shown.append((title, body))

        def add_response(self, _response_id: str, _label: str) -> None:
            return None

        def set_default_response(self, _response_id: str) -> None:
            return None

        def set_close_response(self, _response_id: str) -> None:
            return None

        def set_response_appearance(self, _response_id: str, _appearance) -> None:
            return None

        def connect(self, _signal: str, callback, *args) -> None:
            callback(self, "choose", *args)

        def present(self) -> None:
            return None

    monkeypatch.setattr(application_window_module, "CompatMessageDialog", FakeMessageDialog)
    monkeypatch.setattr(window, "_open_update_file_chooser", lambda candidate_record: opened.append(candidate_record))

    window._present_update_discovery(record, discovery)

    assert shown
    assert shown[0][0] == "No newer AppImage found"
    assert opened == [record]
    window.destroy()
