from __future__ import annotations

from src.foundation.services.sync_v2.dataset_strategies.common import build_default_units


def build_ths_daily_units(request, contract, dao, settings, session):
    return build_default_units(
        request,
        contract,
        dao,
        settings,
        session,
        page_limit=2000,
        anchor_type_override="trade_date",
        window_policy_override="point_or_range",
    )

