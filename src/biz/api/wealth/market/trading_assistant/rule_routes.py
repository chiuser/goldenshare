"""Approved rule routes; checks are reads, never an execution request."""
from typing import Literal
from uuid import UUID
from fastapi import Depends, Request
from src.biz.schemas.wealth.market.trading_assistant import rules as dto, receipts
from src.biz.schemas.wealth.market.trading_assistant.scopes import PlansQuery, AlertsQuery, Pagination
from src.biz.schemas.wealth.market.trading_assistant.value_types import EntityId
from .dependencies import TradingAssistantDependencies
from .record_routes import parse_record_query
from .errors import command_response


def register_rule_routes(router, *, auth_dependency, dependencies_dependency):
    auth, services = Depends(auth_dependency), Depends(dependencies_dependency)

    @router.get("/plans", response_model=dto.PlansResponse)
    async def plans(request: Request, accountMode: Literal["ALL", "SINGLE"], accountId: EntityId | None = None,
                    status: str = "ALL", keyword: str | None = None, limit: int = 20, cursor: str | None = None,
                    owner_id: int = auth, deps: TradingAssistantDependencies = services):
        query = parse_record_query(request, PlansQuery)
        return await deps.read(lambda s, d: deps.rule_queries.list(s, owner_id=owner_id, kind="PLAN", query=query, deadline=d))

    @router.get("/alerts", response_model=dto.AlertsResponse)
    async def alerts(request: Request, status: str = "ALL", keyword: str | None = None,
                     limit: int = 20, cursor: str | None = None,
                     owner_id: int = auth, deps: TradingAssistantDependencies = services):
        query = parse_record_query(request, AlertsQuery)
        return await deps.read(lambda s, d: deps.rule_queries.list(s, owner_id=owner_id, kind="ALERT", query=query, deadline=d))

    def register_kind(kind, path, create_model, receipt_model, detail_model):
        @router.post(path, response_model=receipt_model)
        async def create(command: create_model, owner_id: int = auth, deps: TradingAssistantDependencies = services):
            return command_response(await deps.rules.create(owner_id=owner_id, kind=kind, command=command))

        @router.get(path + "/{rule_id}", response_model=detail_model)
        async def detail(rule_id: EntityId, owner_id: int = auth, deps: TradingAssistantDependencies = services):
            return await deps.read(lambda s, d: deps.rule_queries.detail(s, owner_id=owner_id, kind=kind,
                rule_id=UUID(rule_id), now=deps.now(), deadline=d))

        @router.get(path + "/{rule_id}/checks", response_model=dto.CheckHistoryResponse)
        async def checks(rule_id: EntityId, request: Request, limit: int = 20, cursor: str | None = None,
                         owner_id: int = auth, deps: TradingAssistantDependencies = services):
            query = parse_record_query(request, Pagination)
            return await deps.read(lambda s, d: deps.rule_queries.checks(s, owner_id=owner_id, kind=kind,
                rule_id=UUID(rule_id), query=query, deadline=d))

        @router.get(path + "/{rule_id}/condition-versions", response_model=dto.ConditionHistoryResponse)
        async def versions(rule_id: EntityId, request: Request, limit: int = 20, cursor: str | None = None,
                           owner_id: int = auth, deps: TradingAssistantDependencies = services):
            query = parse_record_query(request, Pagination)
            return await deps.read(lambda s, d: deps.rule_queries.versions(s, owner_id=owner_id, kind=kind,
                rule_id=UUID(rule_id), query=query, deadline=d))

        @router.post(path + "/{rule_id}/condition-revisions", response_model=receipts.ConditionsUpdateReceipt)
        async def revise(rule_id: EntityId, command: dto.ReviseConditionsCommand,
                         owner_id: int = auth, deps: TradingAssistantDependencies = services):
            return command_response(await deps.rules.revise(owner_id=owner_id, kind=kind, rule_id=UUID(rule_id), command=command))

        @router.post(path + "/{rule_id}/close", response_model=receipts.RuleCloseReceipt)
        async def close(rule_id: EntityId, command: dto.CloseRuleCommand,
                        owner_id: int = auth, deps: TradingAssistantDependencies = services):
            return command_response(await deps.rules.close(owner_id=owner_id, kind=kind, rule_id=UUID(rule_id), command=command))

    register_kind("PLAN", "/plans", dto.CreatePlanCommand, receipts.PlanCreateReceipt, dto.PlanDetail)
    register_kind("ALERT", "/alerts", dto.CreateAlertCommand, receipts.AlertCreateReceipt, dto.AlertDetail)
