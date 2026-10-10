"""Pure freezing of a weekly execution intent; never persists business plans."""

from dataclasses import asdict
import json
from uuid import UUID, uuid4

from src.foundation.datasets.stock_weekly_adj_contracts import (
    DATASET_KEY,
    SOURCE_FIELDS,
    UNIT_BUILDER,
    WRITE_PATH,
    WeeklyAdjContractError,
    canonical_json,
    digest,
    weekly_definition_issues,
)


def freeze_weekly_adj_execution(
    definition, *, scope, filters, trigger_source, previous=None
):
    policy = definition.planning.weekly_adj_policy
    if (
        policy is None
        or definition.dataset_key != DATASET_KEY
        or definition.planning.unit_builder_key != UNIT_BUILDER
        or definition.storage.write_path != WRITE_PATH
        or definition.storage.row_identity_filters != {"freq": "week"}
        or definition.source.source_fields != SOURCE_FIELDS
        or weekly_definition_issues(definition)
    ):
        raise WeeklyAdjContractError("周线具名合同和Definition不一致")
    if trigger_source not in {"manual", "schedule", "retry"}:
        raise WeeklyAdjContractError("周线触发来源无效")
    mode = (
        "scheduled_week"
        if trigger_source == "schedule"
        else "historical_refresh"
        if scope["mode"] == "range" and not filters.get("ts_code")
        else "manual_revision"
    )
    snapshot = {
        "policy": asdict(policy),
        "planning": {
            key: value
            for key, value in asdict(definition.planning).items()
            if key != "weekly_adj_policy"
        },
        "storage": asdict(definition.storage),
        "source": asdict(definition.source),
        "date_model": asdict(definition.date_model),
        "normalization": asdict(definition.normalization),
        "quality": asdict(definition.quality),
        "transaction": asdict(definition.transaction),
    }
    snapshot = json.loads(canonical_json(snapshot))
    frozen_scope = {
        "dataset_key": definition.dataset_key,
        "scope": scope,
        "filters": filters,
    }
    if previous is not None:
        if not isinstance(previous, dict):
            raise WeeklyAdjContractError("缺少周线冻结合同")
        try:
            token = str(UUID(previous["execution_token"]))
        except (ValueError, KeyError, TypeError):
            raise WeeklyAdjContractError("周线执行token无效") from None
        if (
            previous.get("contract_kind") != "stock_weekly_adj/v1"
            or previous.get("policy_snapshot") != snapshot
            or previous.get("scope_hash") != digest(frozen_scope)
            or previous.get("contract_digest") != digest(snapshot)
            or previous.get("intent")
            not in {"scheduled_week", "historical_refresh", "manual_revision"}
            or previous.get("trigger_source") not in {"manual", "schedule"}
            or previous.get("intent_digest")
            != digest(
                {
                    "execution_token": token,
                    "scope_hash": digest(frozen_scope),
                    "contract_digest": digest(snapshot),
                    "intent": previous.get("intent"),
                    "trigger_source": previous.get("trigger_source"),
                }
            )
        ):
            raise WeeklyAdjContractError("周线恢复范围、预算或意图不一致")
        mode, trigger_source = previous["intent"], previous["trigger_source"]
        expected_mode = (
            "scheduled_week"
            if trigger_source == "schedule"
            else "historical_refresh"
            if scope["mode"] == "range" and not filters.get("ts_code")
            else "manual_revision"
        )
        if mode != expected_mode:
            raise WeeklyAdjContractError("周线恢复意图与原范围不一致")
    else:
        if trigger_source == "retry":
            raise WeeklyAdjContractError("重试必须携带原冻结合同")
        token = str(uuid4())
    frozen = {
        "contract_kind": "stock_weekly_adj/v1",
        "execution_token": token,
        "contract_digest": digest(snapshot),
        "scope_hash": digest(frozen_scope),
        "policy_snapshot": snapshot,
        "intent": mode,
        "trigger_source": trigger_source,
    }
    frozen["intent_digest"] = digest(
        {
            key: frozen[key]
            for key in (
                "execution_token",
                "scope_hash",
                "contract_digest",
                "intent",
                "trigger_source",
            )
        }
    )
    if len(canonical_json(frozen).encode()) > policy.max_plan_bytes:
        raise WeeklyAdjContractError(
            "冻结合同超过计划字节预算", "weekly_adj.row_budget_exceeded"
        )
    return frozen


def build_weekly_adj_requested_units(request, definition):
    """Requested scope only. P2 resolves automatic debt/factor scopes before execution."""
    from datetime import timedelta
    from src.foundation.ingestion.plan_helpers import build_plan_units
    from src.foundation.ingestion.request_builders import (
        _stk_period_bar_adj_week_params,
    )

    policy = definition.planning.weekly_adj_policy
    if policy is None or definition.dataset_key != DATASET_KEY:
        raise WeeklyAdjContractError("具名周线规划策略不匹配")
    context = request.execution_context or {}
    try:
        token = str(UUID(context["execution_token"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise WeeklyAdjContractError("周线unit必须基于已冻结意图规划") from None
    if request.run_profile == "point_incremental":
        anchors = [request.trade_date]
        if request.trade_date is None or request.trade_date.weekday() != 4:
            raise WeeklyAdjContractError(
                "周线时间点必须为周五", "weekly_adj.scope_mismatch"
            )
    elif request.run_profile == "range_rebuild":
        if (
            request.start_date is None
            or request.end_date is None
            or request.start_date > request.end_date
        ):
            raise WeeklyAdjContractError(
                "周线历史区间不完整", "weekly_adj.scope_mismatch"
            )
        if request.params.get("ts_code"):
            anchors = [None]
        else:
            current = request.start_date + timedelta(
                days=(4 - request.start_date.weekday()) % 7
            )
            anchors = []
            while current <= request.end_date:
                if len(anchors) >= policy.max_units:
                    raise WeeklyAdjContractError(
                        "周线单元数量超过冻结预算", "weekly_adj.row_budget_exceeded"
                    )
                anchors.append(current)
                current += timedelta(days=7)
    else:
        raise WeeklyAdjContractError(
            "复权周线只支持时间点或区间", "weekly_adj.scope_mismatch"
        )
    units = build_plan_units(
        request=request,
        definition=definition,
        anchors=anchors,
        enum_combinations=[{}],
        request_builder=_stk_period_bar_adj_week_params,
        progress_context_builder=lambda anchor, values, params: {
            "unit_kind": "point_week" if anchor is not None else "stock_history",
            "ts_code": params.get("ts_code"),
            "trade_date": params.get("trade_date"),
            "start_date": params.get("start_date"),
            "end_date": params.get("end_date"),
        },
    )
    from dataclasses import replace

    return [
        replace(
            unit,
            unit_id=digest(
                {
                    "contract_version": policy.contract_version,
                    "batch_id": token,
                    "scope_digest": context["scope_hash"],
                    "kind": unit.progress_context["unit_kind"],
                    "params": unit.request_params,
                }
            ),
        )
        for unit in units
    ]
