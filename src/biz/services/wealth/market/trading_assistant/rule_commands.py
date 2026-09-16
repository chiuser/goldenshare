"""Rule commands on the existing request/attempt protocol (§§4.9, 4.17).

Market identity, future-session qualification and robot qualification are trusted
injected readers, not flags from the browser. No minute check or send happens in
these transactions. A successful receipt survives later condition revisions.
"""
import asyncio
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.rules import Rule, RuleVersion, RuleExecution
from src.biz.schemas.wealth.market.trading_assistant.rules import Conditions, PlanRow, AlertRow
from src.biz.schemas.wealth.market.trading_assistant.scopes import RuleScope, RuleCreateScope
from src.biz.schemas.wealth.market.trading_assistant.recovery import RecoveryRejection
from src.biz.schemas.wealth.market.trading_assistant.errors import FieldErrorDto
from .execution_policy import Deadline
from .market_facts import SecurityNotEligible
from .transaction_boundary import CommitOutcomeUnknown
from .write_protocol import WriteProtocol, WriteProtocolConflict
from .rule_values import condition_columns, condition_summary
from .condition_intervals import require_aware


class InvalidRuleInput(ValueError):
    def __init__(self, field, message):
        self.field, self.message = field, message
        super().__init__(message)


class RuleCommandService:
    def __init__(self, transactions, market, policy, now, *, executor_id,
                 resolve_robot, has_future_checkpoint):
        self.transactions, self.market, self.policy, self.now = transactions, market, policy, now
        self.executor_id = executor_id
        self.resolve_robot, self.has_future_checkpoint = resolve_robot, has_future_checkpoint
        self.protocol = WriteProtocol(policy)

    def _now(self):
        now = self.now()
        require_aware(now)
        return now.astimezone(ZoneInfo("Asia/Shanghai"))

    async def create(self, *, owner_id, kind, command):
        scope = RuleCreateScope(scopeType="RULE_CREATE", ruleType=kind, tsCode=command.stockCode,
            accountId=command.accountId if kind == "PLAN" else None)
        return await self._save(owner_id, scope, kind + "_CREATE", command)

    async def revise(self, *, owner_id, kind, rule_id, command):
        return await self._save(owner_id, RuleScope(scopeType="RULE", ruleType=kind,
            ruleId=str(rule_id)), "RULE_CONDITIONS_UPDATE", command)

    async def close(self, *, owner_id, kind, rule_id, command):
        return await self._save(owner_id, RuleScope(scopeType="RULE", ruleType=kind,
            ruleId=str(rule_id)), "RULE_CLOSE", command)

    async def _save(self, owner_id, scope, operation, command):
        deadline = Deadline.after_ms(self.policy.write_request_budget_ms)
        payload = command.model_dump(mode="json", exclude={"requestId", "attemptId", "expectedRequestStateVersion"})
        state = await self.transactions.run(lambda session: self.protocol.register(session,
            owner_id=owner_id, request_id=UUID(command.requestId), attempt_id=UUID(command.attemptId),
            scope=scope, operation=operation, payload=payload, now=self.now(), executor_id=self.executor_id,
            deadline=deadline, expected_state_version=int(command.expectedRequestStateVersion)
            if command.expectedRequestStateVersion is not None else None), deadline=deadline, write=True)
        if not state.execute:
            return state
        try:
            def accept(session):
                now = self.now()
                locked = self.protocol.lock_execution(session, state, now=now,
                    executor_id=self.executor_id, deadline=deadline)
                if isinstance(scope, RuleCreateScope):
                    result, accepted_at = self._create(session, owner_id, scope, command, deadline)
                else:
                    result, accepted_at = self._maintain(session, owner_id, scope, operation, command, deadline)
                deadline.remaining_ms()
                # Recheck the write lease after business validation, before saving.
                self.protocol.lock_execution(session, state, now=self.now(), executor_id=self.executor_id, deadline=deadline)
                return self.protocol.saved(session, locked, dict(requestId=command.requestId,
                    attemptId=command.attemptId, operationType=operation,
                    acceptedAt=accepted_at.isoformat(), result=result), accepted_at)
            return await self.transactions.run(accept, deadline=deadline, write=True)
        except (CommitOutcomeUnknown, asyncio.CancelledError):
            raise
        except Exception as error:
            code, field, message = "TA_WRITE_FAILED", None, "保存未完成，请重新核对"
            if isinstance(error, InvalidRuleInput):
                code, field, message = "TA_REQUEST_INVALID", error.field, error.message
            elif isinstance(error, SecurityNotEligible):
                code, field, message = "TA_REQUEST_INVALID", "stockCode", "请选择有效的 A 股股票"
            elif isinstance(error, WriteProtocolConflict):
                code = error.code
                message = "规则或配置状态已变化，请重新核对"
            rejection = RecoveryRejection(code=code, message=message, field=field)
            def stop(session):
                now = self.now()
                locked = self.protocol.lock_execution(session, state, now=now,
                    executor_id=self.executor_id, deadline=deadline)
                return self.protocol.stop(session, locked, rejection, now)
            stopped = await self.transactions.run(stop, deadline=deadline, write=True)
            fields = () if field is None else (FieldErrorDto(field=field, clientRowId=None,
                message=message, affectedOn=None),)
            return replace(stopped, field_errors=fields)

    def _create(self, session, owner_id, scope, command, deadline):
        security = self.market.resolve_security(session, command.stockCode, deadline)
        account = None
        if scope.ruleType == "PLAN":
            account = session.scalar(select(Account).where(Account.owner_id == owner_id,
                Account.account_id == UUID(command.accountId)))
            if account is None:
                raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        notify = scope.ruleType == "ALERT" or command.notifyEnabled
        robot = self.resolve_robot(session, owner_id, UUID(command.robotId), deadline) if notify else None
        if notify and robot is None:
            raise InvalidRuleInput("robotId", "请先配置并验证飞书机器人。")
        now = self._now()
        through = datetime.fromisoformat(command.deadlineAt)
        if through <= now:
            raise InvalidRuleInput("deadlineAt", "截止时间必须晚于保存生效时间，请重新选择。")
        rule_id, version_id = uuid4(), uuid4()
        conditions = Conditions(priceCondition=command.priceCondition, volumeCondition=command.volumeCondition)
        session.add(Rule(rule_id=rule_id, owner_user_id=owner_id, kind=scope.ruleType,
            account_id=account.account_id if account else None, current_version_id=version_id,
            state="ACTIVE", state_version=1, created_at=now, last_check_no=0))
        session.flush()
        session.add(RuleVersion(rule_version_id=version_id, owner_user_id=owner_id, rule_id=rule_id,
            version_no=1, effective_at=now, deadline_at=through, stock_code=security.ts_code,
            stock_name_at_save=security.name, direction=command.direction if account else None,
            source=command.source, notify_enabled=notify, robot_id=UUID(command.robotId) if notify else None,
            **condition_columns(conditions)))
        session.add(RuleExecution(rule_id=rule_id, owner_user_id=owner_id, next_attempt_at=now,
            fence=0, observed_state_version=1, next_trade_date=now.date(),
            last_business_updated_at=now, transient_failures=0))
        row = dict(ruleId=str(rule_id), ruleVersionId=str(version_id), stockRef=dict(tsCode=security.ts_code, name=security.name),
            createdAt=now.isoformat(), effectiveAt=now.isoformat(), deadlineAt=command.deadlineAt,
            conditions=conditions, conditionSummary=condition_summary(conditions), ruleStatus="ACTIVE",
            checkStatus="PENDING", finalResult=None, notificationSummary=dict(notificationId=None,
                state="NOT_CREATED" if notify else "NOT_ENABLED", stateVersion=None,
                robotId=command.robotId if notify else None, robotName=robot.name if robot else None,
                canRetry=False, reason=None))
        if account:
            row.update(accountRef=dict(accountId=str(account.account_id), name=account.name,
                brokerName=account.broker_name), direction=command.direction)
        return (PlanRow if account else AlertRow).model_validate(row).model_dump(mode="json"), now

    def _maintain(self, session, owner_id, scope, operation, command, deadline):
        rule = session.scalar(select(Rule).where(Rule.owner_user_id == owner_id,
            Rule.rule_id == UUID(scope.ruleId), Rule.kind == scope.ruleType).with_for_update()
            .execution_options(populate_existing=True))
        if rule is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        if rule.state != "ACTIVE" or rule.state_version != int(command.expectedStateVersion):
            raise WriteProtocolConflict("TA_STATE_CONFLICT")
        version = session.get(RuleVersion, rule.current_version_id)
        pending = session.scalar(select(RuleExecution).where(RuleExecution.rule_id == rule.rule_id)
            .with_for_update().execution_options(populate_existing=True))
        if version is None or pending is None:
            raise RuntimeError("Incomplete persisted rule")
        now = self._now()
        if operation == "RULE_CONDITIONS_UPDATE":
            if now <= version.effective_at:
                raise RuntimeError("Rule clock did not advance")
            security = self.market.resolve_security(session, version.stock_code, deadline)
            if not self.has_future_checkpoint(session, security, now, version.deadline_at, deadline):
                raise WriteProtocolConflict("TA_STATE_CONFLICT")
            # Re-read the acceptance clock after source checks. Do not record a
            # pre-validation timestamp as the boundary of a later save.
            now = self._now()
            if now <= version.effective_at or now >= version.deadline_at:
                raise WriteProtocolConflict("TA_STATE_CONFLICT")
            if not self.has_future_checkpoint(session, security, now, version.deadline_at, deadline):
                raise WriteProtocolConflict("TA_STATE_CONFLICT")
            conditions = Conditions(priceCondition=command.priceCondition, volumeCondition=command.volumeCondition)
            new_id = uuid4()
            session.add(RuleVersion(rule_version_id=new_id, owner_user_id=owner_id, rule_id=rule.rule_id,
                version_no=version.version_no+1, effective_at=now, deadline_at=version.deadline_at,
                stock_code=version.stock_code, stock_name_at_save=version.stock_name_at_save,
                direction=version.direction, source=version.source, notify_enabled=version.notify_enabled,
                robot_id=version.robot_id, **condition_columns(conditions)))
            rule.current_version_id = new_id
            # Keep any unfinished earlier day. If the worker has already
            # advanced beyond today, revisit today to prove the newly split
            # intervals (including an empty after-close interval).
            pending.next_trade_date = min(pending.next_trade_date, now.date())
            pending.next_attempt_at = now
            pending.transient_failures = 0
            pending.waiting_reason = None
            result = dict(operationType="REVISE_CONDITIONS", ruleId=str(rule.rule_id),
                ruleVersionId=str(new_id), effectiveAt=now.isoformat(), conditions=conditions.model_dump(mode="json"),
                conditionSummary=condition_summary(conditions))
        else:
            rule.state, rule.closed_at = "CLOSED", now
            pending.next_attempt_at = None
            result = dict(operationType="CLOSE", ruleId=str(rule.rule_id), ruleVersionId=str(version.rule_version_id),
                closedAt=now.isoformat(), ruleStatus="CLOSED", finalResult=None)
        rule.state_version += 1
        pending.fence += 1
        pending.executor_id = pending.lease_until = None
        pending.observed_state_version = rule.state_version
        result["acceptedStateVersion"] = str(rule.state_version)
        return result, now
