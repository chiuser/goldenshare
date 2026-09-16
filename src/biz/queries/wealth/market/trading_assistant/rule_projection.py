"""Project retained rule facts, not today's price or a reconstructed outcome."""
from zoneinfo import ZoneInfo
from src.biz.schemas.wealth.market.trading_assistant import rules as dto
from src.biz.services.wealth.market.trading_assistant.rule_values import version_conditions, condition_summary


def instant(value):
    return value.astimezone(ZoneInfo("Asia/Shanghai")).isoformat() if value is not None else None


def condition_version(version, *, through=None):
    conditions = version_conditions(version)
    values = dict(ruleVersionId=str(version.rule_version_id), versionNo=str(version.version_no),
        effectiveAt=instant(version.effective_at), deadlineAt=instant(version.deadline_at),
        conditions=conditions, conditionSummary=condition_summary(conditions))
    if through is not None:
        return dto.HistoricalConditionVersion(**values, validThroughAt=instant(through))
    return dto.ConditionVersion(**values)


def coverage_summary(check):
    if check is None:
        return "尚未开始验证"
    if check.status == "COMPLETED":
        return "已完成该次范围验证"
    return {"WAITING_DATA": "数据尚不完整，等待补齐", "FAILED": "本次验证失败",
            "CHECKING": "正在验证", "PENDING": "等待验证"}[check.status]


def result_value(result, version, last_check):
    if result is None:
        return None
    point = result.first_match_at if result.triggered else (last_check.checked_through_at if last_check else None)
    conditions = version_conditions(version)
    price = volume = None
    if result.actual_price is not None:
        if conditions.priceCondition is None or point is None:
            raise ValueError("Persisted price evidence has no condition/checkpoint")
        price = dict(**conditions.priceCondition.model_dump(), actualValue=format(result.actual_price, "f"),
            satisfied=result.price_satisfied, checkpointAt=instant(point))
    if result.cumulative_volume_shares is not None:
        if conditions.volumeCondition is None or point is None:
            raise ValueError("Persisted volume evidence has no condition/checkpoint")
        # Display unit is lots. Exact decimal shift, no ambient Decimal context.
        shares = result.cumulative_volume_shares
        sign, digits, exponent = shares.as_tuple()
        lots = type(shares)((sign, digits, exponent - 2))
        volume = dict(**conditions.volumeCondition.model_dump(), actualValue=format(lots, "f"),
            satisfied=result.volume_satisfied, checkpointAt=instant(point))
    return dto.FinalResult(triggered=result.triggered, decidedAt=instant(result.decided_at),
        ruleVersionId=str(result.trigger_version_id) if result.trigger_version_id else None,
        firstTriggeredAt=instant(result.first_match_at), priceCheck=price, volumeCheck=volume,
        coverageSummary="此前有效检查点已连续核验，首次满足全部条件" if result.triggered else "整个有效范围已完整核验，未满足全部条件")


def row_value(rule, version, account, check, result, result_version, notification):
    current = condition_version(version)
    values = dict(ruleId=str(rule.rule_id), ruleVersionId=str(version.rule_version_id),
        stockRef=dict(tsCode=version.stock_code, name=version.stock_name_at_save),
        createdAt=instant(rule.created_at), effectiveAt=current.effectiveAt, deadlineAt=current.deadlineAt,
        conditions=current.conditions, conditionSummary=current.conditionSummary, ruleStatus=rule.state,
        checkStatus=check.status if check else "PENDING",
        finalResult=result_value(result, result_version, check), notificationSummary=notification)
    if rule.kind == "PLAN":
        if account is None:
            raise ValueError("Plan account reference is missing")
        return dto.PlanRow(**values, accountRef=dict(accountId=str(account.account_id), name=account.name,
            brokerName=account.broker_name), direction=version.direction)
    return dto.AlertRow(**values)


def check_value(check, basis):
    return dto.CheckRecord(checkId=str(check.check_id), checkNo=check.check_no,
        ruleVersionId=str(check.rule_version_id), tradeDate=check.trade_date.isoformat(),
        requestedFrom=instant(check.requested_from), requestedThrough=instant(check.requested_through),
        startedAt=instant(check.started_at), completedAt=instant(check.completed_at), status=check.status,
        checkedThroughAt=instant(check.checked_through_at), marketObservedAt=instant(basis.observed_at) if basis else None,
        coverageSummary=coverage_summary(check), missingRanges=check.missing_ranges,
        failureReason=check.failure_reason,
        evidenceSummary=f"{basis.source} · {basis.source_version} · 前复权收盘价／累计成交量" if basis else "尚未取得可核验的行情依据")
