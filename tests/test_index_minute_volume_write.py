from datetime import date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.foundation.datasets import get_dataset_definition
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.raw.index_mins_volume_evidence import IndexMinsVolumeEvidence
from src.foundation.models.raw.raw_index_mins import RawIndexMins


def test_index_minutes_store_shares_and_source_evidence_together():
    engine = create_engine("sqlite://")
    days = [date(2026, 11, day) for day in (9, 10, 11, 12)]
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS raw_tushare")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        for model in (TradeCalendar, RawIndexMins, IndexMinsVolumeEvidence):
            model.__table__.create(connection)

    def bar(day, code, vol):
        return {
            "ts_code": code,
            "freq": "30min",
            "trade_time": datetime.combine(day, datetime.strptime("15:00", "%H:%M").time()),
            "close": 3476.47,
            "vol": vol,
            "amount": 650_000_000_000.0,
        }

    definition = get_dataset_definition("index_mins")
    with Session(engine) as session:
        session.add_all(TradeCalendar(exchange="SSE", trade_date=day, is_open=True) for day in days)
        session.add_all(
            IndexMinsVolumeEvidence(
                ts_code=code,
                freq="30min",
                trade_date=days[0],
                source_vol=total,
                source_unit="share",
            )
            for code, total in (("000001.SH", 42_772_225_700), ("399001.SZ", 39_000_000_000))
        )
        session.commit()

        rows = [
            bar(days[2], "000001.SH", 493_526_296),
            bar(days[1], "000001.SH", 999),
            bar(days[1], "000001.SH", 404_865_177),
            bar(days[3], "000001.SH", 47_256_142_700),
            bar(days[1], "399001.SZ", 40_000_000_000),
        ]
        batch = NormalizedBatch(unit_id="index-minutes", rows_normalized=rows, rows_rejected=0, rejected_reasons={})
        writer = DatasetWriter(session)

        def check():
            result = writer.write(definition=definition, batch=batch)
            assert result.rows_written == 4
            assert result.rows_rejected == 1
            prices = session.scalars(select(RawIndexMins).order_by(RawIndexMins.ts_code, RawIndexMins.trade_time)).all()
            assert [price.vol for price in prices] == [
                40_486_517_700, 49_352_629_600, 47_256_142_700, 40_000_000_000
            ]
            assert all(price.amount == 650_000_000_000 for price in prices)
            facts = session.scalars(select(IndexMinsVolumeEvidence).where(
                IndexMinsVolumeEvidence.ts_code == "000001.SH",
                IndexMinsVolumeEvidence.trade_date > days[0],
            ).order_by(IndexMinsVolumeEvidence.trade_date)).all()
            assert [(fact.source_vol, fact.source_unit) for fact in facts] == [
                (404_865_177, "lot"), (493_526_296, "lot"), (47_256_142_700, "share")
            ]

        check()
        session.rollback()
        assert session.scalars(select(RawIndexMins)).all() == []
        assert len(session.scalars(select(IndexMinsVolumeEvidence)).all()) == 2

        check()
        session.commit()
        check()
        session.commit()
        assert rows[2]["vol"] == 404_865_177
