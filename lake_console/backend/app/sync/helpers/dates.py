from __future__ import annotations

from calendar import monthrange
from datetime import date
from datetime import timedelta
from pathlib import Path

from lake_console.backend.app.services.parquet_writer import read_parquet_rows
from lake_console.backend.app.sync.helpers.params import parse_date


STK_PERIOD_BAR_WEEK_DATASETS = frozenset({"stk_period_bar_week", "stk_period_bar_adj_week"})
STK_PERIOD_BAR_MONTH_DATASETS = frozenset({"stk_period_bar_month", "stk_period_bar_adj_month"})
INDEX_PERIOD_WEEK_DATASETS = frozenset({"index_weekly"})
INDEX_PERIOD_MONTH_DATASETS = frozenset({"index_monthly"})
_SPECIAL_MONTH_NORMALIZED_DATE = date(2020, 2, 28)
_SPECIAL_MONTH_IGNORED_DATE = date(2020, 2, 29)


def load_open_trade_dates(*, lake_root: Path, start_date: date, end_date: date) -> list[date]:
    calendar_file = lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
    if not calendar_file.exists():
        raise RuntimeError(
            "缺少本地交易日历 manifest/trading_calendar/tushare_trade_cal.parquet。"
            "请先执行 sync-trade-cal。"
        )
    rows = read_parquet_rows(calendar_file)
    trade_dates: list[date] = []
    for row in rows:
        if not bool(row.get("is_open")):
            continue
        current_date = parse_date(row.get("cal_date"))
        if start_date <= current_date <= end_date:
            trade_dates.append(current_date)
    return sorted(set(trade_dates))


def resolve_expected_partition_date(*, lake_root: Path, dataset_key: str, trade_date: date) -> date:
    if dataset_key in STK_PERIOD_BAR_WEEK_DATASETS:
        if trade_date.weekday() != 4:
            raise RuntimeError(f"{dataset_key} 要求使用自然周周五锚点。")
        _require_open_trade_day_in_bucket(
            lake_root=lake_root,
            bucket_value=trade_date,
            bucket_window_rule="iso_week",
            dataset_key=dataset_key,
        )
        return trade_date
    if dataset_key in STK_PERIOD_BAR_MONTH_DATASETS:
        if trade_date == _SPECIAL_MONTH_IGNORED_DATE:
            raise RuntimeError(f"{dataset_key} 的 2020-02 异常月只允许使用 2020-02-28，不允许使用 2020-02-29。")
        month_last_day = monthrange(trade_date.year, trade_date.month)[1]
        if trade_date.day != month_last_day and trade_date != _SPECIAL_MONTH_NORMALIZED_DATE:
            raise RuntimeError(f"{dataset_key} 要求使用自然月月末锚点。")
        _require_open_trade_day_in_bucket(
            lake_root=lake_root,
            bucket_value=trade_date,
            bucket_window_rule="natural_month",
            dataset_key=dataset_key,
        )
        return trade_date
    if dataset_key in INDEX_PERIOD_WEEK_DATASETS:
        return _resolve_last_open_trade_day_anchor(
            lake_root=lake_root,
            dataset_key=dataset_key,
            trade_date=trade_date,
            bucket_window_rule="iso_week",
            error_label="周最后开市日锚点",
        )
    if dataset_key in INDEX_PERIOD_MONTH_DATASETS:
        return _resolve_last_open_trade_day_anchor(
            lake_root=lake_root,
            dataset_key=dataset_key,
            trade_date=trade_date,
            bucket_window_rule="natural_month",
            error_label="月最后开市日锚点",
        )

    dates = load_open_trade_dates(lake_root=lake_root, start_date=trade_date, end_date=trade_date)
    if not dates:
        raise RuntimeError(f"本地交易日历中 {trade_date.isoformat()} 不是开市日。")
    return dates[0]


def load_expected_partition_dates(
    *,
    lake_root: Path,
    dataset_key: str,
    start_date: date,
    end_date: date,
) -> list[date]:
    if dataset_key in STK_PERIOD_BAR_WEEK_DATASETS:
        anchors = _expand_calendar_week_fridays(start_date=start_date, end_date=end_date)
        return _filter_anchors_by_bucket_open_trade_days(
            lake_root=lake_root,
            anchors=anchors,
            bucket_window_rule="iso_week",
        )
    if dataset_key in STK_PERIOD_BAR_MONTH_DATASETS:
        anchors = _expand_calendar_month_ends(start_date=start_date, end_date=end_date)
        filtered = _filter_anchors_by_bucket_open_trade_days(
            lake_root=lake_root,
            anchors=anchors,
            bucket_window_rule="natural_month",
        )
        normalized = [
            _SPECIAL_MONTH_NORMALIZED_DATE if item == _SPECIAL_MONTH_IGNORED_DATE else item
            for item in filtered
        ]
        return sorted(set(normalized))
    if dataset_key in INDEX_PERIOD_WEEK_DATASETS:
        return _load_last_open_trade_day_anchors(
            lake_root=lake_root,
            start_date=start_date,
            end_date=end_date,
            bucket_window_rule="iso_week",
        )
    if dataset_key in INDEX_PERIOD_MONTH_DATASETS:
        return _load_last_open_trade_day_anchors(
            lake_root=lake_root,
            start_date=start_date,
            end_date=end_date,
            bucket_window_rule="natural_month",
        )

    dates = load_open_trade_dates(lake_root=lake_root, start_date=start_date, end_date=end_date)
    if not dates:
        raise RuntimeError(f"本地交易日历中 {start_date.isoformat()} ~ {end_date.isoformat()} 没有开市日。")
    return dates


