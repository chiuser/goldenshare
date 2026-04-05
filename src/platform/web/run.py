from __future__ import annotations

import argparse
import os

import uvicorn

from src.db import reset_db
from src.foundation.config.settings import get_settings
from src.platform.web.settings import get_web_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Goldenshare web server")
    parser.add_argument("--host", help="Override WEB_HOST")
    parser.add_argument("--port", type=int, help="Override WEB_PORT")
    parser.add_argument("--reload", action="store_true", help="Force enable reload mode")
    parser.add_argument("--no-reload", action="store_true", help="Force disable reload mode")
    parser.add_argument("--env-file", help="Path to environment file")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.env_file:
        os.environ["GOLDENSHARE_ENV_FILE"] = args.env_file

    get_settings.cache_clear()
    reset_db()

    settings = get_web_settings()
    reload_flag = settings.web_debug
    if args.reload:
        reload_flag = True
    if args.no_reload:
        reload_flag = False
    uvicorn.run(
        "src.platform.web.app:app",
        host=args.host or settings.web_host,
        port=args.port or settings.web_port,
        reload=reload_flag,
    )


if __name__ == "__main__":
    main()
