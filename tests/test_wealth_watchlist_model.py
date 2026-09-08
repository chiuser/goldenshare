from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import create_engine, delete, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.model_registry import MODEL_MODULES, register_all_models
from src.app.models.app_user import AppUser
from src.app.user_provisioning_service import UserProvisioningService
from src.biz.models.wealth.watchlist_group import WealthWatchlistGroup as Group
from src.biz.models.wealth.watchlist_membership import (
    WealthWatchlistMembership as Membership,
)
from src.biz.schemas.wealth.market.watchlist import ApiId
from src.biz.services.wealth.market.watchlist.watchlist_cursor import WatchlistCursor
from src.biz.services.wealth.market.watchlist.watchlist_command_service import (
    WatchlistCommandService,
)
from src.biz.services.wealth.market.watchlist.watchlist_policy import (
    MAX_API_ID,
    PALETTE,
    TRIM_CODEPOINTS,
    WatchlistError,
    WatchlistRequestError,
    count_visible_graphemes,
    normalize_group_name,
)

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures/wealth_watchlist_group_names.json").read_text()
)


@pytest.fixture()
def watchlist_session():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS app")
        for model in (AppUser, Group, Membership):
            model.__table__.create(connection)
    with Session(engine) as session:
        for username in ("one", "two"):
            UserProvisioningService().create_user(
                session, username=username, password_hash="unused"
            )
        session.commit()
        yield session
    engine.dispose()


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["id"])
def test_shared_name_vectors(vector, watchlist_session):
    if not vector["accepted"]:
        with pytest.raises(WatchlistRequestError):
            normalize_group_name(vector["raw"])
        return
    name = normalize_group_name(vector["raw"])
    assert name == vector["normalized"]
    assert count_visible_graphemes(name) == vector["graphemeCount"]
    row = Group(user_id=1, name=name, color=PALETTE[0], is_default=False)
    watchlist_session.add(row)
    watchlist_session.commit()
    assert watchlist_session.get(Group, row.id).name == name


@pytest.mark.parametrize("point", TRIM_CODEPOINTS)
def test_exact_trim_codepoints(point):
    assert normalize_group_name(chr(point) + "AI" + chr(point)) == "AI"


def test_name_bytes_and_normalization_conflict(watchlist_session):
    assert len(("q" + "\u0301" * 511 + " ").encode()) == 1024
    assert normalize_group_name("q" + "\u0301" * 511 + " ") == "q" + "\u0301" * 511
    with pytest.raises(WatchlistRequestError):
        normalize_group_name("q" + "\u0301" * 512)
    session = watchlist_session
    long_name = normalize_group_name("q" + "\u0301" * 511 + " ")
    long_group = Group(user_id=1, name=long_name, color=PALETTE[0])
    session.add(long_group)
    session.commit()
    assert session.get(Group, long_group.id).name == long_name
    session.add(
        Group(user_id=1, name=normalize_group_name(" e\u0301 "), color=PALETTE[0])
    )
    session.commit()
    session.add(Group(user_id=1, name=normalize_group_name("é"), color=PALETTE[0]))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


@pytest.mark.parametrize(
    "fields",
    [
        dict(name="second", is_default=True, color=None),
        dict(name="我的自选", is_default=True, color=None),
        dict(name="我的自选", is_default=False, color=PALETTE[0]),
        dict(name="custom", is_default=False, color=None),
        dict(name="custom", is_default=False, color="#000000"),
        dict(name="", is_default=False, color=PALETTE[0]),
        dict(name="我的自选", is_default=True, color=PALETTE[0]),
    ],
)
def test_group_constraint_rejections(watchlist_session, fields):
    watchlist_session.add(Group(user_id=1, **fields))
    with pytest.raises(IntegrityError):
        watchlist_session.commit()
    watchlist_session.rollback()


