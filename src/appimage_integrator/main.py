from __future__ import annotations

import sys

from appimage_integrator.cli import build_parser, run_cli


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        parser = build_parser()
        args = parser.parse_args(argv)
        if args.command != "gui":
            from appimage_integrator.bootstrap import build_service_container

            services = build_service_container(enable_console_logging=False)
            return run_cli(args, services, sys.stdout, sys.stderr, sys.stdin)
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
