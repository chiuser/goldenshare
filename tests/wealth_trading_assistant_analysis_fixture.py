"""Additional source facts only; all analysis accounts/results must use commands/M3."""
from datetime import date
from sqlalchemy import insert
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.dc_index import DcIndex
from src.foundation.models.core_serving.dc_member import DcMember


def seed_analysis_sources(connection):
    for index in range(1, 12):
        code = f"{1200 + index:06d}.SZ"
        connection.execute(insert(Security), dict(ts_code=code, symbol=code[:6], name=f"分析样本{index:02d}",
            cnspell=f"FXYB{index}", exchange="SZSE", security_type="EQUITY", curr_type="CNY", list_status="L", source="isolated-browser-fixture"))
        for day, price in ((10, 10), (11, 11 if index <= 5 else 9 if index <= 8 else 10)):
            connection.execute(insert(EquityDailyBar), dict(ts_code=code, trade_date=date(2026, 9, day), close=str(price), source="tushare"))
        if index <= 10:
            board = f"BKFX{index:02d}.DC"
            connection.execute(insert(DcIndex), dict(ts_code=board, trade_date=date(2026, 9, 11),
                name=f"细分行业{index:02d}Ⅲ", idx_type="行业板块", level="东财三级行业"))
            connection.execute(insert(DcMember), dict(ts_code=board, trade_date=date(2026, 9, 11), con_code=code))
