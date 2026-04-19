from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies import get_db_session
from src.ops.queries.std_rule_query_service import StdRuleQueryService
from src.ops.schemas.std_rule import (
    CreateStdCleansingRuleRequest,
    CreateStdMappingRuleRequest,
    StdCleansingRuleListResponse,
    StdMappingRuleListResponse,
    UpdateStdCleansingRuleRequest,
    UpdateStdMappingRuleRequest,
)
from src.ops.services.std_rule_service import OpsStdRuleCommandService


router = APIRouter(tags=["ops"])


@router.get("/ops/std-rules/mapping", response_model=StdMappingRuleListResponse)
def list_std_mapping_rules(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    dataset_key: str | None = Query(None),
    source_key: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> StdMappingRuleListResponse:
    return StdRuleQueryService().list_mapping_rules(
        session,
        dataset_key=dataset_key,
        source_key=source_key,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/ops/std-rules/mapping", response_model=StdMappingRuleListResponse)
def create_std_mapping_rule(
    body: CreateStdMappingRuleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StdMappingRuleListResponse:
    OpsStdRuleCommandService().create_mapping_rule(session, user=user, payload=body.model_dump())
    return StdRuleQueryService().list_mapping_rules(
        session,
        dataset_key=body.dataset_key,
        source_key=body.source_key,
        limit=200,
        offset=0,
    )


@router.patch("/ops/std-rules/mapping/{rule_id}", response_model=StdMappingRuleListResponse)
def update_std_mapping_rule(
    rule_id: int,
    body: UpdateStdMappingRuleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StdMappingRuleListResponse:
    OpsStdRuleCommandService().update_mapping_rule(
        session,
        user=user,
        rule_id=rule_id,
        changes=body.model_dump(exclude_unset=True),
    )
    return StdRuleQueryService().list_mapping_rules(session, limit=200, offset=0)


@router.post("/ops/std-rules/mapping/{rule_id}/disable", response_model=StdMappingRuleListResponse)
def disable_std_mapping_rule(
    rule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StdMappingRuleListResponse:
    OpsStdRuleCommandService().disable_mapping_rule(session, user=user, rule_id=rule_id)
    return StdRuleQueryService().list_mapping_rules(session, limit=200, offset=0)


@router.post("/ops/std-rules/mapping/{rule_id}/enable", response_model=StdMappingRuleListResponse)
def enable_std_mapping_rule(
    rule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StdMappingRuleListResponse:
    OpsStdRuleCommandService().enable_mapping_rule(session, user=user, rule_id=rule_id)
    return StdRuleQueryService().list_mapping_rules(session, limit=200, offset=0)


@router.get("/ops/std-rules/cleansing", response_model=StdCleansingRuleListResponse)
def list_std_cleansing_rules(
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    dataset_key: str | None = Query(None),
    source_key: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> StdCleansingRuleListResponse:
    return StdRuleQueryService().list_cleansing_rules(
        session,
        dataset_key=dataset_key,
        source_key=source_key,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/ops/std-rules/cleansing", response_model=StdCleansingRuleListResponse)
def create_std_cleansing_rule(
    body: CreateStdCleansingRuleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StdCleansingRuleListResponse:
    OpsStdRuleCommandService().create_cleansing_rule(session, user=user, payload=body.model_dump())
    return StdRuleQueryService().list_cleansing_rules(
        session,
        dataset_key=body.dataset_key,
        source_key=body.source_key,
        limit=200,
        offset=0,
    )


@router.patch("/ops/std-rules/cleansing/{rule_id}", response_model=StdCleansingRuleListResponse)
def update_std_cleansing_rule(
    rule_id: int,
    body: UpdateStdCleansingRuleRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StdCleansingRuleListResponse:
    OpsStdRuleCommandService().update_cleansing_rule(
        session,
        user=user,
        rule_id=rule_id,
        changes=body.model_dump(exclude_unset=True),
    )
    return StdRuleQueryService().list_cleansing_rules(session, limit=200, offset=0)


@router.post("/ops/std-rules/cleansing/{rule_id}/disable", response_model=StdCleansingRuleListResponse)
def disable_std_cleansing_rule(
    rule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StdCleansingRuleListResponse:
    OpsStdRuleCommandService().disable_cleansing_rule(session, user=user, rule_id=rule_id)
    return StdRuleQueryService().list_cleansing_rules(session, limit=200, offset=0)


@router.post("/ops/std-rules/cleansing/{rule_id}/enable", response_model=StdCleansingRuleListResponse)
def enable_std_cleansing_rule(
    rule_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> StdCleansingRuleListResponse:
    OpsStdRuleCommandService().enable_cleansing_rule(session, user=user, rule_id=rule_id)
    return StdRuleQueryService().list_cleansing_rules(session, limit=200, offset=0)
