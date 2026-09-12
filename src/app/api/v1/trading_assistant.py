"""Authenticate and inject the application-owned M2 services."""
from fastapi import Depends, Request

from src.app.auth.dependencies import get_current_user
from src.app.auth.domain import AuthenticatedUser
from src.biz.api.wealth.market.trading_assistant.router import create_trading_assistant_router


def owner(user: AuthenticatedUser = Depends(get_current_user)) -> int:
    return user.id


def dependencies(request: Request):
    return request.app.state.trading_assistant


router = create_trading_assistant_router(auth_dependency=owner, dependencies_dependency=dependencies)
