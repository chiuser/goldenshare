from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit, ValidatedRunRequest
from src.foundation.services.sync_v2.strategy_helpers.param_format import split_multi_values


STK_MINS_ALLOWED_FREQS: tuple[str, ...] = ("1min", "5min", "15min", "30min", "60min")
STK_MINS_WINDOW_START_TIME = "09:00:00"
STK_MINS_WINDOW_END_TIME = "19:00:00"
STK_MINS_SOURCE_PAGE_LIMIT = 8000


@dataclass(frozen=True, slots=True)
class _SecurityTarget:
    ts_code: str
    name: str | None = None


def _resolve_freqs(request: ValidatedRunRequest) -> list[str]:
    raw_values = split_multi_values(request.params.get("freq"))
    if not raw_values:
        raise RuntimeError("stk_mins requires at least one freq")
    invalid = sorted({value for value in raw_values if value not in STK_MINS_ALLOWED_FREQS})
    if invalid:
        raise RuntimeError(f"stk_mins invalid freq: {', '.join(invalid)}")
    selected = set(raw_values)
    return [freq for freq in STK_MINS_ALLOWED_FREQS if freq in selected]


def _resolve_security_targets(request: ValidatedRunRequest, dao) -> list[_SecurityTarget]:  # type: ignore[no-untyped-def]
    explicit_codes = split_multi_values(request.params.get("ts_code"))
    if explicit_codes:
        targets: list[_SecurityTarget] = []
        get_by_ts_code = getattr(dao.security, "get_by_ts_code", None)
        for code in sorted({str(item).strip().upper() for item in explicit_codes if str(item).strip()}):
            security = get_by_ts_code(code) if callable(get_by_ts_code) else None
            targets.append(_SecurityTarget(ts_code=code, name=getattr(security, "name", None) or None))
        return targets

    securities = list(dao.security.get_active_equities())
    tushare_targets = [
        _SecurityTarget(
            ts_code=str(getattr(item, "ts_code", "") or "").strip().upper(),
            name=getattr(item, "name", None) or None,
        )
        for item in securities
        if str(getattr(item, "source", "tushare") or "").strip().lower() == "tushare"
        and str(getattr(item, "ts_code", "") or "").strip()
    ]
    all_targets = [
        _SecurityTarget(
            ts_code=str(getattr(item, "ts_code", "") or "").strip().upper(),
            name=getattr(item, "name", None) or None,
        )
        for item in securities
        if str(getattr(item, "ts_code", "") or "").strip()
    ]
    targets_by_code = {
        target.ts_code: target
        for target in (tushare_targets or all_targets)
        if target.ts_code
    }
    targets = [targets_by_code[code] for code in sorted(targets_by_code.keys())]
    if not targets:
        raise RuntimeError("stk_mins requires stock_basic/security pool before full-market sync")
    return targets


def _resolve_datetime_window(request: ValidatedRunRequest) -> tuple[date | None, str, str]:
    if request.trade_date is not None:
        current_date = request.trade_date
        return (
            current_date,
            f"{current_date.isoformat()} {STK_MINS_WINDOW_START_TIME}",
            f"{current_date.isoformat()} {STK_MINS_WINDOW_END_TIME}",
        )
    if request.start_date is not None and request.end_date is not None:
        return (
            None,
            f"{request.start_date.isoformat()} {STK_MINS_WINDOW_START_TIME}",
            f"{request.end_date.isoformat()} {STK_MINS_WINDOW_END_TIME}",
        )
    raise RuntimeError("stk_mins requires trade_date or start_date/end_date")


def _build_unit_id(
    *,
    ts_code: str,
    freq: str,
    window_start: str,
    window_end: str,
    ordinal: int,
) -> str:
    safe_start = window_start.replace(" ", "T")
    safe_end = window_end.replace(" ", "T")
    return f"stk_mins:ts_code={ts_code}:freq={freq}:start={safe_start}:end={safe_end}:{ordinal}"


def build_stk_mins_units(
    request: ValidatedRunRequest,
    contract: DatasetSyncContract,
    dao,
    settings,
    session,
) -> list[PlanUnit]:
    del session
    del settings
    trade_date, window_start, window_end = _resolve_datetime_window(request)
    freqs = _resolve_freqs(request)
    security_targets = _resolve_security_targets(request, dao)
    source_key = request.source_key or contract.source_spec.source_key_default

    units: list[PlanUnit] = []
    ordinal = 0
    for target in security_targets:
        for freq in freqs:
            merged_values: dict[str, Any] = {
                "ts_code": target.ts_code,
                "freq": freq,
                "window_start": window_start,
                "window_end": window_end,
            }
            progress_context: dict[str, Any] = {
                "unit": "stock",
                "ts_code": target.ts_code,
                "freq": freq,
                "start_date": window_start,
                "end_date": window_end,
            }
            if target.name:
                progress_context["security_name"] = target.name
            units.append(
                PlanUnit(
                    unit_id=_build_unit_id(
                        ts_code=target.ts_code,
                        freq=freq,
                        window_start=window_start,
                        window_end=window_end,
                        ordinal=ordinal,
                    ),
                    dataset_key=request.dataset_key,
                    source_key=source_key,
                    trade_date=trade_date,
                    request_params=contract.source_spec.unit_params_builder(
                        request,
                        trade_date,
                        merged_values,
                    ),
                    progress_context=progress_context,
                    pagination_policy="offset_limit",
                    page_limit=STK_MINS_SOURCE_PAGE_LIMIT,
                )
            )
            ordinal += 1
    return units
