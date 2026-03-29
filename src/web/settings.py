from __future__ import annotations

from pathlib import Path

from src.config.settings import Settings, get_settings


STATIC_DIR = Path(__file__).resolve().parent / "static"


def get_web_settings() -> Settings:
    return get_settings()
