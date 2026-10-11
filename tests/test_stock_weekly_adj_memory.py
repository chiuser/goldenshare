"""Bounded working sets must preserve the existing weekly unit contract."""

from decimal import Decimal
import json
import subprocess
import sys
from types import SimpleNamespace
import weakref

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.clients.tushare_client import TushareSdkClient
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.source_client import SourceFetchResult, SourcePageResult
from src.foundation.ingestion.writer import DatasetWriter
from test_stock_weekly_adj_p2 import (
    CODE,
    OLD,
    Raw,
    Serving,
    Delivery,
    db as sqlite_db,
    execute,
    fake_pages,
    planned,
    requested,
    row,
)


@pytest.fixture
def db(tmp_path):
    yield from sqlite_db.__wrapped__(tmp_path)


def large_rows():
    return [row(), *(row(code=f"{800000 + n:06d}.SH") for n in range(512))]


def point_plan(engine):
    return planned(engine, requested(mode="point", code=None, end=OLD))


def test_http_and_bounded_worker_import_do_not_load_sdk():
    probe = """
import json, sys
from src.foundation.clients import TushareHttpClient, TushareSdkClient
import src.foundation.clients.bounded_tushare_call
assert callable(TushareSdkClient)
client = TushareHttpClient(token='test-placeholder', base_url='http://invalid.local')
print(json.dumps({name: name in sys.modules for name in ('tushare', 'pandas', 'numpy')}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == {
        "tushare": False,
        "pandas": False,
        "numpy": False,
    }


def test_sdk_still_sets_token_and_delegates_pro_bar(monkeypatch):
    calls = []
    records = [{"ts_code": CODE, "close": 10}]
    sdk = SimpleNamespace(
        set_token=lambda value: calls.append(("token", value)),
        pro_bar=lambda **kw: (
            calls.append(("request", kw))
            or SimpleNamespace(to_dict=lambda **kw: records)
        ),
    )
    monkeypatch.setitem(sys.modules, "tushare", sdk)
    monkeypatch.setattr(
        "src.foundation.clients.tushare_client._get_rate_limiter",
        lambda _: SimpleNamespace(acquire=lambda: calls.append(("limited",))),
    )
    client = TushareSdkClient(token="test-placeholder")
    params = dict(
        ts_code=CODE,
        asset="E",
        start_date="20100101",
        end_date="20260605",
        adj="qfq",
        freq="W",
    )
    assert client.pro_bar(**params) == records
    assert calls == [("token", "test-placeholder"), ("limited",), ("request", params)]
    sdk.pro_bar = lambda **kw: None
    assert client.pro_bar(**params) == []


def test_capture_releases_original_decimal_page_before_normalization(db, monkeypatch):
    definition, request, units = point_plan(db)
    refs = []

    class TrackedRow(dict):
        pass

    def pages(**kwargs):
        value = TrackedRow(row())
        refs.append(weakref.ref(value))
        kwargs["control"].fetching(1, 0)
        yield SourcePageResult(
            unit_id=units[0].unit_id,
            page_number=1,
            offset=0,
            rows_raw=[value],
            retry_count=0,
            latency_ms=0,
            is_short_page=True,
        )

    original = DatasetNormalizer.normalize

    def normalize(self, **kwargs):
        assert refs and all(ref() is None for ref in refs)
        return original(self, **kwargs)

    monkeypatch.setattr(DatasetNormalizer, "normalize", normalize)
    result = execute(db, monkeypatch, definition, request, units, pages)
    assert result.rows_written == 1


def test_write_and_readback_blocks_are_bounded_with_cross_block_duplicate(
    db, monkeypatch
):
    definition, request, units = point_plan(db)
    source = large_rows()
    batches = []
    original = DatasetWriter._write_raw_and_core

    def write(**kwargs):
        batches.append(len(kwargs["batch"].rows_normalized))
        return original(**kwargs)

    monkeypatch.setattr(DatasetWriter, "_write_raw_and_core", staticmethod(write))
    import src.foundation.ingestion.stock_weekly_adj_delivery as delivery

    canonical = delivery.canonical_source_rows
    validation_sizes = []

    def validate(rows, policy):
        validation_sizes.append(len(rows))
        return canonical(rows, policy)

    monkeypatch.setattr(delivery, "canonical_source_rows", validate)
    normalized = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id=units[0].unit_id,
            request_count=1,
            retry_count=0,
            latency_ms=0,
            rows_raw=source + [dict(source[0])],
        ),
    )
    with Session(db) as session:
        result = DatasetWriter(session).write(
            definition=definition,
            batch=normalized,
            plan_unit=units[0],
            delivery_context=request.execution_context,
            cancel_check=lambda: None,
        )
        session.commit()
        receipt = session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
        assert result.rows_written == receipt.rows_unique == 513
        assert receipt.rows_received == 514
    assert batches == [128, 128, 128, 128, 2]
    assert validation_sizes == [514, *([128] * 8), 1, 1]


@pytest.mark.parametrize("problem", ["fail", "cancel", "readback"])
def test_later_block_problem_rolls_back_entire_unit(db, monkeypatch, problem):
    definition, request, units = point_plan(db)
    source = large_rows()
    original = DatasetWriter._write_raw_and_core
    state = {"calls": 0, "cancel": False}

    def write(**kwargs):
        state["calls"] += 1
        if problem == "fail" and state["calls"] == 2:
            raise RuntimeError("later write block failed")
        result = original(**kwargs)
        if problem == "cancel" and state["calls"] == 2:
            state["cancel"] = True
        if problem == "readback" and state["calls"] == 5:
            session = kwargs["core_dao"].session
            value = session.get(Serving, (source[-1]["ts_code"], OLD, "week"))
            value.close_qfq = Decimal(".01")
            session.flush()
        return result

    monkeypatch.setattr(DatasetWriter, "_write_raw_and_core", staticmethod(write))
    expected = (
        RuntimeError
        if problem == "fail"
        else IngestionCanceledError
        if problem == "cancel"
        else Exception
    )
    with pytest.raises(expected) as caught:
        execute(
            db,
            monkeypatch,
            definition,
            request,
            units,
            fake_pages(lambda _: source),
            cancel=lambda _: state["cancel"],
        )
    if problem == "readback":
        assert "读回键和值不一致" in str(caught.value)
    with Session(db) as session:
        assert session.get(Raw, (CODE, OLD, "week")).close_qfq == Decimal("10")
        assert session.get(Serving, (CODE, OLD, "week")).close_qfq == Decimal("10")
        assert session.get(Raw, (source[1]["ts_code"], OLD, "week")) is None
        assert (
            session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
            is None
        )


@pytest.mark.parametrize(
    "value",
    [
        {"中文": ["量价😀", None, True, 17], "rows": [{"price": "1.2500"}]},
        {"large": [{"ts_code": str(n), "value": "1.0000"} for n in range(300)]},
        {"numbers": [-0.0, 1.25, 1e-20], "text": '\\"\n'},
    ],
)
def test_streaming_size_and_digest_match_existing_frozen_bytes(value):
    import hashlib
    from src.foundation.datasets.stock_weekly_adj_contracts import (
        canonical_json,
        canonical_json_size,
        digest,
    )

    original = canonical_json(value).encode()
    assert canonical_json_size(value) == len(original)
    assert digest(value) == hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_streaming_json_still_rejects_nonfinite_values(value):
    from src.foundation.datasets.stock_weekly_adj_contracts import (
        canonical_json_size,
        digest,
    )

    for method in (canonical_json_size, digest):
        with pytest.raises(ValueError):
            method({"value": value})


@pytest.mark.parametrize(
    "problem", ["duplicate_boundary", "unordered_boundary", "noncanonical_value"]
)
def test_delivery_cannot_hide_invalid_rows_between_validation_blocks(db, problem):
    from uuid import uuid4
    from src.foundation.dao.stock_weekly_adj_delivery_dao import (
        StockWeeklyAdjDeliveryDAO,
    )
    from src.foundation.datasets.stock_weekly_adj_contracts import (
        WeeklyAdjExecutionPolicy,
        canonical_source_rows,
    )
    from test_stock_weekly_adj_p1_contracts import record

    policy = WeeklyAdjExecutionPolicy()
    rows = canonical_source_rows(large_rows(), policy)
    if problem == "duplicate_boundary":
        rows[256] = dict(rows[255])
    elif problem == "unordered_boundary":
        rows[256] = dict(rows[0])
    else:
        rows[300]["close_qfq"] = "5.00000"
    values = record(uuid4(), payload={"rows": rows})
    values.update(rows_received=513, rows_unique=513, rows_written=513)
    with Session(db) as session:
        with pytest.raises(ValueError):
            StockWeeklyAdjDeliveryDAO(session).append(values, policy)
        assert (
            session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
            is None
        )


def test_delivery_returns_independent_json_after_borrowing_validation_input(db):
    from uuid import uuid4
    from src.foundation.dao.stock_weekly_adj_delivery_dao import (
        StockWeeklyAdjDeliveryDAO,
    )
    from src.foundation.datasets.stock_weekly_adj_contracts import (
        WeeklyAdjExecutionPolicy,
    )
    from test_stock_weekly_adj_p1_contracts import record

    values = record(uuid4())
    with Session(db) as session:
        receipt = StockWeeklyAdjDeliveryDAO(session).append(
            values, WeeklyAdjExecutionPolicy()
        )
        values["payload"]["rows"][0]["close_qfq"] = "999.0000"
        assert receipt.payload["rows"][0]["close_qfq"] == "1.2500"
        session.commit()
        session.expire_all()
        assert (
            session.get(Delivery, receipt.revision).payload["rows"][0]["close_qfq"]
            == "1.2500"
        )
