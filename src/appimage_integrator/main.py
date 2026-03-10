from __future__ import annotations

def main() -> int:
    try:
        from appimage_integrator.app import AppImageIntegratorApplication
    except ModuleNotFoundError as exc:
        if exc.name == "gi":
            raise SystemExit(
                "PyGObject is not available in this Python interpreter.\n"
                "On Fedora install: sudo dnf install python3-gobject gtk4 libadwaita\n"
                "If you are using a virtual environment, either use the system Python or create a venv with access to system site-packages."
            ) from exc
        raise

    app = AppImageIntegratorApplication()
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
