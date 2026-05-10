from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import (
    WealthMarketTurnoverSnapshot,
)
from src.ops.catalog.biz_table_catalog import (
    BIZ_TABLE_SOURCE_DISPLAY_NAME,
    BIZ_TABLE_SOURCE_KEY,
    BizTableCatalogItem,
    list_biz_table_catalog_items,
)
from src.ops.schemas.dataset_card import (
    DatasetCardGroup,
    DatasetCardItem,
    DatasetCardListResponse,
    DatasetCardStageStatus,
)


_CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
_POST_CLOSE_READY_TIME = time(hour=20, minute=0)


@dataclass(frozen=True, slots=True)
class BizTableObservation:
    earliest_business_date: date | None
    latest_business_date: date | None
    latest_success_at: datetime | None
    latest_observed_at: datetime | None
    row_count: int


@dataclass(frozen=True, slots=True)
class BizTableFreshness:
    status: str
    freshness_status: str
    expected_business_date: date | None
    lag_days: int | None
    note: str


class BizTableCardQueryService:
    """Build read-only Ops cards for internally produced Biz tables."""

    def list_cards(self, session: Session, *, limit: int = 2000) -> DatasetCardListResponse:
        limit = max(1, min(limit, 2000))
        cards = [
            self._build_card(session, item)
            for item in sorted(list_biz_table_catalog_items(), key=lambda value: (value.group_order, value.item_order, value.table_key))
        ]
        sliced = cards[:limit]
        return DatasetCardListResponse(total=len(cards), groups=self._group_cards(sliced))

    def _build_card(self, session: Session, item: BizTableCatalogItem) -> DatasetCardItem:
        observation = self._load_observation(session, item)
        freshness = self._build_freshness(session, observation)
        stage_status = DatasetCardStageStatus(
            stage="biz_table",
            stage_label="Biz表",
            table_name=item.table_name,
            source_key=BIZ_TABLE_SOURCE_KEY,
            source_display_name=BIZ_TABLE_SOURCE_DISPLAY_NAME,
            status=freshness.status,
            rows_in=None,
            rows_out=observation.row_count,
            error_count=0,
            lag_seconds=None,
            message=freshness.note,
            calculated_at=observation.latest_success_at,
            last_success_at=observation.latest_success_at,
            last_failure_at=None,
        )

        return DatasetCardItem(
            card_key=item.table_key,
            dataset_key=item.table_key,
            detail_dataset_key=item.table_key,
            resource_key=item.table_key,
            display_name=item.display_name,
            group_key=item.group_key,
            group_label=item.group_label,
            group_order=item.group_order,
            item_order=item.item_order,
            domain_key=BIZ_TABLE_SOURCE_KEY,
            domain_display_name=BIZ_TABLE_SOURCE_DISPLAY_NAME,
            status=freshness.status,
            freshness_status=freshness.freshness_status,
            delivery_mode="biz_table_snapshot",
            delivery_mode_label="业务派生表",
            delivery_mode_tone="info",
            layer_plan=BIZ_TABLE_SOURCE_KEY,
            cadence="derived",
            cadence_display_name="业务派生",
            raw_table=None,
            raw_table_label=None,
            target_table=item.table_name,
            latest_business_date=observation.latest_business_date,
            earliest_business_date=observation.earliest_business_date,
            latest_observed_at=observation.latest_observed_at,
            earliest_observed_at=None,
            last_sync_date=None,
            latest_success_at=observation.latest_success_at,
            expected_business_date=freshness.expected_business_date,
            lag_days=freshness.lag_days,
            freshness_note=freshness.note,
            primary_action_key=None,
            active_task_run_status=None,
            active_task_run_started_at=None,
            auto_schedule_status="none",
            auto_schedule_total=0,
            auto_schedule_active=0,
            auto_schedule_next_run_at=None,
            probe_total=0,
            probe_active=0,
            std_mapping_configured=False,
            std_cleansing_configured=False,
            resolution_policy_configured=False,
            status_updated_at=observation.latest_success_at,
            stage_statuses=[stage_status],
            raw_sources=[],
        )

    def _load_observation(self, session: Session, item: BizTableCatalogItem) -> BizTableObservation:
        if item.status_policy_key != "wealth_turnover_snapshot":
            raise ValueError(f"unsupported biz table status policy: {item.status_policy_key}")

        row = session.execute(
            select(
                func.min(WealthMarketTurnoverSnapshot.trade_date),
                func.max(WealthMarketTurnoverSnapshot.trade_date),
                func.max(WealthMarketTurnoverSnapshot.built_at),
                func.max(WealthMarketTurnoverSnapshot.latest_trade_time),
                func.count(),
            ).where(
                WealthMarketTurnoverSnapshot.type == "stock",
                WealthMarketTurnoverSnapshot.market == "CN_A",
                WealthMarketTurnoverSnapshot.build_status == "READY",
            )
        ).one()
        earliest_date, latest_date, latest_success_at, latest_observed_at, row_count = row
        return BizTableObservation(
            earliest_business_date=earliest_date,
            latest_business_date=latest_date,
            latest_success_at=latest_success_at,
            latest_observed_at=latest_observed_at,
            row_count=int(row_count or 0),
        )

    def _build_freshness(self, session: Session, observation: BizTableObservation) -> BizTableFreshness:
        expected_date = self._expected_business_date(session)
        if observation.latest_business_date is None:
            return BizTableFreshness(
                status="unknown",
                freshness_status="unknown",
                expected_business_date=expected_date,
                lag_days=None,
                note="暂无 READY 快照。",
            )
        if expected_date is None:
            return BizTableFreshness(
                status="unknown",
                freshness_status="unknown",
                expected_business_date=None,
                lag_days=None,
                note="缺少交易日历，无法判断期望业务日。",
            )
        if observation.latest_business_date >= expected_date:
            return BizTableFreshness(
                status="healthy",
                freshness_status="fresh",
                expected_business_date=expected_date,
                lag_days=0,
                note=f"最新快照 {observation.latest_business_date.isoformat()}，期望 {expected_date.isoformat()}，已就绪。",
            )

        lag_days = self._trading_day_lag(session, latest_date=observation.latest_business_date, expected_date=expected_date)
        if lag_days <= 1:
            return BizTableFreshness(
                status="warning",
                freshness_status="lagging",
                expected_business_date=expected_date,
                lag_days=lag_days,
                note=f"最新快照 {observation.latest_business_date.isoformat()}，期望 {expected_date.isoformat()}，滞后 {lag_days} 个交易日。",
            )
        return BizTableFreshness(
            status="stale",
            freshness_status="stale",
            expected_business_date=expected_date,
            lag_days=lag_days,
            note=f"最新快照 {observation.latest_business_date.isoformat()}，期望 {expected_date.isoformat()}，滞后 {lag_days} 个交易日。",
        )

    def _expected_business_date(self, session: Session) -> date | None:
        exchange = get_settings().default_exchange
        local_now = datetime.now(_CN_TIMEZONE)
        today = local_now.date()
        today_row = session.scalar(
            select(TradeCalendar).where(
                TradeCalendar.exchange == exchange,
                TradeCalendar.trade_date == today,
            )
        )
        if today_row is not None and today_row.is_open:
            if local_now.timetz().replace(tzinfo=None) >= _POST_CLOSE_READY_TIME:
                return today
            if today_row.pretrade_date is not None:
                return today_row.pretrade_date
            return self._latest_open_date(session, exchange=exchange, before_or_on=today, strict_before=True)
        return self._latest_open_date(session, exchange=exchange, before_or_on=today, strict_before=False)

    @staticmethod
    def _latest_open_date(
        session: Session,
        *,
        exchange: str,
        before_or_on: date,
        strict_before: bool,
    ) -> date | None:
        stmt = select(func.max(TradeCalendar.trade_date)).where(
            TradeCalendar.exchange == exchange,
            TradeCalendar.is_open.is_(True),
        )
        if strict_before:
            stmt = stmt.where(TradeCalendar.trade_date < before_or_on)
        else:
            stmt = stmt.where(TradeCalendar.trade_date <= before_or_on)
        return session.scalar(stmt)

    @staticmethod
    def _trading_day_lag(session: Session, *, latest_date: date, expected_date: date) -> int:
        exchange = get_settings().default_exchange
        count = session.scalar(
            select(func.count()).where(
                TradeCalendar.exchange == exchange,
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date > latest_date,
                TradeCalendar.trade_date <= expected_date,
            )
        )
        if count:
            return int(count)
        return max((expected_date - latest_date).days, 0)

    @staticmethod
    def _group_cards(cards: list[DatasetCardItem]) -> list[DatasetCardGroup]:
        grouped: dict[tuple[int, str, str], list[DatasetCardItem]] = {}
        for item in cards:
            grouped.setdefault((item.group_order, item.group_key, item.group_label), []).append(item)
        return [
            DatasetCardGroup(group_key=group_key, group_label=group_label, group_order=group_order, items=items)
            for (group_order, group_key, group_label), items in sorted(grouped.items(), key=lambda entry: (entry[0][0], entry[0][2]))
        ]
