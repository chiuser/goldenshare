"""四来源字段传输、四候选、2N原生事件；全部来源和instance均隔离。"""

from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.bootstrap import index_period_history as history
from orchestrator.defs.bootstrap import index_period_history_cli as cli
from orchestrator.defs.io import index_period_writer as writer
from tests.index_period_test_support import silver_inputs
from tests.test_index_period_contracts import EXPECTED_CODES, row
from tests.test_index_period_writer import read


class SyntheticProd:
    """替换网络与PG；字段顺序来自B只读投影，行情为明确的人工样本。"""

    def __init__(
        self, as_of=date(2026, 7, 2), *,
        serving_vol="12345.6789", serving_amount="98765.4321",
    ):
        self.queries = []
        self.batch_sizes = []
        self.as_of = as_of
        self.serving_vol = serving_vol
        self.serving_amount = serving_amount

    @contextmanager
    def connect_readonly_transaction(self):
        yield self

    @contextmanager
    def cursor(self, *, name):
        owner = self

        class Cursor:
            itersize = 2  # 人工小批次，只用于证明实际fetchmany边界。

            def execute(self, sql, parameters):
                owner.queries.append((sql, parameters))
                weekly = "index_weekly" in sql
                prior = date(2026, 6, 26) if weekly else date(2026, 6, 30)
                self.rows = []
                if "raw_tushare" in sql:
                    self.rows = [
                        row(c, prior.strftime("%Y%m%d"))
                        for c in EXPECTED_CODES
                        if c != "899050.BJ"
                    ]
                else:
                    for day in (prior, owner.as_of):
                        start = (
                            date(2026, 6, 22)
                            if weekly and day == prior
                            else date(2026, 6, 29)
                            if weekly
                            else date(day.year, day.month, 1)
                        )
                        for code in EXPECTED_CODES:
                            if code != "000680.SH":
                                self.rows.append(
                                    (
                                        code,
                                        start,
                                        day,
                                        *map(
                                            Decimal,
                                            (
                                                "100",
                                                "109",
                                                "98",
                                                "104",
                                                "0",
                                                "4",
                                                "0.0123",
                                                owner.serving_vol,
                                                owner.serving_amount,
                                            ),
                                        ),
                                    )
                                )

            def fetchmany(self, size):
                owner.batch_sizes.append(size)
                result, self.rows = self.rows[:size], self.rows[size:]
                return result

        yield Cursor()


class TemporaryDuckDB:
    @contextmanager
    def connect(self):
        with duckdb.connect() as connection:
            yield connection


@pytest.mark.parametrize("layer", ["raw", "serving"])
def test_prod_load_preserves_large_decimal_outside_pandas_type_sample(layer):
    # 字段顺序／类型依据Prod投影；人工周期日期只用于搬运，不验收交易日历。
    # DuckDB 1.5.2默认取样1000；2000行中的索引1001不在该类型样本内。
    fields = (
        ("ts_code", "trade_date", "close", "open", "high", "low", "pre_close",
         "change", "pct_chg", "vol", "amount")
        if layer == "raw" else
        ("ts_code", "period_start_date", "trade_date", "open", "high", "low",
         "close", "pre_close", "change_amount", "pct_chg", "vol", "amount")
    )
    rows = []
    for index in range(2000):
        day = (date(1991, 7, 19) if index < 1000 else date(1995, 1, 27)) + timedelta(weeks=index % 1000)
        values = {
            "ts_code": "000001.SH" if index < 1000 else "399001.SZ",
            "period_start_date": day - timedelta(days=4),
            "trade_date": day.strftime("%Y%m%d") if layer == "raw" else day,
            **dict(zip(
                ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
                map(Decimal, ("100.0000", "109.0000", "98.0000", "104.0000", "100.0000", "4.0000", "0.0400", "12345.6789", "98765.4321")),
                strict=True,
            )),
        }
        if index == 1001:
            values.update(zip(
                ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"),
                map(Decimal, ("1000.0000", "1100.0000", "990.0000", "1011.3470", "1000.0000", "11.3470", "0.0113", "9999999999999999.9999", "9999999999999999.9999")),
                strict=True,
            ))
        values["change_amount"] = values["change"]
        rows.append(tuple(values[name] for name in fields))

    class Source(SyntheticProd):
        @contextmanager
        def cursor(self, *, name):
            batches = iter((rows, []))

            class Cursor:
                itersize = 2000

                def execute(self, sql, parameters):
                    pass

                def fetchmany(self, size):
                    assert size == 2000
                    return next(batches)

            yield Cursor()

    with duckdb.connect() as connection:
        relation, count = history.load_prod_index_period_relation(
            connection, Source(), writer.INDEX_WEEKLY, layer
        )
        assert count == 2000
        assert connection.execute(
            f'SELECT "close",vol,amount FROM {relation} WHERE "close"=1011.3470'
        ).fetchall() == [
            (Decimal("1011.3470"), Decimal("9999999999999999.9999"), Decimal("9999999999999999.9999"))
        ]
        assert connection.execute(
            f'SELECT count(*) FROM {relation} WHERE "close"=104.0000'
        ).fetchone()[0] == 1999


