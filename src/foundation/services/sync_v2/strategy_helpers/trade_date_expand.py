from __future__ import annotations

from datetime import date

from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    ValidatedRunRequest,
    resolve_contract_anchor_type,
    resolve_contract_window_policy,
)


def compress_to_week_end(open_dates: list[date]) -> list[date]:
    latest_by_week: dict[tuple[int, int], date] = {}
    for item in open_dates:
        iso_year, iso_week, _ = item.isocalendar()
        latest_by_week[(iso_year, iso_week)] = item
    return [latest_by_week[key] for key in sorted(latest_by_week.keys())]


def compress_to_month_end(open_dates: list[date]) -> list[date]:
    latest_by_month: dict[tuple[int, int], date] = {}
    for item in open_dates:
        latest_by_month[(item.year, item.month)] = item
    return [latest_by_month[key] for key in sorted(latest_by_month.keys())]


def resolve_anchors(
    *,
    request: ValidatedRunRequest,
    contract: DatasetSyncContract,
    dao,
    settings,
    anchor_type_override: str | None = None,
    window_policy_override: str | None = None,
) -> list[date | None]:
    anchor_type = anchor_type_override or resolve_contract_anchor_type(contract)
    window_policy = window_policy_override or resolve_contract_window_policy(contract)

    if request.run_profile == "snapshot_refresh":
        return [None]

    if request.run_profile == "point_incremental":
        if window_policy not in {"point", "point_or_range"}:
            raise RuntimeError(
                f"run_profile=point_incremental is not allowed for window_policy={window_policy}"
            )
        if anchor_type in {
            "trade_date",
            "week_end_trade_date",
            "month_end_trade_date",
            "month_key_yyyymm",
            "month_range_natural",
            "natural_date_range",
        }:
            return [request.trade_date]
        return [None]

    if request.run_profile != "range_rebuild":
        return [request.trade_date]

    if window_policy not in {"range", "point_or_range"}:
        raise RuntimeError(
            f"run_profile=range_rebuild is not allowed for window_policy={window_policy}"
        )

    if request.start_date is None or request.end_date is None:
        raise RuntimeError("range_rebuild requires start_date and end_date")

    if anchor_type in {"none", "month_range_natural", "natural_date_range"}:
        return [None]

    exchange = str(request.params.get("exchange") or settings.default_exchange)
    open_dates = dao.trade_calendar.get_open_dates(exchange, request.start_date, request.end_date)

    if anchor_type == "trade_date":
        return list(open_dates)
    if anchor_type == "week_end_trade_date":
        return compress_to_week_end(list(open_dates))
    if anchor_type in {"month_end_trade_date", "month_key_yyyymm"}:
        return compress_to_month_end(list(open_dates))
    raise RuntimeError(f"unsupported anchor_type={anchor_type}")

