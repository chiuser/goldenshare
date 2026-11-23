from collections.abc import Callable
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.biz.services.wealth.data_center.data_audit import DataAuditReader


class BoardConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_version: str = Field(min_length=1)


class BoardRecheckRequest(BoardConfirmRequest):
    retry_run_id: UUID | None = None


def build_data_audit_router(reader: DataAuditReader, get_current_user: Callable, require_admin: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/v1/wealth/data-center/data-audit", tags=["wealth-data-center"])
    authenticated = Depends(get_current_user)
    administrator = Depends(require_admin)

    @router.get("/days/{day}")
    def read_day(day: date, user=authenticated) -> dict:
        result = reader.read(day)
        return {
            **result,
            "can_operate": result["state"] == "ready" and user.is_admin,
            "rows": [
                {
                    **{key: value for key, value in row.items() if key != "board_review"},
                    "completeness": {
                        field: row["completeness"][field]
                        for field in ("status", "reason", "checked_at", "components")
                    },
                }
                for row in result["rows"]
            ],
        }

    @router.get("/days/{day}/assets/{asset_key}")
    def read_asset(day: date, asset_key: str, summary_run_id: UUID | None = None):
        result = reader.read(day, str(summary_run_id) if summary_run_id else None)
        if result["state"] == "unavailable":
            raise HTTPException(503, detail={"message": "暂时无法读取本机 DG 总结"})
        for row in result["rows"]:
            if row["scope"]["asset_key"] == asset_key:
                return {key: value for key, value in row.items() if key != "board_review"}
        raise HTTPException(404, detail={"message": "该日没有此资产的审计结果"})

    @router.get("/days/{day}/assets/{asset_key}/board-standard")
    def read_board_standard(day: date, asset_key: str) -> dict:
        return reader.board_review(day, asset_key)

    @router.post("/days/{day}/assets/{asset_key}/board-recheck", status_code=202)
    def recheck_board(day: date, asset_key: str, body: BoardRecheckRequest, user=administrator) -> dict:
        return reader.submit_board(
            day, asset_key, review_version=body.review_version, requested_by=str(user.id), recheck=True,
            retry_run_id=str(body.retry_run_id) if body.retry_run_id else None,
        )

    @router.post("/days/{day}/assets/{asset_key}/board-confirm", status_code=202)
    def confirm_board(day: date, asset_key: str, body: BoardConfirmRequest, user=administrator) -> dict:
        return reader.submit_board(
            day, asset_key, review_version=body.review_version, requested_by=str(user.id), recheck=False,
        )

    @router.get("/runs/{run_id}", dependencies=[administrator])
    def read_board_run(run_id: UUID) -> dict:
        return reader.board_run(str(run_id))

    return router
