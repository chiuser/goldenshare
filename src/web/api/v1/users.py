from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from src.web.auth.dependencies import require_authenticated
from src.web.domain.user import AuthenticatedUser
from src.web.schemas.auth import CurrentUserResponse
from src.web.services.user_service import UserService


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=CurrentUserResponse)
def get_self(user: AuthenticatedUser = Depends(require_authenticated)) -> CurrentUserResponse:
    profile = UserService().get_self_profile(user)
    return CurrentUserResponse(**asdict(profile))
