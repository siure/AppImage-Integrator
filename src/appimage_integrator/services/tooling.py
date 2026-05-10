from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from appimage_integrator.services.cancellation import CancelCallback, OperationCancelled, raise_if_cancelled

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
        should_cancel: CancelCallback | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.logger.info("Running command: %s", " ".join(args))
        raise_if_cancelled(should_cancel)
        stdout_pipe = subprocess.PIPE if capture_output else None
        stderr_pipe = subprocess.PIPE if capture_output else None
        started_at = time.monotonic()
        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=stdout_pipe,
                stderr=stderr_pipe,
                text=True,
            )
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if should_cancel is not None and should_cancel():
                        process.kill()
                        process.communicate()
                        raise OperationCancelled()
                    if timeout is not None and time.monotonic() - started_at >= timeout:
                        process.kill()
                        stdout, stderr = process.communicate()
                        self.logger.info("Command timed out after %s seconds", timeout)
                        return subprocess.CompletedProcess(
                            args,
                            124,
                            self._coerce_output(stdout),
                            self._coerce_output(stderr) or f"Command timed out after {timeout} seconds.",
                        )
        except OSError as exc:
            self.logger.info("Command failed before execution: %s", exc)
            return subprocess.CompletedProcess(args, 127, "", str(exc))
        result = subprocess.CompletedProcess(
            args,
            process.returncode,
            self._coerce_output(stdout),
            self._coerce_output(stderr),
        )
        self.logger.info("Command exited %s", result.returncode)
        if result.stdout:
            self.logger.info("stdout: %s", self._preview_output(result.stdout))
        if result.stderr:
            self.logger.info("stderr: %s", self._preview_output(result.stderr))
        if check and result.returncode:
            raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
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
