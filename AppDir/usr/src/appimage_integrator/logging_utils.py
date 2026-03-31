from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from appimage_integrator.paths import AppPaths


def configure_logging(paths: AppPaths, *, enable_console: bool = True) -> logging.Logger:
    paths.ensure_directories()
    logger = logging.getLogger("appimage_integrator")

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    file_handler = next(
        (handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)),
        None,
    )
    if file_handler is None:
        file_handler = RotatingFileHandler(
            paths.log_file,
            maxBytes=512 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    stream_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler)
    ]
    if enable_console and not stream_handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    if not enable_console:
        for handler in stream_handlers:
            logger.removeHandler(handler)
    return logger
