from __future__ import annotations

from src.foundation.services.sync_v2.dataset_strategies.common import build_default_units


def build_moneyflow_cnt_ths_units(request, contract, dao, settings, session):
    return build_default_units(request, contract, dao, settings, session, page_limit=5000)

