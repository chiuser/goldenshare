from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from src.platform.auth.dependencies import require_authenticated
from src.platform.auth.domain import AuthenticatedUser
from src.platform.schemas.auth import CurrentUserResponse
from src.platform.services.user_service import UserService


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=CurrentUserResponse)
def get_self(user: AuthenticatedUser = Depends(require_authenticated)) -> CurrentUserResponse:
    profile = UserService().get_self_profile(user)
    return CurrentUserResponse(**asdict(profile))
