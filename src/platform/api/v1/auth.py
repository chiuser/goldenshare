from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.platform.auth.dependencies import require_authenticated
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.platform.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse
from src.platform.schemas.common import OkResponse
from src.platform.services.auth_service import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(get_db_session)) -> TokenResponse:
    token, user = AuthService().login(session, username=body.username, password=body.password)
    return TokenResponse(
        token=token,
        username=user.username,
        is_admin=user.is_admin,
        display_name=user.display_name,
    )


@router.get("/me", response_model=CurrentUserResponse)
def me(user: AuthenticatedUser = Depends(require_authenticated)) -> CurrentUserResponse:
    return CurrentUserResponse(**asdict(user))


@router.post("/logout", response_model=OkResponse)
def logout(_user: AuthenticatedUser = Depends(require_authenticated)) -> OkResponse:
    return OkResponse()
