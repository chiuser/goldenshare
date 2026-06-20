from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from src.foundation.config.settings import get_settings
from src.foundation.dao.factory import DAOFactory
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.errors import IngestionPlanningError, StructuredError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot, ValidatedDatasetActionRequest
from src.foundation.ingestion import request_builders
from src.foundation.ingestion.plan_helpers import build_plan_units, build_unit_id, resolve_enum_combinations, split_multi_values
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.raw.raw_stk_factor_pro import RawStkFactorPro
from src.foundation.models.raw_multi.raw_biying_stock_basic import RawBiyingStockBasic


CYQ_CHIPS_RANGE_WINDOW_DAYS = 1095
ETF_SH_CONS_RESOURCE = "etf_sh_cons"


class DatasetUnitPlanner:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dao = DAOFactory(session)
        self.settings = get_settings()

    def plan(self, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> tuple[PlanUnitSnapshot, ...]:
        builder_key = definition.planning.unit_builder_key or "generic"
        builder = _CUSTOM_UNIT_BUILDERS.get(builder_key)
        if builder is None:
            units = self._build_generic_units(request, definition)
        else:
            units = builder(self, request, definition)

        max_units = definition.planning.max_units_per_execution
        if max_units is not None and len(units) > max_units:
            raise IngestionPlanningError(
                StructuredError(
                    error_code="units_exceeded",
                    error_type="planning",
                    phase="planner",
                    message=f"planned units={len(units)} exceeds max_units_per_execution={max_units}",
                    retryable=False,
                )
            )
        return tuple(units)

    def _build_generic_units(
        self,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
    ) -> list[PlanUnitSnapshot]:
        request_builder = self._resolve_request_builder(definition)
        anchors = self._resolve_anchors(request, definition)
        enum_combinations = resolve_enum_combinations(
            request=request,
            fields=definition.planning.enum_fanout_fields,
            missing_field_defaults=definition.planning.enum_fanout_defaults,
        )
        units: list[PlanUnitSnapshot] = []
        for anchor in anchors:
            universe_values = self._resolve_universe_values(request, definition, anchor)
            units.extend(
                build_plan_units(
                    request=request,
                    definition=definition,
                    anchors=[anchor],
                    enum_combinations=enum_combinations,
                    request_builder=request_builder,
                    universe_values=universe_values,
                    pagination_policy_override=definition.planning.pagination_policy,
                    page_limit_override=definition.planning.page_limit,
                    progress_context_builder=self._build_generic_progress_context,
                )
            )
        return units

    def _resolve_anchors(
        self,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
    ) -> list[date | None]:
        date_model = definition.date_model
        if request.run_profile == "snapshot_refresh":
            return [None]
        if request.run_profile == "point_incremental":
            if date_model.input_shape == "month_or_range":
                return [request.trade_date]
            if date_model.date_axis in {"trade_open_day", "natural_day", "month_window"}:
                return [request.trade_date]
            return [None]
        if request.run_profile != "range_rebuild":
            return [request.trade_date]

        if request.start_date is None or request.end_date is None:
            raise IngestionPlanningError(
                StructuredError(
                    error_code="range_required",
                    error_type="planning",
                    phase="planner",
                    message="区间维护必须同时填写开始日期和结束日期",
                    retryable=False,
                )
            )
        if date_model.date_axis == "natural_day":
            if date_model.bucket_rule == "week_friday":
                return self._expand_calendar_week_fridays(request.start_date, request.end_date)
            if date_model.bucket_rule == "month_last_calendar_day":
                return self._expand_calendar_month_ends(request.start_date, request.end_date)
            return [None]
        if date_model.date_axis in {"none", "month_window"}:
            return [None]
        open_dates = self.dao.trade_calendar.get_open_dates(
            str(request.params.get("exchange") or self.settings.default_exchange),
            request.start_date,
            request.end_date,
        )
        if date_model.bucket_rule == "every_open_day":
            return list(open_dates)
        if date_model.bucket_rule == "week_last_open_day":
            return self._compress_to_week_end(open_dates)
        if date_model.bucket_rule == "month_last_open_day":
            return self._compress_to_month_end(open_dates)
        return [None]

    @staticmethod
    def _compress_to_week_end(open_dates: list[date]) -> list[date]:
        latest_by_week: dict[tuple[int, int], date] = {}
        for item in open_dates:
            iso_year, iso_week, _ = item.isocalendar()
            latest_by_week[(iso_year, iso_week)] = item
        return [latest_by_week[key] for key in sorted(latest_by_week)]

    @staticmethod
    def _compress_to_month_end(open_dates: list[date]) -> list[date]:
        latest_by_month: dict[tuple[int, int], date] = {}
        for item in open_dates:
            latest_by_month[(item.year, item.month)] = item
        return [latest_by_month[key] for key in sorted(latest_by_month)]

    @staticmethod
    def _expand_calendar_week_fridays(start_date: date, end_date: date) -> list[date]:
        days_until_friday = (4 - start_date.weekday()) % 7
        current = start_date + timedelta(days=days_until_friday)
        anchors: list[date] = []
        while current <= end_date:
            anchors.append(current)
            current += timedelta(days=7)
        return anchors

    @staticmethod
    def _expand_calendar_month_ends(start_date: date, end_date: date) -> list[date]:
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

    def _resolve_universe_values(
        self,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        anchor: date | None,
    ) -> list[dict[str, Any]]:
        policy = definition.planning.universe_policy
        if policy in {"none", "no_pool"}:
            return [{}]
        raise self._planning_error("unknown_universe_policy", f"不支持的维护对象展开规则：{policy}")

    def _load_board_codes_from_dc_index(self, *, anchor: date, idx_types: list[str]) -> list[str]:
        stmt = select(DcIndex.ts_code).where(DcIndex.trade_date == anchor)
        if idx_types:
            stmt = stmt.where(DcIndex.idx_type.in_(idx_types))
        codes = [str(item).strip().upper() for item in self.session.scalars(stmt.distinct().order_by(DcIndex.ts_code)) if str(item).strip()]
        return sorted(set(codes))

    def _load_board_codes_from_dc_index_range(
        self,
        *,
        start_date: date,
        end_date: date,
        idx_types: list[str],
    ) -> list[str]:
        stmt = select(DcIndex.ts_code).where(DcIndex.trade_date >= start_date, DcIndex.trade_date <= end_date)
        if idx_types:
            stmt = stmt.where(DcIndex.idx_type.in_(idx_types))
        codes = [str(item).strip().upper() for item in self.session.scalars(stmt.distinct().order_by(DcIndex.ts_code)) if str(item).strip()]
        return sorted(set(codes))

    @staticmethod
    def _build_generic_progress_context(anchor: date | None, merged_values: dict[str, Any], request_params: dict[str, Any]) -> dict[str, Any]:
        context: dict[str, Any] = {}
        for key in ("ts_code", "con_code", "index_code", "board_code", "freq", "start_date", "end_date"):
            value = merged_values.get(key, request_params.get(key))
            if value not in (None, ""):
                context[key] = value
        if anchor is not None:
            context.setdefault("trade_date", anchor.isoformat())
        if len(merged_values) == 1:
            key, value = next(iter(merged_values.items()))
            if value not in (None, "") and key not in {"ts_code", "con_code", "index_code", "board_code"}:
                context["enum_field"] = key
                context["enum_value"] = value
        return context

    @staticmethod
    def _resolve_request_builder(definition: DatasetDefinition) -> Callable[[ValidatedDatasetActionRequest, date | None, dict[str, Any]], dict[str, Any]]:
        builder = getattr(request_builders, definition.source.request_builder_key, None)
        if not callable(builder):
            raise IngestionPlanningError(
                StructuredError(
                    error_code="request_builder_not_found",
                    error_type="planning",
                    phase="planner",
                    message=f"request builder not found: {definition.source.request_builder_key}",
                    retryable=False,
                )
            )
        return builder

    @staticmethod
    def _planning_error(error_code: str, message: str) -> IngestionPlanningError:
        return IngestionPlanningError(
            StructuredError(
                error_code=error_code,
                error_type="planning",
                phase="planner",
                message=message,
                retryable=False,
            )
        )


def _resolve_index_codes(request: ValidatedDatasetActionRequest, dao) -> list[str]:  # type: ignore[no-untyped-def]
    explicit_codes = split_multi_values(request.params.get("ts_code"))
    if explicit_codes:
        return sorted({str(code).strip().upper() for code in explicit_codes if str(code).strip()})
    raw_pool_codes = dao.index_series_active.list_active_codes("index_daily_raw")
    normalized = sorted({str(code).strip().upper() for code in raw_pool_codes if str(code).strip()})
    if not normalized:
        raise DatasetUnitPlanner._planning_error("universe_empty", "未找到可维护的指数代码")
    return normalized


def _normalize_universe_codes(codes: list[Any]) -> list[str]:
    return sorted({str(code).strip().upper() for code in codes if str(code).strip()})


def _resolve_index_weight_universe_values(request: ValidatedDatasetActionRequest, definition: DatasetDefinition, dao) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
    if definition.planning.universe_policy != "pool" or definition.planning.universe is None:
        raise DatasetUnitPlanner._planning_error("invalid_universe_config", "指数权重缺少对象池规划配置")

    universe = definition.planning.universe
    request_field = str(universe.request_field or "").strip()
    if not request_field:
        raise DatasetUnitPlanner._planning_error("invalid_universe_config", "指数权重对象池缺少请求字段")

    for override_field in universe.override_fields:
        explicit_codes = _normalize_universe_codes(split_multi_values(request.params.get(override_field)))
        if explicit_codes:
            return [{request_field: code} for code in explicit_codes]

    for source in universe.sources:
        if source.type == "ops_index_series_active":
            resource = str(source.resource or "").strip()
            if not resource:
                raise DatasetUnitPlanner._planning_error("invalid_universe_config", "指数权重 active 池缺少 resource")
            codes = _normalize_universe_codes(dao.index_series_active.list_active_codes(resource))
        elif source.type == "core_index_basic_active":
            codes = _normalize_universe_codes([item.ts_code for item in dao.index_basic.get_active_indexes() if item.ts_code])
        else:
            raise DatasetUnitPlanner._planning_error("invalid_universe_source", f"指数权重不支持的对象池来源：{source.type}")
        if codes:
            return [{request_field: code} for code in codes]

    raise DatasetUnitPlanner._planning_error("universe_empty", "指数权重未找到可维护的指数代码")


def _resolve_dc_member_universe_values(
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
    anchor: date | None,
) -> list[dict[str, str]]:
    universe = definition.planning.universe
    if definition.planning.universe_policy != "pool" or universe is None:
        raise DatasetUnitPlanner._planning_error("invalid_universe_config", "东方财富板块成分缺少对象池规划配置")
    if universe.request_field != "ts_code" or universe.override_fields != ("ts_code", "con_code"):
        raise DatasetUnitPlanner._planning_error("invalid_universe_config", "东方财富板块成分对象池字段配置不符合当前主链")
    actual_sources = tuple((source.type, source.resource) for source in universe.sources)
    if actual_sources != (("core_dc_index_by_trade_date", "dc_index"),):
        raise DatasetUnitPlanner._planning_error("invalid_universe_source", "东方财富板块成分对象池来源配置不符合当前主链")

    explicit_ts_codes = _normalize_universe_codes(split_multi_values(request.params.get("ts_code")))
    if explicit_ts_codes:
        return [{"ts_code": code} for code in explicit_ts_codes]

    explicit_con_codes = _normalize_universe_codes(split_multi_values(request.params.get("con_code")))
    if explicit_con_codes:
        return [{"con_code": code} for code in explicit_con_codes]

    idx_types = split_multi_values(request.params.get("idx_type"))
    board_codes: list[str] = []
    if anchor is not None:
        board_codes = planner._load_board_codes_from_dc_index(anchor=anchor, idx_types=idx_types)
    elif request.trade_date is not None:
        board_codes = planner._load_board_codes_from_dc_index(anchor=request.trade_date, idx_types=idx_types)
    elif request.start_date is not None and request.end_date is not None:
        board_codes = planner._load_board_codes_from_dc_index_range(
            start_date=request.start_date,
            end_date=request.end_date,
            idx_types=idx_types,
        )
    if not board_codes:
        if anchor is None and request.trade_date is None and request.start_date is None and request.end_date is None:
            raise DatasetUnitPlanner._planning_error(
                "trade_date_anchor_required",
                "板块代码范围规划需要交易日期或起止日期",
            )
        raise DatasetUnitPlanner._planning_error(
            "universe_empty",
            "未找到指定日期范围内的东方财富板块代码；请先维护 dc_index 东方财富板块列表数据",
        )
    return [{"ts_code": code} for code in board_codes]


def _build_dc_member_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    anchors = planner._resolve_anchors(request, definition)
    units: list[PlanUnitSnapshot] = []
    for anchor in anchors:
        universe_values = _resolve_dc_member_universe_values(planner, request, definition, anchor)
        units.extend(
            build_plan_units(
                request=request,
                definition=definition,
                anchors=[anchor],
                enum_combinations=[{}],
                request_builder=request_builder,
                universe_values=universe_values,
                pagination_policy_override=definition.planning.pagination_policy,
                page_limit_override=definition.planning.page_limit,
                progress_context_builder=planner._build_generic_progress_context,
            )
        )
    return units


def _resolve_ths_member_universe_values(
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
) -> list[dict[str, str]]:
    universe = definition.planning.universe
    if definition.planning.universe_policy != "pool" or universe is None:
        raise DatasetUnitPlanner._planning_error("invalid_universe_config", "同花顺板块成分缺少对象池规划配置")
    if universe.request_field != "ts_code" or universe.override_fields != ("ts_code", "con_code"):
        raise DatasetUnitPlanner._planning_error("invalid_universe_config", "同花顺板块成分对象池字段配置不符合当前主链")
    actual_sources = tuple((source.type, source.resource) for source in universe.sources)
    if actual_sources != (("core_ths_index_snapshot", "ths_index"),):
        raise DatasetUnitPlanner._planning_error("invalid_universe_source", "同花顺板块成分对象池来源配置不符合当前主链")

    explicit_ts_codes = _normalize_universe_codes(split_multi_values(request.params.get("ts_code")))
    if explicit_ts_codes:
        return [{"ts_code": code} for code in explicit_ts_codes]

    explicit_con_codes = _normalize_universe_codes(split_multi_values(request.params.get("con_code")))
    if explicit_con_codes:
        return [{"con_code": code} for code in explicit_con_codes]

    stmt = select(ThsIndex.ts_code).distinct().order_by(ThsIndex.ts_code)
    codes = [str(item).strip().upper() for item in planner.session.scalars(stmt) if str(item).strip()]
    normalized_codes = sorted(set(codes))
    if not normalized_codes:
        raise DatasetUnitPlanner._planning_error(
            "universe_empty",
            "未找到可维护的同花顺板块代码；请先维护 ths_index 同花顺板块列表数据",
        )
    return [{"ts_code": code} for code in normalized_codes]


def _build_ths_member_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    anchors = planner._resolve_anchors(request, definition)
    universe_values = _resolve_ths_member_universe_values(planner, request, definition)
    return build_plan_units(
        request=request,
        definition=definition,
        anchors=anchors,
        enum_combinations=[{}],
        request_builder=request_builder,
        universe_values=universe_values,
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _expand_natural_dates(start_date: date, end_date: date) -> list[date]:
    current = start_date
    dates: list[date] = []
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _build_dividend_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    if request.run_profile == "snapshot_refresh":
        anchors: list[date | None] = [None]
    elif request.run_profile == "range_rebuild":
        explicit_ann_date = request.params.get("ann_date")
        if isinstance(explicit_ann_date, date):
            anchors = [explicit_ann_date]
        else:
            if request.start_date is None or request.end_date is None:
                raise DatasetUnitPlanner._planning_error("range_required", "分红送股区间维护必须同时填写开始日期和结束日期")
            anchors = _expand_natural_dates(request.start_date, request.end_date)
    else:
        raise DatasetUnitPlanner._planning_error("run_profile_unsupported", f"分红送股不支持该运行模式：{request.run_profile}")
    return build_plan_units(
        request=request,
        definition=definition,
        anchors=anchors,
        enum_combinations=[{}],
        request_builder=request_builder,
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _build_holdernumber_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    if request.run_profile == "snapshot_refresh":
        anchors: list[date | None] = [None]
    elif request.run_profile == "range_rebuild":
        explicit_ann_date = request.params.get("ann_date")
        if isinstance(explicit_ann_date, date):
            anchors = [explicit_ann_date]
        else:
            if request.start_date is None or request.end_date is None:
                raise DatasetUnitPlanner._planning_error("range_required", "股东户数区间维护必须同时填写开始日期和结束日期")
            anchors = _expand_natural_dates(request.start_date, request.end_date)
    else:
        raise DatasetUnitPlanner._planning_error("run_profile_unsupported", f"股东户数不支持该运行模式：{request.run_profile}")
    return build_plan_units(
        request=request,
        definition=definition,
        anchors=anchors,
        enum_combinations=[{}],
        request_builder=request_builder,
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _build_cctv_news_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    if request.run_profile == "point_incremental":
        if request.trade_date is None:
            raise DatasetUnitPlanner._planning_error("missing_anchor_fields", "新闻联播文字稿单日维护缺少日期")
        anchors: list[date | None] = [request.trade_date]
    elif request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise DatasetUnitPlanner._planning_error("range_required", "新闻联播文字稿区间维护必须同时填写开始日期和结束日期")
        anchors = _expand_natural_dates(request.start_date, request.end_date)
    else:
        raise DatasetUnitPlanner._planning_error("run_profile_unsupported", f"新闻联播文字稿不支持该运行模式：{request.run_profile}")
    return build_plan_units(
        request=request,
        definition=definition,
        anchors=anchors,
        enum_combinations=[{}],
        request_builder=request_builder,
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _build_major_news_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    enum_combinations = resolve_enum_combinations(
        request=request,
        fields=definition.planning.enum_fanout_fields,
        missing_field_defaults=definition.planning.enum_fanout_defaults,
    )
    if request.run_profile == "point_incremental":
        if request.trade_date is None:
            raise DatasetUnitPlanner._planning_error("missing_anchor_fields", "新闻通讯单日维护缺少日期")
        anchors: list[date | None] = [request.trade_date]
    elif request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise DatasetUnitPlanner._planning_error("range_required", "新闻通讯区间维护必须同时填写开始日期和结束日期")
        anchors = _expand_natural_dates(request.start_date, request.end_date)
    else:
        raise DatasetUnitPlanner._planning_error("run_profile_unsupported", f"新闻通讯不支持该运行模式：{request.run_profile}")
    return build_plan_units(
        request=request,
        definition=definition,
        anchors=anchors,
        enum_combinations=enum_combinations,
        request_builder=request_builder,
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _build_news_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    enum_combinations = resolve_enum_combinations(
        request=request,
        fields=definition.planning.enum_fanout_fields,
        missing_field_defaults=definition.planning.enum_fanout_defaults,
    )
    if request.run_profile == "point_incremental":
        if request.trade_date is None:
            raise DatasetUnitPlanner._planning_error("missing_anchor_fields", "新闻快讯单日维护缺少日期")
        anchors: list[date | None] = [request.trade_date]
    elif request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise DatasetUnitPlanner._planning_error("range_required", "新闻快讯区间维护必须同时填写开始日期和结束日期")
        anchors = _expand_natural_dates(request.start_date, request.end_date)
    else:
        raise DatasetUnitPlanner._planning_error("run_profile_unsupported", f"新闻快讯不支持该运行模式：{request.run_profile}")
    return build_plan_units(
        request=request,
        definition=definition,
        anchors=anchors,
        enum_combinations=enum_combinations,
        request_builder=request_builder,
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _build_index_daily_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    anchors = [request.trade_date] if request.run_profile == "point_incremental" else [None]
    universe_values = [{"ts_code": code} for code in _resolve_index_codes(request, planner.dao)]
    return build_plan_units(
        request=request,
        definition=definition,
        anchors=anchors,
        enum_combinations=[{}],
        request_builder=request_builder,
        universe_values=universe_values,
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _build_index_weight_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    universe_values = _resolve_index_weight_universe_values(request, definition, planner.dao)
    return build_plan_units(
        request=request,
        definition=definition,
        anchors=[None],
        enum_combinations=[{}],
        request_builder=request_builder,
        universe_values=universe_values,
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _ensure_stk_factor_pro_adj_factor_ready(planner: DatasetUnitPlanner, anchor: date | None) -> None:
    if anchor is None:
        raise DatasetUnitPlanner._planning_error("trade_date_anchor_required", "股票技术面因子需要明确交易日")
    stmt = select(EquityAdjFactor.ts_code).where(EquityAdjFactor.trade_date == anchor).limit(1)
    if planner.session.scalar(stmt) is None:
        raise DatasetUnitPlanner._planning_error("upstream_data_not_ready", "先更新复权因子")


def _build_stk_factor_pro_adj_factor_refresh_units(
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
    anchor: date,
) -> list[PlanUnitSnapshot]:
    if request.run_profile != "point_incremental":
        return []
    if split_multi_values(request.params.get("ts_code")):
        return []

    exchange = str(request.params.get("exchange") or planner.settings.default_exchange)
    previous_trade_date = planner.dao.trade_calendar.get_latest_open_date(exchange, anchor - timedelta(days=1))
    if previous_trade_date is None:
        return []

    changed_codes = _load_stk_factor_pro_adj_factor_changed_codes(
        planner,
        target_date=anchor,
        previous_date=previous_trade_date,
    )
    raw_start_dates = _load_stk_factor_pro_raw_start_dates(planner, changed_codes)
    universe_values = [
        {"ts_code": code, "start_date": raw_start_dates[code], "end_date": anchor}
        for code in changed_codes
        if raw_start_dates.get(code) is not None
    ]
    if not universe_values:
        return []

    return build_plan_units(
        request=request,
        definition=definition,
        anchors=[None],
        enum_combinations=[{}],
        request_builder=planner._resolve_request_builder(definition),
        universe_values=universe_values,
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _load_stk_factor_pro_adj_factor_changed_codes(
    planner: DatasetUnitPlanner,
    *,
    target_date: date,
    previous_date: date,
) -> list[str]:
    today = aliased(EquityAdjFactor)
    previous = aliased(EquityAdjFactor)
    stmt = (
        select(today.ts_code)
        .join(previous, previous.ts_code == today.ts_code)
        .where(
            today.trade_date == target_date,
            previous.trade_date == previous_date,
            today.adj_factor.is_distinct_from(previous.adj_factor),
        )
        .order_by(today.ts_code)
    )
    codes = [str(code).strip().upper() for code in planner.session.scalars(stmt) if str(code).strip()]
    return sorted(set(codes))


def _load_stk_factor_pro_raw_start_dates(planner: DatasetUnitPlanner, codes: list[str]) -> dict[str, date]:
    if not codes:
        return {}
    stmt = (
        select(RawStkFactorPro.ts_code, func.min(RawStkFactorPro.trade_date))
        .where(RawStkFactorPro.ts_code.in_(codes))
        .group_by(RawStkFactorPro.ts_code)
    )
    rows = planner.session.execute(stmt).all()
    return {str(code).strip().upper(): start_date for code, start_date in rows if str(code).strip() and start_date is not None}


def _build_stk_factor_pro_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    anchors = planner._resolve_anchors(request, definition)
    enum_combinations = resolve_enum_combinations(
        request=request,
        fields=definition.planning.enum_fanout_fields,
        missing_field_defaults=definition.planning.enum_fanout_defaults,
    )
    units: list[PlanUnitSnapshot] = []
    for anchor in anchors:
        _ensure_stk_factor_pro_adj_factor_ready(planner, anchor)
        units.extend(
            build_plan_units(
                request=request,
                definition=definition,
                anchors=[anchor],
                enum_combinations=enum_combinations,
                request_builder=request_builder,
                universe_values=planner._resolve_universe_values(request, definition, anchor),
                pagination_policy_override=definition.planning.pagination_policy,
                page_limit_override=definition.planning.page_limit,
                progress_context_builder=planner._build_generic_progress_context,
            )
        )
        units.extend(_build_stk_factor_pro_adj_factor_refresh_units(planner, request, definition, anchor))
    return units


def _build_stock_basic_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    source_mode = str(request.source_key or request.params.get("source_key") or definition.source.source_key_default).strip().lower()
    if source_mode not in {"tushare", "biying", "all"}:
        raise DatasetUnitPlanner._planning_error("invalid_enum", f"{definition.display_name} 不支持该数据来源：{source_mode}")

    units: list[PlanUnitSnapshot] = []
    if source_mode in {"tushare", "all"}:
        enum_combinations = resolve_enum_combinations(
            request=request,
            fields=("list_status", "market", "exchange", "is_hs"),
            missing_field_defaults={"list_status": ("L", "D", "P", "G")},
        )
        ordinal = 0
        for enum_values in enum_combinations:
            merged_values = {**enum_values, "source_key": "tushare"}
            request_params = request_builder(request, None, merged_values)
            units.append(
                PlanUnitSnapshot(
                    unit_id=build_unit_id(dataset_key=request.dataset_key, anchor=None, merged_values=merged_values, ordinal=ordinal),
                    dataset_key=request.dataset_key,
                    source_key="tushare",
                    trade_date=None,
                    request_params=request_params,
                    progress_context={},
                    pagination_policy="offset_limit",
                    page_limit=6000,
                    requested_source_key=source_mode,
                )
            )
            ordinal += 1
    if source_mode in {"biying", "all"}:
        request_params = request_builder(request, None, {"source_key": "biying"})
        units.append(
            PlanUnitSnapshot(
                unit_id=build_unit_id(dataset_key=request.dataset_key, anchor=None, merged_values={"source_key": "biying"}, ordinal=0),
                dataset_key=request.dataset_key,
                source_key="biying",
                trade_date=None,
                request_params=request_params,
                progress_context={},
                pagination_policy="none",
                page_limit=None,
                requested_source_key=source_mode,
            )
        )
    return units


def _build_stock_company_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    explicit_codes = split_multi_values(request.params.get("ts_code"))
    if explicit_codes:
        normalized_codes = sorted({str(code).strip().upper() for code in explicit_codes if str(code).strip()})
        return build_plan_units(
            request=request,
            definition=definition,
            anchors=[None],
            enum_combinations=[{}],
            request_builder=request_builder,
            universe_values=[{"ts_code": code} for code in normalized_codes],
            pagination_policy_override=definition.planning.pagination_policy,
            page_limit_override=definition.planning.page_limit,
            progress_context_builder=planner._build_generic_progress_context,
        )

    requested_exchanges = split_multi_values(request.params.get("exchange"))
    exchange_order = ("SSE", "SZSE", "BSE")
    if requested_exchanges:
        selected = {str(value).strip().upper() for value in requested_exchanges if str(value).strip()}
        exchanges = [exchange for exchange in exchange_order if exchange in selected]
    else:
        exchanges = list(exchange_order)
    return build_plan_units(
        request=request,
        definition=definition,
        anchors=[None],
        enum_combinations=[{}],
        request_builder=request_builder,
        universe_values=[{"exchange": exchange} for exchange in exchanges],
        pagination_policy_override=definition.planning.pagination_policy,
        page_limit_override=definition.planning.page_limit,
        progress_context_builder=planner._build_generic_progress_context,
    )


def _build_cyq_chips_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    targets = _resolve_cyq_chips_targets(planner=planner, request=request, definition=definition)
    if request.run_profile == "point_incremental":
        if request.trade_date is None:
            raise DatasetUnitPlanner._planning_error("missing_anchor_fields", "每日筹码分布单日维护缺少交易日期")
        windows = [(request.trade_date, request.trade_date)]
    elif request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise DatasetUnitPlanner._planning_error("range_required", "每日筹码分布区间维护必须同时填写开始日期和结束日期")
        windows = _split_cyq_chips_date_windows(request.start_date, request.end_date)
    else:
        raise DatasetUnitPlanner._planning_error("run_profile_unsupported", f"每日筹码分布不支持该运行模式：{request.run_profile}")

    units: list[PlanUnitSnapshot] = []
    ordinal = 0
    for ts_code, security_name in targets:
        for window_start, window_end in windows:
            if request.run_profile == "point_incremental":
                unit_trade_date = window_start
                date_values = {"trade_date": window_start.isoformat()}
            else:
                unit_trade_date = None
                date_values = {"start_date": window_start.isoformat(), "end_date": window_end.isoformat()}
            merged_values = {"ts_code": ts_code, **date_values}
            progress_context = {"unit": "stock", "ts_code": ts_code, **date_values}
            if security_name:
                progress_context["security_name"] = security_name
            units.append(
                PlanUnitSnapshot(
                    unit_id=build_unit_id(
                        dataset_key=request.dataset_key,
                        anchor=unit_trade_date,
                        merged_values=merged_values,
                        ordinal=ordinal,
                    ),
                    dataset_key=request.dataset_key,
                    source_key=request.source_key or definition.source.source_key_default,
                    trade_date=unit_trade_date,
                    request_params=request_builder(request, unit_trade_date, {"ts_code": ts_code, **date_values}),
                    progress_context=progress_context,
                    pagination_policy=definition.planning.pagination_policy,
                    page_limit=definition.planning.page_limit,
                )
            )
            ordinal += 1
    return units


def _split_cyq_chips_date_windows(start_date: date, end_date: date) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        window_end = min(cursor + timedelta(days=CYQ_CHIPS_RANGE_WINDOW_DAYS - 1), end_date)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _split_calendar_half_year_windows(start_date: date, end_date: date) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        half_end = date(cursor.year, 6, 30) if cursor.month <= 6 else date(cursor.year, 12, 31)
        window_end = min(half_end, end_date)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _resolve_etf_sh_cons_targets(
    *,
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
) -> list[str]:
    universe = definition.planning.universe
    if definition.planning.universe_policy != "pool" or universe is None:
        raise DatasetUnitPlanner._planning_error("invalid_universe_config", "ETF 申赎清单缺少对象池规划配置")
    if universe.request_field != "ts_code" or universe.override_fields != ("ts_code",):
        raise DatasetUnitPlanner._planning_error("invalid_universe_config", "ETF 申赎清单对象池配置必须绑定 ts_code")
    actual_sources = tuple((source.type, source.resource) for source in universe.sources)
    if actual_sources != (("ops_etf_series_active", ETF_SH_CONS_RESOURCE),):
        raise DatasetUnitPlanner._planning_error("invalid_universe_source", "ETF 申赎清单对象池来源配置不符合当前主链")

    pool_codes = _normalize_universe_codes(planner.dao.etf_series_active.list_active_codes(ETF_SH_CONS_RESOURCE))
    if not pool_codes:
        raise DatasetUnitPlanner._planning_error("universe_empty", "ETF 申赎清单需要先配置 etf_sh_cons ETF 激活池")

    invalid_pool_codes = [code for code in pool_codes if not code.endswith(".SH")]
    if invalid_pool_codes:
        raise DatasetUnitPlanner._planning_error(
            "invalid_enum",
            f"ETF 申赎清单 active 池只允许 .SH ETF 代码：{', '.join(invalid_pool_codes)}",
        )

    explicit_codes = _normalize_universe_codes(split_multi_values(request.params.get("ts_code")))
    if not explicit_codes:
        return pool_codes
    if len(explicit_codes) > 1:
        raise DatasetUnitPlanner._planning_error("invalid_enum", "ETF 申赎清单一次只支持维护一个显式 ETF 代码")

    explicit_code = explicit_codes[0]
    if not explicit_code.endswith(".SH"):
        raise DatasetUnitPlanner._planning_error("invalid_enum", f"ETF 申赎清单只支持上交所 ETF 代码：{explicit_code}")
    if explicit_code not in set(pool_codes):
        raise DatasetUnitPlanner._planning_error("invalid_enum", f"ETF 申赎清单代码未配置到 active 池：{explicit_code}")
    return [explicit_code]


def _build_etf_sh_cons_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    targets = _resolve_etf_sh_cons_targets(planner=planner, request=request, definition=definition)
    if request.run_profile == "point_incremental":
        if request.trade_date is None:
            raise DatasetUnitPlanner._planning_error("missing_anchor_fields", "ETF 申赎清单单日维护缺少交易日期")
        windows = [(request.trade_date, request.trade_date)]
    elif request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise DatasetUnitPlanner._planning_error("range_required", "ETF 申赎清单区间维护必须同时填写开始日期和结束日期")
        windows = _split_calendar_half_year_windows(request.start_date, request.end_date)
    else:
        raise DatasetUnitPlanner._planning_error("run_profile_unsupported", f"ETF 申赎清单不支持该运行模式：{request.run_profile}")

    units: list[PlanUnitSnapshot] = []
    ordinal = 0
    for ts_code in targets:
        for window_start, window_end in windows:
            if request.run_profile == "point_incremental":
                unit_trade_date = window_start
                date_values = {"trade_date": window_start.isoformat()}
            else:
                unit_trade_date = None
                date_values = {"start_date": window_start.isoformat(), "end_date": window_end.isoformat()}
            merged_values = {"ts_code": ts_code, **date_values}
            units.append(
                PlanUnitSnapshot(
                    unit_id=build_unit_id(
                        dataset_key=request.dataset_key,
                        anchor=unit_trade_date,
                        merged_values=merged_values,
                        ordinal=ordinal,
                    ),
                    dataset_key=request.dataset_key,
                    source_key=request.source_key or definition.source.source_key_default,
                    trade_date=unit_trade_date,
                    request_params=request_builder(request, unit_trade_date, merged_values),
                    progress_context={"unit": "etf", "ts_code": ts_code, **date_values},
                    pagination_policy=definition.planning.pagination_policy,
                    page_limit=definition.planning.page_limit,
                )
            )
            ordinal += 1
    return units


def _resolve_cyq_chips_targets(
    *,
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
) -> list[tuple[str, str | None]]:
    universe = definition.planning.universe
    if definition.planning.universe_policy != "pool" or universe is None:
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", "每日筹码分布缺少对象池规划配置")
    if universe.request_field != "ts_code" or universe.override_fields != ("ts_code",):
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", "每日筹码分布对象池配置必须绑定 ts_code")
    actual_sources = tuple((source.type, source.resource) for source in universe.sources)
    if actual_sources != (("core_security_active_equities", "tushare_preferred"),):
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", "每日筹码分布对象池来源配置不符合当前主链")

    explicit_codes = split_multi_values(request.params.get("ts_code"))
    if explicit_codes:
        targets = []
        get_by_ts_code = getattr(planner.dao.security, "get_by_ts_code", None)
        for code in sorted({str(item).strip().upper() for item in explicit_codes if str(item).strip()}):
            security = get_by_ts_code(code) if callable(get_by_ts_code) else None
            targets.append((code, getattr(security, "name", None) or None))
        return targets

    securities = list(planner.dao.security.get_active_equities())
    tushare_targets = [
        (str(getattr(item, "ts_code", "") or "").strip().upper(), getattr(item, "name", None) or None)
        for item in securities
        if str(getattr(item, "source", "tushare") or "").strip().lower() == "tushare"
        and str(getattr(item, "list_status", "L") or "").strip().upper() == "L"
        and str(getattr(item, "ts_code", "") or "").strip()
    ]
    all_targets = [
        (str(getattr(item, "ts_code", "") or "").strip().upper(), getattr(item, "name", None) or None)
        for item in securities
        if str(getattr(item, "list_status", "L") or "").strip().upper() == "L"
        and str(getattr(item, "ts_code", "") or "").strip()
    ]
    targets_by_code = {code: (code, name) for code, name in (tushare_targets or all_targets) if code}
    targets = [targets_by_code[code] for code in sorted(targets_by_code)]
    if not targets:
        raise DatasetUnitPlanner._planning_error("universe_empty", "每日筹码分布需要先准备股票主数据")
    return targets


def _build_stk_mins_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    raw_freqs = split_multi_values(request.params.get("freq"))
    allowed_freqs = ("1min", "5min", "15min", "30min", "60min")
    if not raw_freqs:
        raise DatasetUnitPlanner._planning_error("required_param_missing", "股票历史分钟行情至少需要选择一个频率")
    invalid = sorted({value for value in raw_freqs if value not in allowed_freqs})
    if invalid:
        raise DatasetUnitPlanner._planning_error("invalid_enum", f"股票历史分钟行情频率无效：{', '.join(invalid)}")
    selected_freqs = [freq for freq in allowed_freqs if freq in set(raw_freqs)]

    targets = _resolve_stk_mins_targets(planner=planner, request=request, definition=definition)

    if request.trade_date is not None:
        trade_date = request.trade_date
        window_start = f"{trade_date.isoformat()} 09:00:00"
        window_end = f"{trade_date.isoformat()} 19:00:00"
        unit_trade_date = trade_date
    elif request.start_date is not None and request.end_date is not None:
        window_start = f"{request.start_date.isoformat()} 09:00:00"
        window_end = f"{request.end_date.isoformat()} 19:00:00"
        unit_trade_date = None
    else:
        raise DatasetUnitPlanner._planning_error("range_required", "股票历史分钟行情需要交易日期或起止日期")

    units: list[PlanUnitSnapshot] = []
    ordinal = 0
    for ts_code, security_name in targets:
        for freq in selected_freqs:
            merged_values = {
                "ts_code": ts_code,
                "freq": freq,
                "window_start": window_start,
                "window_end": window_end,
            }
            progress_context = {
                "unit": "stock",
                "ts_code": ts_code,
                "freq": freq,
                "start_date": window_start,
                "end_date": window_end,
            }
            if security_name:
                progress_context["security_name"] = security_name
            units.append(
                PlanUnitSnapshot(
                    unit_id=f"stk_mins:ts_code={ts_code}:freq={freq}:start={window_start.replace(' ', 'T')}:end={window_end.replace(' ', 'T')}:{ordinal}",
                    dataset_key=request.dataset_key,
                    source_key=request.source_key or definition.source.source_key_default,
                    trade_date=unit_trade_date,
                    request_params=request_builder(request, unit_trade_date, merged_values),
                    progress_context=progress_context,
                    pagination_policy="offset_limit",
                    page_limit=definition.planning.page_limit,
                )
            )
            ordinal += 1
    return units


def _resolve_stk_mins_targets(
    *,
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
) -> list[tuple[str, str | None]]:
    universe = definition.planning.universe
    if definition.planning.universe_policy != "pool" or universe is None:
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", "股票历史分钟行情缺少对象池规划配置")
    if universe.request_field != "ts_code" or "ts_code" not in universe.override_fields:
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", "股票历史分钟行情对象池配置必须绑定 ts_code")
    if [(source.type, source.resource) for source in universe.sources] != [("core_security_active_equities", "tushare_preferred")]:
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", "股票历史分钟行情对象池来源配置不符合当前主链")

    explicit_codes = split_multi_values(request.params.get("ts_code"))
    if explicit_codes:
        targets = []
        get_by_ts_code = getattr(planner.dao.security, "get_by_ts_code", None)
        for code in sorted({str(item).strip().upper() for item in explicit_codes if str(item).strip()}):
            security = get_by_ts_code(code) if callable(get_by_ts_code) else None
            targets.append((code, getattr(security, "name", None) or None))
    else:
        securities = list(planner.dao.security.get_active_equities())
        tushare_targets = [
            (str(getattr(item, "ts_code", "") or "").strip().upper(), getattr(item, "name", None) or None)
            for item in securities
            if str(getattr(item, "source", "tushare") or "").strip().lower() == "tushare"
            and str(getattr(item, "ts_code", "") or "").strip()
        ]
        all_targets = [
            (str(getattr(item, "ts_code", "") or "").strip().upper(), getattr(item, "name", None) or None)
            for item in securities
            if str(getattr(item, "ts_code", "") or "").strip()
        ]
        targets_by_code = {code: (code, name) for code, name in (tushare_targets or all_targets) if code}
        targets = [targets_by_code[code] for code in sorted(targets_by_code)]
        if not targets:
            raise DatasetUnitPlanner._planning_error("universe_empty", "全市场分钟行情需要先准备股票主数据")
    return targets


def _build_index_mins_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    allowed_freqs = ("1min", "5min", "15min", "30min", "60min")
    raw_freqs = split_multi_values(request.params.get("freq"))
    if not raw_freqs:
        raw_freqs = list(allowed_freqs)
    invalid = sorted({value for value in raw_freqs if value not in allowed_freqs})
    if invalid:
        raise DatasetUnitPlanner._planning_error("invalid_enum", f"指数历史分钟行情频率无效：{', '.join(invalid)}")
    selected_freqs = [freq for freq in allowed_freqs if freq in set(raw_freqs)]

    targets = _resolve_index_mins_targets(planner=planner, request=request, definition=definition)

    if request.trade_date is not None:
        trade_date = request.trade_date
        window_start = f"{trade_date.isoformat()} 09:00:00"
        window_end = f"{trade_date.isoformat()} 19:00:00"
        unit_trade_date = trade_date
    elif request.start_date is not None and request.end_date is not None:
        window_start = f"{request.start_date.isoformat()} 09:00:00"
        window_end = f"{request.end_date.isoformat()} 19:00:00"
        unit_trade_date = None
    else:
        raise DatasetUnitPlanner._planning_error("range_required", "指数历史分钟行情需要交易日期或起止日期")

    units: list[PlanUnitSnapshot] = []
    ordinal = 0
    for ts_code, index_name in targets:
        for freq in selected_freqs:
            merged_values = {
                "ts_code": ts_code,
                "freq": freq,
                "window_start": window_start,
                "window_end": window_end,
            }
            progress_context = {
                "unit": "index",
                "ts_code": ts_code,
                "freq": freq,
                "start_date": window_start,
                "end_date": window_end,
            }
            if index_name:
                progress_context["index_name"] = index_name
            units.append(
                PlanUnitSnapshot(
                    unit_id=f"index_mins:ts_code={ts_code}:freq={freq}:start={window_start.replace(' ', 'T')}:end={window_end.replace(' ', 'T')}:{ordinal}",
                    dataset_key=request.dataset_key,
                    source_key=request.source_key or definition.source.source_key_default,
                    trade_date=unit_trade_date,
                    request_params=request_builder(request, unit_trade_date, merged_values),
                    progress_context=progress_context,
                    pagination_policy="offset_limit",
                    page_limit=definition.planning.page_limit,
                )
            )
            ordinal += 1
    return units


def _resolve_index_mins_targets(
    *,
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
) -> list[tuple[str, str | None]]:
    universe = definition.planning.universe
    if definition.planning.universe_policy != "pool" or universe is None:
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", "指数历史分钟行情缺少对象池规划配置")
    if universe.request_field != "ts_code" or "ts_code" not in universe.override_fields:
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", "指数历史分钟行情对象池配置必须绑定 ts_code")
    actual_sources = tuple((source.type, source.resource) for source in universe.sources)
    if actual_sources != (("ops_index_series_active", "index_mins"),):
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", "指数历史分钟行情对象池来源配置不符合当前主链")

    active_resource = str(universe.sources[0].resource)
    active_codes = _normalize_universe_codes(planner.dao.index_series_active.list_active_codes(active_resource))
    if not active_codes:
        raise DatasetUnitPlanner._planning_error("universe_empty", "指数历史分钟行情需要先准备 index_mins 激活指数池")

    active_set = set(active_codes)
    explicit_codes = _normalize_universe_codes(split_multi_values(request.params.get("ts_code")))
    if explicit_codes:
        invalid = sorted(code for code in explicit_codes if code not in active_set)
        if invalid:
            raise DatasetUnitPlanner._planning_error(
                "invalid_enum",
                f"指数历史分钟行情代码不在 index_mins 激活池：{', '.join(invalid)}",
            )
        selected_codes = explicit_codes
    else:
        selected_codes = active_codes

    targets: list[tuple[str, str | None]] = []
    get_by_ts_code = getattr(planner.dao.index_basic, "get_by_ts_code", None)
    for code in selected_codes:
        index = get_by_ts_code(code) if callable(get_by_ts_code) else None
        targets.append((code, getattr(index, "name", None) or None))
    return targets


def _build_biying_equity_daily_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    return _build_biying_units(planner, request, definition, window_days=3000, include_adj_type=True)


def _build_biying_moneyflow_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    return _build_biying_units(planner, request, definition, window_days=100, include_adj_type=False)


def _resolve_biying_targets(
    *,
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
) -> list[tuple[str, str | None]]:
    universe = definition.planning.universe
    if definition.planning.universe_policy != "pool" or universe is None:
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", f"{definition.display_name} 缺少 Biying 股票池规划配置")
    if universe.request_field != "dm" or universe.override_fields != ("ts_code",):
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", f"{definition.display_name} Biying 股票池字段配置不符合当前主链")
    expected_sources = (("raw_biying_stock_basic", "dm_mc"),)
    actual_sources = tuple((source.type, source.resource) for source in universe.sources)
    if actual_sources != expected_sources:
        raise DatasetUnitPlanner._planning_error("unknown_universe_policy", f"{definition.display_name} Biying 股票池来源配置不符合当前主链")

    explicit_dms = [str(value).strip().upper().split(".", 1)[0] for value in split_multi_values(request.params.get("ts_code")) if str(value).strip()]
    stmt = select(RawBiyingStockBasic.dm, RawBiyingStockBasic.mc).where(RawBiyingStockBasic.dm.is_not(None))
    if explicit_dms:
        stmt = stmt.where(RawBiyingStockBasic.dm.in_(explicit_dms))
    rows = planner.session.execute(stmt.order_by(RawBiyingStockBasic.dm.asc())).all()
    stocks = [(str(row.dm).strip().upper(), row.mc) for row in rows if row.dm]
    if explicit_dms:
        by_dm = {dm for dm, _ in stocks}
        stocks.extend((dm, None) for dm in explicit_dms if dm not in by_dm)
    if not stocks:
        raise DatasetUnitPlanner._planning_error("universe_empty", f"Biying 股票池为空，无法维护 {request.dataset_key}")
    return stocks


def _build_biying_units(
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
    *,
    window_days: int,
    include_adj_type: bool,
) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    stocks = _resolve_biying_targets(planner=planner, request=request, definition=definition)

    if request.run_profile == "point_incremental":
        if request.trade_date is None:
            raise DatasetUnitPlanner._planning_error("missing_anchor_fields", f"{request.dataset_key} 单日维护缺少交易日期")
        windows = [(request.trade_date, request.trade_date)]
    elif request.run_profile == "range_rebuild":
        if request.start_date is None or request.end_date is None:
            raise DatasetUnitPlanner._planning_error("range_required", f"{request.dataset_key} 区间维护必须同时填写开始日期和结束日期")
        windows = []
        cursor = request.start_date
        while cursor <= request.end_date:
            window_end = min(cursor + timedelta(days=window_days - 1), request.end_date)
            windows.append((cursor, window_end))
            cursor = window_end + timedelta(days=1)
    else:
        raise DatasetUnitPlanner._planning_error("run_profile_unsupported", f"{request.dataset_key} 不支持该运行模式：{request.run_profile}")

    adj_types = ["n", "f", "b"]
    if include_adj_type:
        values = [str(value).strip().lower() for value in split_multi_values(request.params.get("adj_type")) if str(value).strip()]
        if values:
            invalid = sorted({value for value in values if value not in {"n", "f", "b"}})
            if invalid:
                raise DatasetUnitPlanner._planning_error("invalid_enum", f"{definition.display_name} 复权类型不在可选范围内：{','.join(invalid)}")
            adj_types = [item for item in ("n", "f", "b") if item in set(values)]

    units: list[PlanUnitSnapshot] = []
    ordinal = 0
    for dm, mc in stocks:
        active_adj_types = adj_types if include_adj_type else [None]
        for adj_type in active_adj_types:
            for window_start, window_end in windows:
                merged_values = {
                    "dm": dm,
                    "mc": mc,
                    "window_start": window_start,
                    "window_end": window_end,
                }
                if adj_type is not None:
                    merged_values["adj_type"] = adj_type
                request_params = request_builder(request, window_end, merged_values)
                unit_values = {"dm": dm, "st": window_start.isoformat(), "et": window_end.isoformat()}
                if adj_type is not None:
                    unit_values["adj_type"] = adj_type
                units.append(
                    PlanUnitSnapshot(
                        unit_id=build_unit_id(dataset_key=request.dataset_key, anchor=window_end, merged_values=unit_values, ordinal=ordinal),
                        dataset_key=request.dataset_key,
                        source_key=request.source_key or definition.source.source_key_default,
                        trade_date=window_end,
                        request_params=request_params,
                        progress_context={"ts_code": dm, "start_date": window_start.isoformat(), "end_date": window_end.isoformat()},
                        pagination_policy="none",
                        page_limit=None,
                    )
                )
                ordinal += 1
    return units


_CUSTOM_UNIT_BUILDERS: dict[str, Callable[[DatasetUnitPlanner, ValidatedDatasetActionRequest, DatasetDefinition], list[PlanUnitSnapshot]]] = {
    "build_biying_equity_daily_units": _build_biying_equity_daily_units,
    "build_biying_moneyflow_units": _build_biying_moneyflow_units,
    "build_cyq_chips_units": _build_cyq_chips_units,
    "build_etf_sh_cons_units": _build_etf_sh_cons_units,
    "build_cctv_news_units": _build_cctv_news_units,
    "build_dc_member_units": _build_dc_member_units,
    "build_major_news_units": _build_major_news_units,
    "build_news_units": _build_news_units,
    "build_dividend_units": _build_dividend_units,
    "build_index_daily_units": _build_index_daily_units,
    "build_index_mins_units": _build_index_mins_units,
    "build_index_weight_units": _build_index_weight_units,
    "build_stock_company_units": _build_stock_company_units,
    "build_stk_factor_pro_units": _build_stk_factor_pro_units,
    "build_stk_holdernumber_units": _build_holdernumber_units,
    "build_stk_mins_units": _build_stk_mins_units,
    "build_stock_basic_units": _build_stock_basic_units,
    "build_ths_member_units": _build_ths_member_units,
}
