from __future__ import annotations

from src.foundation.services.sync_v2.contracts import DatasetSyncContract, PlanUnit, ValidatedRunRequest
from src.foundation.services.sync_v2.strategy_helpers.param_format import (
    build_unit_id,
    resolve_enum_combinations,
)

_ALL_STOCK_BASIC_LIST_STATUS = ("L", "D", "P", "G")


def _resolve_source_mode(request: ValidatedRunRequest, contract: DatasetSyncContract) -> str:
    source_mode = str(request.source_key or request.params.get("source_key") or contract.source_spec.source_key_default).strip().lower()
    if source_mode not in {"tushare", "biying", "all"}:
        raise RuntimeError(f"stock_basic unsupported source_key={source_mode}")
    return source_mode


def _build_tushare_units(
    *,
    request: ValidatedRunRequest,
    contract: DatasetSyncContract,
    requested_source_key: str,
) -> list[PlanUnit]:
    enum_combinations = resolve_enum_combinations(
        request=request,
        fields=("list_status", "market", "exchange", "is_hs"),
        missing_field_defaults={"list_status": _ALL_STOCK_BASIC_LIST_STATUS},
    )
    units: list[PlanUnit] = []
    for ordinal, enum_values in enumerate(enum_combinations):
        merged_values = {**enum_values, "source_key": "tushare"}
        request_params = contract.source_spec.unit_params_builder(request, None, merged_values)
        units.append(
            PlanUnit(
                unit_id=build_unit_id(
                    dataset_key=request.dataset_key,
                    anchor=None,
                    merged_values=merged_values,
                    ordinal=ordinal,
                ),
                dataset_key=request.dataset_key,
                source_key="tushare",
                trade_date=None,
                request_params=request_params,
                pagination_policy="offset_limit",
                page_limit=6000,
                requested_source_key=requested_source_key,
            )
        )
    return units


def _build_biying_unit(
    *,
    request: ValidatedRunRequest,
    contract: DatasetSyncContract,
    requested_source_key: str,
) -> PlanUnit:
    request_params = contract.source_spec.unit_params_builder(request, None, {"source_key": "biying"})
    return PlanUnit(
        unit_id=build_unit_id(
            dataset_key=request.dataset_key,
            anchor=None,
            merged_values={"source_key": "biying"},
            ordinal=0,
        ),
        dataset_key=request.dataset_key,
        source_key="biying",
        trade_date=None,
        request_params=request_params,
        pagination_policy="none",
        page_limit=None,
        requested_source_key=requested_source_key,
    )


def build_stock_basic_units(
    request: ValidatedRunRequest,
    contract: DatasetSyncContract,
    dao,
    settings,
    session,
) -> list[PlanUnit]:
    del dao, settings, session
    source_mode = _resolve_source_mode(request, contract)
    if source_mode == "tushare":
        return _build_tushare_units(request=request, contract=contract, requested_source_key=source_mode)
    if source_mode == "biying":
        return [_build_biying_unit(request=request, contract=contract, requested_source_key=source_mode)]
    return _build_tushare_units(
        request=request,
        contract=contract,
        requested_source_key=source_mode,
    ) + [
        _build_biying_unit(
            request=request,
            contract=contract,
            requested_source_key=source_mode,
        )
    ]
