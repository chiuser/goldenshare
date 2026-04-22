from __future__ import annotations

from src.foundation.services.sync_v2.dataset_strategies.common import build_default_units


def build_stk_period_bar_adj_month_units(request, contract, dao, settings, session):
    return build_default_units(request, contract, dao, settings, session, page_limit=6000)

