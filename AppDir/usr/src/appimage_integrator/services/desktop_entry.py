from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from collections import OrderedDict
from pathlib import Path
from tempfile import NamedTemporaryFile

from appimage_integrator.config import PRESET_ARGUMENTS
from appimage_integrator.models import AppImageInspection, EmbeddedDesktopEntry, ManagedAppRecord
from appimage_integrator.services.tooling import Tooling

PLACEHOLDER_RE = re.compile(r"^%[UuFf]$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def extract_localized_desktop_entry_lines(raw_text: str) -> list[str]:
    localized_lines: list[str] = []
    in_desktop_entry = False

    for raw_line in raw_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "[Desktop Entry]":
            in_desktop_entry = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_desktop_entry:
                break
            continue
        if in_desktop_entry and (stripped.startswith("Name[") or stripped.startswith("Comment[")):
            localized_lines.append(stripped)

    return localized_lines


def parse_desktop_entry(raw_text: str, source_relpath: str) -> EmbeddedDesktopEntry:
    fields: dict[str, str] = {}
    validation_messages: list[str] = []
    exec_tokens: list[str] = []
    in_desktop_entry = False

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "[Desktop Entry]":
            in_desktop_entry = True
            continue
        if stripped.startswith("[") and stripped.endswith("]") and stripped != "[Desktop Entry]":
            if in_desktop_entry:
                break
            continue
        if not in_desktop_entry or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        fields[key] = value

    if "Type" in fields and fields["Type"] != "Application":
        validation_messages.append("Desktop entry type is not Application.")
    if "Exec" not in fields:
        validation_messages.append("Embedded desktop file is missing Exec.")
    else:
        try:
            exec_tokens = shlex.split(fields["Exec"])
        except ValueError as exc:
            validation_messages.append(f"Could not parse Exec: {exc}")
    if "Name" not in fields:
        validation_messages.append("Embedded desktop file is missing Name.")

    return EmbeddedDesktopEntry(
        source_relpath=source_relpath,
        raw_text=raw_text,
        parsed_fields=fields,
        exec_tokens=exec_tokens,
        icon_key=fields.get("Icon"),
        is_valid=not validation_messages,
        validation_messages=validation_messages,
    )


def serialize_exec_tokens(tokens: list[str]) -> str:
    escaped: list[str] = []
    for token in tokens:
        if PLACEHOLDER_RE.match(token):
            escaped.append(token)
        else:
            escaped.append(shlex.quote(token))
    return " ".join(escaped)


def sanitize_value(value: str | None) -> str | None:
    if value is None:
        return None
    return CONTROL_RE.sub("", value).strip() or None


def partition_validation_messages(messages: list[str]) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    for message in messages:
        lowered = message.lower()
        if "warning:" in lowered and "error:" not in lowered:
            warnings.append(message)
        else:
            errors.append(message)
    return warnings, errors


def _split_semi_colon_field(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in value.split(";") if item]


def _bool_field(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.lower()
    if lowered in {"true", "1"}:
        return True
    if lowered in {"false", "0"}:
        return False
    return None


class DesktopEntryService:
    def __init__(
        self,
        tooling: Tooling,
        launcher_command_resolver: Callable[[], list[str] | None] | None = None,
    ) -> None:
        self.tooling = tooling
        self._launcher_command_resolver = launcher_command_resolver or (lambda: None)

    def _resolve_launcher_command(self) -> list[str] | None:
        launcher_command = self._launcher_command_resolver()
        if not launcher_command:
            return None
        return launcher_command

    def _require_launcher_command(self) -> list[str]:
        launcher_command = self._resolve_launcher_command()
        if launcher_command is None:
            raise ValueError(
                "Could not resolve a concrete launcher path for desktop integration."
            )
        return launcher_command

    def rewrite_exec_tokens(
        self,
        entry: EmbeddedDesktopEntry | None,
        extra_args: list[str],
        arg_preset_id: str | None,
    ) -> list[str]:
        base_tokens = list(entry.exec_tokens) if entry and entry.exec_tokens else []
        placeholders = [token for token in base_tokens if PLACEHOLDER_RE.match(token)]
        preserved_args = [token for token in base_tokens[1:] if not PLACEHOLDER_RE.match(token)]
        preset_args = list(PRESET_ARGUMENTS.get(arg_preset_id or "none", ()))
        return [*preserved_args, *preset_args, *extra_args, *placeholders]

    def build_launch_exec_tokens(
        self,
        internal_id: str,
        entry: EmbeddedDesktopEntry | None,
        extra_args: list[str],
        arg_preset_id: str | None,
    ) -> list[str]:
        launcher_command = self._require_launcher_command()
        passthrough_tokens = self.rewrite_exec_tokens(entry, extra_args, arg_preset_id)
        return [*launcher_command, "launch", internal_id, "--desktop", "--", *passthrough_tokens]

    def desktop_entry_needs_migration(self, text: str, internal_id: str) -> bool:
        entry = parse_desktop_entry(text, "managed.desktop")
        launcher_command = self._resolve_launcher_command()
        if launcher_command is None:
            return False
        expected_prefix = [*launcher_command, "launch", internal_id]
        return (
            entry.parsed_fields.get("TryExec") != launcher_command[0]
            or entry.exec_tokens[: len(expected_prefix)] != expected_prefix
            or "--desktop" not in entry.exec_tokens
        )

    def build_desktop_text(
        self,
        internal_id: str,
        inspection: AppImageInspection,
        appimage_path: Path,
        icon_value: str,
        display_name: str,
        comment: str | None,
        extra_args: list[str],
        arg_preset_id: str | None,
    ) -> tuple[str, list[str], str]:
        entry = inspection.desktop_entry
        exec_template = self.build_exec_template_from_entry(
            internal_id,
            entry,
            arg_preset_id=arg_preset_id,
            extra_args=extra_args,
        )
        return self._build_desktop_text_from_entry(
            entry,
            icon_value=icon_value,
            display_name=display_name,
            fallback_name=inspection.detected_name or "AppImage",
            comment=comment,
            fallback_comment=inspection.detected_comment,
            exec_template=exec_template,
        )

    def build_exec_template_from_entry(
        self,
        internal_id: str,
        entry: EmbeddedDesktopEntry | None,
        *,
        arg_preset_id: str | None,
        extra_args: list[str],
    ) -> str:
        launcher_command = self._require_launcher_command()
        passthrough_tokens = self.rewrite_exec_tokens(entry, extra_args, arg_preset_id)
        exec_tokens = [*launcher_command, "launch", internal_id, "--desktop", "--", *passthrough_tokens]
        return serialize_exec_tokens(exec_tokens)

    def build_exec_template_from_record(
        self,
        record: ManagedAppRecord,
        *,
        arg_preset_id: str | None,
        extra_args: list[str],
    ) -> str:
        passthrough_tokens = self._preserved_passthrough_tokens(record)
        placeholders = self._trailing_placeholders(record.desktop_exec_template)
        launcher_command = self._require_launcher_command()
        exec_tokens = [
            *launcher_command,
            "launch",
            record.internal_id,
            "--desktop",
            "--",
            *passthrough_tokens,
            *list(PRESET_ARGUMENTS.get(arg_preset_id or "none", ())),
            *extra_args,
            *placeholders,
        ]
        return serialize_exec_tokens(exec_tokens)

    def rewrite_managed_desktop_text(
        self,
        record: ManagedAppRecord,
        current_desktop_text: str,
        *,
        display_name: str,
        comment: str | None,
        arg_preset_id: str | None,
        extra_args: list[str],
    ) -> tuple[str, list[str], str]:
        current_entry = parse_desktop_entry(current_desktop_text, "managed.desktop")
        exec_template = self.build_exec_template_from_record(
            record,
            arg_preset_id=arg_preset_id,
            extra_args=extra_args,
        )
        return self._build_desktop_text_from_entry(
            current_entry,
            icon_value=current_entry.parsed_fields.get("Icon") or record.managed_icon_path or "application-x-executable",
            display_name=display_name,
            fallback_name=record.display_name,
            comment=comment,
            fallback_comment=record.comment,
            exec_template=exec_template,
        )

    def _build_desktop_text_from_entry(
        self,
        entry: EmbeddedDesktopEntry | None,
        *,
        icon_value: str,
        display_name: str,
        fallback_name: str,
        comment: str | None,
        fallback_comment: str | None,
        exec_template: str,
    ) -> tuple[str, list[str], str]:
        validation_messages: list[str] = []
        fields = OrderedDict()
        localized_lines: list[str] = []

        if entry and entry.parsed_fields:
            localized_lines = extract_localized_desktop_entry_lines(entry.raw_text)
            for key in (
                "Type",
                "Name",
                "Comment",
                "Categories",
                "StartupWMClass",
                "MimeType",
                "Terminal",
                "StartupNotify",
            ):
                if key in entry.parsed_fields:
                    fields[key] = entry.parsed_fields[key]

        fields["Type"] = "Application"
        fields["Name"] = sanitize_value(display_name) or fallback_name or "AppImage"
        sanitized_comment = sanitize_value(comment) if comment is not None else None
        if sanitized_comment is not None:
            fields["Comment"] = sanitized_comment
        elif "Comment" not in fields and fallback_comment:
            fields["Comment"] = sanitize_value(fallback_comment) or ""
        if sanitize_value(fields.get("Comment")) == fields["Name"]:
            fields.pop("Comment", None)
        launcher_command = self._require_launcher_command()
        fields["Exec"] = exec_template
        fields["TryExec"] = launcher_command[0]
        fields["Icon"] = icon_value
        if "Terminal" not in fields:
            fields["Terminal"] = "false"

        ordered_keys = [
            "Type",
            "Name",
            "Comment",
            "Exec",
            "TryExec",
            "Icon",
            "Terminal",
            "StartupNotify",
            "StartupWMClass",
            "Categories",
            "MimeType",
        ]
        lines = ["[Desktop Entry]"]
        seen = set()
        for key in ordered_keys:
            if key in fields and fields[key] != "":
                seen.add(key)
                lines.append(f"{key}={fields[key]}")
        for line in localized_lines:
            lines.append(line)
        for key, value in fields.items():
            if key not in seen and value != "":
                lines.append(f"{key}={value}")

        desktop_text = "\n".join(lines) + "\n"
        validation_messages.extend(self.validate_text(desktop_text))
        return desktop_text, validation_messages, exec_template

    def inspection_from_managed_record(self, record: ManagedAppRecord, desktop_text: str) -> AppImageInspection:
        entry = parse_desktop_entry(desktop_text, "managed.desktop")
        return AppImageInspection(
            source_path=Path(record.managed_appimage_path),
            is_appimage=True,
            appimage_type=record.appimage_type if record.appimage_type in {"type1", "type2", "unknown"} else "unknown",
            is_executable=Path(record.managed_appimage_path).exists(),
            detected_name=record.display_name,
            detected_comment=record.comment,
            detected_version=record.version,
            appstream_id=record.appstream_id,
            embedded_desktop_filename=record.embedded_desktop_basename,
            desktop_entry=entry,
            chosen_icon_candidate=None,
            startup_wm_class=entry.parsed_fields.get("StartupWMClass"),
            mime_types=_split_semi_colon_field(entry.parsed_fields.get("MimeType")),
            categories=_split_semi_colon_field(entry.parsed_fields.get("Categories")),
            terminal=_bool_field(entry.parsed_fields.get("Terminal")),
            startup_notify=_bool_field(entry.parsed_fields.get("StartupNotify")),
            exec_placeholders=[token for token in entry.exec_tokens if PLACEHOLDER_RE.match(token)],
            warnings=[],
            errors=[],
            extracted_dir=None,
        )

    def _trailing_placeholders(self, exec_template: str) -> list[str]:
        try:
            tokens = shlex.split(exec_template)
        except ValueError:
            return []
        if "--" not in tokens:
            return []
        passthrough = tokens[tokens.index("--") + 1 :]
        placeholders: list[str] = []
        while passthrough and PLACEHOLDER_RE.match(passthrough[-1]):
            placeholders.insert(0, passthrough.pop())
        return placeholders

    def _preserved_passthrough_tokens(self, record: ManagedAppRecord) -> list[str]:
        try:
            tokens = shlex.split(record.desktop_exec_template)
        except ValueError as exc:
            raise ValueError(f"Could not parse the saved launch command: {exc}") from exc
        if "--" not in tokens:
            raise ValueError("The saved launch command is missing the expected passthrough separator.")
        passthrough = tokens[tokens.index("--") + 1 :]
        while passthrough and PLACEHOLDER_RE.match(passthrough[-1]):
            passthrough.pop()
        if record.extra_args:
            if passthrough[-len(record.extra_args) :] != record.extra_args:
                raise ValueError("The saved launch arguments could not be reconciled with the current metadata.")
            del passthrough[-len(record.extra_args) :]
        preset_args = list(PRESET_ARGUMENTS.get(record.arg_preset_id or "none", ()))
        if preset_args:
            if passthrough[-len(preset_args) :] != preset_args:
                raise ValueError("The saved launch preset could not be reconciled with the current metadata.")
            del passthrough[-len(preset_args) :]
        return passthrough

    def validate_text(self, text: str) -> list[str]:
        validator = self.tooling.tools.desktop_file_validate
        if not validator:
            return []
        with NamedTemporaryFile("w", encoding="utf-8", suffix=".desktop", delete=False) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        try:
            result = self.tooling.run([validator, str(temp_path)])
        finally:
            temp_path.unlink(missing_ok=True)
        messages = []
        if result.stdout.strip():
            messages.append(result.stdout.strip())
        if result.stderr.strip():
            messages.append(result.stderr.strip())
        return messages
