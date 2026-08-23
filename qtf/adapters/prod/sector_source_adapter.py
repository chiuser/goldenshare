from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from qtf.contracts.errors import QtfQueryFailed, QtfRequestInvalid
from qtf.contracts.runtime import DatasetEvidence
from qtf.engine.canonical_hash import canonical_json_hash
from qtf.modules.sector.factor_kernel import SectorObservation
from qtf.modules.sector.input_contract import (
    SECTOR_L2_SOURCE_CONTRACT,
    SectorHierarchyNode,
    SectorInputRequest,
    SectorInputSnapshot,
)
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy


SessionFactory = Callable[[], Session]


class ProdSectorInputSource:
    """Bounded read-only access to the frozen level-2 sector source contract."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def read(self, request: SectorInputRequest) -> SectorInputSnapshot:
        if request.start_date > request.end_date:
            raise QtfRequestInvalid("requested start date must not be after end date")
        if request.statement_timeout_ms <= 0:
            raise QtfRequestInvalid("source statement timeout must be positive")

        session = self._session_factory()
        try:
            _begin_read_only(session, statement_timeout_ms=request.statement_timeout_ms)
            calendar_rows = tuple(
                session.execute(
                    select(
                        TradeCalendar.exchange,
                        TradeCalendar.trade_date,
                        TradeCalendar.is_open,
                        TradeCalendar.pretrade_date,
                    )
                    .where(
                        TradeCalendar.exchange == "SSE",
                        TradeCalendar.is_open.is_(True),
                        TradeCalendar.trade_date.between(request.start_date, request.end_date),
                    )
                    .order_by(TradeCalendar.trade_date.asc())
                ).all()
            )
            hierarchy_rows = tuple(
                session.execute(
                    select(
                        WealthSectorHierarchy.sector_code,
                        WealthSectorHierarchy.sector_name,
                        WealthSectorHierarchy.industry_level,
                        WealthSectorHierarchy.parent_sector_code,
                        WealthSectorHierarchy.root_sector_code,
                        WealthSectorHierarchy.display_order,
                        WealthSectorHierarchy.baseline_version,
                        WealthSectorHierarchy.published_at,
                    )
                    .where(WealthSectorHierarchy.industry_level.in_((1, 2)))
                    .order_by(
                        WealthSectorHierarchy.industry_level.asc(),
                        WealthSectorHierarchy.display_order.asc(),
                        WealthSectorHierarchy.sector_code.asc(),
                    )
                ).all()
            )
            l2_codes = tuple(row.sector_code for row in hierarchy_rows if row.industry_level == 2)
            daily_rows = ()
            if l2_codes:
                daily_statement = (
                    select(
                        DcDaily.ts_code,
                        DcDaily.trade_date,
                        DcDaily.category,
                        DcDaily.pct_change,
                        DcDaily.amount,
                    )
                    .where(
                        DcDaily.category == "行业板块",
                        DcDaily.trade_date.between(request.start_date, request.end_date),
                        DcDaily.ts_code.in_(l2_codes),
                    )
                    .order_by(DcDaily.trade_date.asc(), DcDaily.ts_code.asc())
                    .execution_options(stream_results=True, yield_per=2_000)
                )
                daily_rows = tuple(session.execute(daily_statement))

            trade_dates = tuple(row.trade_date for row in calendar_rows)
            hierarchy = tuple(
                SectorHierarchyNode(
                    sector_code=row.sector_code,
                    sector_name=row.sector_name,
                    industry_level=row.industry_level,
                    parent_sector_code=row.parent_sector_code,
                    root_sector_code=row.root_sector_code,
                    display_order=row.display_order,
                    baseline_version=row.baseline_version,
                    published_at=_aware(row.published_at),
                )
                for row in hierarchy_rows
            )
            observations = tuple(
                SectorObservation(
                    trade_date=row.trade_date,
                    sector_code=row.ts_code,
                    parent_sector_code="",
                    pct_change=_number(row.pct_change),
                    amount=_number(row.amount),
                )
                for row in daily_rows
            )
            evidences = (
                _evidence(
                    "core_serving.trade_calendar",
                    SECTOR_L2_SOURCE_CONTRACT["datasets"]["core_serving.trade_calendar"]["fields"],  # type: ignore[index]
                    calendar_rows,
                    keys=lambda row: (row.exchange, row.trade_date),
                    dates=trade_dates,
                    missing_count=0,
                ),
                _evidence(
                    "core_serving.wealth_sector_hierarchy",
                    SECTOR_L2_SOURCE_CONTRACT["datasets"]["core_serving.wealth_sector_hierarchy"]["fields"],  # type: ignore[index]
                    hierarchy_rows,
                    keys=lambda row: row.sector_code,
                    dates=(),
                    missing_count=0,
                ),
                _evidence(
                    "core_serving.dc_daily",
                    SECTOR_L2_SOURCE_CONTRACT["datasets"]["core_serving.dc_daily"]["fields"],  # type: ignore[index]
                    daily_rows,
                    keys=lambda row: (row.trade_date, row.ts_code, row.category),
                    dates=tuple(row.trade_date for row in daily_rows),
                    missing_count=sum(row.pct_change is None or row.amount is None for row in daily_rows),
                ),
            )
            source_contract_hash = canonical_json_hash(SECTOR_L2_SOURCE_CONTRACT)
            content_hash = canonical_json_hash(
                {
                    "source_contract_hash": source_contract_hash,
                    "datasets": [item.as_dict() for item in evidences],
                }
            )
            return SectorInputSnapshot(
                as_of=datetime.now(timezone.utc),
                trade_dates=trade_dates,
                hierarchy=hierarchy,
                observations=observations,
                dataset_evidence=evidences,
                content_hash=content_hash,
                source_contract_hash=source_contract_hash,
            )
        except (QtfRequestInvalid, QtfQueryFailed):
            raise
        except Exception as exc:
            raise QtfQueryFailed("failed to read the bounded production sector input") from exc
        finally:
            session.rollback()
            session.close()


def _begin_read_only(session: Session, *, statement_timeout_ms: int) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    session.execute(text(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}"))


def _number(value: Decimal | int | float | None) -> float:
    if value is None:
        return float("nan")
    number = float(value)
    return number if math.isfinite(number) else float("nan")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _evidence(
    dataset_key: str,
    fields: object,
    rows: tuple[object, ...],
    *,
    keys: Callable[[object], object],
    dates: tuple[date, ...],
    missing_count: int,
) -> DatasetEvidence:
    business_keys = [keys(row) for row in rows]
    duplicate_count = len(business_keys) - len(set(business_keys))
    return DatasetEvidence(
        dataset_key=dataset_key,
        fields=tuple(str(field) for field in fields),  # type: ignore[union-attr]
        start_date=min(dates) if dates else None,
        end_date=max(dates) if dates else None,
        row_count=len(rows),
        unique_key_status="PASS" if duplicate_count == 0 else "FAILED",
        missing_count=missing_count,
        duplicate_count=duplicate_count,
        content_hash=_streaming_row_hash(rows),
    )


def _streaming_row_hash(rows: tuple[object, ...]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for row in rows:
        digest.update(canonical_json_hash(tuple(row)).encode("ascii"))  # type: ignore[arg-type]
        digest.update(b"\n")
    return digest.hexdigest()
