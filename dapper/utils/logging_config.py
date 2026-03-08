from __future__ import annotations

import logging
from pathlib import Path
from typing import TextIO

_MANAGED_HANDLER_ATTR = "_dapper_managed_handler"


def _mark_managed(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _MANAGED_HANDLER_ATTR, True)
    return handler


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if not getattr(handler, _MANAGED_HANDLER_ATTR, False):
            continue
        logger.removeHandler(handler)
        handler.close()


def configure_root_console_logging(
    level: int,
    *,
    stream: TextIO | None = None,
    format_string: str,
    datefmt: str | None = None,
) -> logging.Logger:
    """Configure a single managed console handler on the root logger."""

    root_logger = logging.getLogger()
    _remove_managed_handlers(root_logger)

    handler = _mark_managed(logging.StreamHandler(stream))
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(format_string, datefmt=datefmt))

    root_logger.addHandler(handler)
    root_logger.setLevel(level)
    return root_logger


def configure_package_file_logging(
    package_name: str,
    level: int,
    *,
    file_path: str,
    format_string: str,
    datefmt: str | None = None,
    truncate: bool = False,
) -> logging.Logger:
    """Configure a single managed file handler on a package logger."""

    if truncate:
        Path(file_path).write_text("", encoding="utf-8")

    package_logger = logging.getLogger(package_name)
    _remove_managed_handlers(package_logger)

    handler = _mark_managed(
        logging.FileHandler(file_path, mode="a", encoding="utf-8", delay=False)
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(format_string, datefmt=datefmt))

    package_logger.addHandler(handler)
    package_logger.setLevel(level)
    package_logger.propagate = False
    return package_logger
