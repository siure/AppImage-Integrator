from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Callable

from appimage_integrator.bootstrap import ServiceContainer
from appimage_integrator import cli
from appimage_integrator.cli import build_parser, run_cli
from appimage_integrator.models import AppImageInspection
from appimage_integrator.services.desktop_entry import DesktopEntryService, parse_desktop_entry
from appimage_integrator.services.icon_resolver import IconResolver
from appimage_integrator.services.id_resolver import IdResolver
from appimage_integrator.services.install_manager import InstallManager
from appimage_integrator.services.library_manager import LibraryManager
from appimage_integrator.services.managed_app_runtime import ManagedAppRuntimeService
from appimage_integrator.services.record_editor import RecordEditorService
from appimage_integrator.services.repair_manager import RepairManager
from appimage_integrator.services.update_discovery import UpdateDiscoveryService
from appimage_integrator.storage.metadata_store import MetadataStore


class FakeInspector:
    def __init__(self, inspections: list[AppImageInspection]) -> None:
        self.inspections = inspections
        self.cleanup_calls = 0

    def inspect(self, _source_path: Path) -> AppImageInspection:
        return self.inspections.pop(0)

    def cleanup(self, _inspection: AppImageInspection) -> None:
        self.cleanup_calls += 1


class AppPathsLike:
    def __init__(self, extracted_dir: Path) -> None:
        self.icons_dir = extracted_dir.parent / "icons"


def make_inspection(source_path: Path, extracted_dir: Path, version: str | None) -> AppImageInspection:
    icon_candidate = IconResolver._candidate_from_path(
        IconResolver(AppPathsLike(extracted_dir)),
        extracted_dir,
        extracted_dir / "demo.svg",
    )
    entry = parse_desktop_entry(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Demo Browser\n"
        "Comment=Demo comment\n"
        "Exec=AppRun --existing %U\n"
        "Icon=demo\n"
        "StartupWMClass=DemoBrowser\n"
        "X-AppImage-Version="
        + (version or "")
        + "\n",
        "demo.desktop",
    )
    return AppImageInspection(
        source_path=source_path,
        is_appimage=True,
        appimage_type="type2",
        is_executable=True,
        detected_name="Demo Browser",
        detected_comment="Demo comment",
        detected_version=version,
        appstream_id="org.demo.Browser",
        embedded_desktop_filename="demo.desktop",
        desktop_entry=entry,
        chosen_icon_candidate=icon_candidate,
        startup_wm_class="DemoBrowser",
        mime_types=["x-scheme-handler/http"],
        categories=["Network"],
        terminal=False,
        startup_notify=True,
        exec_placeholders=["%U"],
        warnings=[],
        errors=[],
        extracted_dir=extracted_dir,
    )


def _default_launcher_command(test_paths) -> list[str]:
    return [str(test_paths.self_command_path)]


def build_services(
    test_paths,
    tooling,
    inspections: list[AppImageInspection],
    launcher_command_resolver: Callable[[], list[str] | None] | None = None,
) -> ServiceContainer:
    logger = logging.getLogger("tests.cli")
    store = MetadataStore(test_paths)
    icon_resolver = IconResolver(test_paths)
    inspector = FakeInspector(inspections)
    launcher_command_resolver = launcher_command_resolver or (lambda: _default_launcher_command(test_paths))
    desktop_service = DesktopEntryService(tooling, launcher_command_resolver=launcher_command_resolver)
    runtime_service = ManagedAppRuntimeService(
        test_paths,
        inspector,
        desktop_service,
        icon_resolver,
        IdResolver(),
    )
    install_manager = InstallManager(
        test_paths,
        inspector,
        desktop_service,
        icon_resolver,
        IdResolver(),
        runtime_service,
        store,
        tooling,
    )
    library_manager = LibraryManager(store, runtime_service, desktop_service)
    repair_manager = RepairManager(
        inspector,
        desktop_service,
        icon_resolver,
        runtime_service,
        store,
    )
    record_editor = RecordEditorService(
        store,
        runtime_service,
        desktop_service,
        inspector,
    )
    return ServiceContainer(
        paths=test_paths,
        logger=logger,
        tooling=tooling,
        store=store,
        install_manager=install_manager,
        library_manager=library_manager,
        runtime_service=runtime_service,
        record_editor=record_editor,
        repair_manager=repair_manager,
        update_discovery=UpdateDiscoveryService(test_paths, inspector, IdResolver()),
    )


