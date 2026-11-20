"""Append-only locally confirmed facts and the DG fund status lookup."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extensions import connection
from psycopg2.extras import Json, RealDictCursor

SHANGHAI = ZoneInfo("Asia/Shanghai")
READ_URL = "LAKE_META_POSTGRES_URL"
WRITE_URL = "LAKE_META_POSTGRES_WRITE_URL"


class FactType(StrEnum):
    FUND_LIQUIDATION_STARTED = "fund_liquidation_started"
    FUND_DELISTED = "fund_delisted"


class ConfirmedFactsError(ValueError):
    """An invalid input, unavailable registry, or conflicting fact."""


@dataclass(frozen=True)
class Evidence:
    publisher: str
    url: str
    announcement_id: str | None = None

    def __post_init__(self) -> None:
        url = urlsplit(self.url)
        if (
            not self.publisher.strip()
            or url.scheme not in {"http", "https"}
            or not url.netloc
        ):
            raise ConfirmedFactsError("公告证据须填写发布机构与有效的公告链接。")


@dataclass(frozen=True)
class FactDetails:
    effective_from: date
    effective_until: date | None
    evidence: tuple[Evidence, ...]
    reason: str

    def __post_init__(self) -> None:
        if (
            self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ConfirmedFactsError("结束日期必须晚于生效日期。")
        if not self.evidence or not self.reason.strip():
            raise ConfirmedFactsError("登记和更正须填写公告证据及说明。")


@dataclass(frozen=True)
class FactRevision:
    fact_id: str
    revision: int
    action: str
    subject_type: str
    subject_key: str
    fact_type: FactType
    time_precision: str
    effective_from: datetime
    effective_until: datetime | None
    evidence: tuple[Evidence, ...]
    reason: str
    recorded_by: str
    recorded_at: datetime


@dataclass(frozen=True)
class FundStatus:
    subject_key: str
    business_date: date
    source_status: str | None
    status: str
    fact: FactRevision | None


_TABLE = "public.confirmed_business_facts"
_COLUMNS = """fact_id::text AS fact_id, revision, action, subject_type, subject_key,
    fact_type, time_precision, effective_from, effective_until, evidence, reason,
    recorded_by, recorded_at"""


def validate_etf_code(subject_key: str) -> str:
    if not re.fullmatch(r"[0-9]{6}\.(SH|SZ)", subject_key):
        raise ConfirmedFactsError("ETF 代码须为六位数字加 .SH 或 .SZ。")
    return subject_key


def _start_of_day(day: date | None) -> datetime | None:
    return None if day is None else datetime.combine(day, time.min, tzinfo=SHANGHAI)


def _revision(row: dict) -> FactRevision:
    return FactRevision(
        **{
            **row,
            "fact_type": FactType(row["fact_type"]),
            "evidence": tuple(Evidence(**entry) for entry in row["evidence"]),
        }
    )


@contextmanager
def connect_confirmed_facts(*, writable: bool = False) -> Iterator[connection]:
    """Open a bounded, local transaction using the configured role for this operation."""
    env_name = WRITE_URL if writable else READ_URL
    dsn = os.environ.get(env_name)
    if not dsn:
        raise ConfirmedFactsError(f"请配置 {env_name}。")
    try:
        settings = psycopg2.extensions.parse_dsn(dsn)
    except psycopg2.Error:
        raise ConfirmedFactsError(f"{env_name} 的连接配置无效。") from None
    host = settings.get("host", "")
    local_socket = Path(host).is_absolute() and "," not in host
    if (
        settings.get("dbname") != "goldenshare_lake_meta"
        or (settings.get("service") or os.environ.get("PGSERVICE"))
        or (not local_socket and host not in {"localhost", "127.0.0.1", "::1"})
        or (settings.get("hostaddr") or os.environ.get("PGHOSTADDR", ""))
        not in {"", "127.0.0.1", "::1"}
    ):
        raise ConfirmedFactsError(f"{env_name} 须指向本机 goldenshare_lake_meta。")
    try:
        db = psycopg2.connect(dsn, connect_timeout=10)
    except psycopg2.OperationalError:
        raise ConfirmedFactsError("连接本机业务事实登记库失败。") from None
    try:
        db.set_session(
            readonly=not writable,
            isolation_level="SERIALIZABLE" if writable else "READ COMMITTED",
        )
        with db:
            yield db
    except (psycopg2.errors.SerializationFailure, psycopg2.errors.UniqueViolation):
        raise ConfirmedFactsError("当前登记已变化，请查看最新记录再提交。") from None
    finally:
        db.close()


def _effective_facts(
    cursor,
    *,
    subject_type: str,
    fact_types: Sequence[FactType],
    start: datetime,
    end: datetime | None,
    subject_keys: Sequence[str] | None,
) -> list[FactRevision]:
    cursor.execute(
        f"""
        WITH latest AS (
            SELECT DISTINCT ON (facts.fact_id) {_COLUMNS}
            FROM {_TABLE} AS facts
            WHERE subject_type = %s AND fact_type = ANY(%s)
              AND (%s::text[] IS NULL OR subject_key = ANY(%s::text[]))
            ORDER BY facts.fact_id, revision DESC
        )
        SELECT * FROM latest
        WHERE action <> 'revoke'
          AND (%s::timestamptz IS NULL OR effective_from < %s)
          AND (effective_until IS NULL OR effective_until > %s)
        ORDER BY subject_key, fact_type, fact_id
        """,
        (subject_type, list(fact_types), subject_keys, subject_keys, end, end, start),
    )
    return [_revision(row) for row in cursor.fetchall()]


def find_effective_facts(
    db: connection,
    *,
    subject_type: str,
    fact_types: Sequence[FactType],
    window_start: date,
    window_end_exclusive: date,
    subject_keys: Sequence[str] | None = None,
) -> list[FactRevision]:
    """Get current facts overlapping the given Shanghai date window."""
    if window_end_exclusive <= window_start:
        raise ConfirmedFactsError("查询结束日期必须晚于开始日期。")
    codes = None if subject_keys is None else list(subject_keys)
    with db.cursor(cursor_factory=RealDictCursor) as cursor:
        return _effective_facts(
            cursor,
            subject_type=subject_type,
            fact_types=fact_types,
            start=_start_of_day(window_start),
            end=_start_of_day(window_end_exclusive),
            subject_keys=codes,
        )


def list_fact_history(
    db: connection,
    *,
    fact_id: str | None = None,
    subject_key: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[FactRevision]:
    if (fact_id is None) == (subject_key is None):
        raise ConfirmedFactsError("请指定一个事实编号或 ETF 代码。")
    if limit <= 0 or offset < 0:
        raise ConfirmedFactsError("每页记录数须为正数，起始偏移量须为非负数。")
    with db.cursor(cursor_factory=RealDictCursor) as cursor:
        if fact_id is not None:
            cursor.execute(
                f"""SELECT {_COLUMNS} FROM {_TABLE} WHERE fact_id = %s
                ORDER BY revision DESC LIMIT %s OFFSET %s""",
                (fact_id, limit, offset),
            )
        else:
            cursor.execute(
                f"""SELECT {_COLUMNS} FROM {_TABLE}
                WHERE subject_type = 'etf' AND subject_key = %s
                ORDER BY recorded_at DESC, fact_id, revision DESC LIMIT %s OFFSET %s""",
                (validate_etf_code(subject_key), limit, offset),
            )
        return [_revision(row) for row in cursor.fetchall()]


def _current_revision(cursor, fact_id: str) -> FactRevision:
    cursor.execute(
        f"""SELECT {_COLUMNS} FROM {_TABLE} WHERE fact_id = %s
        ORDER BY revision DESC LIMIT 1""",
        (fact_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ConfirmedFactsError("找不到指定的事实。")
    return _revision(row)


def _same_details(fact: FactRevision, details: FactDetails) -> bool:
    return (
        fact.effective_from == _start_of_day(details.effective_from)
        and fact.effective_until == _start_of_day(details.effective_until)
        and fact.evidence == details.evidence
        and fact.reason == details.reason
    )


def _overlapping_etf_facts(cursor, subject_key, fact_type, details):
    return _effective_facts(
        cursor,
        subject_type="etf",
        fact_types=(fact_type,),
        start=_start_of_day(details.effective_from),
        end=_start_of_day(details.effective_until),
        subject_keys=[subject_key],
    )


def _append_revision(
    cursor,
    *,
    fact_id: str,
    revision: int,
    action: str,
    subject_key: str,
    fact_type: FactType,
    effective_from: datetime,
    effective_until: datetime | None,
    evidence: tuple[Evidence, ...],
    reason: str,
) -> FactRevision:
    cursor.execute(
        f"""
        INSERT INTO {_TABLE} (
            fact_id, revision, action, subject_type, subject_key, fact_type,
            time_precision, effective_from, effective_until, evidence, reason
        ) VALUES (%s, %s, %s, 'etf', %s, %s, 'day', %s, %s, %s, %s)
        RETURNING {_COLUMNS}
        """,
        (
            fact_id,
            revision,
            action,
            subject_key,
            fact_type,
            effective_from,
            effective_until,
            Json([asdict(entry) for entry in evidence]),
            reason,
        ),
    )
    return _revision(cursor.fetchone())


def register_fact(
    db: connection, *, subject_key: str, fact_type: FactType, details: FactDetails
) -> FactRevision:
    subject_key = validate_etf_code(subject_key)
    fact_type = FactType(fact_type)
    with db.cursor(cursor_factory=RealDictCursor) as cursor:
        for fact in _overlapping_etf_facts(cursor, subject_key, fact_type, details):
            if _same_details(fact, details):
                return fact
            raise ConfirmedFactsError(
                "已有同类事实的生效日期重叠，请核对后更正原记录。"
            )
        return _append_revision(
            cursor,
            fact_id=str(uuid4()),
            revision=1,
            action="confirm",
            subject_key=subject_key,
            fact_type=fact_type,
            effective_from=_start_of_day(details.effective_from),
            effective_until=_start_of_day(details.effective_until),
            evidence=details.evidence,
            reason=details.reason,
        )


def correct_fact(
    db: connection, *, fact_id: str, expected_revision: int, details: FactDetails
) -> FactRevision:
    with db.cursor(cursor_factory=RealDictCursor) as cursor:
        current = _current_revision(cursor, fact_id)
        if current.action == "revoke":
            raise ConfirmedFactsError("该事实已撤销，请重新登记。")
        if _same_details(current, details):
            return current
        if current.revision != expected_revision:
            raise ConfirmedFactsError("事实版本已变化，请查看最新记录后更正。")
        overlapping = _overlapping_etf_facts(
            cursor, current.subject_key, current.fact_type, details
        )
        if any(fact.fact_id != current.fact_id for fact in overlapping):
            raise ConfirmedFactsError("更正的生效日期与另一条同类事实重叠。")
        return _append_revision(
            cursor,
            fact_id=current.fact_id,
            revision=current.revision + 1,
            action="correct",
            subject_key=current.subject_key,
            fact_type=current.fact_type,
            effective_from=_start_of_day(details.effective_from),
            effective_until=_start_of_day(details.effective_until),
            evidence=details.evidence,
            reason=details.reason,
        )


def revoke_fact(
    db: connection,
    *,
    fact_id: str,
    expected_revision: int,
    reason: str,
    evidence: tuple[Evidence, ...] = (),
) -> FactRevision:
    if not reason.strip():
        raise ConfirmedFactsError("请填写撤销说明。")
    with db.cursor(cursor_factory=RealDictCursor) as cursor:
        current = _current_revision(cursor, fact_id)
        if current.action == "revoke":
            return current
        if current.revision != expected_revision:
            raise ConfirmedFactsError("事实版本已变化，请查看最新记录后撤销。")
        return _append_revision(
            cursor,
            fact_id=current.fact_id,
            revision=current.revision + 1,
            action="revoke",
            subject_key=current.subject_key,
            fact_type=current.fact_type,
            effective_from=current.effective_from,
            effective_until=current.effective_until,
            evidence=evidence,
            reason=reason,
        )


def resolve_fund_status(
    *,
    subject_key: str,
    business_date: date,
    source_status: str | None,
    effective_facts: Sequence[FactRevision],
) -> FundStatus:
    by_type = {fact.fact_type: fact for fact in effective_facts}
    delisted = by_type.get(FactType.FUND_DELISTED)
    if delisted is not None:
        return FundStatus(subject_key, business_date, source_status, "退市", delisted)
    liquidation = by_type.get(FactType.FUND_LIQUIDATION_STARTED)
    if liquidation is not None:
        return FundStatus(
            subject_key, business_date, source_status, "清算中", liquidation
        )
    status = {"L": "上市", "P": "待上市", "D": "退市"}.get(source_status, "待核实")
    return FundStatus(subject_key, business_date, source_status, status, None)
