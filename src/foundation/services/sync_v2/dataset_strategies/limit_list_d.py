from __future__ import annotations

from src.foundation.services.sync_v2.dataset_strategies.common import build_default_units


def build_limit_list_d_units(request, contract, dao, settings, session):
    return build_default_units(
        request,
        contract,
        dao,
        settings,
        session,
        page_limit=2500,
        enum_fields=("limit_type", "exchange"),
    )
