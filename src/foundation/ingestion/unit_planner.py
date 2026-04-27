from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.connectors.factory import create_source_connector
from src.foundation.config.settings import get_settings
from src.foundation.dao.factory import DAOFactory
from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import IngestionPlanningError, StructuredError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot, ValidatedDatasetActionRequest
from src.foundation.ingestion import request_builders
from src.foundation.ingestion.plan_helpers import build_plan_units, build_unit_id, resolve_enum_combinations, split_multi_values
from src.foundation.ingestion.sentinel_guard import find_forbidden_business_sentinel
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.raw_multi.raw_biying_stock_basic import RawBiyingStockBasic


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
        if date_model.date_axis in {"none", "natural_day", "month_window"}:
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

    def _resolve_universe_values(
        self,
        request: ValidatedDatasetActionRequest,
        definition: DatasetDefinition,
        anchor: date | None,
    ) -> list[dict[str, Any]]:
        policy = definition.planning.universe_policy
        if policy == "none":
            return [{}]
        if policy == "index_active_codes":
            ts_code = str(request.params.get("ts_code") or "").strip().upper()
            if ts_code:
                return [{"ts_code": ts_code}]
            codes = self.dao.index_series_active.list_active_codes(request.dataset_key)
            if not codes:
                codes = [item.ts_code for item in self.dao.index_basic.get_active_indexes() if item.ts_code]
            normalized_codes = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
            if not normalized_codes:
                raise self._planning_error("universe_empty", f"no active index codes found for dataset={request.dataset_key}")
            return [{"ts_code": code} for code in normalized_codes]

        if policy == "ths_index_board_codes":
            ts_code = str(request.params.get("ts_code") or "").strip().upper()
            con_code = str(request.params.get("con_code") or "").strip().upper()
            if ts_code:
                return [{"ts_code": ts_code}]
            if con_code:
                return [{"con_code": con_code}]
            stmt = select(ThsIndex.ts_code).distinct().order_by(ThsIndex.ts_code)
            codes = [str(item).strip().upper() for item in self.session.scalars(stmt) if str(item).strip()]
            normalized_codes = sorted(set(codes))
            if not normalized_codes:
                raise self._planning_error("universe_empty", "no ths_index board codes found")
            return [{"ts_code": code} for code in normalized_codes]

        if policy != "dc_index_board_codes":
            raise self._planning_error("unknown_universe_policy", f"unsupported universe_policy={policy}")

        ts_code = str(request.params.get("ts_code") or "").strip().upper()
        con_code = str(request.params.get("con_code") or "").strip().upper()
        if ts_code:
            return [{"ts_code": ts_code}]
        if con_code:
            return [{"con_code": con_code}]

        idx_types = split_multi_values(request.params.get("idx_type"))
        board_codes: list[str] = []
        if anchor is not None:
            board_codes = self._load_board_codes_from_dc_index(anchor=anchor, idx_types=idx_types)
        elif request.trade_date is not None:
            board_codes = self._load_board_codes_from_dc_index(anchor=request.trade_date, idx_types=idx_types)
        elif request.start_date is not None and request.end_date is not None:
            board_codes = self._load_board_codes_from_dc_index_range(
                start_date=request.start_date,
                end_date=request.end_date,
                idx_types=idx_types,
            )
        if not board_codes:
            fallback_anchor = anchor or request.trade_date
            if fallback_anchor is not None:
                board_codes = self._load_board_codes_from_source(anchor=fallback_anchor, idx_types=idx_types)
        if not board_codes:
            if anchor is None and request.trade_date is None and request.start_date is None and request.end_date is None:
                raise self._planning_error(
                    "trade_date_anchor_required",
                    "板块代码范围规划需要交易日期或起止日期",
                )
            raise self._planning_error(
                "universe_empty",
                "未找到指定日期范围内的东方财富板块代码",
            )
        return [{"ts_code": code} for code in board_codes]

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
    def _load_board_codes_from_source(*, anchor: date, idx_types: list[str]) -> list[str]:
        connector = create_source_connector("tushare")
        dc_index_definition = get_dataset_definition("dc_index")
        query_idx_types = idx_types or [""]
        rows: list[dict[str, Any]] = []
        for idx_type in query_idx_types:
            params: dict[str, Any] = {"trade_date": anchor.strftime("%Y%m%d")}
            if idx_type:
                params["idx_type"] = idx_type
            rows.extend(
                connector.call(
                    api_name="dc_index",
                    params=params,
                    fields=dc_index_definition.source.source_fields,
                )
            )
        codes = [str(row.get("ts_code")).strip().upper() for row in rows if str(row.get("ts_code") or "").strip()]
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
    active_codes = dao.index_series_active.list_active_codes(request.dataset_key)
    if not active_codes:
        active_codes = [item.ts_code for item in dao.index_basic.get_active_indexes() if item.ts_code]
    normalized = sorted({str(code).strip().upper() for code in active_codes if str(code).strip()})
    if not normalized:
        raise DatasetUnitPlanner._planning_error("universe_empty", f"no active index codes found for dataset={request.dataset_key}")
    return normalized


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
    universe_values = [{"index_code": code} for code in split_multi_values(request.params.get("index_code")) or _resolve_index_codes(request, planner.dao)]
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


def _build_stock_basic_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
    source_mode = str(request.source_key or request.params.get("source_key") or definition.source.source_key_default).strip().lower()
    if source_mode not in {"tushare", "biying", "all"}:
        raise DatasetUnitPlanner._planning_error("invalid_enum", f"stock_basic unsupported source_key={source_mode}")

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


def _build_biying_equity_daily_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    return _build_biying_units(planner, request, definition, window_days=3000, include_adj_type=True)


def _build_biying_moneyflow_units(planner: DatasetUnitPlanner, request: ValidatedDatasetActionRequest, definition: DatasetDefinition) -> list[PlanUnitSnapshot]:
    return _build_biying_units(planner, request, definition, window_days=100, include_adj_type=False)


def _build_biying_units(
    planner: DatasetUnitPlanner,
    request: ValidatedDatasetActionRequest,
    definition: DatasetDefinition,
    *,
    window_days: int,
    include_adj_type: bool,
) -> list[PlanUnitSnapshot]:
    request_builder = planner._resolve_request_builder(definition)
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
                raise DatasetUnitPlanner._planning_error("invalid_enum", f"biying_equity_daily invalid adj_type={','.join(invalid)}")
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
    "build_dividend_units": _build_dividend_units,
    "build_index_daily_units": _build_index_daily_units,
    "build_index_weight_units": _build_index_weight_units,
    "build_stk_holdernumber_units": _build_holdernumber_units,
    "build_stk_mins_units": _build_stk_mins_units,
    "build_stock_basic_units": _build_stock_basic_units,
}
