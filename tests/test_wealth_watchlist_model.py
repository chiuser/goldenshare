from __future__ import annotations

from io import StringIO

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.model_registry import MODEL_MODULES, register_all_models
from src.app.models.app_user import AppUser
from src.biz.models.wealth.watchlist_item import WealthWatchlistItem
from src.foundation.models.base import Base


@pytest.fixture()
def watchlist_session():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS app")
        AppUser.__table__.create(connection)
        WealthWatchlistItem.__table__.create(connection)
    with Session(engine) as session:
        session.add_all(
            [
                AppUser(id=1, username="one", password_hash="unused"),
                AppUser(id=2, username="two", password_hash="unused"),
            ]
        )
        session.commit()
        yield session
    engine.dispose()


def test_unique_user_stock_and_independent_users(watchlist_session):
    session = watchlist_session
    session.add_all(
        [
            WealthWatchlistItem(user_id=1, ts_code="000001.SZ"),
            WealthWatchlistItem(user_id=2, ts_code="000001.SZ"),
        ]
    )
    session.commit()
    session.add(WealthWatchlistItem(user_id=1, ts_code="000001.SZ"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert len(session.scalars(select(WealthWatchlistItem)).all()) == 2


def test_user_delete_cascades_only_owned_items_and_ids_are_not_reused(
    watchlist_session,
):
    session = watchlist_session
    first = WealthWatchlistItem(user_id=1, ts_code="000001.SZ")
    second = WealthWatchlistItem(user_id=2, ts_code="000001.SZ")
    session.add_all([first, second])
    session.commit()
    last_id = second.id
    session.execute(delete(AppUser).where(AppUser.id == 2))
    session.commit()
    assert session.scalars(select(WealthWatchlistItem.user_id)).all() == [1]
    next_item = WealthWatchlistItem(user_id=1, ts_code="600000.SH")
    session.add(next_item)
    session.commit()
    assert next_item.id > last_id
    assert session.scalars(
        select(WealthWatchlistItem.id).order_by(WealthWatchlistItem.id)
    ).all() == [first.id, next_item.id]


def test_model_is_registered_by_composition_root():
    assert "src.biz.models.wealth.watchlist_item" in MODEL_MODULES
    register_all_models()
    assert (
        Base.metadata.tables["app.wealth_watchlist_item"]
        is WealthWatchlistItem.__table__
    )


def test_migration_only_creates_watchlist_on_verified_head(monkeypatch):
    module = (
        ScriptDirectory.from_config(Config("alembic.ini"))
        .get_revision("20260903_000169")
        .module
    )
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    monkeypatch.setattr(module, "op", Operations(context))
    module.upgrade()
    sql = output.getvalue()
    assert module.down_revision == "20260831_000168"
    assert "CREATE TABLE app.wealth_watchlist_item" in sql
    assert "BIGSERIAL" in sql
    assert "UNIQUE (user_id, ts_code)" in sql
    assert "REFERENCES app.app_user (id) ON DELETE CASCADE" in sql
    assert "idx_wealth_watchlist_item_user_id_id" in sql
    assert all(
        statement.strip().startswith("CREATE ")
        for statement in sql.split(";")
        if statement.strip()
    )
