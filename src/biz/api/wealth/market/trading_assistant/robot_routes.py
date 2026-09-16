"""Owned robot configuration, test evidence and notification history/commands."""
from uuid import UUID

from fastapi import Depends, Request

from src.biz.schemas.wealth.market.trading_assistant.robot import TestResult
from src.biz.schemas.wealth.market.trading_assistant import robot, receipts
from src.biz.schemas.wealth.market.trading_assistant.value_types import EntityId
from .dependencies import TradingAssistantDependencies
from .record_routes import parse_record_query
from .errors import command_response
from src.biz.schemas.wealth.market.trading_assistant.scopes import Pagination


def register_robot_routes(router, *, auth_dependency, dependencies_dependency):
    auth, services = Depends(auth_dependency), Depends(dependencies_dependency)

    @router.get("/notifications/{notification_id}", response_model=robot.NotificationDetail)
    async def notification(notification_id: EntityId, request: Request, limit: int = 20, cursor: str | None = None,
                           owner_id: int = auth, deps: TradingAssistantDependencies = services):
        query = parse_record_query(request, Pagination)
        return await deps.read(lambda s, d: deps.notification_query.read(s, owner_id=owner_id,
            notification_id=UUID(notification_id), query=query, now=deps.now(), deadline=d))

    @router.post("/notifications/{notification_id}/retry", response_model=receipts.NotificationRetryReceipt, status_code=202)
    async def retry(notification_id: EntityId, command: robot.NotificationRetryCommand,
                    owner_id: int = auth, deps: TradingAssistantDependencies = services):
        state = await deps.notification_commands.retry(owner_id=owner_id,
            notification_id=UUID(notification_id), command=command)
        response = command_response(state)
        if state.status == "SAVED":
            response.status_code = 202
        return response

    @router.get("/robot", response_model=robot.RobotResponse)
    async def configuration(owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s, d: deps.robot_configuration.read(s, owner_id=owner_id, deadline=d))

    @router.post("/robot/candidates", response_model=receipts.CandidateCreateReceipt)
    async def create(command: robot.CandidateCommand, owner_id: int = auth,
                     deps: TradingAssistantDependencies = services):
        return await deps.robot_commands.create(owner_id=owner_id, command=command)

    @router.post("/robot/candidates/{candidate_id}/confirmations", response_model=receipts.RobotConfirmReceipt)
    async def confirm(candidate_id: EntityId, command: robot.ConfirmCandidateCommand, owner_id: int = auth,
                      deps: TradingAssistantDependencies = services):
        return await deps.robot_commands.confirm(owner_id=owner_id, candidate_id=UUID(candidate_id), command=command)

    @router.post("/robot/candidates/{candidate_id}/tests", response_model=receipts.RobotTestReceipt, status_code=202)
    async def test(candidate_id: EntityId, command: robot.TestCandidateCommand, owner_id: int = auth,
                   deps: TradingAssistantDependencies = services):
        return await deps.robot_commands.test(owner_id=owner_id, candidate_id=UUID(candidate_id), command=command)

    @router.get("/robot/candidates/{candidate_id}/tests/{test_id}", response_model=TestResult)
    async def test_result(candidate_id: EntityId, test_id: EntityId,
                          owner_id: int = auth, deps: TradingAssistantDependencies = services):
        return await deps.read(lambda s, d: deps.robot_tests.read(s, owner_id=owner_id,
            candidate_id=UUID(candidate_id), test_id=UUID(test_id), deadline=d))
