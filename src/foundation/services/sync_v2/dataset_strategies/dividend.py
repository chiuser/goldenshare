from __future__ import annotations

from datetime import date, timedelta

from src.foundation.services.sync_v2.strategy_helpers.param_format import (
    build_plan_units,
    resolve_enum_combinations,
)
from src.utils import parse_tushare_date


def _expand_natural_dates(start_date: date, end_date: date) -> list[date]:
    current = start_date
    dates: list[date] = []
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def build_dividend_units(request, contract, dao, settings, session):
    if request.run_profile == "snapshot_refresh":
        anchors: list[date | None] = [None]
    elif request.run_profile == "range_rebuild":
        explicit_ann_date = parse_tushare_date(request.params.get("ann_date"))
        if explicit_ann_date is not None:
            anchors = [explicit_ann_date]
        else:
            if request.start_date is None or request.end_date is None:
                raise RuntimeError("dividend range_rebuild requires start_date and end_date")
            anchors = _expand_natural_dates(request.start_date, request.end_date)
    else:
        raise RuntimeError(f"dividend unsupported run_profile: {request.run_profile}")

    enum_combinations = resolve_enum_combinations(request=request, fields=())
    return build_plan_units(
        request=request,
        contract=contract,
        anchors=anchors,
        enum_combinations=enum_combinations,
        pagination_policy_override="offset_limit",
        page_limit_override=6000,
    )
