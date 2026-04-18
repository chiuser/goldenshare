from __future__ import annotations

from fastapi import APIRouter, Depends

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
def admin_ping(_user: AuthenticatedUser = Depends(require_admin)) -> dict[str, bool | str]:
    return {"ok": True, "role": "admin"}
