"""M1 strict contract tests. No HTTP app, database or source adapters imported."""

import json
import calendar
from copy import deepcopy
from datetime import date
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from src.biz.schemas.wealth.market.trading_assistant import (
    accounts, calculation_status, common, errors, positions, previews, receipts, records,
    recovered_inputs, recovery, returns, robot, rules, scopes, value_types as v,
)

ID = "00000000-0000-0000-0000-000000000001"
ID2 = "00000000-0000-0000-0000-000000000002"
TRADE = dict(tsCode="600000.SH", direction="BUY", tradeDate="2026-09-14",price="10.00",quantity=1)


@pytest.mark.parametrize("value,expected", [("10","10.00"),("10.0","10.00"),("00010.00","10.00"),("-0","0.00")])
def test_type_normalization(value,expected):
    assert TypeAdapter(v.Decimal2Input).validate_python(value) == expected


@pytest.mark.parametrize("value", [10,10.0,True,None,"","1e2","1.001","NaN","Infinity"," 1","1,000","1000000000000000000"])
def test_type_invalid_decimal(value):
    with pytest.raises(ValidationError):
        TypeAdapter(v.Decimal2Input).validate_python(value)


@pytest.mark.parametrize("value", [True,False,"1",1.0,1.5,0,-1,9007199254740992])
def test_quantity_strict(value):
    with pytest.raises(ValidationError):
        TypeAdapter(v.Quantity).validate_python(value)


def test_quantity_versions_dates_and_money():
    for q in (1,39,9007199254740991):
        assert TypeAdapter(v.Quantity).validate_json(str(q)) == q
    assert TypeAdapter(v.AvailableQuantity).validate_python(0) == 0
    assert TypeAdapter(v.Version).validate_python("009007199254740992") == "9007199254740992"
    assert TypeAdapter(v.EntityId).validate_python(ID.upper()) == ID
    assert TypeAdapter(v.Money).validate_python("1" + "0" * 70 + ".01").endswith(".01")
    for kind,value in ((v.Version,1),(v.PositiveVersion,"0"),(v.Version,"9223372036854775808"),
                       (v.BusinessDate,"2026-02-29"),(v.BusinessDate,date(2026,9,14)),
                       (v.Month,"2026-13"),(v.Instant,"2026-09-14T10:30:00"),
                       (v.DeadlineAt,"2026-09-14T10:30:01+08:00"),
                       (v.DeadlineAt,"2026-09-14T10:30:00Z"),
                       (v.Money,"-0.00"),(v.Money,"1.0"),(v.Money,1.0)):
        with pytest.raises(ValidationError):
            TypeAdapter(kind).validate_python(value)
    assert TypeAdapter(v.DeadlineAt).validate_python("2026-09-14T10:30:00+08:00")


def test_grapheme_capacity_and_preservation():
    for kind,limit in ((v.AccountName,50),(v.BrokerName,50),(v.Note,500)):
        for grapheme in ("中","e\u0301","👨‍👩‍👧‍👦"):
            value = grapheme * limit
            assert TypeAdapter(kind).validate_python(value) == value
            with pytest.raises(ValidationError):
                TypeAdapter(kind).validate_python(value+grapheme)
    assert TypeAdapter(v.Note).validate_python("  保留备注  ") == "  保留备注  "
    assert TypeAdapter(v.Decimal2Input).validate_python("000"+"9"*18) == "9"*18+".00"


@pytest.mark.parametrize("field", ["commissionAmount","stampTaxAmount","commissionRateWan","stampTaxRatePct","ownerId","closedTradeId","profitAmount"])
def test_fee_and_derived_fields_cannot_be_written(field):
    with pytest.raises(ValidationError):
        accounts.TradeInput.model_validate({**TRADE,field:"0.00"})


def test_initialization_and_tax_zero():
    base = dict(clientRowId="row-a",tsCode="600000.SH",quantity=1000,costPrice="10")
    for qty in (0,600,1000):
        assert accounts.InitializationPositionInput(**base,availableQuantity=qty).availableQuantity == qty
    for qty in (None,-1,1001,1.5,True):
        with pytest.raises(ValidationError):
            accounts.InitializationPositionInput(**base,availableQuantity=qty)
    with pytest.raises(ValidationError):
        accounts.InitializationPositionInput(**base)
    data = dict(name="账户",brokerName="券商",commissionRateWan="3",minimumCommission="0",
                stampTaxRatePct="0",initialCash="0",initialPositions=[])
    result = accounts.CreateAccountInput(**data)
    assert result.minimumCommission == result.stampTaxRatePct == result.initialCash == "0.00"
    for key in ("brokerName","commissionRateWan","minimumCommission"):
        with pytest.raises(ValidationError):
            accounts.CreateAccountInput(**{k:v for k,v in data.items() if k != key})
    row = {**base,"availableQuantity":0}
    with pytest.raises(ValidationError):
        accounts.CreateAccountInput(**{**data,"initialPositions":[row,row]})
    for tax in ("-0.01","100.01","0.001"):
        with pytest.raises(ValidationError):
            accounts.CreateAccountInput(**{**data,"stampTaxRatePct":tax})


def test_commands_scope_and_receipt_keys():
    command = accounts.TradeCommand(**TRADE,requestId=ID,attemptId=ID2)
    assert accounts.TradeCommand.model_validate_json(command.model_dump_json(exclude_unset=True)) == command
    assert accounts.TradeInput(**TRADE).note is None
    for bad in (dict(accountMode="ALL",accountId=ID),dict(accountMode="ALL",accountId=None),dict(accountMode="SINGLE")):
        with pytest.raises(ValidationError):
            common.AccountScopeInput(**bad)
    with pytest.raises(ValidationError):
        common.ScopeInput(accountMode="ALL",stockMode="ALL",tsCode="600000.SH")
    with pytest.raises(ValidationError):
        common.ReturnTriple(profitAmount="0.00",capitalAmount=None,returnPct="0.00")
    with pytest.raises(ValidationError):
        common.ReturnTriple(profitAmount="0.00",capitalAmount="0.00",returnPct="0.00")
    with pytest.raises(ValidationError):
        common.ReturnTriple()
    assert common.ReturnTriple(profitAmount=None,capitalAmount=None,returnPct=None).capitalAmount is None


