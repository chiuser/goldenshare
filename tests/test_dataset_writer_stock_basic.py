from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core.equity_top_list import EquityTopList
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.raw.raw_index_basic import RawIndexBasic
from src.foundation.models.raw.raw_top_list import RawTopList


class _StubUpsertDao:
    def __init__(self, written: int = 1) -> None:
        self.written = written
        self.calls: list[list[dict]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.calls.append(rows)
        return self.written


class _StubSecurityDao:
    def __init__(self, existing: set[str] | None = None, written: int = 1) -> None:
        self.existing = existing or set()
        self.written = written
        self.upsert_calls: list[list[dict]] = []
        self.existing_calls: list[list[str]] = []

    def get_existing_ts_codes(self, ts_codes):  # type: ignore[no-untyped-def]
        self.existing_calls.append(list(ts_codes))
        return set(self.existing)

    def upsert_many(self, rows: list[dict]) -> int:
        self.upsert_calls.append(rows)
        return self.written if rows else 0


class _StubConflictDao:
    def __init__(self, model) -> None:  # type: ignore[no-untyped-def]
        self.model = model
        self.calls: list[tuple[list[dict], list[str] | None]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.calls.append((rows, conflict_columns))
        return len(rows)


def test_writer_stock_basic_tushare_direct_publish(mocker) -> None:
    raw_tushare = _StubUpsertDao(written=2)
    raw_biying = _StubUpsertDao(written=0)
    security_std = _StubUpsertDao(written=2)
    security = _StubSecurityDao(existing=set(), written=2)
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(
            raw_stock_basic=raw_tushare,
            raw_tushare_stock_basic=raw_tushare,
            raw_biying_stock_basic=raw_biying,
            security_std=security_std,
            security=security,
        ),
    )
    writer = DatasetWriter(session=object())  # type: ignore[arg-type]
    definition = get_dataset_definition("stock_basic")
    batch = NormalizedBatch(
        unit_id="u-stock-basic-tushare",
        rows_normalized=[
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "list_status": "L",
                "list_date": date(1991, 4, 3),
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )
    plan_unit = PlanUnitSnapshot(
        unit_id="u-stock-basic-tushare",
        dataset_key="stock_basic",
        source_key="tushare",
        trade_date=None,
        request_params={},
        progress_context={},
        requested_source_key="tushare",
    )

    result = writer.write(definition=definition, batch=batch, plan_unit=plan_unit)

    assert len(raw_tushare.calls) == 1
    assert len(security_std.calls) == 1
    assert len(security.upsert_calls) == 1
    assert result.rows_written == 2
    assert result.conflict_strategy == "tushare_direct_upsert"


def test_writer_stock_basic_biying_only_inserts_missing_codes(mocker) -> None:
    raw_tushare = _StubUpsertDao(written=0)
    raw_biying = _StubUpsertDao(written=2)
    security_std = _StubUpsertDao(written=2)
    security = _StubSecurityDao(existing={"000001.SZ"}, written=1)
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(
            raw_stock_basic=raw_tushare,
            raw_tushare_stock_basic=raw_tushare,
            raw_biying_stock_basic=raw_biying,
            security_std=security_std,
            security=security,
        ),
    )
    writer = DatasetWriter(session=object())  # type: ignore[arg-type]
    definition = get_dataset_definition("stock_basic")
    batch = NormalizedBatch(
        unit_id="u-stock-basic-biying",
        rows_normalized=[
            {"dm": "000001.SZ", "mc": "平安银行", "jys": "SZSE"},
            {"dm": "000002.SZ", "mc": "万科A", "jys": "SZSE"},
        ],
        rows_rejected=0,
        rejected_reasons={},
    )
    plan_unit = PlanUnitSnapshot(
        unit_id="u-stock-basic-biying",
        dataset_key="stock_basic",
        source_key="biying",
        trade_date=None,
        request_params={},
        progress_context={},
        requested_source_key="biying",
    )

    result = writer.write(definition=definition, batch=batch, plan_unit=plan_unit)

    assert len(raw_biying.calls) == 1
    assert len(security_std.calls) == 1
    assert security.existing_calls == [["000001.SZ", "000002.SZ"]]
    assert len(security.upsert_calls) == 1
    assert [row["ts_code"] for row in security.upsert_calls[0]] == ["000002.SZ"]
    assert result.conflict_strategy == "biying_missing_only"
    assert result.rows_rejected == 1
    assert result.rejected_reason_counts == {"write.filtered_by_business_rule:ts_code": 1}


def test_writer_counts_duplicate_conflict_keys() -> None:
    reason_counts = DatasetWriter._duplicate_reason_counts(
        rows=[
            {"row_key_hash": "a", "title": "第一条"},
            {"row_key_hash": "a", "title": "重复条"},
            {"row_key_hash": "b", "title": "第二条"},
        ],
        conflict_columns=("row_key_hash",),
    )

    assert reason_counts == {"write.duplicate_conflict_key_in_batch:row_key_hash": 1}


def test_writer_coerces_rows_per_target_model_date_columns() -> None:
    rows = [
        {
            "ts_code": "000300.SH",
            "base_date": "20041231",
            "list_date": "20050408",
            "exp_date": "",
        }
    ]

    raw_rows = DatasetWriter._coerce_rows_for_dao(rows, SimpleNamespace(model=RawIndexBasic))
    core_rows = DatasetWriter._coerce_rows_for_dao(rows, SimpleNamespace(model=IndexBasic))

    assert raw_rows[0]["base_date"] == "20041231"
    assert raw_rows[0]["list_date"] == "20050408"
    assert core_rows[0]["base_date"] == date(2004, 12, 31)
    assert core_rows[0]["list_date"] == date(2005, 4, 8)
    assert core_rows[0]["exp_date"] is None


def test_writer_top_list_uses_reason_hash_only_for_serving_upsert() -> None:
    batch = NormalizedBatch(
        unit_id="u-top-list",
        rows_normalized=[
            {
                "ts_code": "603256.SH",
                "trade_date": date(2019, 7, 19),
                "reason": "当日无价格涨跌幅限制的A股，出现异常波动停牌的",
                "reason_hash": "644a65b32e1965db7c889958fc4a47f114ed7b3762d3fe465cb67784249e4582",
                "payload_hash": "payload-a",
            },
            {
                "ts_code": "603256.SH",
                "trade_date": date(2019, 7, 19),
                "reason": "当日无价格涨跌幅限制的A股,出现异常波动停牌的",
                "reason_hash": "644a65b32e1965db7c889958fc4a47f114ed7b3762d3fe465cb67784249e4582",
                "payload_hash": "payload-b",
            },
        ],
        rows_rejected=0,
        rejected_reasons={},
    )
    raw_dao = _StubConflictDao(RawTopList)
    core_dao = _StubConflictDao(EquityTopList)

    written = DatasetWriter._write_raw_and_core(
        batch=batch,
        raw_dao=raw_dao,
        core_dao=core_dao,
        raw_conflict_columns=("ts_code", "trade_date", "reason", "payload_hash"),
        conflict_columns=("ts_code", "trade_date", "reason_hash"),
        serving_conflict_resolution_policy="top_list_variant_resolution_v1",
    )

    assert written == 1
    assert raw_dao.calls[0][1] == ["ts_code", "trade_date", "reason", "payload_hash"]
    assert core_dao.calls[0][1] == ["ts_code", "trade_date", "reason_hash"]
    assert core_dao.calls[0][0][0]["selected_payload_hash"] == "payload-b"
    assert core_dao.calls[0][0][0]["variant_count"] == 2
    assert core_dao.calls[0][0][0]["resolution_policy_version"] == "top_list_variant_resolution_v1"


def test_writer_top_list_prefers_non_null_float_values_for_serving_conflict() -> None:
    batch = NormalizedBatch(
        unit_id="u-top-list-float-values",
        rows_normalized=[
            {
                "ts_code": "603517.SH",
                "trade_date": date(2017, 3, 29),
                "reason": "非ST、*ST和S证券连续三个交易日内收盘价格涨幅偏离值累计达到20%的证券",
                "reason_hash": "0370e845c74bc4b1f9eb4ead034413a8bf0d40df9fa25cadd95f1afafca1d274",
                "payload_hash": "payload-1",
                "float_values": "2482500000.0",
            },
            {
                "ts_code": "603517.SH",
                "trade_date": date(2017, 3, 29),
                "reason": "非ST、*ST和S证券连续三个交易日内收盘价格涨幅偏离值累计达到20%的证券",
                "reason_hash": "0370e845c74bc4b1f9eb4ead034413a8bf0d40df9fa25cadd95f1afafca1d274",
                "payload_hash": "payload-2",
                "float_values": None,
            },
        ],
        rows_rejected=0,
        rejected_reasons={},
    )
    raw_dao = _StubConflictDao(RawTopList)
    core_dao = _StubConflictDao(EquityTopList)

    written = DatasetWriter._write_raw_and_core(
        batch=batch,
        raw_dao=raw_dao,
        core_dao=core_dao,
        raw_conflict_columns=("ts_code", "trade_date", "reason", "payload_hash"),
        conflict_columns=("ts_code", "trade_date", "reason_hash"),
        serving_conflict_resolution_policy="top_list_variant_resolution_v1",
    )

    assert written == 1
    assert len(raw_dao.calls[0][0]) == 2
    assert core_dao.calls[0][1] == ["ts_code", "trade_date", "reason_hash"]
    assert len(core_dao.calls[0][0]) == 1
    assert core_dao.calls[0][0][0]["float_values"] == "2482500000.0"
    assert core_dao.calls[0][0][0]["selected_payload_hash"] == "payload-1"
    assert core_dao.calls[0][0][0]["variant_count"] == 2


def test_writer_top_list_counts_only_duplicate_raw_versions_as_rejections() -> None:
    reason_counts = DatasetWriter._duplicate_reason_counts(
        rows=[
            {
                "ts_code": "603517.SH",
                "trade_date": date(2017, 3, 29),
                "reason": "非ST、*ST和S证券连续三个交易日内收盘价格涨幅偏离值累计达到20%的证券",
                "payload_hash": "payload-1",
            },
            {
                "ts_code": "603517.SH",
                "trade_date": date(2017, 3, 29),
                "reason": "非ST、*ST和S证券连续三个交易日内收盘价格涨幅偏离值累计达到20%的证券",
                "payload_hash": "payload-2",
            },
        ],
        conflict_columns=("ts_code", "trade_date", "reason", "payload_hash"),
    )

    assert reason_counts == {}
