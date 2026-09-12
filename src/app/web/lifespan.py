from __future__ import annotations

from contextlib import asynccontextmanager

from src.app.web.logging import configure_web_logging, get_web_logger
from src.app.web.settings import get_web_settings
from src.foundation.config.settings import get_settings
from src.app.runtime.trading_assistant_lifespan import trading_assistant_lifespan


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
    async with trading_assistant_lifespan(_app, database_url=get_settings().database_url, logger=logger):
        yield
    logger.info("stopping goldenshare web")