def test_condition_branches():
    assert rules.Conditions(priceCondition=None,volumeCondition={"operator":"GTE","thresholdLots":"0.01"})
    for price in ({"operator":"LTE","upper":"10"},{"operator":"GTE","lower":"10"},
                  {"operator":"BETWEEN","lower":"10","upper":"10"}):
        assert rules.Conditions(priceCondition=price,volumeCondition=None)
    for price in ({"operator":"LTE","upper":"10","lower":"1"},{"operator":"GT","lower":"1"},
                  {"operator":"BETWEEN","lower":"11","upper":"10"},None):
        with pytest.raises(ValidationError):
            rules.Conditions(priceCondition=price,volumeCondition=None)
    fields = dict(stockCode="600000.SH",deadlineAt="2026-09-14T10:30:00+08:00",source="STOCK_DETAIL",
                  priceCondition={"operator":"LTE","upper":"10"},volumeCondition=None)
    assert rules.CreatePlanInput(**fields,accountId=ID,direction="SELL").notifyEnabled is False
    with pytest.raises(ValidationError):
        rules.CreatePlanInput(**fields,accountId=ID,direction="SELL",notifyEnabled=True)
    with pytest.raises(ValidationError):
        rules.CreateAlertInput(**fields,robotId=ID,accountId=ID)
    with pytest.raises(ValidationError):
        rules.CreateAlertInput(**fields,robotId=ID,notifyEnabled=False)


def test_closed_trade_exact_field_fixture():
    fixture = dict(accountRef={"accountId":ID,"name":"账户","brokerName":"券商"},
                   stockRef={"tsCode":"600000.SH","name":"股票"},tradeId=ID2,sellRevision="1",
                   tradeDate="2026-09-14",recordedAt="2026-09-14T16:00:00+08:00",
                   roundRef={"accountId":ID,"roundId":ID2,"roundNumber":1,"status":"OPEN"},
                   quantity=100,price="34.00",grossAmount="3400.00",commissionAmount="4.00",stampTaxAmount="1.70",
                   totalFeeAmount="5.70",netProceeds="3394.30",dayOpeningUnitCost="33.33",
                   allocatedCost="3333.34",dayEndQuantity=200,dayGroup={"accountId":ID,"tsCode":"600000.SH","tradeDate":"2026-09-14"},
                   calculationRuleVersion="1",dayResultId=ID2,profitAmount="60.96",returnPct="1.83")
    result = records.ClosedTrade(**fixture)
    assert set(fixture) == set(records.ClosedTrade.model_fields)
    for field in fixture:
        with pytest.raises(ValidationError):
            records.ClosedTrade(**{key:value for key,value in fixture.items() if key != field})
    for field in ("allocatedCost","quantity","dayEndQuantity","profitAmount"):
        with pytest.raises(ValidationError):
            records.ClosedTrade(**{**fixture,field:None})
    assert result.model_dump(mode="json") == fixture


def test_all_current_models_generate_strict_json_schema():
    for module in (accounts, calculation_status, common, errors, positions, previews, receipts,
                   records, recovered_inputs, recovery, returns, robot, rules, scopes):
        for cls in vars(module).values():
            if isinstance(cls,type) and issubclass(cls,common.Contract) and cls.__module__ == module.__name__:
                schema = cls.model_json_schema()
                assert schema["additionalProperties"] is False, cls.__name__
                json.dumps(schema,allow_nan=False)


def test_read_context_has_only_existing_fields():
    account = dict(accountId=ID, factVersion="1", calculationTargetVersion="2", publishedGenerationId=None)
    fixture = dict(contextToken="eyJ2IjoxfQ", accounts=[account], targetThrough="2026-09-11T15:00:00+08:00")
    assert common.ReadContext(**fixture).model_dump() == fixture
    assert common.ReadContext(**{**fixture, "accounts": []})
    for key in fixture:
        with pytest.raises(ValidationError):
            common.ReadContext(**{k: value for k, value in fixture.items() if k != key})
    for bad_accounts in ([account, account], [{**account, "accountId": ID2}, account],
                         [{**account, "valuationBasisDigest": "a" * 64}],
                         [{**account, "publishedGenerationId": "0"}],
                         [{**account, "factVersion": "0"}]):
        with pytest.raises(ValidationError):
            common.ReadContext(**{**fixture, "accounts": bad_accounts})
    for token in ("", "token=", "token with spaces", None, 1):
        with pytest.raises(ValidationError):
            common.ReadContext(**{**fixture, "contextToken": token})


def test_recovery_summary_is_required_text_not_recovered_input():
    fixture = dict(title="卖出登记", lines=["账户：主账户", "卖出：400 股，成交价 40.00 元"])
    result = recovery.RecoverySummary(**fixture)
    assert result.model_dump() == fixture
    assert recovery.RecoverySummary.model_validate_json(result.model_dump_json()) == result
    for key in fixture:
        with pytest.raises(ValidationError):
            recovery.RecoverySummary(**{k: value for k, value in fixture.items() if k != key})
    for extra in ("requestId", "webhook", "secret", "receipt", "input", "outcome"):
        with pytest.raises(ValidationError):
            recovery.RecoverySummary(**fixture, **{extra: "not allowed"})
    for invalid in ({"title": " "}, {"title": 123}, {"lines": [None]}, {"lines": [""]}, {"lines": "text"}):
        with pytest.raises(ValidationError):
            recovery.RecoverySummary(**{**fixture, **invalid})


def calendar_fixture(month="2026-09", today="2026-09-11"):
    context = dict(contextToken="eyJ2IjoxfQ", accounts=[], targetThrough="2026-09-11T15:00:00+08:00")
    coverage = dict(dataStatus="Empty", reason="无收益结果", isFinal=False, accounts=[])
    summary = dict(periodProfitAmount=None, periodCapitalAmount=None, periodReturnPct=None,
                   positiveDayCount=0, negativeDayCount=0, flatDayCount=0, computedDayCount=0,
                   minDailyReturnPct=None, minDailyReturnDates=[], closedTradeCount=0,
                   closedProfitAmount="0.00", periodCoverage=coverage, dailyStatsCoverage=coverage,
                   closedCoverage=coverage)
    year, month_number = map(int, month.split("-"))
    days = []
    for value in calendar.Calendar().itermonthdates(year, month_number):
        if value.weekday() >= 5:
            continue
        value = value.isoformat()
        temporal = "PAST" if value < today else "FUTURE" if value > today else "TODAY"
        days.append(dict(date=value, inSelectedMonth=value[:7] == month, temporalState=temporal,
                         profitAmount=None, capitalAmount=None, returnPct=None,
                         calculationState=None if temporal == "FUTURE" else "Empty",
                         reason=None if temporal == "FUTURE" else "纯现金，无股票收益",
                         valuationAt=None, readContext=None))
    return dict(month=month, today=today, calculatedThrough=None, days=days, monthSummary=summary,
                readContext=context)


