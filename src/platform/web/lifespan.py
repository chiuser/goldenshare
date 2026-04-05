from __future__ import annotations

from contextlib import asynccontextmanager

from src.platform.web.logging import configure_web_logging, get_web_logger
from src.platform.web.settings import get_web_settings


@asynccontextmanager
async def web_lifespan(_app):  # type: ignore[no-untyped-def]
    configure_web_logging()
    settings = get_web_settings()
    logger = get_web_logger()
    logger.info(
        "starting goldenshare web env=%s host=%s port=%s debug=%s",
        settings.app_env,
        settings.web_host,
        settings.web_port,
        settings.web_debug,
    )
    yield
    logger.info("stopping goldenshare web")
