from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    env: str


class OkResponse(BaseModel):
    ok: bool = True


class ApiErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str | None = None


__all__ = ["ApiErrorResponse", "HealthResponse", "OkResponse"]