def test_calendar_required_keys_and_weekday_grid():
    fixture = calendar_fixture()
    result = returns.CalendarResponse(**fixture)
    assert result.model_dump() == fixture
    assert len(result.days) == 25
    for field in fixture:
        with pytest.raises(ValidationError):
            returns.CalendarResponse(**{key: value for key, value in fixture.items() if key != field})
    for field in fixture["days"][0]:
        changed = deepcopy(fixture)
        del changed["days"][0][field]
        with pytest.raises(ValidationError):
            returns.CalendarResponse(**changed)
    for field in fixture["monthSummary"]:
        changed = deepcopy(fixture)
        del changed["monthSummary"][field]
        with pytest.raises(ValidationError):
            returns.CalendarResponse(**changed)
    for bad_days in (fixture["days"][:-1], list(reversed(fixture["days"])), fixture["days"] * 2):
        with pytest.raises(ValidationError):
            returns.CalendarResponse(**{**fixture, "days": bad_days})


def test_calendar_zero_partial_future_and_month_extremes():
    fixture = calendar_fixture()
    ready = dict(profitAmount="0.00", capitalAmount="10000.00", returnPct="0.00",
                 calculationState="Ready", reason=None, valuationAt="2026-09-01T15:00:00+08:00",
                 readContext=fixture["readContext"])
    fixture["days"][1].update(ready)
    fixture["monthSummary"].update(computedDayCount=1, flatDayCount=1,
                                    minDailyReturnPct="0.00", minDailyReturnDates=["2026-09-01"])
    assert returns.CalendarResponse(**fixture).days[1].profitAmount == "0.00"
    for patch in ({"calculationState":"Partial"}, {"calculationState":"Delayed"},
                  {"capitalAmount":"0.00"}, {"returnPct":0}, {"inSelectedMonth":False},
                  {"readContext":None}, {"temporalState":"FUTURE"}):
        changed = deepcopy(fixture)
        changed["days"][1].update(patch)
        with pytest.raises(ValidationError):
            returns.CalendarResponse(**changed)
    for patch in ({"computedDayCount":0}, {"closedProfitAmount":None},
                  {"minDailyReturnDates":["2026-08-31"]},
                  {"minDailyReturnDates":["2026-09-01","2026-09-01"]},
                  {"minDailyReturnDates":[]}, {"positiveDayCount":True}):
        changed = deepcopy(fixture)
        changed["monthSummary"].update(patch)
        with pytest.raises(ValidationError):
            returns.CalendarResponse(**changed)
    changed = deepcopy(fixture)
    changed["days"][-1].update(ready)
    with pytest.raises(ValidationError):
        returns.CalendarResponse(**changed)


def test_calendar_grid_all_months_in_gregorian_cycle():
    # Independent stdlib grid fixture, not the implementation's date algorithm.
    for year in range(2000, 2400):
        for month in range(1, 13):
            result = returns.CalendarResponse(**calendar_fixture(f"{year}-{month:02d}"))
            assert 20 <= len(result.days) <= 30


def test_curve_null_period_keeps_identity_and_order():
    context = calendar_fixture()["readContext"]
    coverage = dict(dataStatus="Empty", reason="纯现金", isFinal=True, accounts=[])
    point = dict(**coverage, profitAmount=None, capitalAmount=None, returnPct=None,
                 periodStartDate="2026-09-01", periodEndDate="2026-09-30", isPeriodEnded=True)
    fixture = dict(scope=dict(accountMode="ALL", accounts=[], stockMode="ALL", stockRef=None),
                   requestedStartDate="2026-09-01", requestedEndDate="2026-09-30", granularity="MONTH",
                   readContext=context, coverage=coverage, points=[point])
    assert returns.CurveResponse(**fixture).points[0].periodStartDate == "2026-09-01"
    for patch in ({"points":[point,point]}, {"requestedEndDate":"2026-08-01"}, {"granularity":"YEAR"}):
        with pytest.raises(ValidationError):
            returns.CurveResponse(**{**fixture, **patch})


def test_entry_context_cash_only_and_stock_quantity_branches():
    fixture = dict(accountId=ID, factVersion="1", occurredOn="2026-09-11",
                   cashThrough="2026-09-11T15:00:00+08:00", availableCash="0.00",
                   stockRef=None, quantity=None, availableQuantity=None,
                   fees=dict(accountId=ID, feeVersionId=ID2, commissionRateWan="2.50",
                             minimumCommission="5.00", stampTaxRatePct="0.05"),
                   calendarDataStatus="Ready", reason=None)
    assert accounts.EntryContext(**fixture).quantity is None
    stock = dict(stockRef={"tsCode":"600000.SH", "name":"股票"}, quantity=101, availableQuantity=1)
    assert accounts.EntryContext(**{**fixture, **stock}).availableQuantity == 1
    for field in fixture:
        with pytest.raises(ValidationError):
            accounts.EntryContext(**{k: val for k, val in fixture.items() if k != field})
    for patch in ({"quantity":0}, {"availableCash":"-0.01"},
                  {"fees":{**fixture["fees"], "accountId":ID2}},
                  {**stock, "availableQuantity":102}, {**stock, "quantity":None}):
        with pytest.raises(ValidationError):
            accounts.EntryContext(**{**fixture, **patch})
    defaults = dict(stampTaxRatePct="0.05", commissionRateUnit="WAN", stampTaxRateUnit="PERCENT", currency="CNY")
    assert accounts.InitializationDefaults(**defaults)
    with pytest.raises(ValidationError):
        accounts.InitializationDefaults(**defaults, minimumCommission="5.00")


def test_records_summary_and_empty_page_are_not_unknown_results():
    context = calendar_fixture()["readContext"]
    scope = dict(accountMode="ALL", accounts=[], stockMode="ALL", stockRef=None)
    fixture = dict(scope=scope, requestedStartDate="2026-09-01", requestedEndDate="2026-09-30",
                   readContext=context, tradeCount=2, buyCount=1, sellCount=1,
                   cashInAmount="0.00", cashOutAmount="0.00", closedTradeCount=None,
                   closedProfitAmount=None, closedDataStatus="Recalculating", reason="重算中")
    assert records.RecordsSummary(**fixture).tradeCount == 2
    for patch in ({"tradeCount":1}, {"tradeCount":True}, {"closedTradeCount":0},
                  {"cashInAmount":None}, {"requestedEndDate":"2026-08-01"}):
        with pytest.raises(ValidationError):
            records.RecordsSummary(**{**fixture, **patch})
    page = dict(scope=scope, requestedStartDate="2026-09-01", requestedEndDate="2026-09-30",
                readContext=context, coverage=dict(dataStatus="Empty", reason="无记录", isFinal=True, accounts=[]),
                items=[], nextCursor=None)
    assert records.RecordsResponse[records.TradeRecord](**page).items == []
    with pytest.raises(ValidationError):
        records.RecordsResponse[records.TradeRecord](**{**page, "nextCursor":"next"})
    with pytest.raises(ValidationError):
        records.RecordsResponse[records.TradeRecord](**{**page, "items":[{"tradeId":ID}]})


