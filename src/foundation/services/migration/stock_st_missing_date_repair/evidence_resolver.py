from __future__ import annotations

from src.foundation.services.migration.stock_st_missing_date_repair.membership_resolver import is_st_like_name
from src.foundation.services.migration.stock_st_missing_date_repair.models import (
    StockStEventRecord,
    StockStNamechangeRecord,
    StockStResolvedCandidate,
    StockStReviewItem,
)


def resolve_candidate(
    *,
    trade_date,
    ts_code: str,
    prev_name: str | None,
    next_name: str | None,
    same_day_st_events: tuple[StockStEventRecord, ...],
    active_namechanges: tuple[StockStNamechangeRecord, ...],
) -> tuple[StockStResolvedCandidate, StockStReviewItem | None]:
    selected_namechange = active_namechanges[0] if active_namechanges else None
    active_count = len(active_namechanges)
    stable_name = prev_name if prev_name and next_name and prev_name == next_name else None

    if selected_namechange is None:
        review = StockStReviewItem(
            trade_date=trade_date,
            ts_code=ts_code,
            review_code="missing_namechange_interval",
            review_message="候选代码在缺失日没有命中的 namechange 区间，无法自动判定。",
            prev_name=prev_name,
            next_name=next_name,
            selected_namechange=None,
            same_day_st_events=same_day_st_events,
        )
        candidate = StockStResolvedCandidate(
            trade_date=trade_date,
            ts_code=ts_code,
            include=False,
            resolved_name=None,
            name_source=None,
            prev_name=prev_name,
            next_name=next_name,
            selected_namechange=None,
            active_namechange_row_count=0,
            same_day_st_events=same_day_st_events,
            validation_status="not_ok_missing_namechange_interval",
            validation_message=review.review_message,
        )
        return candidate, review

    selected_is_st = is_st_like_name(selected_namechange.name)
    same_day_event_names = [event.name for event in same_day_st_events if event.name]
    has_same_day_st_like_name = any(is_st_like_name(name) for name in same_day_event_names)

    if not selected_is_st:
        review = None
        status = "excluded_non_st_namechange"
        message = "最新有效 namechange 记录已不是 ST，候选代码不写入缺失日快照。"
        if same_day_event_names and has_same_day_st_like_name:
            review = StockStReviewItem(
                trade_date=trade_date,
                ts_code=ts_code,
                review_code="same_day_st_event_conflicts_with_non_st_namechange",
                review_message="同日 st 事件名称仍显示 ST-like，但最新有效 namechange 已判为非 ST，需要人工确认。",
                prev_name=prev_name,
                next_name=next_name,
                selected_namechange=selected_namechange,
                same_day_st_events=same_day_st_events,
            )
            status = "not_ok_same_day_st_event_conflicts_with_non_st_namechange"
            message = review.review_message
        candidate = StockStResolvedCandidate(
            trade_date=trade_date,
            ts_code=ts_code,
            include=False,
            resolved_name=None,
            name_source=None,
            prev_name=prev_name,
            next_name=next_name,
            selected_namechange=selected_namechange,
            active_namechange_row_count=active_count,
            same_day_st_events=same_day_st_events,
            validation_status=status,
            validation_message=message,
        )
        return candidate, review

    resolved_name = None
    name_source = None
    if stable_name and stable_name == selected_namechange.name:
        resolved_name = stable_name
        name_source = "stable_snapshot"
    elif selected_namechange.name:
        resolved_name = selected_namechange.name
        name_source = "namechange"
    elif same_day_event_names:
        resolved_name = same_day_event_names[0]
        name_source = "st"

    if not resolved_name:
        review = StockStReviewItem(
            trade_date=trade_date,
            ts_code=ts_code,
            review_code="missing_resolved_name",
            review_message="已判定为 ST，但无法给出输出名称，需要人工确认。",
            prev_name=prev_name,
            next_name=next_name,
            selected_namechange=selected_namechange,
            same_day_st_events=same_day_st_events,
        )
        candidate = StockStResolvedCandidate(
            trade_date=trade_date,
            ts_code=ts_code,
            include=False,
            resolved_name=None,
            name_source=None,
            prev_name=prev_name,
            next_name=next_name,
            selected_namechange=selected_namechange,
            active_namechange_row_count=active_count,
            same_day_st_events=same_day_st_events,
            validation_status="not_ok_missing_resolved_name",
            validation_message=review.review_message,
        )
        return candidate, review

    if same_day_event_names and not has_same_day_st_like_name:
        review = StockStReviewItem(
            trade_date=trade_date,
            ts_code=ts_code,
            review_code="same_day_st_event_non_st_name",
            review_message="同日 st 事件名称不再是 ST-like，但 namechange 仍判定为 ST，需要人工确认。",
            prev_name=prev_name,
            next_name=next_name,
            selected_namechange=selected_namechange,
            same_day_st_events=same_day_st_events,
        )
        status = "not_ok_same_day_st_event_non_st_name"
        message = review.review_message
    elif same_day_st_events:
        review = None
        status = "ok_same_day_st_event"
        message = "同日存在 st 事件，且事件名称与 ST 判定不冲突。"
    else:
        review = None
        status = "ok_no_same_day_st_event"
        message = "缺失日没有同日 st 事件，按 namechange 主事实重建。"

    candidate = StockStResolvedCandidate(
        trade_date=trade_date,
        ts_code=ts_code,
        include=review is None,
        resolved_name=resolved_name if review is None else None,
        name_source=name_source if review is None else None,
        prev_name=prev_name,
        next_name=next_name,
        selected_namechange=selected_namechange,
        active_namechange_row_count=active_count,
        same_day_st_events=same_day_st_events,
        validation_status=status,
        validation_message=message,
    )
    return candidate, review

