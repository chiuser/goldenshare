from __future__ import annotations

from datetime import date
from itertools import product
from typing import Any

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.dao.factory import DAOFactory
from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit, ValidatedRunRequest
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2PlanningError


class SyncV2Planner:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dao = DAOFactory(session)
        self.settings = get_settings()

    def plan(self, request: ValidatedRunRequest, contract: DatasetSyncContract) -> list[PlanUnit]:
        anchors = self._resolve_anchors(request, contract)
        fanout_values = self._resolve_enum_fanout_values(request, contract)

        units: list[PlanUnit] = []
        for anchor in anchors:
            for enum_values in fanout_values:
                request_params = contract.source_spec.unit_params_builder(request, anchor, enum_values)
                source_key = request.source_key or contract.source_spec.source_key_default
                units.append(
                    PlanUnit(
                        unit_id=self._build_unit_id(request.dataset_key, anchor, enum_values),
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
        policy = contract.planning_spec.date_anchor_policy
        if request.run_profile == "snapshot_refresh" or policy == "none":
            return [None]
        if request.run_profile == "point_incremental":
            return [request.trade_date]
        if request.run_profile != "range_rebuild":
            return [request.trade_date]
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
        open_dates = self.dao.trade_calendar.get_open_dates(
            str(request.params.get("exchange") or self.settings.default_exchange),
            request.start_date,
            request.end_date,
        )
        if policy == "trade_date":
            return list(open_dates)
        if policy == "week_end_trade_date":
            return self._compress_to_week_end(open_dates)
        if policy == "month_end_trade_date":
            return self._compress_to_month_end(open_dates)
        return [None]

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

    @staticmethod
    def _build_unit_id(dataset_key: str, anchor: date | None, enum_values: dict[str, Any]) -> str:
        anchor_text = anchor.isoformat() if anchor is not None else "none"
        if not enum_values:
            return f"{dataset_key}:{anchor_text}"
        enum_text = ",".join(f"{key}={enum_values[key]}" for key in sorted(enum_values.keys()))
        return f"{dataset_key}:{anchor_text}:{enum_text}"