def operation_fixtures():
    account = dict(accountId=ID, name="账户", brokerName="券商")
    fees = dict(accountId=ID, feeVersionId=ID2, commissionRateWan="2.50", minimumCommission="5.00", stampTaxRatePct="0.05")
    fee_values = {key: value for key, value in fees.items() if key not in ("accountId", "feeVersionId")}
    initialization = dict(accountId=ID, initializedOn="2026-09-11", initializationId=ID2,
                          initializationRevision="1", initialCash="0.00", initialPositions=[])
    fee_breakdown = dict(grossAmount="10.00", commissionAmount="5.00", stampTaxAmount="0.00",
                         netCashChange="-15.00", feeVersionId=ID2)
    trade = dict(accountId=ID, tradeId=ID2, revision="1", factVersion="1", affectedFromDate="2026-09-11", **fee_breakdown)
    cash = dict(accountId=ID, cashFlowId=ID2, revision="1", factVersion="1", affectedFromDate="2026-09-11", netCashChange="10.00")
    conditions = dict(priceCondition={"operator":"LTE", "upper":"10.00"}, volumeCondition=None)
    notice = dict(notificationId=None, state="NOT_ENABLED", stateVersion=None, robotId=None,
                  robotName=None, canRetry=False, reason=None)
    rule = dict(ruleId=ID, ruleVersionId=ID2, stockRef={"tsCode":"600000.SH", "name":"股票"},
                createdAt="2026-09-11T16:00:00+08:00", effectiveAt="2026-09-11T16:00:00+08:00",
                deadlineAt="2026-09-14T10:30:00+08:00", conditions=conditions, conditionSummary="价格不高于10.00",
                ruleStatus="ACTIVE", checkStatus="PENDING", finalResult=None, notificationSummary=notice)
    config = dict(name="机器人", maskedWebhook="***", hasSigningSecret=False, keywords=[])
    progress = dict(accountId=ID, calculationTargetVersion="1", publishedGenerationId=None, affectedFromDate="2026-09-11",
                    stage="PREPARING", reason=None, progress=dict(completedTradeDateCount=0, totalTradeDateCount=None,
                    currentTradeDate=None, lastCompletedTradeDate=None, lastBusinessUpdatedAt=None))
    results = {
        "ACCOUNT_CREATE": dict(account={**account, "initializedOn":"2026-09-11", "factVersion":"1", "feeVersionId":ID2}, initialization=initialization, fees=fees),
        "INITIALIZATION_CORRECT": dict(accountId=ID, initializationId=ID2, initializationRevision="2", factVersion="2", affectedFromDate="2026-09-11"),
        "FEES_UPDATE": fees,
        "TRADE_CREATE": trade, "TRADE_CORRECT": trade, "TRADE_VOID": {**trade, "status":"VOID"},
        "CASH_FLOW_CREATE": cash, "CASH_FLOW_CORRECT": cash, "CASH_FLOW_VOID": {**cash, "status":"VOID"},
        "CALCULATION_RETRY": progress,
        "PLAN_CREATE": dict(**rule, accountRef=account, direction="BUY"), "ALERT_CREATE": rule,
        "RULE_CONDITIONS_UPDATE": dict(operationType="REVISE_CONDITIONS", ruleId=ID, acceptedStateVersion="2",
             ruleVersionId=ID2, effectiveAt=rule["effectiveAt"], conditions=conditions, conditionSummary=rule["conditionSummary"]),
        "RULE_CLOSE": dict(operationType="CLOSE", ruleId=ID, acceptedStateVersion="2", ruleVersionId=ID2,
                           closedAt=rule["effectiveAt"], ruleStatus="CLOSED", finalResult=None),
        "ROBOT_CANDIDATE_CREATE": dict(**config, candidateId=ID, candidateVersion="1"),
        "ROBOT_TEST": dict(testId=ID, state="IN_FLIGHT", startedAt=rule["effectiveAt"], completedAt=None, reason=None),
        "ROBOT_CONFIRM": dict(**config, robotId=ID, configVersionId=ID2),
        "NOTIFICATION_RETRY": dict(notificationId=ID, stateVersion="2", state="PENDING"),
    }
    basic_rule = dict(stockCode="600000.SH", deadlineAt=rule["deadlineAt"], source="STOCK_DETAIL", **conditions)
    inputs = {
        "ACCOUNT_CREATE": dict(name="账户", brokerName="券商", **fee_values, initialCash="0.00", initialPositions=[]),
        "INITIALIZATION_CORRECT": dict(initialCash="0.00", initialPositions=[], expectedRevision="1"),
        "FEES_UPDATE": dict(**fee_values, expectedFeeVersionId=ID2),
        "TRADE_CREATE": TRADE, "TRADE_CORRECT": dict(**TRADE, expectedRevision="1"), "TRADE_VOID": dict(expectedRevision="1"),
        "CASH_FLOW_CREATE": dict(direction="IN", occurredOn="2026-09-11", amount="10.00"),
        "CASH_FLOW_CORRECT": dict(direction="IN", occurredOn="2026-09-11", amount="10.00", expectedRevision="1"),
        "CASH_FLOW_VOID": dict(expectedRevision="1"), "CALCULATION_RETRY": dict(calculationTargetVersion="1"),
        "PLAN_CREATE": dict(**basic_rule, accountId=ID, direction="BUY"), "ALERT_CREATE": dict(**basic_rule, robotId=ID),
        "RULE_CONDITIONS_UPDATE": dict(**conditions, expectedStateVersion="1"), "RULE_CLOSE": dict(expectedStateVersion="1"),
        "ROBOT_CANDIDATE_CREATE": dict(**config, expectedConfigVersionId=None),
        "ROBOT_TEST": dict(expectedCandidateVersion="1"),
        "ROBOT_CONFIRM": dict(expectedConfigVersionId=None, testId=ID, receivedConfirmed=True),
        "NOTIFICATION_RETRY": dict(expectedStateVersion="1"),
    }
    return results, inputs


