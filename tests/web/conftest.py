from __future__ import annotations

from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.config.settings import get_settings
from src.models.app.app_user import AppUser
from src.web.auth.password_service import PasswordService


@pytest.fixture(autouse=True)
def configured_web_env(monkeypatch) -> Generator[None, None, None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-with-32-bytes-min")
    monkeypatch.setenv("WEB_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PLATFORM_CHECK_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def web_engine(configured_web_env) -> Generator:

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS app")
        AppUser.__table__.create(connection)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(web_engine) -> Generator[Session, None, None]:
    testing_session_local = sessionmaker(bind=web_engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def user_factory(db_session: Session) -> Callable[..., AppUser]:
    def build(
        *,
        username: str = "admin",
        password: str = "secret",
        display_name: str | None = "Administrator",
        email: str | None = None,
        is_admin: bool = False,
        is_active: bool = True,
    ) -> AppUser:
        user = AppUser(
            username=username,
            password_hash=PasswordService().hash_password(password),
            display_name=display_name,
            email=email,
            is_admin=is_admin,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return build


@pytest.fixture()
def app_client(db_session: Session) -> Generator[TestClient, None, None]:
    from src.web.app import app
    from src.web.dependencies import get_db_session

    def override_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_token(app_client: TestClient, user_factory: Callable[..., AppUser]) -> str:
    user_factory(username="admin", password="secret", is_admin=True)
    response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    assert response.status_code == 200
    return response.json()["token"]
