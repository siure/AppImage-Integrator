# AGENTS.md

## Scope

These instructions apply to the repository root.

## Preferred interface

Use the CLI, not the GTK GUI.

- Prefer `python -m appimage_integrator ...` or the installed `appimage-integrator ...` entrypoint.
- Do not use the GUI in automation, CI, or headless environments.
- If `gi` / GTK dependencies are missing, continue with the CLI workflow rather than trying to launch the UI.

## Setup

Typical local setup:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run without installing:

```bash
PYTHONPATH=src python3 -m appimage_integrator presets
```

## CLI workflow

Useful commands:

```bash
PYTHONPATH=src python3 -m appimage_integrator inspect /path/to/App.AppImage --trust
PYTHONPATH=src python3 -m appimage_integrator install /path/to/App.AppImage --trust --json
PYTHONPATH=src python3 -m appimage_integrator list --json
PYTHONPATH=src python3 -m appimage_integrator details <internal-id> --json
PYTHONPATH=src python3 -m appimage_integrator repair <internal-id> --json
PYTHONPATH=src python3 -m appimage_integrator reinstall <internal-id> --trust --json
PYTHONPATH=src python3 -m appimage_integrator update <internal-id>
PYTHONPATH=src python3 -m appimage_integrator uninstall <internal-id>
PYTHONPATH=src python3 -m appimage_integrator presets
```

Agent guidance:

- Prefer `--json` whenever a command supports it.
- Use `--trust` when the source AppImage may not have its execute bit set.
- Use internal IDs from `list --json` instead of display names when scripting follow-up commands.
- `gui` is only for manual human testing.

## Validation

Before closing work, run:

```bash
pytest
ruff check src tests
```

## Repository notes

- Treat `src/` and `tests/` as the source of truth.
- `AppDir/`, `appimage-build/`, `build/`, and `dist/` contain generated or packaged artifacts; do not audit or edit them unless the task is explicitly about packaging.
- Use `rg` for searching.

## Known caveats

- The current update discovery path inspects candidate AppImages by executing them. Be careful when running `update` during automated work against untrusted files.
- Prefer narrow, explicit test fixtures when exercising install/update flows.