@pytest.mark.parametrize("operation", list(operation_fixtures()[0]))
def test_all_operation_receipts_and_recovery_inputs(operation):
    results, inputs = operation_fixtures()
    fixture = dict(requestId=ID, attemptId=ID2, operationType=operation,
                   acceptedAt="2026-09-11T16:00:00+08:00", result=results[operation])
    adapter = TypeAdapter(receipts.SuccessReceipt)
    parsed = adapter.validate_python(fixture)
    assert parsed.model_dump() == fixture
    for field in fixture:
        with pytest.raises(ValidationError):
            adapter.validate_python({key: value for key, value in fixture.items() if key != field})
    for field in fixture["result"]:
        with pytest.raises(ValidationError):
            adapter.validate_python({**fixture, "result":{key: value for key, value in fixture["result"].items() if key != field}})
    with pytest.raises(ValidationError):
        adapter.validate_python({**fixture, "result":{**fixture["result"], "unexpected":"rejected"}})
    input_fixture = dict(requestId=ID, operationType=operation, inputSchemaVersion="1", input=inputs[operation])
    recovered = TypeAdapter(recovered_inputs.RecoveryInputResponse).validate_python(input_fixture)
    assert recovered.operationType == operation
    assert "attemptId" not in type(recovered.input).model_fields
    with pytest.raises(ValidationError):
        TypeAdapter(recovered_inputs.RecoveryInputResponse).validate_python({**input_fixture, "input":{**inputs[operation], "commissionAmount":"5.00"}})


def test_recovery_does_not_infer_not_saved_or_mix_receipts():
    fixture = dict(requestId=ID, attemptId=ID2, operationType="TRADE_CREATE",
                   scope=dict(scopeType="ACCOUNT_LEDGER", accountId=ID), stateVersion="1", outcome="UNKNOWN",
                   inputRetained=False, summary=dict(title="买入登记", lines=[]), receipt=None, rejection=None,
                   updatedAt="2026-09-11T16:00:00+08:00")
    assert recovery.PendingRecoveryResponse(pendingRequest=fixture)
    success = dict(requestId=ID, attemptId=ID2, operationType="TRADE_CREATE", acceptedAt=fixture["updatedAt"],
                   result=operation_fixtures()[0]["TRADE_CREATE"])
    assert recovery.RecoveryStatusDto(**{**fixture, "outcome":"SAVED", "receipt":success})
    for patch in ({"outcome":"SAVED"}, {"receipt":success}, {"outcome":"NOT_SAVED", "receipt":success},
                  {"scope":{"scopeType":"ROBOT"}}, {"outcome":"FAILED"}, {"inputRetained":1},
                  {"rejection":{"code":"TA_WRITE_FAILED", "message":"未保存", "field":None}},
                  {"outcome":"SAVED", "receipt":{**success, "attemptId":ID}}):
        with pytest.raises(ValidationError):
            recovery.RecoveryStatusDto(**{**fixture, **patch})
    with pytest.raises(ValidationError):
        recovery.PendingRecoveryResponse(pendingRequest={**fixture, "outcome":"NOT_SAVED"})
    assert recovery.PendingRecoveryResponse(pendingRequest=None).pendingRequest is None


def test_robot_secret_intents_and_output_separation():
    candidate = dict(expectedConfigVersionId=None, name="机器人", webhook={"action":"REPLACE", "value":"private-address"},
                     signingSecret={"action":"REPLACE", "value":"private-secret"}, keywords=[])
    parsed = robot.CandidateInput(**candidate)
    assert "private-address" not in repr(parsed) and "private-secret" not in parsed.model_dump_json()
    for patch in ({"webhook":{"action":"CLEAR"}}, {"webhook":{"action":"KEEP"}},
                  {"signingSecret":{"action":"KEEP"}}, {"webhook":{"action":"REPLACE", "value":123}},
                  {"webhook":{"action":"REPLACE", "value":""}}, {"groupId":"forbidden"}):
        with pytest.raises(ValidationError):
            robot.CandidateInput(**{**candidate, **patch})
    assert robot.CandidateInput(**{**candidate, "expectedConfigVersionId":ID, "webhook":{"action":"KEEP"}, "signingSecret":{"action":"CLEAR"}})
    for confirmed in (False, 1, "true"):
        with pytest.raises(ValidationError):
            robot.ConfirmCandidateInput(expectedConfigVersionId=None, testId=ID, receivedConfirmed=confirmed)
    assert robot.RobotResponse(robot=None).robot is None
    safe = operation_fixtures()[1]["ROBOT_CANDIDATE_CREATE"]
    with pytest.raises(ValidationError):
        recovered_inputs.SafeCandidateInput(**safe, webhook="private-address")


def test_query_scope_and_pagination_boundaries():
    for count in (1, 20, 100):
        assert scopes.Pagination(limit=count).limit == count
    for count in (0, -1, 101, True, 2.5, "20"):
        with pytest.raises(ValidationError):
            scopes.Pagination(limit=count)
    adapter = TypeAdapter(scopes.ClosedRecordsQuery)
    assert adapter.validate_python(dict(accountId=ID, roundId=ID2))
    assert adapter.validate_python(dict(accountMode="ALL", stockMode="ALL", requestedStartDate="2026-09-01", requestedEndDate="2026-09-30"))
    for extra in ({"accountMode":"ALL"}, {"requestedStartDate":"2026-09-01"}, {"tsCode":"600000.SH"}):
        with pytest.raises(ValidationError):
            adapter.validate_python(dict(accountId=ID, roundId=ID2, **extra))
    with pytest.raises(ValidationError):
        TypeAdapter(scopes.RecoveryScope).validate_python({"scopeType":"RULE_CREATE", "ruleType":"ALERT", "tsCode":"600000.SH", "accountId":ID})


def assert_complete_fixture(model, fixture):
    parsed = model.model_validate(fixture)
    assert model.model_validate_json(parsed.model_dump_json()) == parsed
    for name, field in model.model_fields.items():
        key = field.alias or name
        if field.is_required():
            with pytest.raises(ValidationError):
                model.model_validate({k: value for k, value in fixture.items() if k != key})
    with pytest.raises(ValidationError):
        model.model_validate({**fixture, "notInContract": "rejected"})
    return parsed


