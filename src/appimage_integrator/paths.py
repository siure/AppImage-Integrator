from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from appimage_integrator.config import APP_DATA_DIR_NAME


@dataclass(frozen=True)
class AppPaths:
    home: Path
    applications_dir: Path
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
            self.desktop_entries_dir,
            self.icons_dir,
            self.metadata_apps_dir,
            self.logs_dir,
            self.cache_extract_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
