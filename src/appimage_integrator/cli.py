from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from appimage_integrator.config import PRESET_LABELS
from appimage_integrator.launcher import build_managed_app_launch_command
from appimage_integrator.models import AppImageInspection, InstallRequest, ManagedAppRecord


class AppImageArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed, unknown = self.parse_known_args(args, namespace)
        if unknown:
            if getattr(parsed, "command", None) == "launch":
                launch_args = list(getattr(parsed, "launch_args", []))
                if unknown and unknown[0] == "--":
                    unknown = unknown[1:]
                parsed.launch_args = [*launch_args, *unknown]
                return parsed
            self.error(f"unrecognized arguments: {' '.join(unknown)}")
        return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = AppImageArgumentParser(
        prog="appimage-integrator",
        description="Manage AppImage desktop integrations from the command line.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("gui", help="Launch the graphical interface")
    subparsers.add_parser("presets", help="List the available launch argument presets")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect an AppImage before installing it")
    inspect_parser.add_argument("path", type=Path, help="Path to the AppImage")
    inspect_parser.add_argument(
        "--trust",
        action="store_true",
        help="Mark the AppImage executable before inspection if needed",
    )
    inspect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    install_parser = subparsers.add_parser("install", help="Install or update an AppImage integration")
    install_parser.add_argument("path", type=Path, help="Path to the AppImage")
    _add_install_options(install_parser)

    list_parser = subparsers.add_parser("list", help="List managed AppImages")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    list_parser.add_argument(
        "--validate",
        action="store_true",
        help="Refresh validation status for every record before listing",
    )

    details_parser = subparsers.add_parser("details", help="Show stored details for a managed AppImage")
    details_parser.add_argument("identifier", help="Internal ID, unique ID prefix, or display name")
    details_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    launch_parser = subparsers.add_parser("launch", help="Launch a managed AppImage")
    launch_parser.add_argument("identifier", help="Internal ID, unique ID prefix, or display name")
    launch_parser.add_argument(
        "--desktop",
        action="store_true",
        help="Show a GUI-visible error dialog when launch is blocked",
    )
    launch_parser.set_defaults(launch_args=[])

    repair_parser = subparsers.add_parser("repair", help="Repair a managed AppImage integration")
    repair_parser.add_argument("identifier", help="Internal ID, unique ID prefix, or display name")
    repair_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    uninstall_parser = subparsers.add_parser("uninstall", help="Remove a managed AppImage integration")
    uninstall_parser.add_argument("identifier", help="Internal ID, unique ID prefix, or display name")

    reinstall_parser = subparsers.add_parser("reinstall", help="Reinstall from the original AppImage source")
    reinstall_parser.add_argument("identifier", help="Internal ID, unique ID prefix, or display name")
    reinstall_parser.add_argument(
        "--trust",
        action="store_true",
        help="Mark the original AppImage executable before reinstalling if needed",
    )
    reinstall_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    update_parser = subparsers.add_parser("update", help="Alias for reinstall")
    update_parser.add_argument("identifier", help="Internal ID, unique ID prefix, or display name")
    update_parser.add_argument(
        "--trust",
        action="store_true",
        help="Mark the original AppImage executable before reinstalling if needed",
    )
    update_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    return parser


def _add_install_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", dest="display_name", help="Override the launcher display name")
    parser.add_argument("--comment", help="Override the launcher comment")
    parser.add_argument(
        "--extra-args",
        default="",
        help="Extra launch arguments as a shell-style string",
    )
    parser.add_argument(
        "--arg",
        dest="args",
        action="append",
        default=[],
        help="Additional launch argument, may be passed multiple times",
    )
    parser.add_argument(
        "--preset",
        default="none",
        choices=tuple(PRESET_LABELS),
        help="Launch argument preset to append",
    )
    parser.add_argument(
        "--trust",
        action="store_true",
        help="Mark the AppImage executable before inspection and installation if needed",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")


def run_cli(
    args: argparse.Namespace,
    services,
    stdout: TextIO,
    stderr: TextIO,
    stdin: TextIO | None = None,
) -> int:
    stdin = stdin or sys.stdin
    command = args.command
    if command == "presets":
        return _cmd_presets(stdout)
    if command == "inspect":
        return _cmd_inspect(args, services, stdout, stderr)
    if command == "install":
        return _cmd_install(args, services, stdout, stderr)
    if command == "list":
        return _cmd_list(args, services, stdout)
    if command == "details":
        return _cmd_details(args, services, stdout, stderr)
    if command == "launch":
        return _cmd_launch(args, services, stdout, stderr)
    if command == "repair":
        return _cmd_repair(args, services, stdout, stderr)
    if command == "uninstall":
        return _cmd_uninstall(args, services, stdout, stderr)
    if command == "reinstall":
        return _cmd_reinstall(args, services, stdout, stderr)
    if command == "update":
        return _cmd_update(args, services, stdout, stderr, stdin)
    raise ValueError(f"Unsupported CLI command: {command}")


def _cmd_presets(stdout: TextIO) -> int:
    for preset_id, label in PRESET_LABELS.items():
        stdout.write(f"{preset_id}: {label}\n")
    return 0


def _cmd_inspect(args: argparse.Namespace, services, stdout: TextIO, stderr: TextIO) -> int:
    path = args.path.expanduser()
    if not _prepare_source_path(path, services, args.trust, stderr):
        return 1

    inspection, existing, mode = services.install_manager.inspect(path)
    try:
        payload = _inspection_payload(inspection, existing, mode)
        if args.json:
            _write_json(stdout, payload)
            return 0
        _write_inspection(stdout, payload)
        return 0 if not inspection.errors else 1
    finally:
        services.install_manager.inspector.cleanup(inspection)


def _cmd_install(args: argparse.Namespace, services, stdout: TextIO, stderr: TextIO) -> int:
    path = args.path.expanduser()
    if not _prepare_source_path(path, services, args.trust, stderr):
        return 1

    try:
        result = services.install_manager.install(
            InstallRequest(
                source_path=path,
                display_name_override=args.display_name,
                comment_override=args.comment,
                extra_args=_combine_extra_args(args.extra_args, args.args),
                arg_preset_id=args.preset,
                allow_update=True,
                allow_reinstall=True,
            )
        )
    except ValueError as exc:
        stderr.write(f"{exc}\n")
        return 1
    if args.json:
        _write_json(
            stdout,
            {
                "mode": result.mode,
                "record": result.record.to_dict(),
                "warnings": result.warnings,
                "validation_messages": result.validation_messages,
            },
        )
        return 0

    stdout.write(f"{result.mode.capitalize()} complete: {result.record.display_name}\n")
    stdout.write(f"ID: {result.record.internal_id}\n")
    stdout.write(f"Managed AppImage: {result.record.managed_appimage_path}\n")
    stdout.write(f"Desktop file: {result.record.managed_desktop_path}\n")
    if result.record.managed_icon_path:
        stdout.write(f"Icon: {result.record.managed_icon_path}\n")
    _write_messages(stdout, "Warnings", result.warnings)
    _write_messages(stdout, "Desktop validation", result.validation_messages)
    return 0


def _cmd_list(args: argparse.Namespace, services, stdout: TextIO) -> int:
    records = services.library_manager.list_records()
    if args.validate:
        records = [_sync_record_validation(record, services) for record in records]
    if args.json:
        _write_json(stdout, [record.to_dict() for record in records])
        return 0
    if not records:
        stdout.write("No managed AppImages.\n")
        return 0
    for record in records:
        version = record.version or "unknown"
        stdout.write(f"{record.internal_id}  {record.display_name}  {version}  {record.last_validation_status}\n")
    return 0


def _cmd_details(args: argparse.Namespace, services, stdout: TextIO, stderr: TextIO) -> int:
    try:
        record = _resolve_record(args.identifier, services)
    except ValueError as exc:
        stderr.write(f"{exc}\n")
        return 1
    record = _sync_record_validation(record, services)
    if args.json:
        _write_json(stdout, record.to_dict())
        return 0
    stdout.write(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    stdout.write("\n")
    return 0


def _cmd_launch(args: argparse.Namespace, services, stdout: TextIO, stderr: TextIO) -> int:
    try:
        record = _resolve_record(args.identifier, services)
    except ValueError as exc:
        stderr.write(f"{exc}\n")
        return 1
    launch_args = _normalize_launch_args(args.launch_args)
    record = _prepare_record_for_launch(record, services)
    launch_blocking_issues = _launch_blocking_issues(record)
    if launch_blocking_issues:
        _write_launch_blocked(stderr, launch_blocking_issues)
        if args.desktop:
            _show_launch_error_dialog(
                "Launch blocked",
                "AppImage Integrator could not launch this AppImage.",
                launch_blocking_issues,
            )
        return 1
    try:
        subprocess.Popen(build_managed_app_launch_command(record, launch_args))
    except OSError as exc:
        issue = _format_launch_error(exc)
        updated = ManagedAppRecord.from_dict(
            {
                **record.to_dict(),
                "last_validation_status": "error",
                "last_validation_messages": [issue],
            }
        )
        services.store.save(updated)
        stderr.write(f"{issue}\n")
        if args.desktop:
            _show_launch_error_dialog(
                "Launch failed",
                "AppImage Integrator could not start this AppImage.",
                [issue],
            )
        return 1
    stdout.write(f"Launched {record.display_name}\n")
    return 0


def _prepare_record_for_launch(record: ManagedAppRecord, services) -> ManagedAppRecord:
    if not _launch_blocking_issues(record):
        return record

    recovered = services.runtime_service.recover_record_for_launch(record)
    if recovered != record:
        services.store.save(recovered)
    return recovered


def _cmd_repair(args: argparse.Namespace, services, stdout: TextIO, stderr: TextIO) -> int:
    try:
        record = _resolve_record(args.identifier, services)
    except ValueError as exc:
        stderr.write(f"{exc}\n")
        return 1
    repaired, report = services.repair_manager.repair(record)
    services.store.save(repaired)
    if args.json:
        _write_json(
            stdout,
            {
                "record": repaired.to_dict(),
                "report": {
                    "internal_id": report.internal_id,
                    "issues": report.issues,
                    "actions_taken": report.actions_taken,
                    "success": report.success,
                },
            },
        )
        return 0 if report.success else 1
    stdout.write(f"Repair {'succeeded' if report.success else 'failed'} for {repaired.display_name}\n")
    _write_messages(stdout, "Actions", report.actions_taken)
    _write_messages(stdout, "Issues", report.issues)
    return 0 if report.success else 1


def _cmd_uninstall(args: argparse.Namespace, services, stdout: TextIO, stderr: TextIO) -> int:
    try:
        record = _resolve_record(args.identifier, services)
    except ValueError as exc:
        stderr.write(f"{exc}\n")
        return 1
    services.install_manager.uninstall(record)
    stdout.write(f"Removed {record.display_name}\n")
    return 0


def _cmd_reinstall(args: argparse.Namespace, services, stdout: TextIO, stderr: TextIO) -> int:
    try:
        record = _resolve_record(args.identifier, services)
    except ValueError as exc:
        stderr.write(f"{exc}\n")
        return 1

    source_path = Path(record.source_path_last_seen).expanduser()
    if not _prepare_source_path(source_path, services, args.trust, stderr):
        return 1

    return _install_from_record_source(record, source_path, services, stdout, stderr, args.json)


def _cmd_update(
    args: argparse.Namespace,
    services,
    stdout: TextIO,
    stderr: TextIO,
    stdin: TextIO,
) -> int:
    try:
        record = _resolve_record(args.identifier, services)
    except ValueError as exc:
        stderr.write(f"{exc}\n")
        return 1

    discovery = services.update_discovery.discover_updates(record)
    interaction_output = stderr if args.json else stdout
    chosen_path = _choose_update_source(record, discovery, interaction_output, stderr, stdin)
    if chosen_path is None:
        return 0
    matched_candidate = _candidate_from_discovery(discovery, chosen_path)
    if matched_candidate is None:
        try:
            matched_candidate = services.update_discovery.evaluate_candidate(record, chosen_path)
        except OSError as exc:
            stderr.write(f"Could not inspect selected AppImage: {exc}\n")
            return 1
    if matched_candidate is None:
        stderr.write("Selected AppImage does not appear to be the same application.\n")
        return 1
    if not _prepare_source_path_with_prompt(
        chosen_path,
        services,
        args.trust,
        interaction_output,
        stderr,
        stdin,
    ):
        return 1
    return _install_from_record_source(record, chosen_path, services, stdout, stderr, args.json)


def _install_from_record_source(
    record: ManagedAppRecord,
    source_path: Path,
    services,
    stdout: TextIO,
    stderr: TextIO,
    json_output: bool,
) -> int:
    try:
        result = services.install_manager.install(
            InstallRequest(
                source_path=source_path,
                display_name_override=record.display_name,
                comment_override=record.comment,
                extra_args=record.extra_args,
                arg_preset_id=record.arg_preset_id,
                allow_update=True,
                allow_reinstall=True,
            )
        )
    except ValueError as exc:
        stderr.write(f"{exc}\n")
        return 1
    if json_output:
        _write_json(
            stdout,
            {
                "mode": result.mode,
                "record": result.record.to_dict(),
                "warnings": result.warnings,
                "validation_messages": result.validation_messages,
            },
        )
        return 0
    stdout.write(f"{result.mode.capitalize()} complete: {result.record.display_name}\n")
    stdout.write(f"Managed AppImage: {result.record.managed_appimage_path}\n")
    _write_messages(stdout, "Warnings", result.warnings)
    _write_messages(stdout, "Desktop validation", result.validation_messages)
    return 0


def _combine_extra_args(extra_args_text: str, appended_args: Iterable[str]) -> list[str]:
    combined = shlex.split(extra_args_text) if extra_args_text else []
    combined.extend(appended_args)
    return combined


def _prepare_source_path(path: Path, services, trust: bool, stderr: TextIO) -> bool:
    if not path.exists():
        stderr.write(f"AppImage not found: {path}\n")
        return False
    if os.access(path, os.X_OK):
        return True
    if not trust:
        stderr.write(
            "The AppImage is not executable. Re-run with --trust to mark it executable before continuing.\n"
        )
        return False
    try:
        services.install_manager.ensure_source_executable(path)
    except OSError as exc:
        stderr.write(f"Could not mark the AppImage executable: {exc}\n")
        return False
    return True


def _prepare_source_path_with_prompt(
    path: Path,
    services,
    trust: bool,
    stdout: TextIO,
    stderr: TextIO,
    stdin: TextIO,
) -> bool:
    if path.exists() and os.access(path, os.X_OK):
        return True
    if trust:
        return _prepare_source_path(path, services, trust, stderr)
    if not path.exists():
        stderr.write(f"AppImage not found: {path}\n")
        return False
    answer = _prompt(stdin, stdout, "Mark it executable and continue? [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        stderr.write("Update cancelled.\n")
        return False
    return _prepare_source_path(path, services, True, stderr)


def _choose_update_source(record, discovery, stdout: TextIO, stderr: TextIO, stdin: TextIO) -> Path | None:
    if discovery.higher_version_candidates:
        candidate = discovery.higher_version_candidates[0]
        stdout.write(
            "Detected update candidate:\n"
            f"- Current version: {record.version or 'unknown'}\n"
            f"- Detected version: {candidate.detected_version or 'unknown'}\n"
            f"- File: {candidate.path}\n"
            f"- Match: {candidate.match_kind}\n"
        )
        choice = _prompt(
            stdin,
            stdout,
            "Choose an action [1=update detected, 2=choose AppImage, 3=cancel]: ",
        ).strip()
        if choice == "1":
            return candidate.path
        if choice == "2":
            return _prompt_for_update_path(stdin, stdout, stderr)
        return None

    stdout.write("No higher-version AppImage was detected automatically.\n")
    if discovery.searched_directories:
        stdout.write("Searched:\n")
        for directory in discovery.searched_directories:
            stdout.write(f"- {directory}\n")
    return _prompt_for_update_path(stdin, stdout, stderr)


def _candidate_from_discovery(discovery, path: Path):
    resolved_path = path.resolve(strict=False)
    for candidate in [*discovery.higher_version_candidates, *discovery.same_or_unknown_candidates]:
        if candidate.path.resolve(strict=False) == resolved_path:
            return candidate
    return None


def _prompt_for_update_path(stdin: TextIO, stdout: TextIO, stderr: TextIO) -> Path | None:
    for attempt in range(2):
        entered = _prompt(stdin, stdout, "Enter AppImage path to update from (blank to cancel): ").strip()
        if not entered:
            return None
        path = Path(entered).expanduser()
        if path.exists():
            return path
        stderr.write(f"AppImage not found: {path}\n")
        if attempt == 1:
            return None
    return None


def _prompt(stdin: TextIO, stdout: TextIO, message: str) -> str:
    stdout.write(message)
    stdout.flush()
    return stdin.readline()


def _inspection_payload(
    inspection: AppImageInspection,
    existing: ManagedAppRecord | None,
    mode: str,
) -> dict[str, object]:
    payload = {
        "mode": mode,
        "inspection": inspection.to_dict(),
        "existing_record": existing.to_dict() if existing else None,
    }
    return payload


def _write_inspection(stdout: TextIO, payload: dict[str, object]) -> None:
    inspection = payload["inspection"]
    assert isinstance(inspection, dict)
    stdout.write(f"Mode: {payload['mode']}\n")
    stdout.write(f"Name: {inspection['detected_name'] or Path(str(inspection['source_path'])).stem}\n")
    stdout.write(f"Version: {inspection['detected_version'] or 'unknown'}\n")
    stdout.write(f"AppImage type: {inspection['appimage_type']}\n")
    stdout.write(f"Desktop file: {inspection['embedded_desktop_filename'] or 'fallback'}\n")
    stdout.write(f"AppStream ID: {inspection['appstream_id'] or 'not found'}\n")
    stdout.write(f"Icon: {inspection['chosen_icon_candidate']['source_path'] if inspection['chosen_icon_candidate'] else 'fallback'}\n")
    _write_messages(stdout, "Warnings", inspection["warnings"])
    _write_messages(stdout, "Errors", inspection["errors"])


def _write_messages(stdout: TextIO, title: str, messages: list[str]) -> None:
    if not messages:
        return
    stdout.write(f"{title}:\n")
    for message in messages:
        stdout.write(f"- {message}\n")


def _write_json(stdout: TextIO, payload: object) -> None:
    stdout.write(json.dumps(payload, indent=2, sort_keys=True))
    stdout.write("\n")


def _resolve_record(identifier: str, services) -> ManagedAppRecord:
    records = services.library_manager.list_records()
    if not records:
        raise ValueError("No managed AppImages exist yet.")

    exact_id = [record for record in records if record.internal_id == identifier]
    if exact_id:
        return exact_id[0]

    exact_name = [record for record in records if record.display_name.casefold() == identifier.casefold()]
    if len(exact_name) == 1:
        return exact_name[0]
    if len(exact_name) > 1:
        raise ValueError(f"Multiple AppImages share the display name '{identifier}'. Use the internal ID.")

    prefix_matches = [record for record in records if record.internal_id.startswith(identifier)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        raise ValueError(f"Identifier '{identifier}' matches multiple AppImages. Use the full internal ID.")

    raise ValueError(f"Managed AppImage not found: {identifier}")


def _sync_record_validation(record: ManagedAppRecord, services) -> ManagedAppRecord:
    validated_record, status, messages = services.library_manager.validate_record(record)
    if status == validated_record.last_validation_status and messages == validated_record.last_validation_messages:
        if validated_record != record:
            services.store.save(validated_record)
        return validated_record
    updated = ManagedAppRecord.from_dict(
        {
            **validated_record.to_dict(),
            "last_validation_status": status,
            "last_validation_messages": messages,
        }
    )
    services.store.save(updated)
    return updated


def _normalize_launch_args(launch_args: list[str]) -> list[str]:
    if launch_args and launch_args[0] == "--":
        return launch_args[1:]
    return launch_args


def _write_launch_blocked(stderr: TextIO, messages: list[str]) -> None:
    stderr.write("Launch blocked by integration errors:\n")
    for message in messages:
        stderr.write(f"- {message}\n")


def _launch_blocking_issues(record: ManagedAppRecord) -> list[str]:
    appimage_path = Path(record.managed_appimage_path)
    if not appimage_path.exists():
        return ["Managed AppImage is missing."]
    if not os.access(appimage_path, os.X_OK):
        return ["Managed AppImage is not executable."]
    return []


def _show_launch_error_dialog(title: str, intro: str, messages: list[str]) -> None:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib

        from appimage_integrator.ui.dialogs import CompatMessageDialog
    except Exception:
        return

    loop = GLib.MainLoop()
    body = intro
    if messages:
        message_lines = "\n".join(f"- {message}" for message in messages)
        body = f"{intro}\n\n{message_lines}"
    dialog = CompatMessageDialog(None, title, body)
    dialog.add_response("ok", "OK")
    dialog.set_default_response("ok")
    dialog.set_close_response("ok")
    dialog.connect("response", lambda *_args: loop.quit())
    try:
        dialog.present()
        loop.run()
    except Exception:
        loop.quit()


def _format_launch_error(exc: OSError) -> str:
    if isinstance(exc, FileNotFoundError):
        return "Managed AppImage is missing."
    if isinstance(exc, PermissionError):
        return "Managed AppImage is not executable."
    return f"Launching failed: {exc}"
