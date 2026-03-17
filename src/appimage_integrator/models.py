from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from appimage_integrator.config import SCHEMA_VERSION


ValidationStatus = Literal["ok", "warning", "error"]
AppImageType = Literal["type1", "type2", "unknown"]
UpdateMatchKind = Literal["identity", "filename"]
UpdateSourceDirKind = Literal["source_dir", "downloads", "managed_payload_dir"]


@dataclass(frozen=True)
class IconCandidate:
    source_path: Path
    relpath: str
    kind: Literal["svg", "png", "xpm", "named"]
    width: int | None = None
    height: int | None = None
    score: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_path"] = str(self.source_path)
        return data


@dataclass(frozen=True)
class EmbeddedDesktopEntry:
    source_relpath: str
    raw_text: str
    parsed_fields: dict[str, str]
    exec_tokens: list[str]
    icon_key: str | None
    is_valid: bool
    validation_messages: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AppImageInspection:
    source_path: Path
    is_appimage: bool
    appimage_type: AppImageType
    is_executable: bool
    detected_name: str | None
    detected_comment: str | None
    detected_version: str | None
    appstream_id: str | None
    embedded_desktop_filename: str | None
    desktop_entry: EmbeddedDesktopEntry | None
    chosen_icon_candidate: IconCandidate | None
    startup_wm_class: str | None
    mime_types: list[str]
    categories: list[str]
    terminal: bool | None
    startup_notify: bool | None
    exec_placeholders: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    extracted_dir: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_path"] = str(self.source_path)
        data["extracted_dir"] = str(self.extracted_dir) if self.extracted_dir else None
        if self.chosen_icon_candidate:
            data["chosen_icon_candidate"] = self.chosen_icon_candidate.to_dict()
        if self.desktop_entry:
            data["desktop_entry"] = self.desktop_entry.to_dict()
        return data


@dataclass(frozen=True)
class InstallRequest:
    source_path: Path
    display_name_override: str | None
    comment_override: str | None
    extra_args: list[str]
    arg_preset_id: str | None
    allow_update: bool
    allow_reinstall: bool


@dataclass(frozen=True)
class ManagedRecordUpdateRequest:
    internal_id: str
    display_name: str
    comment: str | None
    arg_preset_id: str | None
    extra_args: list[str]


@dataclass(frozen=True)
class ManagedAppRecord:
    internal_id: str
    display_name: str
    comment: str | None
    version: str | None
    appstream_id: str | None
    embedded_desktop_basename: str | None
    identity_fingerprint: str
    managed_appimage_path: str
    managed_desktop_path: str
    managed_icon_path: str | None
    source_file_name_at_install: str
    source_path_last_seen: str
    desktop_exec_template: str
    extra_args: list[str]
    arg_preset_id: str | None
    installed_at: str
    updated_at: str
    appimage_type: str
    icon_managed_by_app: bool
    managed_files: list[str]
    last_validation_status: ValidationStatus
    last_validation_messages: list[str]
    managed_payload_path: str | None = None
    managed_payload_dir: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ManagedAppRecord":
        data = dict(payload)
        data.setdefault("managed_payload_path", None)
        data.setdefault("managed_payload_dir", None)
        data.setdefault("managed_files", [])
        data.setdefault("schema_version", SCHEMA_VERSION)
        return cls(**data)


@dataclass(frozen=True)
class RepairReport:
    internal_id: str
    issues: list[str]
    actions_taken: list[str]
    success: bool


@dataclass(frozen=True)
class InstallResult:
    mode: Literal["install", "update", "reinstall", "repair"]
    record: ManagedAppRecord
    warnings: list[str]
    validation_messages: list[str]


@dataclass(frozen=True)
class IdentityResolution:
    internal_id: str
    identity_fingerprint: str
    basis: str


@dataclass(frozen=True)
class UpdateCandidate:
    path: Path
    detected_version: str | None
    is_executable: bool
    match_kind: UpdateMatchKind
    match_score: int
    identity_internal_id: str | None
    identity_fingerprint: str | None
    detected_name: str | None
    source_dir_kind: UpdateSourceDirKind
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass(frozen=True)
class UpdateDiscoveryResult:
    record: ManagedAppRecord
    searched_directories: list[Path]
    higher_version_candidates: list[UpdateCandidate]
    same_or_unknown_candidates: list[UpdateCandidate]
    skipped_paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.to_dict(),
            "searched_directories": [str(path) for path in self.searched_directories],
            "higher_version_candidates": [candidate.to_dict() for candidate in self.higher_version_candidates],
            "same_or_unknown_candidates": [candidate.to_dict() for candidate in self.same_or_unknown_candidates],
            "skipped_paths": list(self.skipped_paths),
        }