def apply(tmp_path, instance, source, operation="bootstrap"):
    return history.bootstrap_index_period_history(
        duckdb=TemporaryDuckDB(),
        prod_postgres=source,
        lake_root=tmp_path / "lake",
        staging_root=tmp_path / "staging",
        operation_id=operation,
        instance=instance,
    )


@pytest.mark.parametrize("period", [writer.INDEX_WEEKLY, history.INDEX_MONTHLY])
def test_prod_serving_load_preserves_source_schema_and_units(period):
    # 完整来源类型依据当前Prod周／月Serving模型；不使用DG目标schema生成预期。
    with duckdb.connect() as connection:
        relation, count = history.load_prod_index_period_relation(
            connection, SyntheticProd(), period, "serving"
        )
        assert count == 20
        assert tuple(
            (r[0], r[1]) for r in connection.execute(f"DESCRIBE {relation}").fetchall()
        ) == (
            ("ts_code", "VARCHAR"),
            ("period_start_date", "DATE"),
            ("trade_date", "DATE"),
            ("open", "DECIMAL(18,4)"),
            ("high", "DECIMAL(18,4)"),
            ("low", "DECIMAL(18,4)"),
            ("close", "DECIMAL(18,4)"),
            ("pre_close", "DECIMAL(18,4)"),
            ("change_amount", "DECIMAL(18,4)"),
            ("pct_chg", "DECIMAL(10,4)"),
            ("vol", "DECIMAL(20,4)"),
            ("amount", "DECIMAL(20,4)"),
        )
        assert connection.execute(
            f"SELECT DISTINCT pct_chg,vol,amount FROM {relation}"
        ).fetchall() == [
            (Decimal("0.0123"), Decimal("12345.6789"), Decimal("98765.4321"))
        ]


@pytest.mark.parametrize(
    "source_vol,source_amount,expected_vol,expected_amount",
    [
        ("12345.6789", "98765.4321", "123.456789", "98.7654321"),
        (
            "12345.6789", "10000000000000.4321",
            "123.456789", "10000000000.0004321",
        ),
        (
            "100000000000000.6789", "10000000000000.0000",
            "1000000000000.006789", "10000000000.0000000",
        ),
        (
            "9999999999999999.9999", "9999999999999999.9999",
            "99999999999999.999999", "9999999999999.9999999",
        ),
    ],
    ids=("ordinary", "large-amount-fraction", "large-volume", "source-maximum"),
)
def test_bootstrap_four_files_units_sources_and_native_partitions(
    tmp_path, monkeypatch, source_vol, source_amount, expected_vol, expected_amount
):
    # Prod Numeric(20,4)为16位整数、4位小数；精度上限样本不代表真实市场成交额。
    # 归一化预期为独立字面值：股除100、元除1000，保留新增的小数位。
    silver_inputs(tmp_path / "lake")
    monkeypatch.setattr(
        writer.TushareDownloader, "load", lambda: pytest.fail("初始化不请求Tushare")
    )
    source = SyntheticProd(serving_vol=source_vol, serving_amount=source_amount)
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        fetch = instance.fetch_materializations
        queries = []

        def counted(*args, **kwargs):
            queries.append((args, kwargs))
            return fetch(*args, **kwargs)

        monkeypatch.setattr(instance, "fetch_materializations", counted)
        result = apply(tmp_path, instance, source)
        first_run = result.pop("run_id")
        assert instance.get_run_by_id(first_run).status == dg.DagsterRunStatus.SUCCESS
        assert result == {
            "files": 4,
            "partitions": 6,
            "events": 12,
            "file_rows": {
                "raw_index_weekly": 10,
                "silver_index_weekly": 22,
                "raw_index_monthly": 10,
                "silver_index_monthly": 22,
            },
        }
        assert len(queries) == 4
        assert len(source.queries) == 4 and set(source.batch_sizes) == {2}
        assert [len(parameters[0]) for _, parameters in source.queries] == [
            11,
            10,
            11,
            10,
        ]
        assert instance.get_dynamic_partitions("cn_a_index_week_ends") == [
            "2026-06-26",
            "2026-07-03",
        ]
        assert instance.get_dynamic_partitions("cn_a_index_months") == [
            "2026-06",
            "2026-07",
        ]
        for period in (writer.INDEX_WEEKLY, history.INDEX_MONTHLY):
            path = writer.index_period_path(tmp_path / "lake", period, "silver")
            rows = read(path)
            accepted = next(r for r in rows if r[0] == "000001.SH")
            assert accepted[7] == 0  # 不重算／拒绝Serving的已接受首期零前收盘。
            assert accepted[9:] == (
                Decimal("1.2300"),
                Decimal(expected_vol),
                Decimal(expected_amount),
            )
            current = next(
                r for r in rows if r[0] == "000680.SH" and r[2] == date(2026, 7, 2)
            )
            assert current[3:] == tuple(
                map(
                    Decimal,
                    (
                        "100",
                        "108",
                        "98",
                        "106",
                        "100",
                        "6",
                        "6",
                        "300.3601",
                        "501.2467",
                    ),
                )
            )
            for layer in ("raw", "silver"):
                asset = getattr(period, layer + "_asset")
                check = getattr(period, layer + "_check")
                mats = instance.fetch_materializations(
                    dg.AssetKey(asset), limit=10
                ).records
                evaluations = (
                    instance.event_log_storage.get_asset_check_execution_history(
                        dg.AssetCheckKey(dg.AssetKey(asset), check), limit=10
                    )
                )
                assert len(mats) == len(evaluations) == (1 if layer == "raw" else 2)
                by_id = {record.storage_id: record for record in mats}
                assert all(
                    record.asset_materialization.metadata["goldenshare/units"].value
                    == ("股／元／比例" if layer == "raw" else "手／千元／百分数")
                    for record in mats
                )
                assert all(
                    record.asset_materialization.metadata[
                        "goldenshare/source_method"
                    ].value
                    == "index_period_bootstrap"
                    for record in mats
                )
                for record in evaluations:
                    evaluation = record.evaluation
                    assert evaluation.passed and evaluation.blocking
                    assert record.run_id == first_run
                    target = by_id[evaluation.target_materialization_data.storage_id]
                    assert (
                        target.partition_key == record.partition == evaluation.partition
                    )
        previous = {
            p: read(p)
            for p in (tmp_path / "lake").glob("*/index_*/full/part-000.parquet")
            if "index_basic" not in p.parts
        }
        again = apply(
            tmp_path, instance,
            SyntheticProd(serving_vol=source_vol, serving_amount=source_amount),
            "replay",
        )
        second_run = again.pop("run_id")
        assert first_run != second_run
        assert instance.get_run_by_id(second_run).status == dg.DagsterRunStatus.SUCCESS
        assert again == result
        assert all(read(path) == rows for path, rows in previous.items())


