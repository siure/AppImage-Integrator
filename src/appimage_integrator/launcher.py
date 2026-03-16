from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import sys
from pathlib import Path

from appimage_integrator.assets import APP_DESKTOP_ENTRY_PATH
from appimage_integrator.models import ManagedAppRecord
from appimage_integrator.paths import AppPaths
from appimage_integrator.services.desktop_entry import serialize_exec_tokens


DEFAULT_LAUNCHER_COMMAND = "appimage-integrator"
_DESKTOP_PLACEHOLDER_RE = re.compile(r"^%[A-Za-z]$")


def current_appimage_path() -> Path | None:
    value = os.environ.get("APPIMAGE")
    if not value:
        return None
    return Path(value).expanduser().resolve(strict=False)


def resolve_current_launcher_executable() -> Path | None:
    appimage_path = current_appimage_path()
    if appimage_path is not None and appimage_path.exists():
        return appimage_path

    argv0 = sys.argv[0].strip() if sys.argv and sys.argv[0] else ""
    if argv0:
        argv_path = Path(argv0).expanduser()
        if argv_path.is_absolute() and argv_path.exists():
            return argv_path.resolve(strict=False)
        discovered = shutil.which(argv0)
        if discovered:
            return Path(discovered).resolve(strict=False)

    discovered = shutil.which(DEFAULT_LAUNCHER_COMMAND)
    if discovered:
        return Path(discovered).resolve(strict=False)
    return None


def resolve_launcher_command(paths: AppPaths) -> list[str] | None:
    if paths.self_command_path.exists():
        return [str(paths.self_command_path)]
    if paths.self_appimage_path.exists():
        return [str(paths.self_appimage_path)]

    current = resolve_current_launcher_executable()
    if current is not None:
        return [str(current)]
    return None


def build_app_desktop_text(launcher_command: list[str]) -> str:
    raw_text = APP_DESKTOP_ENTRY_PATH.read_text(encoding="utf-8")
    lines: list[str] = []
    saw_tryexec = False
    try_exec = launcher_command[0]
    exec_line = f"Exec={serialize_exec_tokens(launcher_command)}"
    tryexec_line = f"TryExec={try_exec}"

    for line in raw_text.splitlines():
        if line.startswith("Exec="):
            lines.append(exec_line)
            continue
        if line.startswith("TryExec="):
            lines.append(tryexec_line)
            saw_tryexec = True
            continue
        lines.append(line)

    if not saw_tryexec:
        insert_at = 0
        for index, line in enumerate(lines):
            if line.startswith("Exec="):
                insert_at = index + 1
                break
        lines.insert(insert_at, tryexec_line)

    return "\n".join(lines) + "\n"


def launch_tokens_from_exec_template(exec_template: str) -> list[str]:
    try:
        tokens = shlex.split(exec_template)
    except ValueError:
        return []
    if "--" not in tokens:
        return []
    passthrough = tokens[tokens.index("--") + 1 :]
    return [token for token in passthrough if not _DESKTOP_PLACEHOLDER_RE.match(token)]


def build_managed_app_launch_command(
    record: ManagedAppRecord,
    launch_args: list[str] | None = None,
) -> list[str]:
    return [
        record.managed_appimage_path,
        *launch_tokens_from_exec_template(record.desktop_exec_template),
        *(launch_args or []),
    ]


def install_self_command(paths: AppPaths, appimage_path: Path) -> None:
    paths.local_bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper_text = (
        "#!/bin/sh\n"
        f'exec "{appimage_path}" "$@"\n'
    )
    paths.self_command_path.write_text(wrapper_text, encoding="utf-8")
    current_mode = paths.self_command_path.stat().st_mode
    paths.self_command_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_self_appimage(paths: AppPaths, source_appimage: Path) -> Path:
    paths.applications_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_appimage, paths.self_appimage_path)
    current_mode = paths.self_appimage_path.stat().st_mode
    paths.self_appimage_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return paths.self_appimage_path
