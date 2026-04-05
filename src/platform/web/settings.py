from __future__ import annotations

from pathlib import Path

from src.foundation.config.settings import Settings, get_settings


STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"


def get_web_settings() -> Settings:
    return get_settings()
