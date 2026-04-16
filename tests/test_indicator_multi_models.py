from src.foundation.models.core_multi.indicator_kdj_std import IndicatorKdjStd
from src.foundation.models.core_multi.indicator_macd_std import IndicatorMacdStd
from src.foundation.models.core_multi.indicator_rsi_std import IndicatorRsiStd


def test_indicator_macd_std_primary_key_and_indexes() -> None:
    assert [column.name for column in IndicatorMacdStd.__table__.primary_key.columns] == [
        "source_key",
        "ts_code",
        "trade_date",
        "adjustment",
        "version",
    ]
    assert {index.name for index in IndicatorMacdStd.__table__.indexes} == {
        "idx_indicator_macd_std_trade_date",
        "idx_indicator_macd_std_source_trade_date",
    }


def test_indicator_kdj_std_primary_key_and_indexes() -> None:
    assert [column.name for column in IndicatorKdjStd.__table__.primary_key.columns] == [
        "source_key",
        "ts_code",
        "trade_date",
        "adjustment",
        "version",
    ]
    assert {index.name for index in IndicatorKdjStd.__table__.indexes} == {
        "idx_indicator_kdj_std_trade_date",
        "idx_indicator_kdj_std_source_trade_date",
    }
    assert "rsv" in IndicatorKdjStd.__table__.columns
    assert "is_valid" in IndicatorKdjStd.__table__.columns


def test_indicator_rsi_std_primary_key_and_indexes() -> None:
    assert [column.name for column in IndicatorRsiStd.__table__.primary_key.columns] == [
        "source_key",
        "ts_code",
        "trade_date",
        "adjustment",
        "version",
    ]
    assert {index.name for index in IndicatorRsiStd.__table__.indexes} == {
        "idx_indicator_rsi_std_trade_date",
        "idx_indicator_rsi_std_source_trade_date",
    }
    assert "is_valid" in IndicatorRsiStd.__table__.columns