def holding_fixtures():
    account = dict(accountId=ID, name="账户", brokerName="券商")
    stock = dict(tsCode="600000.SH", name="股票")
    light_round = dict(accountId=ID, roundId=ID2, roundNumber=1)
    row = dict(stockRef=stock, quantity=600, availableQuantity=600, dynamicCostPrice="6.67",
               dynamicCostAmount="4000.00", price="15.00", marketValue="9000.00",
               holdingProfitAmount="5000.00", holdingReturnPct="50.00", dayProfitAmount="0.00",
               stockValueWeightPct="100.00", totalAssetWeightPct="90.00", estimatedSellCommission="0.00",
               estimatedStampTax="0.00", estimatedNetProceeds="9000.00", industry=None,
               quoteAt="2026-09-11T15:00:00+08:00", accountRounds=[light_round], dataStatus="Ready", reason=None)
    scope = dict(accountMode="ALL", accounts=[account], stockMode="ALL", stockRef=None)
    context = calendar_fixture()["readContext"]
    coverage = dict(dataStatus="Ready", reason=None, isFinal=True, accounts=[])
    weighted = dict(stockRef=stock, marketValue="9000.00", weightPct="100.00")
    summary = dict(cashAmount="1000.00", stockMarketValue="9000.00", totalAssets="10000.00",
                   holdingProfitAmount="5000.00", holdingReturnPct="50.00", dayProfitAmount="0.00",
                   dayReturnPct="0.00", positionCount=1, largestPosition=weighted)
    allocation = dict(stockMarketValue="9000.00", totalAssets="10000.00",
                      stockValueSlices=[dict(kind="STOCK", **weighted, members=[])],
                      totalAssetSlices=[dict(kind="STOCK", **{**weighted,"weightPct":"90.00"}, members=[]),
                                        dict(kind="CASH", stockRef=None, marketValue="1000.00", weightPct="10.00", members=[])])
    return row, dict(scope=scope, readContext=context, coverage=coverage, items=[row], summary=summary, allocation=allocation)


def test_positions_complete_values_unknowns_and_pie_members():
    row, fixture = holding_fixtures()
    assert_complete_fixture(positions.PositionRow, row)
    assert_complete_fixture(positions.PositionsResponse, fixture)
    assert_complete_fixture(positions.PositionsSummary, fixture["summary"])
    assert_complete_fixture(positions.Allocation, fixture["allocation"])
    assert_complete_fixture(positions.PositionRow, {**row, "dynamicCostPrice":"-1.00", "dynamicCostAmount":"-600.00"})
    for patch in ({"quantity":0}, {"availableQuantity":601}, {"accountRounds":[]},
                  {"accountRounds":row["accountRounds"] * 2}, {"marketValue":"Infinity"}, {"dayProfitAmount":0.0}):
        with pytest.raises(ValidationError):
            positions.PositionRow(**{**row, **patch})
    unknown = {**row, "marketValue":None, "holdingProfitAmount":None, "holdingReturnPct":None,
               "dataStatus":"Delayed", "reason":"行情未就绪"}
    assert positions.PositionRow(**unknown).marketValue is None
    members = [dict(stockRef={"tsCode":f"{index:06}.SH", "name":"股票"}, marketValue="100.00", weightPct="1.00") for index in range(8,12)]
    other = dict(kind="OTHER", stockRef=None, marketValue="400.00", weightPct="4.00", members=members)
    assert len(assert_complete_fixture(positions.AllocationSlice, other).members) == 4
    for patch in ({"members":members[:-1]}, {"kind":"CASH"}, {"stockRef":row["stockRef"]}):
        with pytest.raises(ValidationError):
            positions.AllocationSlice(**{**other, **patch})
    with pytest.raises(ValidationError):
        positions.Allocation(stockMarketValue=None, totalAssets=None, stockValueSlices=[], totalAssetSlices=[])
    extreme = dict(stockRef=row["stockRef"], profitAmount="100.00")
    contribution = dict(maxPositive=extreme, maxNegative=None, positiveCount=1, negativeCount=0,
                        flatCount=0, positiveAmount="100.00", negativeAmount="0.00", unknownCount=0,
                        dataStatus="Ready", reason=None)
    assert_complete_fixture(positions.HoldingContributions, contribution)
    with pytest.raises(ValidationError):
        positions.HoldingContributions(**{**contribution, "maxNegative":extreme})
    analysis = dict(scope=fixture["scope"], readContext=fixture["readContext"], coverage=fixture["coverage"],
                    largestPosition=fixture["summary"]["largestPosition"], top3WeightPct="100.00", top5WeightPct="100.00",
                    cashWeightPct="10.00", cashAmount="1000.00", industries=[dict(industryCode=None, industryName="未分类",
                    marketValue="9000.00", weightPct="100.00", classificationStatus="UNCLASSIFIED")], cumulative=contribution, daily=contribution)
    assert_complete_fixture(positions.PositionsAnalysis, analysis)


def test_rule_final_result_checks_and_details():
    row = operation_fixtures()[0]["ALERT_CREATE"]
    assert_complete_fixture(rules.AlertRow, row)
    final = dict(triggered=True, decidedAt="2026-09-14T17:00:00+08:00", ruleVersionId=ID2,
                 firstTriggeredAt="2026-09-14T10:20:00+08:00", coverageSummary="此前检查范围完整",
                 priceCheck=dict(operator="LTE", upper="10.00", actualValue="9.99", satisfied=True, checkpointAt="2026-09-14T10:20:00+08:00"), volumeCheck=None)
    assert_complete_fixture(rules.FinalResult, final)
    assert rules.AlertRow(**{**row, "ruleStatus":"ENDED", "finalResult":final})
    with pytest.raises(ValidationError):
        rules.AlertRow(**{**row, "finalResult":final})
    for patch in ({"triggered":1}, {"ruleVersionId":None}, {"priceCheck":None},
                  {"priceCheck":{**final["priceCheck"], "satisfied":False}},
                  {"volumeCheck":dict(operator="GTE", thresholdLots="10.00", actualValue="11.00", satisfied=True, checkpointAt="2026-09-14T10:21:00+08:00")}):
        with pytest.raises(ValidationError):
            rules.FinalResult(**{**final, **patch})
    check = dict(checkId=ID, checkNo=1, ruleVersionId=ID2, tradeDate="2026-09-14",
                 requestedFrom="2026-09-14T09:31:00+08:00", requestedThrough="2026-09-14T10:30:00+08:00",
                 startedAt=final["decidedAt"], completedAt=None, status="WAITING_DATA", checkedThroughAt=None,
                 marketObservedAt=None, coverageSummary="分钟缺数", missingRanges=[{"from":"2026-09-14T09:31:00+08:00", "through":"2026-09-14T09:32:00+08:00"}],
                 failureReason=None, evidenceSummary="尚未形成最终结果")
    assert assert_complete_fixture(rules.CheckRecord, check).model_dump() == check
    detail = dict(**row, stateVersion="1", serverNow="2026-09-11T16:00:00+08:00", closedAt=None, endedAt=None,
                  currentConditionVersion=dict(ruleVersionId=ID2, versionNo="1", effectiveAt=row["effectiveAt"], deadlineAt=row["deadlineAt"], conditions=row["conditions"], conditionSummary=row["conditionSummary"]),
                  maintenance=dict(canEditConditions=True, canClose=True, editUnavailableReason=None, closeUnavailableReason=None),
                  checkedAt=None, marketObservedAt=None, coverageSummary="待检查", missingRanges=[], failureReason=None)
    assert_complete_fixture(rules.AlertDetail, detail)
    for state in ("UNKNOWN", "SUCCEEDED", "SENDING"):
        with pytest.raises(ValidationError):
            rules.NotificationSummary(notificationId=ID, state=state, stateVersion="1", robotId=ID,
                                      robotName="机器人", canRetry=True, reason=None)