def _filter_anchors_by_bucket_open_trade_days(
    *,
    lake_root: Path,
    anchors: list[date],
    bucket_window_rule: str,
) -> list[date]:
    if not anchors:
        return []
    window_start, _ = _bucket_window(anchors[0], bucket_window_rule)
    _, window_end = _bucket_window(anchors[-1], bucket_window_rule)
    open_trade_date_set = set(load_open_trade_dates(lake_root=lake_root, start_date=window_start, end_date=window_end))
    filtered: list[date] = []
    for anchor in anchors:
        anchor_window_start, anchor_window_end = _bucket_window(anchor, bucket_window_rule)
        if any(anchor_window_start <= open_trade_date <= anchor_window_end for open_trade_date in open_trade_date_set):
            filtered.append(anchor)
    return filtered


def _require_open_trade_day_in_bucket(
    *,
    lake_root: Path,
    bucket_value: date,
    bucket_window_rule: str,
    dataset_key: str,
) -> None:
    window_start, window_end = _bucket_window(bucket_value, bucket_window_rule)
    dates = load_open_trade_dates(lake_root=lake_root, start_date=window_start, end_date=window_end)
    if dates:
        return
    if bucket_window_rule == "iso_week":
        raise RuntimeError(f"{dataset_key} 的 {bucket_value.isoformat()} 所在自然周没有开市交易日。")
    raise RuntimeError(f"{dataset_key} 的 {bucket_value.isoformat()} 所在自然月没有开市交易日。")


def _bucket_window(bucket_value: date, bucket_window_rule: str) -> tuple[date, date]:
    if bucket_window_rule == "iso_week":
        window_start = bucket_value - timedelta(days=bucket_value.weekday())
        return window_start, window_start + timedelta(days=6)
    if bucket_window_rule == "natural_month":
        window_start = date(bucket_value.year, bucket_value.month, 1)
        return window_start, date(bucket_value.year, bucket_value.month, monthrange(bucket_value.year, bucket_value.month)[1])
    raise ValueError(f"不支持的日期桶窗口规则：{bucket_window_rule}")


def _expand_calendar_week_fridays(*, start_date: date, end_date: date) -> list[date]:
    days_until_friday = (4 - start_date.weekday()) % 7
    current = start_date + timedelta(days=days_until_friday)
    anchors: list[date] = []
    while current <= end_date:
        anchors.append(current)
        current += timedelta(days=7)
    return anchors


def _expand_calendar_month_ends(*, start_date: date, end_date: date) -> list[date]:
    current = date(
        start_date.year,
        start_date.month,
        monthrange(start_date.year, start_date.month)[1],
    )
    anchors: list[date] = []
    while current <= end_date:
        if current >= start_date:
            anchors.append(current)
        next_month = date(
            current.year + (1 if current.month == 12 else 0),
            1 if current.month == 12 else current.month + 1,
            1,
        )
        current = date(
            next_month.year,
            next_month.month,
            monthrange(next_month.year, next_month.month)[1],
        )
    return anchors


def _resolve_last_open_trade_day_anchor(
    *,
    lake_root: Path,
    dataset_key: str,
    trade_date: date,
    bucket_window_rule: str,
    error_label: str,
) -> date:
    window_start, window_end = _bucket_window(trade_date, bucket_window_rule)
    dates = load_open_trade_dates(lake_root=lake_root, start_date=window_start, end_date=window_end)
    if not dates:
        raise RuntimeError(f"{dataset_key} 的 {trade_date.isoformat()} 所在日期桶没有开市交易日。")
    expected = max(dates)
    if trade_date != expected:
        raise RuntimeError(f"{dataset_key} 要求使用{error_label}。")
    return expected


def _load_last_open_trade_day_anchors(
    *,
    lake_root: Path,
    start_date: date,
    end_date: date,
    bucket_window_rule: str,
) -> list[date]:
    first_window_start, _ = _bucket_window(start_date, bucket_window_rule)
    _, last_window_end = _bucket_window(end_date, bucket_window_rule)
    open_dates = load_open_trade_dates(lake_root=lake_root, start_date=first_window_start, end_date=last_window_end)
    anchors_by_bucket: dict[tuple[int, int], date] = {}
    for open_date in open_dates:
        anchors_by_bucket[_bucket_group_key(open_date, bucket_window_rule)] = open_date
    anchors = [anchor for anchor in anchors_by_bucket.values() if start_date <= anchor <= end_date]
    if not anchors:
        raise RuntimeError(f"本地交易日历中 {start_date.isoformat()} ~ {end_date.isoformat()} 没有可导出的锚点日期。")
    return sorted(anchors)


def _bucket_group_key(current_date: date, bucket_window_rule: str) -> tuple[int, int]:
    if bucket_window_rule == "iso_week":
        iso = current_date.isocalendar()
        return iso.year, iso.week
    if bucket_window_rule == "natural_month":
        return current_date.year, current_date.month
    raise ValueError(f"不支持的日期桶窗口规则：{bucket_window_rule}")
