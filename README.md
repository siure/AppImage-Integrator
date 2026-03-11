# AppImage Integrator

`AppImage Integrator` is a Python + PyGObject desktop application for managing
user-local AppImage integrations on Linux. It inspects embedded metadata,
extracts icons, writes `.desktop` launchers, and tracks installed AppImages for
update, repair, reinstall, and uninstall flows.

## Development

Install the system GUI dependencies first. On Fedora:

```bash
sudo dnf install python3-gobject gtk4 libadwaita
```

Create a virtual environment and install the package in editable mode:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run the application:

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

List the supported launch argument presets:

```bash
appimage-integrator presets
```

Run directly from the repository without installing:

```bash
PYTHONPATH=src python3 -m appimage_integrator
```

Run tests:

```bash
pytest
```
