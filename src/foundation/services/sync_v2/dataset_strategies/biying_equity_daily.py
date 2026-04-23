from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from src.foundation.models.raw_multi.raw_biying_stock_basic import RawBiyingStockBasic
from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit, ValidatedRunRequest
from src.foundation.services.sync_v2.strategy_helpers.param_format import build_unit_id, split_multi_values


WINDOW_DAYS = 3000
DEFAULT_ADJ_TYPES: tuple[str, ...] = ("n", "f", "b")


def _normalize_dm(raw_value: str) -> str:
    value = str(raw_value or "").strip().upper()
    if "." in value:
        value = value.split(".", 1)[0]
    return value


def _resolve_explicit_dms(request: ValidatedRunRequest) -> list[str]:
    values = split_multi_values(request.params.get("ts_code"))
    return sorted({_normalize_dm(value) for value in values if _normalize_dm(value)})


def _load_stock_pool(
    *,
    session,
    explicit_dms: list[str],
) -> list[tuple[str, str | None]]:
    stmt = select(RawBiyingStockBasic.dm, RawBiyingStockBasic.mc).where(RawBiyingStockBasic.dm.is_not(None))
    if explicit_dms:
        stmt = stmt.where(RawBiyingStockBasic.dm.in_(explicit_dms))
    rows = session.execute(stmt.order_by(RawBiyingStockBasic.dm.asc())).all()
    pool = [(str(row.dm).strip().upper(), row.mc) for row in rows if row.dm]
    if not explicit_dms:
        return pool
    by_dm = {dm for dm, _ in pool}
    missing = [dm for dm in explicit_dms if dm not in by_dm]
    return pool + [(dm, None) for dm in missing]


def _resolve_adj_types(request: ValidatedRunRequest) -> list[str]:
    values = split_multi_values(request.params.get("adj_type"))
    if not values:
        return list(DEFAULT_ADJ_TYPES)
    normalized = [str(value).strip().lower() for value in values if str(value).strip()]
    invalid = sorted({value for value in normalized if value not in DEFAULT_ADJ_TYPES})
    if invalid:
        raise RuntimeError(f"biying_equity_daily invalid adj_type={','.join(invalid)}; expected n/f/b")
    return sorted(set(normalized), key=lambda item: DEFAULT_ADJ_TYPES.index(item))


def _split_windows(start_date: date, end_date: date, *, window_days: int) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        window_end = min(cursor + timedelta(days=window_days - 1), end_date)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _resolve_windows(request: ValidatedRunRequest) -> list[tuple[date, date]]:
    if request.run_profile == "point_incremental":
        if request.trade_date is None:
            raise RuntimeError("biying_equity_daily point_incremental requires trade_date")
        return [(request.trade_date, request.trade_date)]
    if request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise RuntimeError("biying_equity_daily range_rebuild requires start_date and end_date")
        return _split_windows(request.start_date, request.end_date, window_days=WINDOW_DAYS)
    raise RuntimeError(f"biying_equity_daily unsupported run_profile: {request.run_profile}")


def build_biying_equity_daily_units(
    request: ValidatedRunRequest,
    contract: DatasetSyncContract,
    dao,
    settings,
    session,
) -> list[PlanUnit]:
    explicit_dms = _resolve_explicit_dms(request)
    stocks = _load_stock_pool(session=session, explicit_dms=explicit_dms)
    if not stocks:
        raise RuntimeError("raw_biying.stock_basic is empty for biying_equity_daily")
    windows = _resolve_windows(request)
    adj_types = _resolve_adj_types(request)
    source_key = request.source_key or contract.source_spec.source_key_default

    units: list[PlanUnit] = []
    ordinal = 0
    for dm, mc in stocks:
        for adj_type in adj_types:
            for window_start, window_end in windows:
                merged_values = {
                    "dm": dm,
                    "mc": mc,
                    "adj_type": adj_type,
                    "window_start": window_start,
                    "window_end": window_end,
                }
                request_params = contract.source_spec.unit_params_builder(request, window_end, merged_values)
                units.append(
                    PlanUnit(
                        unit_id=build_unit_id(
                            dataset_key=request.dataset_key,
                            anchor=window_end,
                            merged_values={
                                "dm": dm,
                                "adj_type": adj_type,
                                "st": window_start.isoformat(),
                                "et": window_end.isoformat(),
                            },
                            ordinal=ordinal,
                        ),
                        dataset_key=request.dataset_key,
                        source_key=source_key,
                        trade_date=window_end,
                        request_params=request_params,
                        pagination_policy="none",
                        page_limit=None,
                    )
                )
                ordinal += 1
    return units
