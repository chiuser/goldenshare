from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.foundation.datasets.models import DatasetDefinition


CalendarPolicy = Literal[
    "monthly_last_day",
    "monthly_last_trading_day",
    "monthly_window_current_month",
    "trigger_day_single_range",
    "trigger_day_point",
]
ScheduleType = Literal["cron", "once"]
CronRepeatMode = Literal["daily", "weekly", "monthly", "intraday_interval"]


@dataclass(frozen=True, slots=True)
class DatasetScheduleTimePolicyCapability:
    policy: CalendarPolicy
    schedule_types: tuple[ScheduleType, ...]
    cron_repeat_modes: tuple[CronRepeatMode, ...]
    explicit_time_input: Literal["allowed", "forbidden"]
    generated_time_mode: Literal["point", "range"]
    generated_time_field: Literal["trade_date", "ann_date", "start_date_end_date"] = "trade_date"
    declared_by_action: bool = False


class DatasetScheduleTimePolicyResolver:
    """Resolve schedule date semantics from DatasetDefinition only."""

    def resolve(
        self,
        *,
        definition: DatasetDefinition,
        action: str,
    ) -> tuple[DatasetScheduleTimePolicyCapability, ...]:
        action_capability = definition.capabilities.get_action(action)
        if action_capability is None or not action_capability.schedule_enabled:
            return ()
        declared = action_capability.schedule_time_policy
        if declared is not None:
            return (
                DatasetScheduleTimePolicyCapability(
                    policy=declared.policy,  # type: ignore[arg-type]
                    schedule_types=declared.schedule_types,  # type: ignore[arg-type]
                    cron_repeat_modes=declared.cron_repeat_modes,  # type: ignore[arg-type]
                    explicit_time_input=declared.explicit_time_input,  # type: ignore[arg-type]
                    generated_time_mode=declared.generated_time_mode,  # type: ignore[arg-type]
                    generated_time_field=declared.generated_time_field,  # type: ignore[arg-type]
                    declared_by_action=True,
                ),
            )

        date_model = definition.date_model
        if date_model.bucket_rule == "month_last_calendar_day":
            return (self._derived("monthly_last_day", "point", ("monthly",)),)
        if date_model.bucket_rule == "month_last_open_day":
            return (self._derived("monthly_last_trading_day", "point", ("monthly",)),)
        if (
            date_model.date_axis == "month_window"
            and date_model.bucket_rule == "month_window_has_data"
            and date_model.input_shape == "start_end_month_window"
        ):
            return (self._derived("monthly_window_current_month", "range", ("monthly",)),)
        if (
            tuple(action_capability.supported_time_modes) == ("range",)
            and date_model.date_axis == "natural_day"
            and date_model.input_shape == "ann_date_or_start_end"
        ):
            return (
                self._derived(
                    "trigger_day_single_range",
                    "range",
                    ("daily", "weekly", "monthly"),
                ),
            )
        return ()

    def rule_for_policy(
        self,
        *,
        definition: DatasetDefinition,
        action: str,
        policy: str,
    ) -> DatasetScheduleTimePolicyCapability | None:
        return next((item for item in self.resolve(definition=definition, action=action) if item.policy == policy), None)

    def required_policy_for_schedule(
        self,
        *,
        definition: DatasetDefinition,
        action: str,
        schedule_type: str,
        cron_expr: str | None,
    ) -> DatasetScheduleTimePolicyCapability | None:
        rules = self.resolve(definition=definition, action=action)
        declared = next((item for item in rules if item.declared_by_action), None)
        if declared is None or schedule_type not in declared.schedule_types:
            return None
        if schedule_type != "cron":
            return declared
        repeat_mode = self.classify_cron_repeat_mode(cron_expr)
        return declared if repeat_mode in declared.cron_repeat_modes else None

    @staticmethod
    def classify_cron_repeat_mode(cron_expr: str | None) -> CronRepeatMode | None:
        parts = str(cron_expr or "").split()
        if len(parts) != 5:
            return None
        minute_expr, _hour_expr, day_of_month_expr, _month_expr, day_of_week_expr = parts
        if minute_expr.startswith("*/"):
            return "intraday_interval"
        if day_of_month_expr != "*":
            return "monthly"
        if day_of_week_expr != "*":
            return "weekly"
        return "daily"

    @staticmethod
    def _derived(
        policy: CalendarPolicy,
        generated_time_mode: Literal["point", "range"],
        cron_repeat_modes: tuple[CronRepeatMode, ...],
    ) -> DatasetScheduleTimePolicyCapability:
        return DatasetScheduleTimePolicyCapability(
            policy=policy,
            schedule_types=("cron",),
            cron_repeat_modes=cron_repeat_modes,
            explicit_time_input="forbidden",
            generated_time_mode=generated_time_mode,
            generated_time_field="trade_date" if generated_time_mode == "point" else "start_date_end_date",
        )
