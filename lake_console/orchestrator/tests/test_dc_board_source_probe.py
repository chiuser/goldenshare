from contextlib import contextmanager

from orchestrator.defs.asset_guards.dc_board_source_probe import (
    load_prod_dc_board_completion_snapshot,
    load_tushare_dc_index_daily_source_snapshot,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_FIELDS,
    DC_INDEX_FIELDS,
    DC_INDEX_TYPES,
    build_dc_board_prod_completion_snapshot,
    is_dc_index_placeholder,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

_TRADE_DATE = "2026-07-14"
_RAW_TRADE_DATE = _TRADE_DATE.replace("-", "")
_INDEX_IDENTITY = (
    ("行业板块", "BK0001.DC"),
    ("概念板块", "BK0002.DC"),
    ("地域板块", "BK0003.DC"),
)


def _completion(*, daily_identity=_INDEX_IDENTITY):
    return build_dc_board_prod_completion_snapshot(
        trade_date=_TRADE_DATE,
        index_identity=_INDEX_IDENTITY,
        daily_identity=daily_identity,
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
    def __init__(
        self,
        *,
        partial_daily: bool = False,
        fail_daily: bool = False,
        daily_close: float = 1.0,
        placeholder_index: bool = False,
    ):
        self.calls = []
        self.partial_daily = partial_daily
        self.fail_daily = fail_daily
        self.daily_close = daily_close
        self.placeholder_index = placeholder_index

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        if params["offset"]:
            return TushareResult(rows=[], columns=tuple(fields), metadata={})
        if api_name == "dc_index":
            index = DC_INDEX_TYPES.index(params["idx_type"])
            rows = [
                {
                    "idx_type": params["idx_type"],
                    "ts_code": f"BK{index + 1:04d}.DC",
                    "trade_date": _RAW_TRADE_DATE,
                }
            ]
            if self.placeholder_index and params["idx_type"] == "概念板块":
                rows.append(
                    {
                        "idx_type": params["idx_type"],
                        "ts_code": "BK1675.DC",
                        "trade_date": _RAW_TRADE_DATE,
                        "name": "历史新高",
                        "leading": "-",
                        "leading_code": None,
                        "pct_change": 0.0,
                        "leading_pct": 0.0,
                        "total_mv": 0.0,
                        "turnover_rate": 0.0,
                        "up_num": None,
                        "down_num": None,
                    }
                )
            return TushareResult(
                rows=rows,
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
                    "close": self.daily_close,
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


def test_prod_completion_requires_three_closed_identity_queries():
    result = load_prod_dc_board_completion_snapshot(
        prod_postgres=_FakeProd(),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is True
    assert result.reason_code == "ready"
    assert result.query_count == 3
    assert result.snapshot is not None
    assert (
        result.snapshot.completion_fingerprint == _completion().completion_fingerprint
    )


def test_prod_completion_fails_closed_on_member_key_problem():
    result = load_prod_dc_board_completion_snapshot(
        prod_postgres=_FakeProd(invalid_member_keys=1),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is False
    assert result.reason_code == "prod_completion_not_closed"
    assert result.snapshot is None


def test_prod_completion_accepts_member_subset_index_subset_daily():
    result = load_prod_dc_board_completion_snapshot(
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


def test_prod_completion_rejects_index_code_missing_from_daily():
    result = load_prod_dc_board_completion_snapshot(
        prod_postgres=_FakeProd(daily_identity=_INDEX_IDENTITY[:-1]),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is False
    assert result.reason_code == "prod_completion_not_closed"
    assert result.snapshot is None


def test_prod_completion_rejects_member_code_outside_index():
    result = load_prod_dc_board_completion_snapshot(
        prod_postgres=_FakeProd(member_codes=("BK0001.DC", "BK0002.DC", "BK9999.DC")),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is False
    assert result.reason_code == "prod_completion_not_closed"
    assert result.snapshot is None


def test_prod_completion_keeps_completed_query_count_when_query_fails():
    result = load_prod_dc_board_completion_snapshot(
        prod_postgres=_FailingProd(fail_on_query=2),
        trade_date=_TRADE_DATE,
    )

    assert result.ready is False
    assert result.reason_code == "prod_completion_unavailable"
    assert result.query_count == 2


def test_complete_tushare_source_requires_all_index_and_daily_rows():
    source = _FakeTushare()
    result = load_tushare_dc_index_daily_source_snapshot(
        tushare=source,
        trade_date=_TRADE_DATE,
        prod_completion=_completion(),
        policy=_policy(),
    )

    assert result.ready is True
    assert result.reason_code == "ready"
    assert result.snapshot is not None
    assert len(result.snapshot.source_fingerprint) == 64
    assert result.content_matches_prod is True
    assert [call[0] for call in source.calls] == [
        "dc_index",
        "dc_index",
        "dc_index",
        "dc_daily",
    ]
    assert all(call[2] in (DC_INDEX_FIELDS, DC_DAILY_FIELDS) for call in source.calls)


def test_source_filters_exact_placeholder_but_keeps_normal_rows():
    source = _FakeTushare(placeholder_index=True)
    result = load_tushare_dc_index_daily_source_snapshot(
        tushare=source,
        trade_date=_TRADE_DATE,
        prod_completion=_completion(),
        policy=_policy(),
    )

    assert result.ready is True
    assert result.placeholder_row_count == 1
    assert result.snapshot is not None
    assert result.snapshot.index_row_count == 3
    assert all(
        "BK1675.DC" not in {row["ts_code"] for row in rows}
        for rows in result.index_rows_by_type.values()
    )
    assert is_dc_index_placeholder(
        {
            "name": "历史新高",
            "leading": "-",
            "leading_code": None,
            "pct_change": 0.0,
            "leading_pct": 0.0,
            "total_mv": 0.0,
            "turnover_rate": 0.0,
            "up_num": None,
            "down_num": None,
        }
    )
    assert not is_dc_index_placeholder(
        {
            "name": "历史新高",
            "leading": "股票一",
            "leading_code": "000001.SZ",
            "pct_change": 1.0,
            "leading_pct": 2.0,
            "total_mv": 100.0,
            "turnover_rate": 3.0,
            "up_num": 1,
            "down_num": 1,
        }
    )


def test_complete_tushare_source_rejects_partial_daily_response():
    result = load_tushare_dc_index_daily_source_snapshot(
        tushare=_FakeTushare(partial_daily=True),
        trade_date=_TRADE_DATE,
        prod_completion=_completion(),
        policy=_policy(),
    )

    assert result.ready is False
    assert result.reason_code == "source_validation_failed"
    assert result.snapshot is None


def test_tushare_source_counts_late_failed_request():
    result = load_tushare_dc_index_daily_source_snapshot(
        tushare=_FakeTushare(fail_daily=True),
        trade_date=_TRADE_DATE,
        prod_completion=_completion(),
        policy=_policy(),
    )

    assert result.ready is False
    assert result.reason_code == "source_request_error"
    assert result.request_count == len(DC_INDEX_TYPES) + 1


def test_prod_content_difference_is_diagnostic_not_source_failure():
    result = load_tushare_dc_index_daily_source_snapshot(
        tushare=_FakeTushare(),
        trade_date=_TRADE_DATE,
        prod_completion=_completion(
            daily_identity=(*_INDEX_IDENTITY, ("行业板块", "BK0004.DC")),
        ),
        policy=_policy(),
    )

    assert result.ready is True
    assert result.content_matches_prod is False
    assert result.daily_missing_count == 1
    assert result.daily_extra_count == 0


def test_tushare_source_fingerprint_covers_business_values():
    first = load_tushare_dc_index_daily_source_snapshot(
        tushare=_FakeTushare(daily_close=1.0),
        trade_date=_TRADE_DATE,
        prod_completion=_completion(),
        policy=_policy(),
    )
    second = load_tushare_dc_index_daily_source_snapshot(
        tushare=_FakeTushare(daily_close=2.0),
        trade_date=_TRADE_DATE,
        prod_completion=_completion(),
        policy=_policy(),
    )

    assert first.snapshot is not None
    assert second.snapshot is not None
    assert first.snapshot.source_fingerprint != second.snapshot.source_fingerprint
