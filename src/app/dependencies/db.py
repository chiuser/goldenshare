from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from src.db import get_session
from src.foundation.clients.reference_data import bind_reference_data


def get_db_session(request: Request) -> Generator[Session, None, None]:
    for session in get_session():
        bind_reference_data(session, getattr(request.app.state, "reference_data", None))
        yield session