@pytest.mark.parametrize("failure", ["missing_daily", "last_candidate"])
def test_bootstrap_failure_never_promotes_incomplete_candidates(
    tmp_path, monkeypatch, failure
):
    root = tmp_path / "lake"
    silver_inputs(root)
    targets = []
    for period in (writer.INDEX_WEEKLY, history.INDEX_MONTHLY):
        for layer in ("raw", "silver"):
            target = writer.index_period_path(root, period, layer)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"existing untouched file")
            targets.append(target)
    if failure == "missing_daily":
        from orchestrator.defs.paths import silver_index_daily_path

        silver_index_daily_path(root, "2026-07-02").unlink()
    else:
        original = writer.copy_query_to_parquet

        def broken(sql, path):
            if "silver" in path.parts and "index_monthly" in path.parts:
                sql = f"SELECT *,1 extra FROM ({sql})"
            return original(sql, path)

        monkeypatch.setattr(writer, "copy_query_to_parquet", broken)
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        with pytest.raises((ValueError, writer.IndexPeriodContractError)):
            apply(tmp_path, instance, SyntheticProd())
        assert all(path.read_bytes() == b"existing untouched file" for path in targets)
        assert instance.get_dynamic_partitions("cn_a_index_months") == []


def test_bootstrap_event_failure_preserves_files_and_manual_retry(
    tmp_path, monkeypatch
):
    silver_inputs(tmp_path / "lake")
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        original = dg.OpExecutionContext.log_event

        def interrupted(context, event):
            if isinstance(event, dg.AssetCheckEvaluation):
                raise RuntimeError("模拟事件写入中断")  # noqa: TRY004 - injected write failure, not type validation.
            return original(context, event)

        with monkeypatch.context() as patch:
            patch.setattr(dg.OpExecutionContext, "log_event", interrupted)
            with pytest.raises(RuntimeError, match="中断"):
                apply(tmp_path, instance, SyntheticProd())
        assert instance.get_runs()[0].status == dg.DagsterRunStatus.FAILURE
        paths = [
            writer.index_period_path(tmp_path / "lake", p, layer)
            for p in (writer.INDEX_WEEKLY, history.INDEX_MONTHLY)
            for layer in ("raw", "silver")
        ]
        assert all(path.is_file() for path in paths)
        assert (
            apply(tmp_path, instance, SyntheticProd(), "manual-retry")["events"] == 12
        )


def test_bootstrap_cli_default_does_not_construct_resources(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("默认入口不得构造资源、访问来源或写入")

    monkeypatch.setattr(cli, "bootstrap_index_period_history", forbidden)
    monkeypatch.setattr(cli, "LakeRootResource", forbidden)
    monkeypatch.setattr(cli.dg.DagsterInstance, "get", forbidden)
    assert cli.main(["--operation-id", "review"]) == 0
    assert '"apply": false' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["--operation-id", "../escape"])
    with pytest.raises(SystemExit):
        cli.main(["--operation-id", "review", "--lake-root", "old_lake"])
