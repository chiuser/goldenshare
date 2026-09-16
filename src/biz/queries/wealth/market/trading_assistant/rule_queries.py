"""Owned, bounded SQL rule reads. GET never creates execution work."""
from uuid import UUID

from sqlalchemy import func, or_, select, tuple_

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.rules import Rule, RuleVersion
from src.biz.models.wealth.trading_assistant.rule_checks import RuleCheck, RuleResult, RuleMarketBasis
from src.biz.schemas.wealth.market.trading_assistant import rules as dto
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .rule_cursor import RuleCursor
from .rule_projection import condition_version, row_value, check_value, coverage_summary, instant


class RuleQueries:
    def __init__(self, policy, *, notification_summaries, maintenance):
        self.policy = policy
        self.notification_summaries = notification_summaries
        self.maintenance = maintenance

    def owned(self, session, *, owner_id, kind, rule_id, deadline):
        apply_sql_budget(session, deadline, self.policy)
        row = session.scalar(select(Rule).where(Rule.owner_user_id == owner_id,
            Rule.kind == kind, Rule.rule_id == rule_id))
        if row is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        return row

    def list(self, session, *, owner_id, kind, query, deadline):
        apply_sql_budget(session, deadline, self.policy)
        account_id = UUID(query.accountId) if kind == "PLAN" and query.accountMode == "SINGLE" else None
        if account_id is not None and session.scalar(select(Account.account_id).where(
                Account.owner_id == owner_id, Account.account_id == account_id)) is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        counts_query = select(Rule.kind, func.count()).where(Rule.owner_user_id == owner_id)
        if account_id is not None:
            counts_query = counts_query.where(or_(Rule.kind == "ALERT", Rule.account_id == account_id))
        counts = dict(session.execute(counts_query.group_by(Rule.kind)).all())
        cursor = RuleCursor(owner_id=owner_id, kind=kind,
            filters=query.model_dump(exclude={"cursor", "limit"}))
        after = cursor.decode(query.cursor)
        statement = select(Rule).join(RuleVersion, Rule.current_version_id == RuleVersion.rule_version_id).where(
            Rule.owner_user_id == owner_id, Rule.kind == kind)
        if account_id is not None:
            statement = statement.where(Rule.account_id == account_id)
        if query.status in ("ACTIVE", "CLOSED"):
            statement = statement.where(Rule.state == query.status)
        elif query.status in ("TRIGGERED", "NOT_TRIGGERED"):
            statement = statement.join(RuleResult, Rule.result_id == RuleResult.result_id).where(
                Rule.state == "ENDED", RuleResult.triggered.is_(query.status == "TRIGGERED"))
        if query.keyword is not None:
            # LIKE wildcards from user input remain ordinary characters.
            literal = query.keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(or_(RuleVersion.stock_name_at_save.like("%" + literal + "%", escape="\\"),
                RuleVersion.stock_code.ilike("%" + literal + "%", escape="\\")))
        if after is not None:
            statement = statement.where(tuple_(Rule.created_at, Rule.rule_id) < tuple_(*after))
        rows = session.scalars(statement.order_by(Rule.created_at.desc(), Rule.rule_id.desc())
            .limit(query.limit + 1)).all()
        more, rows = len(rows) > query.limit, rows[:query.limit]
        items = self._rows(session, rows, owner_id=owner_id, deadline=deadline)
        next_cursor = cursor.encode([rows[-1].created_at.isoformat(), str(rows[-1].rule_id)]) if more else None
        return (dto.PlansResponse if kind == "PLAN" else dto.AlertsResponse)(items=items,
            nextCursor=next_cursor, counts=dto.RuleCounts(planCount=counts.get("PLAN", 0), alertCount=counts.get("ALERT", 0)))

    def _rows(self, session, rows, *, owner_id, deadline):
        if not rows:
            return []
        apply_sql_budget(session, deadline, self.policy)
        ids = [r.rule_id for r in rows]
        versions = {v.rule_version_id: v for v in session.scalars(select(RuleVersion).where(
            RuleVersion.owner_user_id == owner_id, RuleVersion.rule_version_id.in_([r.current_version_id for r in rows])))}
        accounts = {a.account_id: a for a in session.scalars(select(Account).where(
            Account.owner_id == owner_id, Account.account_id.in_([r.account_id for r in rows if r.account_id])))}
        latest = select(RuleCheck.rule_id, func.max(RuleCheck.check_no).label("n")).where(
            RuleCheck.owner_user_id == owner_id, RuleCheck.rule_id.in_(ids)).group_by(RuleCheck.rule_id).subquery()
        checks = {c.rule_id: c for c in session.scalars(select(RuleCheck).join(latest,
            (RuleCheck.rule_id == latest.c.rule_id) & (RuleCheck.check_no == latest.c.n)))}
        results = {r.rule_id: r for r in session.scalars(select(RuleResult).where(
            RuleResult.owner_user_id == owner_id, RuleResult.rule_id.in_(ids)))}
        result_versions = [r.trigger_version_id or checks[r.rule_id].rule_version_id for r in results.values()]
        versions.update({v.rule_version_id: v for v in session.scalars(select(RuleVersion).where(
            RuleVersion.owner_user_id == owner_id, RuleVersion.rule_version_id.in_(result_versions)))})
        notifications = self.notification_summaries(session, owner_id=owner_id, rules=rows,
            versions=versions, deadline=deadline)
        output = []
        for rule in rows:
            result = results.get(rule.rule_id)
            check = checks.get(rule.rule_id)
            result_version = versions[result.trigger_version_id or check.rule_version_id] if result else None
            output.append(row_value(rule, versions[rule.current_version_id], accounts.get(rule.account_id),
                check, result, result_version, notifications[rule.rule_id]))
        deadline.remaining_ms()
        return output

    def detail(self, session, *, owner_id, kind, rule_id, now, deadline):
        rule = self.owned(session, owner_id=owner_id, kind=kind, rule_id=rule_id, deadline=deadline)
        row = self._rows(session, [rule], owner_id=owner_id, deadline=deadline)[0]
        version = session.get(RuleVersion, rule.current_version_id)
        check = session.scalar(select(RuleCheck).where(RuleCheck.owner_user_id == owner_id,
            RuleCheck.rule_id == rule_id).order_by(RuleCheck.check_no.desc()).limit(1))
        basis = session.get(RuleMarketBasis, check.market_basis_id) if check and check.market_basis_id else None
        return (dto.PlanDetail if kind == "PLAN" else dto.AlertDetail)(**row.model_dump(),
            stateVersion=str(rule.state_version), serverNow=instant(now),
            maintenance=self.maintenance(session, rule=rule, version=version, now=now, deadline=deadline),
            closedAt=instant(rule.closed_at), endedAt=instant(rule.ended_at), currentConditionVersion=condition_version(version),
            checkedAt=instant(check.completed_at or check.started_at) if check else None,
            marketObservedAt=instant(basis.observed_at) if basis else None, coverageSummary=coverage_summary(check),
            missingRanges=check.missing_ranges if check else [], failureReason=check.failure_reason if check else None)

    def checks(self, session, *, owner_id, kind, rule_id, query, deadline):
        self.owned(session, owner_id=owner_id, kind=kind, rule_id=rule_id, deadline=deadline)
        cursor = RuleCursor(owner_id=owner_id, kind=kind + "_CHECKS", filters=dict(ruleId=str(rule_id)))
        after = cursor.decode(query.cursor, numbered=True)
        statement = select(RuleCheck, RuleMarketBasis).outerjoin(RuleMarketBasis,
            RuleCheck.market_basis_id == RuleMarketBasis.market_basis_id).where(
            RuleCheck.owner_user_id == owner_id, RuleCheck.rule_id == rule_id)
        if after is not None:
            statement = statement.where(RuleCheck.check_no < after)
        rows = session.execute(statement.order_by(RuleCheck.check_no.desc()).limit(query.limit + 1)).all()
        more, rows = len(rows) > query.limit, rows[:query.limit]
        return dto.CheckHistoryResponse(items=[check_value(c, b) for c, b in rows],
            nextCursor=cursor.encode(rows[-1][0].check_no) if more else None)

    def versions(self, session, *, owner_id, kind, rule_id, query, deadline):
        self.owned(session, owner_id=owner_id, kind=kind, rule_id=rule_id, deadline=deadline)
        cursor = RuleCursor(owner_id=owner_id, kind=kind + "_VERSIONS", filters=dict(ruleId=str(rule_id)))
        position = cursor.decode(query.cursor, history=True)
        after, ceiling = position if position else (0, session.scalar(select(func.max(RuleVersion.version_no)).where(
            RuleVersion.owner_user_id == owner_id, RuleVersion.rule_id == rule_id)))
        # Freeze the first page's upper version and compute boundaries before filtering.
        sequence = select(RuleVersion.rule_version_id, RuleVersion.version_no,
            func.lead(RuleVersion.effective_at).over(order_by=RuleVersion.version_no).label("next_at")).where(
            RuleVersion.owner_user_id == owner_id, RuleVersion.rule_id == rule_id,
            RuleVersion.version_no <= ceiling).subquery()
        statement = select(RuleVersion, sequence.c.next_at).join(sequence,
            sequence.c.rule_version_id == RuleVersion.rule_version_id)
        statement = statement.where(sequence.c.version_no > after)
        rows = session.execute(statement.order_by(RuleVersion.version_no.asc()).limit(query.limit + 1)).all()
        more, rows = len(rows) > query.limit, rows[:query.limit]
        return dto.ConditionHistoryResponse(items=[condition_version(v,
            through=min(v.deadline_at, next_at) if next_at else v.deadline_at) for v, next_at in rows],
            nextCursor=cursor.encode([rows[-1][0].version_no, ceiling]) if more else None)