def run_args(parser, services, *argv: str, stdin_text: str = "") -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_cli(parser.parse_args(list(argv)), services, stdout, stderr, io.StringIO(stdin_text))
    return code, stdout.getvalue(), stderr.getvalue()


def test_cli_install_list_details_reinstall_and_uninstall(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    source.chmod(0o644)
    extracted = test_paths.cache_extract_dir / "extract-cli"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    services = build_services(
        test_paths,
        tooling,
        [
            make_inspection(source, extracted, "1.0.0"),
            make_inspection(source, extracted, "1.0.0"),
        ],
    )
    parser = build_parser()

    code, stdout, stderr = run_args(
        parser,
        services,
        "install",
        str(source),
        "--trust",
        "--name",
        "CLI Demo",
        "--comment",
        "Managed from CLI",
        "--extra-args",
        '--foo "bar baz"',
        "--arg=--tail",
        "--preset",
        "disable_gpu",
        "--json",
    )
    assert code == 0, stderr
    payload = json.loads(stdout)
    internal_id = payload["record"]["internal_id"]
    assert payload["record"]["display_name"] == "CLI Demo"
    assert payload["record"]["comment"] == "Managed from CLI"
    assert payload["record"]["extra_args"] == ["--foo", "bar baz", "--tail"]
    assert source.stat().st_mode & 0o100

    code, stdout, stderr = run_args(parser, services, "list", "--json")
    assert code == 0, stderr
    listed = json.loads(stdout)
    assert len(listed) == 1
    assert listed[0]["internal_id"] == internal_id

    original_validate_record = services.library_manager.validate_record

    def fail_validation(*_args, **_kwargs):
        raise AssertionError("list should not validate records unless requested")

    services.library_manager.validate_record = fail_validation
    code, stdout, stderr = run_args(parser, services, "list", "--json")
    assert code == 0, stderr
    assert json.loads(stdout)[0]["internal_id"] == internal_id
    services.library_manager.validate_record = original_validate_record

    code, stdout, stderr = run_args(parser, services, "details", internal_id, "--json")
    assert code == 0, stderr
    details = json.loads(stdout)
    assert details["display_name"] == "CLI Demo"

    code, stdout, stderr = run_args(parser, services, "reinstall", internal_id, "--json")
    assert code == 0, stderr
    reinstall = json.loads(stdout)
    assert reinstall["mode"] == "reinstall"
    assert reinstall["record"]["display_name"] == "CLI Demo"

    code, stdout, stderr = run_args(parser, services, "uninstall", internal_id)
    assert code == 0, stderr
    assert "Removed CLI Demo" in stdout


def test_cli_inspect_requires_trust_for_non_executable_source(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "inspect.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    source.chmod(0o644)
    extracted = test_paths.cache_extract_dir / "extract-inspect-cli"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    services = build_services(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    parser = build_parser()

    code, stdout, stderr = run_args(parser, services, "inspect", str(source))

    assert code == 1
    assert stdout == ""
    assert "--trust" in stderr


def test_cli_launch_reports_validation_errors(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "launch.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-launch-cli"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    services = build_services(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    parser = build_parser()
    code, stdout, stderr = run_args(parser, services, "install", str(source), "--trust", "--json")
    assert code == 0, stderr
    internal_id = json.loads(stdout)["record"]["internal_id"]

    record = services.store.load(internal_id)
    assert record is not None
    Path(record.managed_appimage_path).chmod(0o644)

    code, stdout, stderr = run_args(parser, services, "launch", internal_id)

    assert code == 1
    assert stdout == ""
    assert "Launch blocked by integration errors:" in stderr
    assert "Managed AppImage is not executable." in stderr


def test_cli_install_rejects_non_appimage(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "fake.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("not an appimage", encoding="utf-8")
    source.chmod(0o755)

    services = build_services(
        test_paths,
        tooling,
        [
            AppImageInspection(
                source_path=source,
                is_appimage=False,
                appimage_type="unknown",
                is_executable=True,
                detected_name=source.stem,
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
                warnings=["The file does not strongly identify itself as an AppImage."],
                errors=["Could not extract AppImage contents."],
                extracted_dir=None,
            )
        ],
    )
    parser = build_parser()

    code, stdout, stderr = run_args(parser, services, "install", str(source), "--json")

    assert code == 1
    assert stdout == ""
    assert "not a valid AppImage" in stderr


def test_cli_launch_allows_desktop_warnings(monkeypatch, test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "warning-launch.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-warning-launch"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    services = build_services(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    parser = build_parser()
    code, stdout, stderr = run_args(parser, services, "install", str(source), "--trust", "--json")
    assert code == 0, stderr
    internal_id = json.loads(stdout)["record"]["internal_id"]

    services.library_manager.desktop_service.validate_text = (
        lambda _text: ["demo.desktop: warning: comment matches name"]
    )

    launched: list[list[str]] = []

    class DummyProcess:
        pass

    def fake_popen(args):
        launched.append(args)
        return DummyProcess()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)

    code, stdout, stderr = run_args(parser, services, "launch", internal_id)

    assert code == 0
    assert stderr == ""
    assert "Launched Demo Browser" in stdout
    assert launched == [[services.store.load(internal_id).managed_appimage_path, "--existing"]]


def test_cli_launch_forwards_passthrough_args(monkeypatch, test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "launch-args.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-launch-args"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    services = build_services(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    parser = build_parser()
    code, stdout, stderr = run_args(parser, services, "install", str(source), "--trust", "--json")
    assert code == 0, stderr
    internal_id = json.loads(stdout)["record"]["internal_id"]

    launched: list[list[str]] = []

    class DummyProcess:
        pass

    def fake_popen(args):
        launched.append(args)
        return DummyProcess()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)

    code, stdout, stderr = run_args(
        parser,
        services,
        "launch",
        internal_id,
        "--",
        "--sample",
        "value",
        "%U",
    )

    assert code == 0
    assert stderr == ""
    assert launched == [[services.store.load(internal_id).managed_appimage_path, "--existing", "--sample", "value", "%U"]]


def test_cli_launch_desktop_auto_heals_renamed_payload(monkeypatch, test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "self-update.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-self-update-launch"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    services = build_services(
        test_paths,
        tooling,
        [
            make_inspection(source, extracted, "1.0.0"),
            make_inspection(source.parent / "self-update-v2.AppImage", extracted, "2.0.0"),
        ],
    )
    parser = build_parser()
    code, stdout, stderr = run_args(parser, services, "install", str(source), "--trust", "--json")
    assert code == 0, stderr
    internal_id = json.loads(stdout)["record"]["internal_id"]
    record = services.store.load(internal_id)
    assert record is not None

    Path(record.managed_payload_path).unlink()
    replacement = Path(record.managed_payload_dir) / "self-update-v2.AppImage"
    replacement.write_text("appimage", encoding="utf-8")
    replacement.chmod(0o755)

    launched: list[list[str]] = []
    shown_dialogs: list[tuple[str, str, list[str]]] = []

    class DummyProcess:
        pass

    def fake_popen(args):
        launched.append(args)
        return DummyProcess()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli, "_show_launch_error_dialog", lambda title, intro, messages: shown_dialogs.append((title, intro, messages)))

    code, stdout, stderr = run_args(parser, services, "launch", internal_id, "--desktop")

    assert code == 0
    assert stderr == ""
    assert shown_dialogs == []
    updated_record = services.store.load(internal_id)
    assert updated_record is not None
    assert updated_record.version == "2.0.0"
    assert Path(updated_record.managed_appimage_path).resolve() == replacement.resolve()
    assert launched == [[updated_record.managed_appimage_path, "--existing"]]


def test_cli_launch_desktop_shows_visible_failure_when_recovery_fails(monkeypatch, test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "desktop-failure.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    extracted = test_paths.cache_extract_dir / "extract-desktop-failure-launch"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    services = build_services(
        test_paths,
        tooling,
        [make_inspection(source, extracted, "1.0.0")],
    )
    parser = build_parser()
    code, stdout, stderr = run_args(parser, services, "install", str(source), "--trust", "--json")
    assert code == 0, stderr
    internal_id = json.loads(stdout)["record"]["internal_id"]
    record = services.store.load(internal_id)
    assert record is not None
    Path(record.managed_payload_path).unlink()

    shown_dialogs: list[tuple[str, str, list[str]]] = []
    monkeypatch.setattr(cli, "_show_launch_error_dialog", lambda title, intro, messages: shown_dialogs.append((title, intro, messages)))

    code, stdout, stderr = run_args(parser, services, "launch", internal_id, "--desktop")

    assert code == 1
    assert stdout == ""
    assert "Launch blocked by integration errors:" in stderr
    assert shown_dialogs == [
        (
            "Launch blocked",
            "AppImage Integrator could not launch this AppImage.",
            ["Managed AppImage is missing."],
        )
    ]


def test_cli_update_uses_detected_higher_version(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    update_source = source.parent / "demo-v2.AppImage"
    update_source.write_text("appimage", encoding="utf-8")
    update_source.chmod(0o755)
    extracted = test_paths.cache_extract_dir / "extract-update-cli"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    services = build_services(
        test_paths,
        tooling,
        [
            make_inspection(source, extracted, "1.0.0"),
            make_inspection(update_source, extracted, "2.0.0"),
            make_inspection(update_source, extracted, "2.0.0"),
            make_inspection(update_source, extracted, "2.0.0"),
        ],
    )
    parser = build_parser()

    code, stdout, stderr = run_args(parser, services, "install", str(source), "--trust", "--json")
    assert code == 0, stderr
    internal_id = json.loads(stdout)["record"]["internal_id"]

    code, stdout, stderr = run_args(parser, services, "update", internal_id, "--json", stdin_text="1\n")

    assert code == 0, stderr
    payload = json.loads(stdout)
    assert payload["mode"] == "update"
    assert payload["record"]["source_path_last_seen"] == str(update_source)
    assert len(services.install_manager.inspector.inspections) == 1


def test_cli_update_falls_back_to_manual_path_when_no_higher_version_exists(test_paths, tooling) -> None:
    source = test_paths.home / "Downloads" / "demo-v1.AppImage"
    source.parent.mkdir(parents=True)
    source.write_text("appimage", encoding="utf-8")
    manual_source = test_paths.home / "Manual" / "demo-v2.AppImage"
    manual_source.parent.mkdir(parents=True)
    manual_source.write_text("appimage", encoding="utf-8")
    manual_source.chmod(0o755)
    extracted = test_paths.cache_extract_dir / "extract-update-manual-cli"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    services = build_services(
        test_paths,
        tooling,
        [
            make_inspection(source, extracted, "1.0.0"),
            make_inspection(manual_source, extracted, "2.0.0"),
            make_inspection(manual_source, extracted, "2.0.0"),
        ],
    )
    parser = build_parser()

    code, stdout, stderr = run_args(parser, services, "install", str(source), "--trust", "--json")
    assert code == 0, stderr
    internal_id = json.loads(stdout)["record"]["internal_id"]

    code, stdout, stderr = run_args(
        parser,
        services,
        "update",
        internal_id,
        "--json",
        stdin_text=f"{manual_source}\n",
    )

    assert code == 0, stderr
    payload = json.loads(stdout)
    assert payload["mode"] == "update"
    assert payload["record"]["source_path_last_seen"] == str(manual_source)
