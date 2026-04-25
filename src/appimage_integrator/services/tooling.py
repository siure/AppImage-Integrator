from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
MAX_CAPTURED_OUTPUT_BYTES = 2_000_000


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
        timeout: float | None = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        self.logger.info("Running command: %s", " ".join(args))
        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                check=check,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
            )
        except OSError as exc:
            self.logger.info("Command failed before execution: %s", exc)
            return subprocess.CompletedProcess(args, 127, "", str(exc))
        except subprocess.TimeoutExpired as exc:
            self.logger.info("Command timed out after %s seconds", exc.timeout)
            return subprocess.CompletedProcess(
                args,
                124,
                self._coerce_output(exc.stdout),
                self._coerce_output(exc.stderr) or f"Command timed out after {exc.timeout} seconds.",
            )
        result = subprocess.CompletedProcess(
            result.args,
            result.returncode,
            self._limit_output(result.stdout),
            self._limit_output(result.stderr),
        )
        self.logger.info("Command exited %s", result.returncode)
        if result.stdout:
            self.logger.info("stdout: %s", self._preview_output(result.stdout))
        if result.stderr:
            self.logger.info("stderr: %s", self._preview_output(result.stderr))
        return result

    def _coerce_output(self, output: str | bytes | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return self._limit_output(output)

    def _limit_output(self, output: str | None) -> str:
        if output is None:
            return ""
        encoded = output.encode("utf-8", errors="replace")
        if len(encoded) <= MAX_CAPTURED_OUTPUT_BYTES:
            return output
        trimmed = encoded[:MAX_CAPTURED_OUTPUT_BYTES].decode("utf-8", errors="replace")
        return f"{trimmed}\n[truncated {len(encoded) - MAX_CAPTURED_OUTPUT_BYTES} bytes]"

    def _preview_output(self, output: str, limit: int = 2000) -> str:
        text = output.strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit]}... [truncated {len(text) - limit} chars]"
