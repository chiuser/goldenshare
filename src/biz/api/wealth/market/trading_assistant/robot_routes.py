"""Approved robot reads. Commands are exposed only once durable sending is wired."""
from uuid import UUID

from fastapi import Depends

from src.biz.schemas.wealth.market.trading_assistant.robot import TestResult
from src.biz.schemas.wealth.market.trading_assistant.value_types import EntityId
from .dependencies import TradingAssistantDependencies


def register_robot_routes(router, *, auth_dependency, dependencies_dependency):
    auth, services = Depends(auth_dependency), Depends(dependencies_dependency)

    @router.get("/robot/candidates/{candidate_id}/tests/{test_id}", response_model=TestResult)
    async def test_result(candidate_id: EntityId, test_id: EntityId,
                          owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s, d: deps.robot_tests.read(s, owner_id=owner_id,
            candidate_id=UUID(candidate_id), test_id=UUID(test_id), deadline=d))
