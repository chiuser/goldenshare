"""Real SQL read contracts, using fresh test databases and explicit source facts."""
import base64
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import insert, update
from sqlalchemy.orm import Session

from tests.test_wealth_trading_assistant_persistence import database, seed_account
from tests.test_wealth_trading_assistant_rule_storage import rule_database, seed_rule, NOW
from src.biz.models.wealth.trading_assistant.rules import Rule, RuleVersion
from src.biz.queries.wealth.market.trading_assistant.rule_queries import RuleQueries
from src.biz.schemas.wealth.market.trading_assistant.scopes import PlansQuery, AlertsQuery, Pagination
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


def queries():
    def notifications(session, *, rules, **kwargs):
        return {r.rule_id: dict(notificationId=None, state="NOT_ENABLED", stateVersion=None,
            robotId=None, robotName=None, canRetry=False, reason=None) for r in rules}
    def maintenance(session, *, rule, **kwargs):
        active = rule.state == "ACTIVE"
        return dict(canEditConditions=active, canClose=active,
            editUnavailableReason=None if active else "规则已结束", closeUnavailableReason=None if active else "规则已结束")
    return RuleQueries(TradingAssistantExecutionPolicyV1(), notification_summaries=notifications, maintenance=maintenance)


def test_complete_server_filtering_literal_keyword_counts_and_cursor_owner(rule_database):
    with rule_database.begin() as conn:
        account, _, _ = seed_account(conn)
        ids = [seed_rule(conn, account=account, version_overrides={"stock_name_at_save": name})[0]
            for name in ("普通", "百分%_银行", "普通2")]
        conn.execute(update(Rule).where(Rule.rule_id == ids[2]).values(state="CLOSED", closed_at=NOW))
    reader = queries()
    with Session(rule_database) as session, session.begin():
        first = reader.list(session, owner_id=1, kind="PLAN", deadline=Deadline.after_ms(5000),
            query=PlansQuery(accountMode="SINGLE", accountId=str(account), limit=1))
        assert first.counts.planCount == 3
        seen = [first.items[0].ruleId]
        cursor = first.nextCursor
        while cursor:
            page = reader.list(session, owner_id=1, kind="PLAN", deadline=Deadline.after_ms(5000),
                query=PlansQuery(accountMode="SINGLE", accountId=str(account), limit=1, cursor=cursor))
            seen += [r.ruleId for r in page.items]
            cursor = page.nextCursor
        assert seen == sorted(map(str, ids), reverse=True)
        filtered = reader.list(session, owner_id=1, kind="PLAN", deadline=Deadline.after_ms(5000),
            query=PlansQuery(accountMode="SINGLE", accountId=str(account), keyword="  %_  ", status="ACTIVE"))
        assert [r.ruleId for r in filtered.items] == [str(ids[1])]
        assert filtered.counts.planCount == 3
        code = reader.list(session, owner_id=1, kind="PLAN", deadline=Deadline.after_ms(5000),
            query=PlansQuery(accountMode="SINGLE", accountId=str(account), keyword="000001.sz"))
        assert len(code.items) == 3
        with pytest.raises(WriteProtocolConflict, match="TA_REQUEST_INVALID"):
            reader.list(session, owner_id=1, kind="PLAN", deadline=Deadline.after_ms(5000),
                query=PlansQuery(accountMode="SINGLE", accountId=str(account), status="CLOSED", cursor=first.nextCursor))
        with pytest.raises(WriteProtocolConflict, match="TA_ACCOUNT_NOT_FOUND"):
            reader.list(session, owner_id=2, kind="PLAN", deadline=Deadline.after_ms(5000),
                query=PlansQuery(accountMode="SINGLE", accountId=str(account), cursor=first.nextCursor))
        for owner, kind in ((2, "PLAN"), (1, "ALERT")):
            with pytest.raises(WriteProtocolConflict, match="TA_OBJECT_NOT_FOUND"):
                reader.detail(session, owner_id=owner, kind=kind, rule_id=ids[0], now=NOW, deadline=Deadline.after_ms(5000))
        # Alerts are owner-scoped and need no account, including an owner with no accounts.
        assert reader.list(session, owner_id=2, kind="ALERT", query=AlertsQuery(), deadline=Deadline.after_ms(5000)).items == []


