from src.foundation.models.core_multi.indicator_kdj_std import IndicatorKdjStd
from src.foundation.models.core_multi.indicator_macd_std import IndicatorMacdStd
from src.foundation.models.core_multi.indicator_rsi_std import IndicatorRsiStd
from src.foundation.models.core_serving.ind_kdj import IndicatorKdj
from src.foundation.models.core_serving.ind_macd import IndicatorMacd
from src.foundation.models.core_serving.ind_rsi import IndicatorRsi


def _pk(model) -> list[str]:
    return [column.name for column in model.__table__.primary_key.columns]


def test_indicator_std_and_serving_pk_shapes_are_compatible() -> None:
    assert _pk(IndicatorMacdStd) == ["source_key", "ts_code", "trade_date", "adjustment", "version"]
    assert _pk(IndicatorKdjStd) == ["source_key", "ts_code", "trade_date", "adjustment", "version"]
    assert _pk(IndicatorRsiStd) == ["source_key", "ts_code", "trade_date", "adjustment", "version"]

    assert _pk(IndicatorMacd) == ["ts_code", "trade_date", "adjustment", "version"]
    assert _pk(IndicatorKdj) == ["ts_code", "trade_date", "adjustment", "version"]
    assert _pk(IndicatorRsi) == ["ts_code", "trade_date", "adjustment", "version"]
