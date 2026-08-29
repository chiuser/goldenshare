from __future__ import annotations

from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_auction_open import EquityAuctionOpen
from src.foundation.models.core_serving.wealth_sector_heat_daily import WealthSectorHeatDaily
from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy
from src.foundation.models.raw.raw_cyq_chips import RawCyqChips
from src.foundation.models.raw.raw_daily import RawDaily
from src.foundation.models.raw.raw_etf_sh_cons import RawEtfShCons
from src.foundation.models.raw.raw_etf_share_size import RawEtfShareSize
from src.foundation.models.raw.raw_etf_sz_cons import RawEtfSzCons
from src.foundation.models.raw.raw_fina_indicator import RawFinaIndicator
from src.foundation.models.raw.raw_stk_auction_o import RawStkAuctionO
from src.foundation.models.table_model_registry import get_model_by_table_name, table_model_registry


def test_table_model_registry_derives_models_from_sqlalchemy_metadata() -> None:
    assert get_model_by_table_name("core_serving.equity_daily_bar") is EquityDailyBar
    assert get_model_by_table_name("raw_tushare.daily") is RawDaily
    assert get_model_by_table_name("core_serving.equity_auction_open") is EquityAuctionOpen
    assert get_model_by_table_name("raw_tushare.stk_auction_o") is RawStkAuctionO
    assert get_model_by_table_name("raw_tushare.cyq_chips") is RawCyqChips
    assert get_model_by_table_name("raw_tushare.etf_sh_cons") is RawEtfShCons
    assert get_model_by_table_name("raw_tushare.etf_share_size") is RawEtfShareSize
    assert get_model_by_table_name("raw_tushare.etf_sz_cons") is RawEtfSzCons
    assert get_model_by_table_name("raw_tushare.fina_indicator") is RawFinaIndicator
    assert get_model_by_table_name("core_serving.wealth_sector_hierarchy") is WealthSectorHierarchy
    assert get_model_by_table_name("core_serving.wealth_sector_heat_daily") is WealthSectorHeatDaily


def test_table_model_registry_excludes_ops_tables() -> None:
    assert "ops.task_run" not in table_model_registry()
