from __future__ import annotations

from datetime import date
from itertools import product
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.connectors.factory import create_source_connector
from src.foundation.config.settings import get_settings
from src.foundation.dao.factory import DAOFactory
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.services.sync_v2.fields import DC_INDEX_FIELDS
from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    PlanUnit,
    ValidatedRunRequest,
    resolve_contract_anchor_type,
    resolve_contract_window_policy,
)
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2PlanningError


class SyncV2Planner:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dao = DAOFactory(session)
        self.settings = get_settings()

    def plan(self, request: ValidatedRunRequest, contract: DatasetSyncContract) -> list[PlanUnit]:
        anchors = self._resolve_anchors(request, contract)

        units: list[PlanUnit] = []
        for anchor in anchors:
            enum_fanout_values = self._resolve_enum_fanout_values(request, contract)
            universe_values = self._resolve_universe_values(request, contract, anchor)
            for enum_values in enum_fanout_values:
                for universe_value in universe_values:
                    merged_values = {**enum_values, **universe_value}
                    request_params = contract.source_spec.unit_params_builder(request, anchor, merged_values)
                    source_key = request.source_key or contract.source_spec.source_key_default
                    units.append(
                        PlanUnit(
                            unit_id=self._build_unit_id(request.dataset_key, anchor, merged_values),
                            dataset_key=request.dataset_key,
                            source_key=source_key,
                            trade_date=anchor,
                            request_params=request_params,
                            attempt=0,
                            priority=0,
                        )
                    )

        max_units = contract.planning_spec.max_units_per_execution
        if max_units is not None and len(units) > max_units:
            raise SyncV2PlanningError(
                StructuredError(
                    error_code="units_exceeded",
                    error_type="planning",
                    phase="planner",
                    message=f"planned units={len(units)} exceeds max_units_per_execution={max_units}",
                    retryable=False,
                )
            )
        return units

    def _resolve_anchors(self, request: ValidatedRunRequest, contract: DatasetSyncContract) -> list[date | None]:
        anchor_type = resolve_contract_anchor_type(contract)
        window_policy = resolve_contract_window_policy(contract)
        if request.run_profile == "snapshot_refresh":
            return [None]
        if request.run_profile == "point_incremental":
            if window_policy not in {"point", "point_or_range"}:
                raise SyncV2PlanningError(
                    StructuredError(
                        error_code="invalid_window_for_profile",
                        error_type="planning",
                        phase="planner",
                        message=(
                            f"run_profile=point_incremental is not allowed "
                            f"for window_policy={window_policy}"
                        ),
                        retryable=False,
                    )
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
            raise SyncV2PlanningError(
                StructuredError(
                    error_code="invalid_window_for_profile",
                    error_type="planning",
                    phase="planner",
                    message=f"run_profile=range_rebuild is not allowed for window_policy={window_policy}",
                    retryable=False,
                )
            )
        if request.start_date is None or request.end_date is None:
            raise SyncV2PlanningError(
                StructuredError(
                    error_code="range_required",
                    error_type="planning",
                    phase="planner",
                    message="range_rebuild requires start_date and end_date",
                    retryable=False,
                )
            )
        if anchor_type in {"none", "month_range_natural", "natural_date_range"}:
            return [None]
        open_dates = self.dao.trade_calendar.get_open_dates(
            str(request.params.get("exchange") or self.settings.default_exchange),
            request.start_date,
            request.end_date,
        )
        if anchor_type == "trade_date":
            return list(open_dates)
        if anchor_type == "week_end_trade_date":
            return self._compress_to_week_end(open_dates)
        if anchor_type in {"month_end_trade_date", "month_key_yyyymm"}:
            return self._compress_to_month_end(open_dates)
        raise SyncV2PlanningError(
            StructuredError(
                error_code="invalid_anchor_type",
                error_type="planning",
                phase="planner",
                message=f"unsupported anchor_type={anchor_type}",
                retryable=False,
            )
        )

    @staticmethod
    def _compress_to_week_end(open_dates: list[date]) -> list[date]:
        latest_by_week: dict[tuple[int, int], date] = {}
        for item in open_dates:
            iso_year, iso_week, _ = item.isocalendar()
            latest_by_week[(iso_year, iso_week)] = item
        return [latest_by_week[key] for key in sorted(latest_by_week.keys())]

    @staticmethod
    def _compress_to_month_end(open_dates: list[date]) -> list[date]:
        latest_by_month: dict[tuple[int, int], date] = {}
        for item in open_dates:
            latest_by_month[(item.year, item.month)] = item
        return [latest_by_month[key] for key in sorted(latest_by_month.keys())]

    def _resolve_enum_fanout_values(self, request: ValidatedRunRequest, contract: DatasetSyncContract) -> list[dict[str, Any]]:
        fields = contract.planning_spec.enum_fanout_fields
        if not fields:
            return [{}]

        options: list[list[Any]] = []
        for field_name in fields:
            value = request.params.get(field_name)
            if value in (None, "", []):
                defaults = contract.planning_spec.enum_fanout_defaults.get(field_name, ())
                if not defaults:
                    raise SyncV2PlanningError(
                        StructuredError(
                            error_code="fanout_missing",
                            error_type="planning",
                            phase="planner",
                            message=f"enum fanout field {field_name} has no input and no defaults",
                            retryable=False,
                        )
                    )
                options.append(list(defaults))
                continue

            if isinstance(value, str):
                parsed = [part.strip() for part in value.split(",") if part.strip()]
                options.append(parsed or [value])
                continue
            if isinstance(value, (list, tuple, set)):
                parsed = [str(item).strip() for item in value if str(item).strip()]
                options.append(parsed)
                continue
            options.append([value])

        keys = list(fields)
        combinations: list[dict[str, Any]] = []
        for row in product(*options):
            combinations.append({keys[index]: row[index] for index in range(len(keys))})
        return combinations

    def _resolve_universe_values(
        self,
        request: ValidatedRunRequest,
        contract: DatasetSyncContract,
        anchor: date | None,
    ) -> list[dict[str, Any]]:
        policy = contract.planning_spec.universe_policy
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
                raise SyncV2PlanningError(
                    StructuredError(
                        error_code="universe_empty",
                        error_type="planning",
                        phase="planner",
                        message=f"no active index codes found for dataset={request.dataset_key}",
                        retryable=False,
                    )
                )
            return [{"ts_code": code} for code in normalized_codes]
        if policy == "ths_index_board_codes":
            ts_code = str(request.params.get("ts_code") or "").strip().upper()
            con_code = str(request.params.get("con_code") or "").strip().upper()
            if ts_code:
                return [{"ts_code": ts_code}]
            if con_code:
                return [{"con_code": con_code}]

            board_codes = self._load_board_codes_from_ths_index()
            if not board_codes:
                raise SyncV2PlanningError(
                    StructuredError(
                        error_code="universe_empty",
                        error_type="planning",
                        phase="planner",
                        message="no ths_index board codes found",
                        retryable=False,
                    )
                )
            return [{"ts_code": code} for code in board_codes]

        if policy != "dc_index_board_codes":
            raise SyncV2PlanningError(
                StructuredError(
                    error_code="unknown_universe_policy",
                    error_type="planning",
                    phase="planner",
                    message=f"unsupported universe_policy={policy}",
                    retryable=False,
                )
            )

        ts_code = str(request.params.get("ts_code") or "").strip().upper()
        con_code = str(request.params.get("con_code") or "").strip().upper()
        if ts_code:
            return [{"ts_code": ts_code}]
        if con_code:
            return [{"con_code": con_code}]

        idx_type = str(request.params.get("idx_type") or "").strip()
        board_codes: list[str] = []
        if anchor is not None:
            board_codes = self._load_board_codes_from_dc_index(anchor=anchor, idx_type=idx_type or None)
        elif request.trade_date is not None:
            board_codes = self._load_board_codes_from_dc_index(anchor=request.trade_date, idx_type=idx_type or None)
        elif request.start_date is not None and request.end_date is not None:
            board_codes = self._load_board_codes_from_dc_index_range(
                start_date=request.start_date,
                end_date=request.end_date,
                idx_type=idx_type or None,
            )
        if not board_codes:
            fallback_anchor = anchor or request.trade_date
            if fallback_anchor is not None:
                board_codes = self._load_board_codes_from_source(anchor=fallback_anchor, idx_type=idx_type or None)
        if not board_codes:
            if anchor is None and request.trade_date is None and request.start_date is None and request.end_date is None:
                raise SyncV2PlanningError(
                    StructuredError(
                        error_code="trade_date_anchor_required",
                        error_type="planning",
                        phase="planner",
                        message="dc_index_board_codes requires trade_date or start/end range",
                        retryable=False,
                    )
                )
            raise SyncV2PlanningError(
                StructuredError(
                    error_code="universe_empty",
                    error_type="planning",
                    phase="planner",
                    message=(
                        "no dc_index board codes found for requested anchor/range "
                        f"(trade_date={request.trade_date}, start_date={request.start_date}, end_date={request.end_date})"
                    ),
                    retryable=False,
                )
            )
        return [{"ts_code": code} for code in board_codes]

    def _load_board_codes_from_dc_index(self, *, anchor: date, idx_type: str | None) -> list[str]:
        stmt = select(DcIndex.ts_code).where(DcIndex.trade_date == anchor)
        if idx_type:
            stmt = stmt.where(DcIndex.idx_type == idx_type)
        codes = [
            str(item).strip().upper()
            for item in self.session.scalars(stmt.distinct().order_by(DcIndex.ts_code))
            if str(item).strip()
        ]
        return sorted(set(codes))

    def _load_board_codes_from_dc_index_range(
        self,
        *,
        start_date: date,
        end_date: date,
        idx_type: str | None,
    ) -> list[str]:
        stmt = select(DcIndex.ts_code).where(DcIndex.trade_date >= start_date, DcIndex.trade_date <= end_date)
        if idx_type:
            stmt = stmt.where(DcIndex.idx_type == idx_type)
        codes = [
            str(item).strip().upper()
            for item in self.session.scalars(stmt.distinct().order_by(DcIndex.ts_code))
            if str(item).strip()
        ]
        return sorted(set(codes))

    def _load_board_codes_from_ths_index(self) -> list[str]:
        stmt = select(ThsIndex.ts_code).distinct().order_by(ThsIndex.ts_code)
        codes = [str(item).strip().upper() for item in self.session.scalars(stmt) if str(item).strip()]
        return sorted(set(codes))

    @staticmethod
    def _load_board_codes_from_source(*, anchor: date, idx_type: str | None) -> list[str]:
        connector = create_source_connector("tushare")
        params: dict[str, Any] = {"trade_date": anchor.strftime("%Y%m%d")}
        if idx_type:
            params["idx_type"] = idx_type
        rows = connector.call(
            api_name="dc_index",
            params=params,
            fields=tuple(DC_INDEX_FIELDS),
        )
        codes = [
            str(row.get("ts_code")).strip().upper()
            for row in rows
            if str(row.get("ts_code") or "").strip()
        ]
        return sorted(set(codes))

    @staticmethod
    def _build_unit_id(dataset_key: str, anchor: date | None, enum_values: dict[str, Any]) -> str:
        anchor_text = anchor.isoformat() if anchor is not None else "none"
        if not enum_values:
            return f"{dataset_key}:{anchor_text}"
        enum_text = ",".join(f"{key}={enum_values[key]}" for key in sorted(enum_values.keys()))
        return f"{dataset_key}:{anchor_text}:{enum_text}"
