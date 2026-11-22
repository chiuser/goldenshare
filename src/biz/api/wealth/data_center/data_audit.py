from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException

from src.biz.services.wealth.data_center.data_audit import DataAuditReader


def build_data_audit_router(reader: DataAuditReader) -> APIRouter:
    router = APIRouter(prefix="/api/v1/wealth/data-center/data-audit", tags=["wealth-data-center"])

    @router.get("/days/{day}")
    def read_day(day: date) -> dict:
        result = reader.read(day)
        return {
            **result,
            "rows": [
                {
                    **row,
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
                return row
        raise HTTPException(404, detail={"message": "该日没有此资产的审计结果"})

    return router