def test_error_and_progress_outputs_are_not_business_success():
    error = dict(code="TA_REQUEST_INVALID", message="填写数据错误", requestId=None, attemptId=None,
                 stateVersion=None, fieldErrors=[dict(field="amount", clientRowId=None, message="转出金额超过当前可用现金，请检查。", affectedOn=None)], recovery=None)
    assert_complete_fixture(errors.TradingAssistantErrorDto, error)
    with pytest.raises(ValidationError):
        errors.TradingAssistantErrorDto(**{**error, "code":"UNREGISTERED"})
    with pytest.raises(ValidationError):
        errors.FieldErrorDto(**error["fieldErrors"][0], rejectedValue="secret")
    progress = operation_fixtures()[0]["CALCULATION_RETRY"]
    assert_complete_fixture(calculation_status.CalculationStatus, progress)
    with pytest.raises(ValidationError):
        calculation_status.CalculationStatus(**{**progress,"stage":"PUBLISHED"})
    with pytest.raises(ValidationError):
        calculation_status.CalculationProgress(**{**progress["progress"],"completedTradeDateCount":2,"totalTradeDateCount":1})


def test_generated_schema_bundle_is_repeatable_and_uses_wire_aliases():
    from src.biz.schemas.wealth.market.trading_assistant.schema_catalog import contract_models, json_schema_bundle
    bundle = json_schema_bundle()
    assert bundle == json_schema_bundle()
    encoded = json.dumps(bundle, allow_nan=False, sort_keys=True)
    assert len(contract_models()) > 100
    assert '"from_"' not in encoded
    assert set(bundle["$defs"]["MissingRange"]["properties"]) == {"from", "through"}
    assert "valuationBasisDigest" not in encoded
    assert "ROBOT_CANDIDATE_CREATE" in encoded and "RULE_CONDITIONS_UPDATE" in encoded


def test_round_position_day_and_review_complete_fixtures():
    row, holdings = holding_fixtures()
    account = holdings["scope"]["accounts"][0]
    round_scope = dict(accountId=ID, roundId=ID2)
    round_ref = dict(**round_scope, roundNumber=1, status="OPEN")
    current = dict(accountRef=account, roundRef=round_ref, openedOn="2026-09-01", openingSource="TRADE",
                   quantity=600, availableQuantity=600, buyInvestmentAmount="10000.00", sellNetProceedsAmount="6000.00",
                   dynamicCostAmount="4000.00", dynamicCostPrice="6.67", price="15.00", marketValue="9000.00",
                   estimatedSellCommission="0.00", estimatedStampTax="0.00", estimatedNetProceeds="9000.00",
                   holdingProfitAmount="5000.00", holdingReturnPct="50.00", dayProfitAmount="0.00",
                   recordsScope=round_scope, dataStatus="Ready", reason=None)
    assert_complete_fixture(positions.PositionAccountRound, current)
    assert_complete_fixture(positions.PositionDetail, dict(scope=holdings["scope"],readContext=holdings["readContext"],
                            coverage=holdings["coverage"],stockRef=row["stockRef"],accountRounds=[current]))
    closed_round = dict(accountRef=account, stockRef=row["stockRef"], roundRef={**round_ref,"status":"CLOSED"},
                        openedOn="2026-09-01", closedOn="2026-09-11", openingSource="TRADE", initializationSource=None,
                        buyQuantity=1000, sellQuantity=1000, buyInvestmentAmount="10000.00", sellNetProceedsAmount="11000.00",
                        roundProfitAmount="1000.00", roundReturnPct="10.00", closedTradeCount=2, recordsScope=round_scope)
    assert_complete_fixture(records.RoundDetail, closed_round)
    for patch in ({"sellQuantity":999},{"closedOn":None},{"roundProfitAmount":"2000.00"},{"openingSource":"INITIALIZATION"}):
        with pytest.raises(ValidationError):
            records.RoundDetail(**{**closed_round, **patch})
    selection = dict(scope=holdings["scope"],requestedStartDate="2026-09-11",requestedEndDate="2026-09-11")
    triple = dict(profitAmount="100.00",capitalAmount="10000.00",returnPct="1.00")
    day = dict(scope=holdings["scope"],date="2026-09-11",readContext=holdings["readContext"],coverage=holdings["coverage"],
               **triple, closedTradeCount=2, closedProfitAmount="1000.00",commissionAmount="10.00",stampTaxAmount="5.00",
               closedDataStatus="Ready",feeDataStatus="Ready",contributionsScope={"scope":holdings["scope"],"date":"2026-09-11"},recordsScope=selection)
    assert_complete_fixture(returns.DayDetail, day)
    contribution = dict(**triple,stockRef=row["stockRef"],accountRounds=row["accountRounds"],dataStatus="Ready",reason=None)
    assert_complete_fixture(returns.DayContributions,dict(scope=holdings["scope"],date=day["date"],readContext=holdings["readContext"],
                             coverage=holdings["coverage"],totalCount=1,totalProfitAmount="100.00",items=[contribution],nextCursor=None))
    stats = dict(positiveDayCount=1,negativeDayCount=0,flatDayCount=0,computedDayCount=1,
                 maxDailyReturn={"returnPct":"1.00","dates":["2026-09-11"]}, minDailyReturn={"returnPct":"1.00","dates":["2026-09-11"]},
                 dataStatus="Ready",resultKind="HAS_VALID_DAYS",isFinal=True,reason=None)
    review = dict(**selection,readContext=holdings["readContext"],coverage=holdings["coverage"],dailyStats=stats,
                  closedTrades=dict(closedTradeCount=2,dataStatus="Ready",reason=None),
                  completedRounds=dict(completedRoundCount=1,dataStatus="Ready",reason=None))
    assert_complete_fixture(returns.ReviewResponse, review)
    for patch in ({"computedDayCount":0},{"resultKind":"UNDETERMINED"},{"dataStatus":"Partial"}):
        with pytest.raises(ValidationError):
            returns.DailyStats(**{**stats,**patch})
    with pytest.raises(ValidationError):
        returns.ReviewResponse(**{**review,"requestedEndDate":"2026-09-10"})