def test_historical_versions_keep_boundary_across_pages_and_detail_is_real(rule_database):
    with rule_database.begin() as conn:
        rule_id, original = seed_rule(conn)
        second = uuid4()
        conn.execute(insert(RuleVersion).values(rule_version_id=second, owner_user_id=1, rule_id=rule_id,
            version_no=2, effective_at=NOW + timedelta(microseconds=1), deadline_at=NOW + timedelta(hours=5),
            stock_code="000001.SZ", stock_name_at_save="平安银行", direction="BUY", source="TRADING_ASSISTANT",
            price_operator="GTE", price_lower="12.00", notify_enabled=False))
        conn.execute(update(Rule).where(Rule.rule_id == rule_id).values(current_version_id=second, state_version=2))
    reader = queries()
    with Session(rule_database) as session, session.begin():
        detail = reader.detail(session, owner_id=1, kind="PLAN", rule_id=rule_id, now=NOW,
            deadline=Deadline.after_ms(5000))
        assert detail.stateVersion == "2" and detail.conditions.priceCondition.lower == "12.00"
        assert detail.finalResult is None and detail.checkedAt is None and detail.checkStatus == "PENDING"
        page1 = reader.versions(session, owner_id=1, kind="PLAN", rule_id=rule_id,
            query=Pagination(limit=1), deadline=Deadline.after_ms(5000))
        # Another request saves a third version between pages. The historical
        # cursor freezes its ceiling, including the second version's boundary.
        with rule_database.begin() as conn:
            third = uuid4()
            conn.execute(insert(RuleVersion).values(rule_version_id=third, owner_user_id=1, rule_id=rule_id,
                version_no=3, effective_at=NOW + timedelta(minutes=1), deadline_at=NOW + timedelta(hours=5),
                stock_code="000001.SZ", stock_name_at_save="平安银行", direction="BUY", source="TRADING_ASSISTANT",
                price_operator="GTE", price_lower="13.00", notify_enabled=False))
            conn.execute(update(Rule).where(Rule.rule_id == rule_id).values(current_version_id=third, state_version=3))
        page2 = reader.versions(session, owner_id=1, kind="PLAN", rule_id=rule_id,
            query=Pagination(limit=1, cursor=page1.nextCursor), deadline=Deadline.after_ms(5000))
        assert page1.items[0].ruleVersionId == str(original)
        assert page1.items[0].validThroughAt == (NOW + timedelta(microseconds=1)).isoformat()
        assert page1.items[0].conditions.priceCondition.upper == "10.00"
        assert page2.items[0].versionNo == "2" and page2.nextCursor is None
        assert page2.items[0].validThroughAt == (NOW + timedelta(hours=5)).isoformat()
        assert reader.checks(session, owner_id=1, kind="PLAN", rule_id=rule_id,
            query=Pagination(), deadline=Deadline.after_ms(5000)).items == []


@pytest.mark.parametrize("change", [{"status": "ENDED"}, {"keyword": 12}, {"limit": True}, {"limit": 101}, {"unknown": "x"}])
def test_filter_contract_negative(change):
    with pytest.raises(ValidationError):
        AlertsQuery.model_validate(change)


def test_keyword_blank_is_unfiltered():
    assert AlertsQuery(keyword=" \t ").keyword is None


@pytest.mark.parametrize("change", [{"owner": 2}, {"kind": "ALERT"}, {"v": True}, {"key": ["2026-09-15", str(uuid4())]}, {"extra": 1}])
def test_rule_cursor_rejects_mutated_identity_and_shape(change):
    from src.biz.queries.wealth.market.trading_assistant.rule_cursor import RuleCursor, encode
    cursor = RuleCursor(owner_id=1, kind="PLAN", filters={})
    token = cursor.encode([NOW.isoformat(), str(uuid4())])
    doc = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    with pytest.raises(WriteProtocolConflict, match="TA_REQUEST_INVALID"):
        cursor.decode(encode(doc | change))
