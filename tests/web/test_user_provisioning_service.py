from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.auth.user_repository import UserRepository
from src.app.auth.services.auth_service import AuthService
from src.app.auth.services.admin_user_service import AdminUserService
from src.app.models.app_user import AppUser
from src.app.user_provisioning_service import UserProvisioningService
from src.biz.models.wealth.watchlist_group import WealthWatchlistGroup as Group
from src.biz.services.wealth.market.watchlist.watchlist_group_initializer import (
    WatchlistGroupInitializer,
)
from src.scripts import create_user


def test_provisioning_flushes_but_does_not_commit(db_session):
    with patch.object(
        db_session, "commit", side_effect=AssertionError("must not commit")
    ):
        user = UserProvisioningService().create_user(
            db_session, username="new", password_hash="hash"
        )
        group = db_session.scalar(select(Group).where(Group.user_id == user.id))
        assert group.name == "我的自选" and group.is_default and group.color is None
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(AppUser)) == 0
    assert db_session.scalar(select(func.count()).select_from(Group)) == 0
    assert not hasattr(UserRepository(), "create_user")


def test_initializer_failure_rolls_back_account(web_engine):
    with Session(web_engine) as session:
        with patch.object(
            WatchlistGroupInitializer,
            "initialize_default_group",
            side_effect=RuntimeError("init"),
        ):
            with pytest.raises(RuntimeError):
                UserProvisioningService().create_user(
                    session, username="fail", password_hash="hash"
                )
        session.rollback()
    with Session(web_engine) as read:
        assert read.scalar(select(AppUser).where(AppUser.username == "fail")) is None
        assert read.scalar(select(Group)) is None


def test_cli_uses_same_provisioning_transaction(web_engine, monkeypatch):
    monkeypatch.setattr(create_user, "SessionLocal", lambda: Session(web_engine))
    monkeypatch.setattr(
        "sys.argv", ["create_user", "--username", "cli-test", "--password", "secret"]
    )
    create_user.main()
    with Session(web_engine) as session:
        user = session.scalar(select(AppUser).where(AppUser.username == "cli-test"))
        assert (
            session.scalar(
                select(func.count()).select_from(Group).where(Group.user_id == user.id)
            )
            == 1
        )


@pytest.mark.parametrize("failure", ["initialize", "commit"])
def test_cli_failure_closes_uncommitted_account_and_group(
    web_engine, monkeypatch, failure
):
    monkeypatch.setattr(
        "sys.argv", ["create_user", "--username", "cli-fail", "--password", "secret"]
    )
    session = Session(web_engine)
    monkeypatch.setattr(create_user, "SessionLocal", lambda: session)
    if failure == "initialize":
        monkeypatch.setattr(
            WatchlistGroupInitializer,
            "initialize_default_group",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("initialize failure")
            ),
        )
    else:
        monkeypatch.setattr(
            session,
            "commit",
            lambda: (_ for _ in ()).throw(RuntimeError("commit rejected")),
        )
    with pytest.raises(RuntimeError):
        create_user.main()
    with Session(web_engine) as read:
        assert read.scalar(select(AppUser.id)) is None
        assert read.scalar(select(Group.id)) is None


@pytest.mark.parametrize("entry", ["registration", "admin"])
@pytest.mark.parametrize("failure", ["roles", "audit", "commit"])
def test_user_entry_failure_persists_neither_user_nor_default(
    web_engine, monkeypatch, entry, failure
):
    with Session(web_engine) as session:
        service = AuthService() if entry == "registration" else AdminUserService()
        if entry == "registration":
            monkeypatch.setattr(service.settings, "auth_register_mode", "public")
            monkeypatch.setattr(
                service.settings, "auth_require_email_verification", False
            )
            target = service
            method = {"roles": "_assign_roles", "audit": "_audit", "commit": "commit"}[
                failure
            ]
            kwargs = dict(
                username="failing",
                password="Password123!",
                display_name=None,
                email=None,
                invite_code=None,
            )
            operation = service.register
        else:
            target = service.auth_service if failure == "roles" else service
            method = {"roles": "replace_roles", "audit": "_audit", "commit": "commit"}[
                failure
            ]
            kwargs = dict(
                username="failing",
                password="Password123!",
                display_name=None,
                email=None,
                is_admin=False,
                is_active=True,
                account_state="active",
                roles=[],
                actor_user_id=None,
            )
            operation = service.create_user
        with patch.object(
            session if failure == "commit" else target,
            method,
            side_effect=RuntimeError("injected"),
        ):
            with pytest.raises(RuntimeError, match="injected"):
                operation(session, **kwargs)
        session.rollback()
    with Session(web_engine) as read:
        assert read.scalar(select(AppUser).where(AppUser.username == "failing")) is None
        assert read.scalar(select(Group)) is None
