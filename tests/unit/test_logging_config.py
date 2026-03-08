from __future__ import annotations

import io
import logging

from dapper.utils.logging_config import configure_package_file_logging
from dapper.utils.logging_config import configure_root_console_logging


def test_configure_root_console_logging_replaces_managed_handlers_only() -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    unmanaged_handler = logging.NullHandler()
    root_logger.addHandler(unmanaged_handler)

    try:
        first_stream = io.StringIO()
        second_stream = io.StringIO()

        configure_root_console_logging(
            logging.INFO,
            stream=first_stream,
            format_string="%(levelname)s:%(message)s",
        )
        configure_root_console_logging(
            logging.DEBUG,
            stream=second_stream,
            format_string="%(levelname)s:%(message)s",
        )

        managed_handlers = [
            handler
            for handler in root_logger.handlers
            if getattr(handler, "_dapper_managed_handler", False)
        ]
        assert len(managed_handlers) == 1
        assert root_logger.level == logging.DEBUG

        root_logger.debug("hello")
        assert "DEBUG:hello" in second_stream.getvalue()
        assert first_stream.getvalue() == ""
        assert unmanaged_handler in root_logger.handlers
    finally:
        for handler in list(root_logger.handlers):
            if handler in original_handlers or handler is unmanaged_handler:
                continue
            root_logger.removeHandler(handler)
            handler.close()
        root_logger.removeHandler(unmanaged_handler)


def test_configure_package_file_logging_replaces_managed_handlers_only(tmp_path) -> None:
    package_logger = logging.getLogger("dapper")
    original_handlers = list(package_logger.handlers)
    original_propagate = package_logger.propagate
    unmanaged_handler = logging.NullHandler()
    package_logger.addHandler(unmanaged_handler)
    log_path = tmp_path / "dapper.log"
    log_path.write_text("stale\n", encoding="utf-8")

    try:
        configure_package_file_logging(
            "dapper",
            logging.INFO,
            file_path=str(log_path),
            format_string="%(levelname)s:%(message)s",
            truncate=True,
        )
        configure_package_file_logging(
            "dapper",
            logging.DEBUG,
            file_path=str(log_path),
            format_string="%(levelname)s:%(message)s",
            truncate=False,
        )

        managed_handlers = [
            handler
            for handler in package_logger.handlers
            if getattr(handler, "_dapper_managed_handler", False)
        ]
        assert len(managed_handlers) == 1
        assert package_logger.level == logging.DEBUG
        assert package_logger.propagate is False

        package_logger.debug("hello")
        contents = log_path.read_text(encoding="utf-8")
        assert "stale" not in contents
        assert "DEBUG:hello" in contents
        assert unmanaged_handler in package_logger.handlers
    finally:
        for handler in list(package_logger.handlers):
            if handler in original_handlers or handler is unmanaged_handler:
                continue
            package_logger.removeHandler(handler)
            handler.close()
        package_logger.propagate = original_propagate
        package_logger.removeHandler(unmanaged_handler)
