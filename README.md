# AppImage Integrator

AppImage Integrator is a Linux desktop tool for creating and maintaining local
AppImage integrations. It inspects AppImages, extracts metadata and icons,
creates `.desktop` launchers, and keeps installed entries repairable and
updatable.

## Features

- Install AppImages into a managed library under `~/Applications`
- Generate and validate local `.desktop` launchers
- Extract embedded icons and metadata from AppImages
- Track installed entries for repair, reinstall, and update flows
- Use the same backend from the GUI and CLI

## Requirements

- Linux
- Python 3.10+
- GTK 4 and Libadwaita runtime packages
- `python3-gobject` available in the Python environment

On Ubuntu/Debian:

On Fedora:

```bash
sudo dnf install python3-gobject gtk4 libadwaita
```

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
```

On Arch Linux:

```bash
sudo pacman -S python-gobject gtk4 libadwaita
```

## Development

Create a virtual environment with access to system site-packages, then install
the project in editable mode:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

If you prefer a `requirements.txt` workflow, use:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Both approaches install the project in editable mode with the development tools.
They do not replace the required system packages such as GTK 4, Libadwaita, and
`python3-gobject`.

Run the GUI:

```bash
appimage-integrator
```

Run the CLI:

```bash
appimage-integrator inspect /path/to/App.AppImage --trust
appimage-integrator install /path/to/App.AppImage --trust --preset disable_gpu
appimage-integrator list
appimage-integrator details <internal-id>
appimage-integrator repair <internal-id>
appimage-integrator reinstall <internal-id>
appimage-integrator uninstall <internal-id>
```

Run from the repository without installing:

```bash
PYTHONPATH=src python3 -m appimage_integrator
```

Run checks:

```bash
pytest
ruff check .
```

## Releases

Pushing a tag in the form `vX.Y.Z` now builds an AppImage on GitHub Actions and
publishes it to the matching GitHub Release.

The workflow expects the tag version to match `project.version` in
`pyproject.toml`. A typical release flow is:

```bash
git commit -am "Release v0.1.0"
git tag v0.1.0
git push origin main --tags
```

You can also trigger the release workflow manually from the Actions tab to
produce a downloadable AppImage artifact without publishing a GitHub Release.

## Repository Layout

```text
src/appimage_integrator/   Application package
tests/                    Automated tests
tests/fixtures/           Small committed test fixtures and local fixture notes
.github/workflows/        CI configuration
```

Local AppImage binaries used for manual testing should stay outside version
control.
