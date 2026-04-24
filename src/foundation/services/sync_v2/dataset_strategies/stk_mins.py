from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit, ValidatedRunRequest
from src.foundation.services.sync_v2.strategy_helpers.param_format import split_multi_values
from src.foundation.services.sync_v2.strategy_helpers.trade_date_expand import resolve_anchors


STK_MINS_ALLOWED_FREQS: tuple[str, ...] = ("1min", "5min", "15min", "30min", "60min")
STK_MINS_TRADING_SESSIONS: tuple[tuple[str, str, str], ...] = (
    ("morning", "09:30:00", "11:30:00"),
    ("afternoon", "13:00:00", "15:00:00"),
)
STK_MINS_SOURCE_PAGE_LIMIT = 8000


def _resolve_freqs(request: ValidatedRunRequest) -> list[str]:
    raw_values = split_multi_values(request.params.get("freq"))
    if not raw_values:
        raise RuntimeError("stk_mins requires at least one freq")
    invalid = sorted({value for value in raw_values if value not in STK_MINS_ALLOWED_FREQS})
    if invalid:
        raise RuntimeError(f"stk_mins invalid freq: {', '.join(invalid)}")
    selected = set(raw_values)
    return [freq for freq in STK_MINS_ALLOWED_FREQS if freq in selected]


def _resolve_security_codes(request: ValidatedRunRequest, dao) -> list[str]:  # type: ignore[no-untyped-def]
    explicit_codes = split_multi_values(request.params.get("ts_code"))
    if explicit_codes:
        return sorted({str(code).strip().upper() for code in explicit_codes if str(code).strip()})

    securities = list(dao.security.get_active_equities())
    tushare_codes = [
        getattr(item, "ts_code", None)
        for item in securities
        if str(getattr(item, "source", "tushare") or "").strip().lower() == "tushare"
    ]
    all_codes = [getattr(item, "ts_code", None) for item in securities]
    codes = sorted({str(code).strip().upper() for code in (tushare_codes or all_codes) if str(code or "").strip()})
    if not codes:
        raise RuntimeError("stk_mins requires stock_basic/security pool before full-market sync")
    return codes


def _session_window(anchor: date, *, start_time: str, end_time: str) -> tuple[str, str]:
    prefix = anchor.isoformat()
    return f"{prefix} {start_time}", f"{prefix} {end_time}"


def _build_unit_id(
    *,
    trade_date: date,
    ts_code: str,
    freq: str,
    session_tag: str,
    ordinal: int,
) -> str:
    return f"stk_mins:{trade_date.isoformat()}:ts_code={ts_code}:freq={freq}:session={session_tag}:{ordinal}"


def build_stk_mins_units(
    request: ValidatedRunRequest,
    contract: DatasetSyncContract,
    dao,
    settings,
    session,
) -> list[PlanUnit]:
    del session
    anchors = resolve_anchors(request=request, contract=contract, dao=dao, settings=settings)
    trade_dates = [anchor for anchor in anchors if isinstance(anchor, date)]
    freqs = _resolve_freqs(request)
    ts_codes = _resolve_security_codes(request, dao)
    source_key = request.source_key or contract.source_spec.source_key_default

    units: list[PlanUnit] = []
    ordinal = 0
    for current_date in trade_dates:
        for ts_code in ts_codes:
            for freq in freqs:
                for session_tag, start_time, end_time in STK_MINS_TRADING_SESSIONS:
                    session_start, session_end = _session_window(
                        current_date,
                        start_time=start_time,
                        end_time=end_time,
                    )
                    merged_values: dict[str, Any] = {
                        "ts_code": ts_code,
                        "freq": freq,
                        "session_start": session_start,
                        "session_end": session_end,
                    }
                    units.append(
                        PlanUnit(
                            unit_id=_build_unit_id(
                                trade_date=current_date,
                                ts_code=ts_code,
                                freq=freq,
                                session_tag=session_tag,
                                ordinal=ordinal,
                            ),
                            dataset_key=request.dataset_key,
                            source_key=source_key,
                            trade_date=current_date,
                            request_params=contract.source_spec.unit_params_builder(
                                request,
                                current_date,
                                merged_values,
                            ),
                            pagination_policy="offset_limit",
                            page_limit=STK_MINS_SOURCE_PAGE_LIMIT,
                        )
                    )
                    ordinal += 1
    return units
