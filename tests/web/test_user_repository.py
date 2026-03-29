from __future__ import annotations

from datetime import datetime, timezone

from src.web.repositories.user_repository import UserRepository


def test_user_repository_create_and_get(db_session) -> None:
    repository = UserRepository()
    user = repository.create_user(
        db_session,
        username="admin",
        password_hash="hashed",
        display_name="Administrator",
        is_admin=True,
    )
    db_session.commit()

    found_by_username = repository.get_by_username(db_session, "admin")
    found_by_id = repository.get_by_id(db_session, user.id)

    assert found_by_username is not None
    assert found_by_username.username == "admin"
    assert found_by_id is not None
    assert found_by_id.id == user.id


def test_user_repository_update_last_login(db_session) -> None:
    repository = UserRepository()
    user = repository.create_user(db_session, username="admin", password_hash="hashed")
    db_session.commit()

    ts = datetime.now(timezone.utc)
    repository.update_last_login(db_session, user, ts)
    db_session.commit()

    refreshed = repository.get_by_id(db_session, user.id)
    assert refreshed is not None
    assert refreshed.last_login_at is not None
