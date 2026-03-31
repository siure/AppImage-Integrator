from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from appimage_integrator.config import APP_DATA_DIR_NAME, APP_ID
from appimage_integrator.services.id_resolver import resolve_internal_id_from_appstream_id


@dataclass(frozen=True)
class AppPaths:
    home: Path
    applications_dir: Path
    managed_payloads_root: Path
    desktop_entries_dir: Path
    icons_dir: Path
    app_data_dir: Path
    metadata_apps_dir: Path
    metadata_index_path: Path
    logs_dir: Path
    log_file: Path
    cache_extract_dir: Path

    @classmethod
    def default(cls) -> "AppPaths":
        home = Path.home()
        data_home = Path.home() / ".local" / "share"
        cache_home = Path.home() / ".cache"
        app_data_dir = data_home / APP_DATA_DIR_NAME
        return cls(
            home=home,
            applications_dir=home / "Applications",
            managed_payloads_root=home / "Applications" / ".appimage-integrator",
            desktop_entries_dir=data_home / "applications",
            icons_dir=data_home / "icons" / "hicolor" / "256x256" / "apps",
            app_data_dir=app_data_dir,
            metadata_apps_dir=app_data_dir / "apps",
            metadata_index_path=app_data_dir / "index.json",
            logs_dir=app_data_dir / "logs",
            log_file=app_data_dir / "logs" / "app.log",
            cache_extract_dir=cache_home / APP_DATA_DIR_NAME / "extract",
        )

    def ensure_directories(self) -> None:
        for path in (
            self.applications_dir,
            self.managed_payloads_root,
            self.desktop_entries_dir,
            self.icons_dir,
            self.metadata_apps_dir,
            self.logs_dir,
            self.cache_extract_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def local_bin_dir(self) -> Path:
        return self.home / ".local" / "bin"

    @property
    def self_command_path(self) -> Path:
        return self.local_bin_dir / "appimage-integrator"

    @property
    def self_appimage_path(self) -> Path:
        return self.applications_dir / "appimage-integrator.AppImage"

    @property
    def self_desktop_basename(self) -> str:
        return f"{APP_ID}.desktop"

    @property
    def self_desktop_entry_path(self) -> Path:
        return self.desktop_entries_dir / self.self_desktop_basename

    @property
    def legacy_self_desktop_entry_path(self) -> Path:
        return self.desktop_entries_dir / f"{resolve_internal_id_from_appstream_id(APP_ID)}.desktop"

    @property
    def self_integration_state_path(self) -> Path:
        return self.app_data_dir / "self-integration-state"

    @property
    def self_icon_path(self) -> Path:
        return (
            self.home
            / ".local"
            / "share"
            / "icons"
            / "hicolor"
            / "512x512"
            / "apps"
            / f"{APP_ID}.png"
        )
