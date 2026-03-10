from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from appimage_integrator.paths import AppPaths


def configure_logging(paths: AppPaths) -> logging.Logger:
    paths.ensure_directories()
    logger = logging.getLogger("appimage_integrator")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        paths.log_file,
        maxBytes=512 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger
