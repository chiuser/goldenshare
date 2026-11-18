"""Bootstrap 专用的四张 Prod 周月表只读投影；不供日常任务调用。"""

from contextlib import contextmanager

from orchestrator.defs.run_contracts.column_schema import ColumnContract
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_WEEKLY,
    index_period_codes,
)
from orchestrator.tushare_download.contracts.index_weekly import SOURCE_FIELDS

RAW_COLUMNS = tuple(field.name for field in SOURCE_FIELDS)
# Prod来源仍是股／元／比例，不能提前套用换算后的DG Silver精度。
PROD_INDEX_PERIOD_SERVING_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "指数代码"),
    ColumnContract("period_start_date", "DATE", "自然周期首个开市日"),
    ColumnContract("trade_date", "DATE", "行情实际截至日"),
    *(ColumnContract(name, "DECIMAL(18,4)", description) for name, description in (
        ("open", "开盘点位"), ("high", "最高点位"), ("low", "最低点位"),
        ("close", "收盘点位"), ("pre_close", "前收盘点位"), ("change_amount", "涨跌点位"),
    )),
    ColumnContract("pct_chg", "DECIMAL(10,4)", "涨跌幅比例，1%为0.0100"),
    ColumnContract("vol", "DECIMAL(20,4)", "成交量，股"),
    ColumnContract("amount", "DECIMAL(20,4)", "成交额，元"),
)
SERVING_COLUMNS = tuple(column.name for column in PROD_INDEX_PERIOD_SERVING_SCHEMA)


def prod_index_period_query(period, layer):
    if period not in (INDEX_WEEKLY, INDEX_MONTHLY) or layer not in ("raw", "serving"):
        raise ValueError("只允许指定指数周月线 Raw／Serving 投影")
    raw = layer == "raw"
    columns = RAW_COLUMNS if raw else SERVING_COLUMNS
    projection = ", ".join(
        "to_char(trade_date, 'YYYYMMDD') AS trade_date"
        if raw and name == "trade_date"
        else f'"{name}"'
        for name in columns
    )
    schema, suffix = ("raw_tushare", "bar") if raw else ("core_serving", "serving")
    codes = tuple(code for code in index_period_codes() if raw or code != "000680.SH")
    return (
        (
            f"SELECT {projection} FROM {schema}.{period.dataset_id}_{suffix} "
            "WHERE ts_code = ANY(%s) ORDER BY ts_code, trade_date"
        ),
        (list(codes),),
    )


@contextmanager
def open_prod_index_period_rows(prod_postgres, *, period, layer):
    """查询范围固定为获准11／10码；消费者在只读事务内取得行，不在此导出。"""
    sql, parameters = prod_index_period_query(period, layer)
    with (
        prod_postgres.connect_readonly_transaction() as connection,
        connection.cursor(name=f"dg_{period.dataset_id}_{layer}") as cursor,
    ):
        cursor.execute(sql, parameters)
        yield cursor