def test_cross_group_members_and_user_cascade_id_nonreuse(watchlist_session):
    session = watchlist_session
    groups = list(session.scalars(select(Group).order_by(Group.id)))
    session.add_all([Group(user_id=i, name="共同", color=PALETTE[0]) for i in (1, 2)])
    session.commit()
    session.add_all([Membership(group_id=g.id, ts_code="000001.SZ") for g in groups])
    session.commit()
    last = session.scalar(select(Membership.id).order_by(Membership.id.desc()))
    session.add(Membership(group_id=groups[0].id, ts_code="000001.SZ"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.execute(delete(AppUser).where(AppUser.id == 2))
    session.commit()
    assert session.scalars(select(Group.user_id)).all() == [1, 1]
    assert len(session.scalars(select(Membership)).all()) == 1
    new = Membership(group_id=groups[0].id, ts_code="600000.SH")
    session.add(new)
    session.commit()
    assert new.id > last
    session.execute(delete(Group).where(Group.id == groups[0].id))
    session.commit()
    assert session.scalars(select(Membership)).all() == []
    # DB deletion is allowed; API protection is tested separately, not invented as a trigger.


def test_model_registration_and_indexes(watchlist_session):
    register_all_models()
    assert "src.biz.models.wealth.watchlist_item" not in MODEL_MODULES
    assert not (
        Path(__file__).parents[1] / "src/biz/models/wealth/watchlist_item.py"
    ).exists()
    indexes = inspect(watchlist_session.get_bind()).get_indexes(
        "wealth_watchlist_group", schema="app"
    )
    assert any(
        i["name"] == "uq_wealth_watchlist_group_user_default" and i["unique"]
        for i in indexes
    )
    assert "src.biz.models.wealth.watchlist_group" in MODEL_MODULES
    assert "src.biz.models.wealth.watchlist_membership" in MODEL_MODULES


@pytest.mark.parametrize("value", [1, MAX_API_ID])
def test_strict_api_id_accepts_bounds(value):
    assert TypeAdapter(ApiId).validate_python(value) == value


@pytest.mark.parametrize("value", [0, -1, MAX_API_ID + 1, True, "1", 1.0, None])
def test_strict_api_id_rejects_coercion_and_range(value):
    with pytest.raises(ValidationError):
        TypeAdapter(ApiId).validate_python(value)


def cursor_payload(**changes):
    return (
        dict(
            v=1,
            g=1,
            s="price",
            d="desc",
            o="2026-09-07",
            p=0,
            m=0,
            x="1.234567890123456789",
            i=2,
        )
        | changes
    )


def decode_payload(payload, **context):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    token = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    return WatchlistCursor.decode(
        token,
        **(
            dict(
                group_id=1, sort_by="price", direction="desc", observed=date(2026, 9, 7)
            )
            | context
        ),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"v": 2},
        {"v": True},
        {"extra": 1},
        {"g": 0},
        {"g": MAX_API_ID + 1},
        {"g": "1"},
        {"i": False},
        {"i": 2.0},
        {"i": -1},
        {"i": MAX_API_ID + 1},
        {"p": True},
        {"p": 2},
        {"m": "0"},
        {"m": -1},
        {"s": "unknown"},
        {"s": []},
        {"d": "DESC"},
        {"d": None},
        {"o": "2026-9-7"},
        {"o": "2026-02-30"},
        {"o": 20260907},
        {"x": 1.5},
        {"x": "NaN"},
        {"x": "Infinity"},
        {"x": "-Infinity"},
        {"x": " 1"},
        {"x": None},
        {"m": 1, "x": "1"},
        {"s": None},
        {"s": None, "d": None, "m": 1, "x": None},
    ],
)
def test_cursor_rejects_invalid_fields(changes):
    with pytest.raises(WatchlistError) as error:
        decode_payload(cursor_payload(**changes))
    assert error.value.code == "WL_CURSOR_INVALID"


@pytest.mark.parametrize("payload", ["[]", "null", '{"v":1,"v":1}', '{"v":1}', "{"])
def test_cursor_rejects_invalid_json_shape(payload):
    with pytest.raises(WatchlistError):
        decode_payload(payload)


@pytest.mark.parametrize(
    "context",
    [
        {"group_id": 2},
        {"sort_by": "vol"},
        {"direction": "asc"},
        {"observed": date(2026, 9, 8)},
        {"observed": None},
    ],
)
def test_cursor_binds_all_context(context):
    with pytest.raises(WatchlistError):
        decode_payload(cursor_payload(), **context)


def test_cursor_roundtrip_keeps_decimal_and_safe_id_precision():
    cursor = decode_payload(cursor_payload(i=MAX_API_ID))
    assert cursor.value == Decimal("1.234567890123456789")
    assert cursor.membership_id == MAX_API_ID
    assert (
        WatchlistCursor.decode(
            cursor.encode(),
            group_id=1,
            sort_by="price",
            direction="desc",
            observed=date(2026, 9, 7),
        )
        == cursor
    )
    assert decode_payload(cursor_payload(m=1, x=None)).value is None
    assert (
        decode_payload(
            cursor_payload(s=None, d=None, x=None, o=None),
            sort_by=None,
            direction=None,
            observed=None,
        ).value
        is None
    )


def test_group_id_is_not_reused(watchlist_session):
    session = watchlist_session
    group = Group(user_id=1, name="删除", color=PALETTE[0])
    session.add(group)
    session.flush()
    previous_id = group.id
    session.delete(group)
    session.commit()
    replacement = Group(user_id=1, name="新建", color=PALETTE[0])
    session.add(replacement)
    session.flush()
    assert replacement.id > previous_id


def test_sqlite_insert_helper_only_ignores_membership_uniqueness(watchlist_session):
    session = watchlist_session
    group_id = session.scalar(select(Group.id).where(Group.user_id == 1))
    service = WatchlistCommandService()
    assert service._insert_missing_memberships(session, []) == 0
    assert service._insert_missing_memberships(session, [(group_id, "000001.SZ")]) == 1
    session.commit()
    assert service._insert_missing_memberships(session, [(group_id, "000001.SZ")]) == 0
    for pair in [(MAX_API_ID, "000001.SZ"), (group_id, None)]:
        with pytest.raises(IntegrityError):
            service._insert_missing_memberships(session, [pair])
        session.rollback()
    assert session.scalars(select(Membership.ts_code)).all() == ["000001.SZ"]
