from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolAvailability:
    desktop_file_validate: str | None
    appstreamcli: str | None
    update_desktop_database: str | None
    gtk_update_icon_cache: str | None
    unsquashfs: str | None
    file_cmd: str | None
    sha256sum: str | None


class Tooling:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.tools = ToolAvailability(
            desktop_file_validate=shutil.which("desktop-file-validate"),
            appstreamcli=shutil.which("appstreamcli"),
            update_desktop_database=shutil.which("update-desktop-database"),
            gtk_update_icon_cache=shutil.which("gtk-update-icon-cache"),
            unsquashfs=shutil.which("unsquashfs"),
            file_cmd=shutil.which("file"),
            sha256sum=shutil.which("sha256sum"),
        )

    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        check: bool = False,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.logger.info("Running command: %s", " ".join(args))
        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                check=check,
                capture_output=capture_output,
                text=True,
            )
        except OSError as exc:
            self.logger.info("Command failed before execution: %s", exc)
            return subprocess.CompletedProcess(args, 127, "", str(exc))
        self.logger.info("Command exited %s", result.returncode)
        if result.stdout:
            self.logger.info("stdout: %s", self._preview_output(result.stdout))
        if result.stderr:
            self.logger.info("stderr: %s", self._preview_output(result.stderr))
        return result

    def _preview_output(self, output: str, limit: int = 2000) -> str:
        text = output.strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit]}... [truncated {len(text) - limit} chars]"
