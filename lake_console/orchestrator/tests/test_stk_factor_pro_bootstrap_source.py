"""Isolated source streaming: fake Prod transport, real 261-column temp Parquet."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from psycopg2 import sql

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_source as source
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection

DAY = date(2019, 10, 16)


def render(query):
    # Independent visibility into the composed fixed SQL, without a real PG socket.
    if isinstance(query, str):
        return query
    if isinstance(query, sql.SQL):
        return query.string
    if isinstance(query, sql.Identifier):
        return ".".join('"' + part.replace('"', '""') + '"' for part in query.strings)
    return "".join(render(part) for part in query.seq)


class Cursor:
    def __init__(self, remote, *, named):
        self.remote, self.named = remote, named
        self.description = tuple((name,) for name in C.STK_FACTOR_PRO_SOURCE_COLUMNS)
        self.result, self.position, self.closed = [], 0, False
        self.itersize = None

    def execute(self, query, parameters=None):
        text = render(query)
        self.remote.queries.append((self.named, text, parameters))
        if self.named:
            assert "OFFSET" not in text and "SELECT *" not in text
            self.result = self.remote.rows
        elif text.startswith("SELECT set_config"):
            self.result = []
        elif "information_schema.columns" in text:
            self.result = [
                (name, kind, "YES" if nullable else "NO")
                for name, kind, nullable in self.remote.identity.columns
            ]
        elif "MIN(trade_date)" in text:
            self.result = [
                (
                    self.remote.approval.start_trade_date,
                    self.remote.approval.end_trade_date,
                )
            ]
        elif "COUNT(*)" in text:
            self.result = [
                (day, number)
                for day, number in self.remote.counts.items()
                if day in parameters[2] and number
            ]
        elif "ts_code=ANY" in text:
            self.result = [
                row
                for row in self.remote.sample_rows
                if row[1] == parameters[0] and row[0] in parameters[1]
            ][: parameters[2]]
        else:
            raise AssertionError(text)
        self.position = 0

    def fetchmany(self, size):
        if self.named:
            self.remote.fetch_sizes.append(size)
            if self.remote.read_failure_at == len(self.remote.fetch_sizes):
                raise RuntimeError("injected remote read failure")
        rows = self.result[self.position : self.position + size]
        self.position += len(rows)
        return rows

    def fetchone(self):
        return self.fetchmany(1)[0]

    def fetchall(self):
        raise AssertionError("unbounded fetchall is forbidden")

    def close(self):
        self.closed = True
        self.remote.closes.append("named" if self.named else "control")
        if self.remote.close_failure:
            raise RuntimeError("injected cursor close failure")


class FakeProd:
    # Carrier types mirror Prod DATE/float source, independently from HTTP fixtures.
    host_env_var, port_env_var, database_env_var = "HOST", "PORT", "DATABASE"

    def __init__(self, approval, identity, counts, rows, *, sample_rows=None):
        self.approval, self.identity, self.counts = approval, identity, dict(counts)
        self.rows, self.sample_rows = (
            list(rows),
            list(rows if sample_rows is None else sample_rows),
        )
        self.queries, self.fetch_sizes, self.closes, self.cursors = [], [], [], []
        self.connections = 0
        self.read_failure_at = None
        self.close_failure = False
        self.exit_failure = False

    def _required_env(self, name):
        return {
            "HOST": self.identity.host,
            "PORT": str(self.identity.port),
            "DATABASE": self.identity.database,
        }[name]

    @contextmanager
    def connect_readonly_transaction(self):
        self.connections += 1
        try:
            yield self
        finally:
            self.closes.extend(("rollback", "connection"))
            if self.exit_failure:
                raise RuntimeError("injected rollback/connection failure")

    def cursor(self, name=None, **kwargs):
        if name is not None:
            assert kwargs == {"scrollable": False, "withhold": False}
            assert name.startswith("stk_factor_bootstrap_")
        cursor = Cursor(self, named=name is not None)
        self.cursors.append(cursor)
        return cursor


def execute(conn, staging, approval, remote, *, callback, month=None, selected=None):
    month = month or approval.month_limits[0]
    if selected is None:
        selected = tuple(
            month.month_start + timedelta(days=i)
            for i in range((month.month_end_exclusive - month.month_start).days)
        )
    return source.export_stk_factor_pro_bootstrap_month(
        prod_postgres=remote,
        connection=conn,
        staging_root=staging,
        approval=approval,
        month=month,
        selected_dates=selected,
        on_complete_date=callback,
        check_space=check_test_space,
    )


def accept_source_only(monkeypatch, seen):
    # Publication is deliberately replaced here. Source facts and temp Parquet are real;
    # public callback-shape validation has separate positive/negative tests below.
    monkeypatch.setattr(source, "_validate_date_result", lambda record, result: ())

    def callback(record):
        seen.append(record)

    return callback


@pytest.mark.parametrize("size", [4999, 5000, 5001])
def test_named_stream_batches_and_true_eof(tmp_path, monkeypatch, size):
    counts = ((DAY, size),)
    rows = [native_row(f"{i:06}.SZ") for i in range(size)]
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, rows, sample_rows=[native_row()])
        seen = []
        result = execute(
            conn,
            staging,
            approval,
            remote,
            callback=accept_source_only(monkeypatch, seen),
        )
        assert result.source_rows == size and result.complete_dates == (DAY,)
        assert len(result.fragments) == (1 if size <= 5000 else 2)
        assert seen[0].actual_rows == size and seen[0].close_reason == "eof"
        assert remote.fetch_sizes == (
            [size + 1, 1]
            if size < 5000
            else [5000, 1]
            if size == 5000
            else [5000, 2, 1]
        )
        assert remote.closes == ["named", "control", "rollback", "connection"]
        named = [item for item in remote.queries if item[0]]
        assert len(named) == 1 and named[0][2][-1] == size + 1
        assert remote.cursors[-1].itersize == 5000
        assert '"api_name"' not in named[0][1] and '"raw_payload"' not in named[0][1]
        assert named[0][1].count('"') == 2 * (261 + 2)
        assert remote.queries[0][2] == ("30000",)
        assert not conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'stk_factor_bootstrap%'"
        ).fetchall()


def test_multiple_days_cross_batches_and_empty_days_wait_for_eof(tmp_path, monkeypatch):
    counts = ((DAY, 3), (DAY + timedelta(days=1), 0), (DAY + timedelta(days=2), 2))
    rows = [native_row(f"{i:06}.SZ", DAY) for i in range(3)] + [
        native_row(f"{i:06}.SZ", DAY + timedelta(days=2)) for i in range(2)
    ]
    monkeypatch.setattr(C, "STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS", 2)
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, rows, sample_rows=[native_row()])
        seen = []
        result = execute(
            conn,
            staging,
            approval,
            remote,
            callback=accept_source_only(monkeypatch, seen),
        )
        assert [item.trade_date for item in seen] == [
            DAY,
            DAY + timedelta(days=1),
            DAY + timedelta(days=2),
        ]
        assert [(item.close_reason, len(item.fragments)) for item in seen] == [
            ("next_date", 2),
            ("eof", 0),
            ("eof", 2),
        ]
        assert [item.actual_rows for item in seen] == [3, 0, 2]
        assert result.complete_dates == tuple(day for day, _ in counts)
        assert remote.fetch_sizes == [2, 2, 2, 1]


@pytest.mark.parametrize("delta", [-1, 1])
def test_short_eof_and_r_plus_one_reject_current_batch(tmp_path, monkeypatch, delta):
    counts = ((DAY, 2),)
    rows = [native_row(f"{i:06}.SZ") for i in range(2 + delta)]
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, rows, sample_rows=[native_row()])
        seen = []
        with pytest.raises(ValueError, match="EOF|R\\+1"):
            execute(
                conn,
                staging,
                approval,
                remote,
                callback=accept_source_only(monkeypatch, seen),
            )
        assert not seen
        root = records.operation_root(staging, approval)
        assert not list(root.rglob("source-complete.json"))
        assert len(list(root.rglob("fragment-*.parquet"))) == int(delta == -1)
        assert remote.closes == ["named", "control", "rollback", "connection"]


@pytest.mark.parametrize(
    "kind", ["duplicate", "reverse", "wrong_date", "wrong_type", "wrong_fields"]
)
def test_invalid_batch_never_saves_or_calls_back(tmp_path, monkeypatch, kind):
    counts = ((DAY, 2),)
    rows = [native_row("000001.SZ"), native_row("000002.SZ")]
    if kind == "duplicate":
        rows[1] = rows[0]
    elif kind == "reverse":
        rows.reverse()
    elif kind == "wrong_date":
        rows[1] = native_row("000002.SZ", DAY + timedelta(days=1))
    elif kind == "wrong_type":
        rows[1] = tuple("1.2" if i == 2 else value for i, value in enumerate(rows[1]))
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, rows, sample_rows=[native_row()])
        if kind == "wrong_fields":
            original = remote.cursor

            def bad_cursor(*args, **kwargs):
                cursor = original(*args, **kwargs)
                if cursor.named:
                    cursor.description = cursor.description[:-1]
                return cursor

            remote.cursor = bad_cursor
        seen = []
        with pytest.raises(ValueError):
            execute(
                conn,
                staging,
                approval,
                remote,
                callback=accept_source_only(monkeypatch, seen),
            )
        assert not seen and not list(
            records.operation_root(staging, approval).rglob("fragment-*.parquet")
        )


def test_completed_source_removed_from_plan_without_prod_connection(
    tmp_path, monkeypatch
):
    counts = ((DAY, 1),)
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, [native_row()])
        execute(
            conn,
            staging,
            approval,
            remote,
            callback=accept_source_only(monkeypatch, []),
        )
        before = remote.connections
        result = execute(
            conn,
            staging,
            approval,
            remote,
            selected=(),
            callback=lambda _: pytest.fail("unexpected callback"),
        )
        assert (
            remote.connections == before
            and result.source_rows == 0
            and result.complete_dates == ()
        )
        with pytest.raises(ValueError, match="待读取日期"):
            execute(conn, staging, approval, remote, callback=lambda _: None)
        path = records.operation_path(
            staging, approval, f"source/dates/{DAY}/source-complete.json"
        )
        path.write_text("{}")
        with pytest.raises((TypeError, ValueError)):
            execute(
                conn, staging, approval, remote, selected=(), callback=lambda _: None
            )
        assert remote.connections == before


def test_callback_failure_and_multiple_cleanup_failures_keep_first_error(tmp_path):
    counts = ((DAY, 1), (DAY + timedelta(days=1), 1))
    rows = [native_row(), native_row(day=DAY + timedelta(days=1))]
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, rows)
        remote.close_failure = remote.exit_failure = True

        def callback(_record):
            raise LookupError("business callback failed")

        with pytest.raises(LookupError, match="business callback failed") as error:
            execute(conn, staging, approval, remote, callback=callback)
        assert len(error.value.__notes__) == 3
        assert remote.closes == ["named", "control", "rollback", "connection"]
        assert len(remote.fetch_sizes) == 1
        assert (
            records.read_stk_factor_pro_bootstrap_source_complete(
                conn, staging_root=staging, approval=approval, trade_date=DAY
            )
            is not None
        )
        assert (
            records.read_stk_factor_pro_bootstrap_source_complete(
                conn,
                staging_root=staging,
                approval=approval,
                trade_date=DAY + timedelta(days=1),
            )
            is None
        )


def test_normal_body_close_failure_is_failure(tmp_path, monkeypatch):
    counts = ((DAY, 1),)
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, [native_row()])
        remote.close_failure = True
        with pytest.raises(RuntimeError, match="cursor close"):
            execute(
                conn,
                staging,
                approval,
                remote,
                callback=accept_source_only(monkeypatch, []),
            )
        assert all(cursor.closed for cursor in remote.cursors)


def test_preflight_and_window_are_separate_from_local_approval_validation(
    tmp_path, monkeypatch
):
    counts = ((DAY, 1),)
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, [native_row()])
        source.preflight_stk_factor_pro_bootstrap_source(
            prod_postgres=remote,
            connection=conn,
            staging_root=staging,
            approval=approval,
            month=approval.month_limits[0],
            selected_dates=(DAY,),
        )
        assert remote.connections == 1 and not remote.fetch_sizes
        expired = approval.source_maintenance_end
        assert (
            source.validate_stk_factor_pro_bootstrap_approval(
                approval=approval, now=expired, source_identity=identity
            )
            == approval.month_limits
        )
        monkeypatch.setattr(source, "_now", lambda: expired)
        with pytest.raises(ValueError, match="维护窗口"):
            execute(conn, staging, approval, remote, callback=lambda _: None)
        assert remote.connections == 1


def test_planner_clips_exact_whole_range_and_rejects_extra_months():
    months = source.plan_stk_factor_pro_bootstrap_months(
        date(2019, 12, 31),
        date(2020, 2, 29),
        {"2019-12": 1, "2020-01": 0, "2020-02": 2},
    )
    assert [(m.month_start, m.month_end_exclusive) for m in months] == [
        (date(2019, 12, 31), date(2020, 1, 1)),
        (date(2020, 1, 1), date(2020, 2, 1)),
        (date(2020, 2, 1), date(2020, 3, 1)),
    ]
    with pytest.raises(ValueError, match="范围外月份"):
        source.plan_stk_factor_pro_bootstrap_months(
            DAY, DAY, {"2019-10": 1, "2019-11": 1}
        )


def test_empty_and_nonempty_callback_contracts(tmp_path):
    empty_record = SimpleNamespace(
        trade_date=DAY, source_complete_digest="a" * 64, source_empty=True
    )
    result = C.StkFactorProBootstrapDateResult(DAY, "a" * 64, None, None, None)
    assert source._validate_date_result(empty_record, result) == ()
    with pytest.raises(ValueError, match="身份不符"):
        source._validate_date_result(
            empty_record, replace(result, trade_date=DAY + timedelta(days=1))
        )
    nonempty_record = SimpleNamespace(
        trade_date=DAY, source_complete_digest="a" * 64, source_empty=False
    )
    with pytest.raises(ValueError, match="两层检查"):
        source._validate_date_result(nonempty_record, result)


def test_partial_month_plan_never_reads_completed_source_business_columns(
    tmp_path, monkeypatch
):
    following = DAY + timedelta(days=1)
    counts = ((DAY, 1), (following, 1))
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        source_fixture(
            conn, staging_root=staging, approval=approval, rows=[native_row()]
        )
        with monkeypatch.context() as probe:
            probe.setattr(
                records,
                "load_complete_source",
                lambda *_a, **_k: pytest.fail(
                    "planner reread completed source business columns"
                ),
            )
            assert source._selected_dates(
                conn,
                staging_root=staging,
                approval=approval,
                month=approval.month_limits[0],
            ) == (following,)
        remote = FakeProd(
            approval,
            identity,
            counts,
            [native_row(day=following)],
            sample_rows=[native_row()],
        )
        seen = []
        result = execute(
            conn,
            staging,
            approval,
            remote,
            selected=(following,),
            callback=accept_source_only(monkeypatch, seen),
        )
        assert result.complete_dates == (following,)
        assert [query[2][2] for query in remote.queries if query[0]] == [[following]]


def test_selected_zero_source_date_is_completed_only_after_real_eof(tmp_path):
    empty_day, last = DAY + timedelta(days=1), DAY + timedelta(days=2)
    counts = ((DAY, 1), (empty_day, 0), (last, 1))
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        source_fixture(
            conn, staging_root=staging, approval=approval, rows=[native_row()], day=DAY
        )
        source_fixture(
            conn,
            staging_root=staging,
            approval=approval,
            rows=[native_row(day=last)],
            day=last,
            attempt="b" * 32,
        )
        remote = FakeProd(approval, identity, counts, [], sample_rows=[native_row()])
        seen = []

        def callback(record):
            seen.append(record)
            assert remote.fetch_sizes == [3]
            return C.StkFactorProBootstrapDateResult(
                empty_day, record.source_complete_digest, None, None, None
            )

        result = execute(
            conn, staging, approval, remote, selected=(empty_day,), callback=callback
        )
        assert (
            result.source_rows == 0
            and result.fragments == ()
            and result.complete_dates == (empty_day,)
        )
        assert seen[0].source_empty and seen[0].close_reason == "eof"
        assert seen[0].approved_rows == seen[0].actual_rows == 0


def test_r_plus_one_batch_preserves_earlier_complete_day(tmp_path, monkeypatch):
    following = DAY + timedelta(days=1)
    counts = ((DAY, 1), (following, 2))
    rows = [native_row(day=DAY)] + [
        native_row(f"{i:06}.SZ", following) for i in range(3)
    ]
    monkeypatch.setattr(C, "STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS", 2)
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, rows)
        seen = []
        with pytest.raises(ValueError, match="R\\+1"):
            execute(
                conn,
                staging,
                approval,
                remote,
                callback=accept_source_only(monkeypatch, seen),
            )
        assert [record.trade_date for record in seen] == [DAY]
        assert (
            len(
                list(
                    records.operation_root(staging, approval).rglob(
                        "fragment-*.parquet"
                    )
                )
            )
            == 1
        )
        assert (
            records.read_stk_factor_pro_bootstrap_source_complete(
                conn, staging_root=staging, approval=approval, trade_date=DAY
            )
            is not None
        )
        assert (
            records.read_stk_factor_pro_bootstrap_source_complete(
                conn, staging_root=staging, approval=approval, trade_date=following
            )
            is None
        )


@pytest.mark.parametrize("kind", ["duplicate", "reverse"])
def test_strict_order_across_batches(tmp_path, monkeypatch, kind):
    counts = ((DAY, 3),)
    rows = [
        native_row("000001.SZ"),
        native_row("000002.SZ"),
        native_row("000002.SZ" if kind == "duplicate" else "000000.SZ"),
    ]
    monkeypatch.setattr(C, "STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS", 2)
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, rows)
        with pytest.raises(ValueError, match="跨批逆序"):
            execute(
                conn,
                staging,
                approval,
                remote,
                callback=lambda _: pytest.fail("half day callback"),
            )
        assert (
            len(
                list(
                    records.operation_root(staging, approval).rglob(
                        "fragment-*.parquet"
                    )
                )
            )
            == 1
        )
        assert not list(
            records.operation_root(staging, approval).rglob("source-complete.json")
        )


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_fetch_error_or_cancellation_keeps_half_day_incomplete(
    tmp_path, monkeypatch, failure
):
    counts = ((DAY, 3),)
    rows = [native_row(f"{i:06}.SZ") for i in range(3)]
    monkeypatch.setattr(C, "STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS", 2)
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, rows)
        original = Cursor.fetchmany

        def failing_fetch(cursor, size):
            if cursor.named and len(remote.fetch_sizes) == 1:
                raise failure("stop")
            return original(cursor, size)

        monkeypatch.setattr(Cursor, "fetchmany", failing_fetch)
        with pytest.raises(failure, match="stop"):
            execute(
                conn,
                staging,
                approval,
                remote,
                callback=lambda _: pytest.fail("half day callback"),
            )
        assert not list(
            records.operation_root(staging, approval).rglob("source-complete.json")
        )
        assert remote.closes == ["named", "control", "rollback", "connection"]


@pytest.mark.parametrize("kind", ["schema", "range", "counts", "sample"])
def test_preflight_changes_stop_before_named_cursor(tmp_path, kind):
    counts = ((DAY, 1),)
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, [native_row()])
        if kind == "schema":
            remote.identity = replace(
                identity,
                columns=tuple(
                    (name, "real" if i == 2 else data_type, nullable)
                    for i, (name, data_type, nullable) in enumerate(identity.columns)
                ),
            )
        elif kind == "range":
            remote.approval = replace(
                approval,
                end_trade_date=DAY + timedelta(days=1),
                source_cutoff_trade_date=DAY + timedelta(days=1),
                month_limits=(
                    replace(
                        approval.month_limits[0],
                        month_end_exclusive=DAY + timedelta(days=2),
                    ),
                ),
            )
        elif kind == "counts":
            remote.counts[DAY] = 2
        else:
            remote.sample_rows = []
        with pytest.raises(ValueError):
            execute(
                conn,
                staging,
                approval,
                remote,
                callback=lambda _: pytest.fail("preflight callback"),
            )
        assert not any(cursor.named for cursor in remote.cursors)
        assert remote.closes == ["control", "rollback", "connection"]


def test_zero_row_month_has_real_eof_and_no_fragments(tmp_path):
    first = date(2019, 12, 31)
    counts = tuple((first + timedelta(days=i), int(i in (0, 32))) for i in range(33))
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        month = approval.month_limits[1]
        remote = FakeProd(
            approval, identity, counts, [], sample_rows=[native_row(day=first)]
        )
        observed = []

        def callback(record):
            observed.append(record.trade_date)
            return C.StkFactorProBootstrapDateResult(
                record.trade_date, record.source_complete_digest, None, None, None
            )

        result = execute(
            conn, staging, approval, remote, month=month, callback=callback
        )
        assert month.row_upper_bound == 0 and remote.fetch_sizes == [1]
        assert len(observed) == 31 and observed == sorted(observed)
        assert result.source_rows == 0 and not result.fragments
        assert len(result.complete_dates) == 31


def test_maintenance_expiry_during_fetch_does_not_save_batch(tmp_path, monkeypatch):
    counts = ((DAY, 1),)
    with connection(tmp_path) as conn:
        _, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
        remote = FakeProd(approval, identity, counts, [native_row()])
        original = Cursor.fetchmany

        def expire(cursor, size):
            result = original(cursor, size)
            if cursor.named:
                monkeypatch.setattr(
                    source, "_now", lambda: approval.source_maintenance_end
                )
            return result

        monkeypatch.setattr(Cursor, "fetchmany", expire)
        with pytest.raises(ValueError, match="维护窗口"):
            execute(
                conn,
                staging,
                approval,
                remote,
                callback=lambda _: pytest.fail("expired callback"),
            )
        assert not list(
            records.operation_root(staging, approval).rglob("fragment-*.parquet")
        )
        assert not list(
            records.operation_root(staging, approval).rglob("source-complete.json")
        )
        assert remote.closes == ["named", "control", "rollback", "connection"]
