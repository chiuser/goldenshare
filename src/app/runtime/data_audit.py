import httpx
from fastapi import Depends, FastAPI

from src.app.auth.dependencies import get_current_user, require_admin
from src.biz.api.wealth.data_center.data_audit import build_data_audit_router
from src.biz.services.wealth.data_center.data_audit import DataAuditReader
from src.foundation.config.data_audit import data_audit_enabled


def install_data_audit(app: FastAPI, settings) -> None:
    if data_audit_enabled(settings):
        reader = DataAuditReader(httpx.Client(trust_env=False))
        app.include_router(
            build_data_audit_router(reader, get_current_user, require_admin),
            dependencies=[Depends(get_current_user)],
        )
