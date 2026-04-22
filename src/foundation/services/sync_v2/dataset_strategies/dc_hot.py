from __future__ import annotations

from src.foundation.services.sync_v2.dataset_strategies.common import build_default_units


def build_dc_hot_units(request, contract, dao, settings, session):
    return build_default_units(
        request,
        contract,
        dao,
        settings,
        session,
        page_limit=2000,
        enum_fields=("market", "hot_type", "is_new"),
    )

