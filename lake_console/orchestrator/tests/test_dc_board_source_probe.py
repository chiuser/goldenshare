from contextlib import contextmanager

from orchestrator.defs.asset_guards.dc_board_source_probe import (
    compare_tushare_index_and_daily_to_reference,
    load_prod_dc_board_reference,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_FIELDS,
    DC_INDEX_FIELDS,
    DC_INDEX_TYPES,
    build_dc_board_prod_reference_snapshot,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

_TRADE_DATE = "2026-07-14"
_RAW_TRADE_DATE = _TRADE_DATE.replace("-", "")
_INDEX_IDENTITY = (
    ("行业板块", "BK0001.DC"),
    ("概念板块", "BK0002.DC"),
    ("地域板块", "BK0003.DC"),
)


def _reference():
    return build_dc_board_prod_reference_snapshot(
        trade_date=_TRADE_DATE,
        index_identity=_INDEX_IDENTITY,
        daily_identity=_INDEX_IDENTITY,
        member_codes=("BK0001.DC", "BK0002.DC", "BK0003.DC"),
        member_row_count=3,
    )


def _policy():
    return TushareRequestPolicy(
        minimum_interval_seconds=0.0,
        max_retries=0,
        max_requests=20,
        max_elapsed_seconds=30.0,
    )


class _FakeTushare:
    def __init__(self, *, partial_daily: bool = False, fail_daily: bool = False):
        self.calls = []
        self.partial_daily = partial_daily
        self.fail_daily = fail_daily

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        if params["offset"]:
            return TushareResult(rows=[], columns=tuple(fields), metadata={})
        if api_name == "dc_index":
            index = DC_INDEX_TYPES.index(params["idx_type"])
            return TushareResult(
                rows=[
                    {
                        "idx_type": params["idx_type"],
                        "ts_code": f"BK{index + 1:04d}.DC",
                        "trade_date": _RAW_TRADE_DATE,
                    }
                ],
                columns=tuple(fields),
                metadata={},
            )
        if api_name == "dc_daily":
            if self.fail_daily:
                raise RuntimeError("Tushare daily response interrupted")
            rows = [
                {
                    "category": category,
                    "ts_code": code,
                    "trade_date": _RAW_TRADE_DATE,
                }
                for category, code in _INDEX_IDENTITY
            ]
            if self.partial_daily:
                rows.pop()
            return TushareResult(rows=rows, columns=tuple(fields), metadata={})
        raise AssertionError(api_name)


class _FakeCursor:
    def __init__(
        self,
        *,
        invalid_member_keys: int = 0,
        index_identity=_INDEX_IDENTITY,
        daily_identity=_INDEX_IDENTITY,
        member_codes=("BK0001.DC", "BK0002.DC", "BK0003.DC"),
    ):
        self.invalid_member_keys = invalid_member_keys
        self.index_identity = index_identity
        self.daily_identity = daily_identity
        self.member_codes = member_codes
        self.query = ""

    def execute(self, query, _params):
        self.query = query

    def fetchall(self):
        if "core_serving.dc_index" in self.query:
            return list(self.index_identity)
        if "core_serving.dc_daily" in self.query:
            return list(self.daily_identity)
        raise AssertionError(self.query)

    def fetchone(self):
        assert "core_serving.dc_member" in self.query
        return (
            len(self.member_codes),
            self.invalid_member_keys,
            0,
            list(self.member_codes),
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeProdConnection:
    def __init__(self, *, invalid_member_keys: int = 0):
        self.cursor_instance = _FakeCursor(invalid_member_keys=invalid_member_keys)

    def cursor(self):
        return self.cursor_instance


class _FakeProd:
    def __init__(
        self,
        *,
        invalid_member_keys: int = 0,
        index_identity=_INDEX_IDENTITY,
        daily_identity=_INDEX_IDENTITY,
        member_codes=("BK0001.DC", "BK0002.DC", "BK0003.DC"),
    ):
        self.connection = _FakeProdConnection(invalid_member_keys=invalid_member_keys)
        self.connection.cursor_instance = _FakeCursor(
            invalid_member_keys=invalid_member_keys,
            index_identity=index_identity,
            daily_identity=daily_identity,
            member_codes=member_codes,
        )

    @contextmanager
    def connect_readonly_transaction(self):
        yield self.connection


class _FailingProdCursor(_FakeCursor):
    def __init__(self, *, fail_on_query: int):
        super().__init__()
        self.fail_on_query = fail_on_query
        self.query_count = 0

    def execute(self, query, _params):
        self.query_count += 1
        if self.query_count == self.fail_on_query:
            raise RuntimeError("prod connection interrupted")
        super().execute(query, _params)


class _FailingProd(_FakeProd):
    def __init__(self, *, fail_on_query: int):
        cursor = _FailingProdCursor(fail_on_query=fail_on_query)
        self.connection = _FakeProdConnection()
        self.connection.cursor_instance = cursor


def test_prod_reference_requires_three_closed_identity_queries():
    result = load_prod_dc_board_reference(
        prod_postgres=_FakeProd(),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is True
    assert result.reason_code == "ready"
    assert result.query_count == 3
    assert result.snapshot is not None
    assert result.snapshot.fingerprint == _reference().fingerprint


def test_prod_reference_fails_closed_on_member_key_problem():
    result = load_prod_dc_board_reference(
        prod_postgres=_FakeProd(invalid_member_keys=1),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is False
    assert result.reason_code == "prod_reference_not_closed"
    assert result.snapshot is None


def test_prod_reference_accepts_member_subset_index_subset_daily():
    result = load_prod_dc_board_reference(
        prod_postgres=_FakeProd(
            daily_identity=(*_INDEX_IDENTITY, ("行业板块", "BK0004.DC")),
            member_codes=("BK0001.DC", "BK0002.DC"),
        ),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is True
    assert result.reason_code == "ready"
    assert result.snapshot is not None
    assert result.snapshot.index_row_count == 3
    assert result.snapshot.daily_row_count == 4
    assert result.snapshot.member_code_count == 2


def test_prod_reference_rejects_index_code_missing_from_daily():
    result = load_prod_dc_board_reference(
        prod_postgres=_FakeProd(daily_identity=_INDEX_IDENTITY[:-1]),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is False
    assert result.reason_code == "prod_reference_not_closed"
    assert result.snapshot is None


def test_prod_reference_rejects_member_code_outside_index():
    result = load_prod_dc_board_reference(
        prod_postgres=_FakeProd(
            member_codes=("BK0001.DC", "BK0002.DC", "BK9999.DC")
        ),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is False
    assert result.reason_code == "prod_reference_not_closed"
    assert result.snapshot is None


def test_prod_reference_keeps_completed_query_count_when_query_fails():
    result = load_prod_dc_board_reference(
        prod_postgres=_FailingProd(fail_on_query=2),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is False
    assert result.reason_code == "prod_reference_unavailable"
    assert result.query_count == 2


def test_complete_tushare_comparison_requires_all_index_and_daily_identity_rows():
    source = _FakeTushare()
    result = compare_tushare_index_and_daily_to_reference(
        tushare=source,
        trade_date=_TRADE_DATE,
        reference=_reference(),
        policy=_policy(),
    )

    assert result.ready is True
    assert result.reason_code == "ready"
    assert [call[0] for call in source.calls] == [
        "dc_index",
        "dc_index",
        "dc_index",
        "dc_daily",
    ]
    assert all(call[2] in (DC_INDEX_FIELDS, DC_DAILY_FIELDS) for call in source.calls)


def test_complete_tushare_comparison_rejects_partial_daily_response():
    result = compare_tushare_index_and_daily_to_reference(
        tushare=_FakeTushare(partial_daily=True),
        trade_date=_TRADE_DATE,
        reference=_reference(),
        policy=_policy(),
    )

    assert result.ready is False
    assert result.reason_code == "tushare_reference_mismatch"
    assert result.daily_missing_count == 1


def test_tushare_comparison_counts_late_failed_request():
    result = compare_tushare_index_and_daily_to_reference(
        tushare=_FakeTushare(fail_daily=True),
        trade_date=_TRADE_DATE,
        reference=_reference(),
        policy=_policy(),
    )

    assert result.ready is False
    assert result.reason_code == "source_request_error"
    assert result.request_count == len(DC_INDEX_TYPES) + 1
