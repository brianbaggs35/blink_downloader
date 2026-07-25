"""Logging configuration renders JSON in production style, console in dev."""

import structlog

from app.logs import configure_logging, get_logger
from tests.conftest import PlainSettings


def _renderer() -> object:
    return structlog.get_config()["processors"][-1]


def test_console_renderer_in_development() -> None:
    configure_logging(PlainSettings(log_json=False))
    assert isinstance(_renderer(), structlog.dev.ConsoleRenderer)


def test_json_renderer_when_requested() -> None:
    configure_logging(PlainSettings(log_json=True))
    assert isinstance(_renderer(), structlog.processors.JSONRenderer)


def test_unknown_level_falls_back_to_info() -> None:
    configure_logging(PlainSettings(log_level="NOPE"))
    logger = get_logger("test")
    logger.info("still works")


def test_get_logger_returns_bound_logger() -> None:
    configure_logging(PlainSettings())
    assert get_logger("x") is not None
