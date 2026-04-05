from __future__ import annotations

import logging

from src.platform.web.settings import get_web_settings


LOGGER_NAME = "goldenshare.web"


def configure_web_logging() -> logging.Logger:
    settings = get_web_settings()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, settings.web_log_level.upper(), logging.INFO))
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=getattr(logging, settings.web_log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    return logger


def get_web_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
