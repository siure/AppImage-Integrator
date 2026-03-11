from __future__ import annotations

import re
import shlex
from collections import OrderedDict
from pathlib import Path
from tempfile import NamedTemporaryFile

from appimage_integrator.config import PRESET_ARGUMENTS
from appimage_integrator.models import AppImageInspection, EmbeddedDesktopEntry
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


class DesktopEntryService:
    def __init__(self, tooling: Tooling) -> None:
        self.tooling = tooling

    def rewrite_exec_tokens(
        self,
        entry: EmbeddedDesktopEntry | None,
        appimage_path: Path,
        extra_args: list[str],
        arg_preset_id: str | None,
    ) -> list[str]:
        base_tokens = list(entry.exec_tokens) if entry and entry.exec_tokens else []
        placeholders = [token for token in base_tokens if PLACEHOLDER_RE.match(token)]
        preserved_args = [token for token in base_tokens[1:] if not PLACEHOLDER_RE.match(token)]
        preset_args = list(PRESET_ARGUMENTS.get(arg_preset_id or "none", ()))
        rewritten = [str(appimage_path), *preserved_args, *preset_args, *extra_args, *placeholders]
        return rewritten

    def build_desktop_text(
        self,
        inspection: AppImageInspection,
        appimage_path: Path,
        icon_value: str,
        display_name: str,
        comment: str | None,
        extra_args: list[str],
        arg_preset_id: str | None,
    ) -> tuple[str, list[str], str]:
        validation_messages: list[str] = []
        fields = OrderedDict()
        entry = inspection.desktop_entry
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
        fields["Name"] = sanitize_value(display_name) or inspection.detected_name or "AppImage"
        sanitized_comment = sanitize_value(comment) if comment is not None else None
        if sanitized_comment is not None:
            fields["Comment"] = sanitized_comment
        elif "Comment" not in fields and inspection.detected_comment:
            fields["Comment"] = sanitize_value(inspection.detected_comment) or ""
        exec_tokens = self.rewrite_exec_tokens(entry, appimage_path, extra_args, arg_preset_id)
        fields["Exec"] = serialize_exec_tokens(exec_tokens)
        fields["TryExec"] = str(appimage_path)
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
        return desktop_text, validation_messages, fields["Exec"]

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