def test_previews_have_no_save_identity_and_keep_nullable_added_removed_rows():
    before = dict(**TRADE, note=None, grossAmount="10.00", commissionAmount="5.00", stampTaxAmount="0.00", netCashChange="-15.00", feeVersionId=ID)
    after = dict(**{**before,"price":"11.00","grossAmount":"11.00","netCashChange":"-16.00"})
    fixture = dict(before=before,after=after,changedFields=[dict(field="price",clientRowId=None)],affectedFromDate="2026-09-14",
                   factVersion="1",expectedRevision="1",fieldErrors=[])
    assert_complete_fixture(previews.TradeCorrectionPreview,fixture)
    with pytest.raises(ValidationError):
        previews.TradeCorrectionPreview(**fixture,requestId=ID)
    row = dict(clientRowId="row-a",tsCode="600000.SH",quantity=1,availableQuantity=0,costPrice="10.00",
               stockRef=dict(tsCode="600000.SH",name="股票"),costAmount="10.00")
    initial = {**fixture,"before":{"initialCash":"0.00","initialPositions":[None]},
               "after":{"initialCash":"0.00","initialPositions":[row]}}
    assert_complete_fixture(previews.InitializationCorrectionPreview,initial)


def test_no_arbitrary_json_in_generated_concrete_contracts():
    from src.biz.schemas.wealth.market.trading_assistant.schema_catalog import json_schema_bundle
    def visit(node):
        if isinstance(node,dict):
            for value in node.get("properties",{}).values():
                # Every field has a type/ref/union, not unconstrained Any/dict.
                assert any(key in value for key in ("type","$ref","anyOf","oneOf","allOf")), value
            for value in node.values():
                visit(value)
        elif isinstance(node,list):
            for value in node:
                visit(value)
    visit(json_schema_bundle())


def test_source_evidence_precision_is_not_display_precision():
    evidence = rules.PriceLTEEvidence(operator="LTE",upper="10.00",actualValue="10.0049",
                                      satisfied=False,checkpointAt="2026-09-14T10:20:00+08:00")
    assert evidence.actualValue == "10.0049"
    for bad in (10.0049,"NaN","Infinity","-1","1e2"):
        with pytest.raises(ValidationError):
            rules.PriceLTEEvidence(**{**evidence.model_dump(),"actualValue":bad})
    with pytest.raises(ValidationError):
        common.Coverage(dataStatus="Partial",reason="缺数",isFinal=True,accounts=[])


def test_every_save_command_has_identity_and_forbids_manual_results():
    commands = {
        "ACCOUNT_CREATE":accounts.CreateAccountCommand, "INITIALIZATION_CORRECT":accounts.CorrectInitializationCommand,
        "FEES_UPDATE":accounts.UpdateFeesCommand, "TRADE_CREATE":accounts.TradeCommand,
        "TRADE_CORRECT":accounts.CorrectTradeCommand, "TRADE_VOID":accounts.VoidCommand,
        "CASH_FLOW_CREATE":accounts.CashFlowCommand, "CASH_FLOW_CORRECT":accounts.CorrectCashFlowCommand,
        "CASH_FLOW_VOID":accounts.VoidCommand, "CALCULATION_RETRY":calculation_status.CalculationRetryCommand,
        "PLAN_CREATE":rules.CreatePlanCommand, "ALERT_CREATE":rules.CreateAlertCommand,
        "RULE_CONDITIONS_UPDATE":rules.ReviseConditionsCommand, "RULE_CLOSE":rules.CloseRuleCommand,
        "ROBOT_CANDIDATE_CREATE":robot.CandidateCommand, "ROBOT_TEST":robot.TestCandidateCommand,
        "ROBOT_CONFIRM":robot.ConfirmCandidateCommand, "NOTIFICATION_RETRY":robot.NotificationRetryCommand,
    }
    from typing import get_args
    assert set(commands) == set(get_args(common.OperationType))
    inputs = operation_fixtures()[1]
    inputs["ROBOT_CANDIDATE_CREATE"] = dict(expectedConfigVersionId=None,name="机器人",webhook=dict(action="REPLACE",value="private"),signingSecret=dict(action="CLEAR"),keywords=[])
    for operation, model in commands.items():
        fixture = dict(**inputs[operation],requestId=ID,attemptId=ID2)
        assert model.model_validate(fixture)
        for field in ("requestId","attemptId"):
            with pytest.raises(ValidationError):
                model.model_validate({key:value for key,value in fixture.items() if key != field})
        with pytest.raises(ValidationError):
            model.model_validate({**fixture,"profitAmount":"10.00"})
    with pytest.raises(ValidationError):
        accounts.TradePreviewInput(**TRADE,note="not part of the fee preview")
    with pytest.raises(ValidationError):
        scopes.AlertsQuery(accountMode="ALL")
    with pytest.raises(ValidationError):
        scopes.CashRecordsQuery(accountMode="ALL",requestedStartDate="2026-09-01",requestedEndDate="2026-09-30",tsCode="600000.SH")


def test_original_record_and_history_contracts_reconcile_cash():
    record = dict(accountRef=dict(accountId=ID,name="账户",brokerName="券商"),tradeId=ID2,revision="1",
                  tradeDate="2026-09-14",recordedAt="2026-09-14T16:00:00+08:00",acceptedAt="2026-09-14T16:00:00+08:00",
                  stockRef=dict(tsCode="600000.SH",name="股票"),direction="BUY",quantity=1,price="10.00",
                  grossAmount="10.00",commissionAmount="5.00",stampTaxAmount="0.00",netCashChange="-15.00",feeVersionId=ID2,
                  commissionRateWan="2.50",minimumCommission="5.00",stampTaxRatePct="0.05",note=None,status="ACTIVE")
    assert_complete_fixture(records.TradeRecord,record)
    assert_complete_fixture(records.TradeDetail,dict(record=record,revisions=dict(items=[record],nextCursor=None),
                            readContext=calendar_fixture()["readContext"],closedTrade=None,closedDataStatus="Empty",reason="买入无闭环"))
    for patch in ({"price":"0.00"},{"grossAmount":"11.00"},{"stampTaxAmount":"0.01"},{"netCashChange":"15.00"}):
        with pytest.raises(ValidationError):
            records.TradeRecord(**{**record,**patch})
    cash = dict(accountRef=record["accountRef"],cashFlowId=ID2,revision="1",occurredOn="2026-09-14",
                recordedAt=record["recordedAt"],acceptedAt=record["acceptedAt"],direction="OUT",amount="10.00",
                netCashChange="-10.00",note=None,status="ACTIVE")
    assert_complete_fixture(records.CashFlowRecord,cash)
    assert_complete_fixture(records.CashFlowDetail,dict(record=cash,revisions=dict(items=[cash],nextCursor=None),readContext=calendar_fixture()["readContext"]))
    with pytest.raises(ValidationError):
        records.CashFlowRecord(**{**cash,"netCashChange":"10.00"})
