from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import duckdb
import pytest

from orchestrator.defs.asset_guards import dc_board_source_freeze as freeze
from orchestrator.defs.asset_guards.dc_board_lake_readiness import (
    batch_raw_dc_daily_lake_readiness,
)
from orchestrator.defs.asset_guards.dc_board_raw_quality import RAW_DC_DAILY_QUALITY
from orchestrator.defs.asset_guards.dc_board_silver_lake_readiness import (
    batch_silver_dc_daily_lake_readiness,
)
from orchestrator.defs.asset_guards.dc_board_silver_quality import (
    SILVER_DC_DAILY_QUALITY,
)
from orchestrator.defs.assets.dc_board import (
    write_dc_daily_partition,
    write_dc_index_partition,
    write_dc_member_partition,
)
from orchestrator.defs.assets.dc_board_silver import (
    write_silver_dc_daily_partition,
    write_silver_dc_index_partition,
    write_silver_dc_member_partition,
)
from orchestrator.defs.checks.dc_board_checks import _core_check as raw_check
from orchestrator.defs.checks.dc_board_silver_checks import _core_check as silver_check
from orchestrator.defs.paths import raw_dc_daily_path, raw_dc_member_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.dc_board import (
    build_dc_board_prod_completion_snapshot,
)
from tests.dc_board_quote_test_support import prod_result
from tests.test_dc_board_quote_coverage import (
    IsolatedDuckDB,
    write_calendar,
    write_history,
)
from tests.test_dc_board_raw_io import (
    _completion,
    _FakeTushare,
    _full_response,
    _index_row,
    _member_row,
    _test_policy,
)

DAY = "2026-07-14"


def test_waiting_quote_is_preserved_and_raw_silver_core_metadata_agree(tmp_path, monkeypatch):
    resource = IsolatedDuckDB()
    write_calendar(tmp_path, ["2026-07-13", DAY])
    write_history(tmp_path, "2026-07-13")
    base = _completion()
    completion = build_dc_board_prod_completion_snapshot(trade_date=DAY,
        index_identity=(*base.index_identity, ("概念板块", "BK1754.DC")),
        daily_identity=base.daily_identity, member_codes=(*base.member_codes, "BK1754.DC"), member_row_count=4)
    monkeypatch.setattr(freeze, "load_prod_dc_board_reference_snapshot", lambda **_: prod_result(completion))
    def response(api, params, fields):
        if api == "dc_member":
            return [_member_row(params["ts_code"])]
        rows = _full_response(api, params, fields)
        if api == "dc_index" and params["idx_type"] == "概念板块":
            rows.append(_index_row("概念板块", "BK1754.DC"))
        return rows
    source = _FakeTushare(response)
    monkeypatch.setattr("orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs",
                        lambda **_: tuple((code, "000001.SZ") for code in completion.member_codes))
    # Real complete fake-source fetches, not fabricated writer permission.
    for dataset, writer in (("dc_index", write_dc_index_partition), ("dc_daily", write_dc_daily_partition),
                            ("dc_member", write_dc_member_partition)):
        asset = f"raw_tushare_{dataset}"
        moment = datetime.now(timezone.utc)
        first = freeze.observe_dc_board_source(lake_root=tmp_path, duckdb_resource=resource,
            prod_postgres=object(), tushare=source, trade_date=DAY, policy=_test_policy(),
            now=lambda moment=moment: moment - timedelta(seconds=300))
        second = freeze.observe_dc_board_source(lake_root=tmp_path, duckdb_resource=resource,
            prod_postgres=object(), tushare=source, trade_date=DAY, policy=_test_policy(), now=lambda moment=moment: moment)
        proof = freeze.confirm_dc_board_source(second, asset_name=asset, prior=first.checkpoint(asset), now=moment)
        assert proof and proof.coverage_gap_count == 1
        kwargs = {"candidate_codes": completion.member_codes} if dataset == "dc_member" else {}
        result = writer(lake_root_path=tmp_path, duckdb_resource=resource, tushare=source,
            prod_postgres=object(), partition_key=DAY, source_snapshot_config=proof, policy=_test_policy(), **kwargs)
        assert result.written_row_count == (3 if dataset == "dc_daily" else 4)
    with duckdb.connect(":memory:") as connection:
        assert connection.execute("SELECT count(*) FROM read_parquet(?, hive_partitioning=false) WHERE ts_code='BK1754.DC'",
                                  [str(raw_dc_daily_path(tmp_path, DAY))]).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM read_parquet(?, hive_partitioning=false) WHERE ts_code='BK1754.DC'",
                                  [str(raw_dc_member_path(tmp_path, DAY))]).fetchone()[0] == 1
    for writer in (write_silver_dc_index_partition, write_silver_dc_daily_partition, write_silver_dc_member_partition):
        writer(duckdb=resource, lake_root_path=tmp_path, partition_key=DAY)
    context = SimpleNamespace(partition_keys=(DAY,))
    raw = RAW_DC_DAILY_QUALITY
    raw_result = raw_check(context=context, lake_root=LakeRootResource(root_path=str(tmp_path)),
        duckdb_resource=resource, dataset="dc_daily", path_builder=raw.path_builder, schema=raw.schema,
        key_columns=raw.key_columns, identity_predicate=raw.identity_condition,
        identity_columns=raw.key_columns, numeric_predicate=raw.numeric_condition,
        coverage_column=raw.coverage_column, coverage_values=raw.coverage_values, relation_mode="index_subset_daily")
    silver = SILVER_DC_DAILY_QUALITY
    silver_result = silver_check(context=context, lake_root=LakeRootResource(root_path=str(tmp_path)),
        duckdb_resource=resource, path_builder=silver.path_builder, schema=silver.schema, key_columns=silver.key_columns,
        identity_condition=silver.identity_condition, numeric_condition=silver.numeric_condition, relation_mode="index_subset_daily")
    for result in (raw_result, silver_result):
        assert result.passed
        assert result.metadata["goldenshare/failed_row_count"].value == 0
        assert result.metadata["goldenshare/awaiting_count"].value == 1
        assert result.metadata["goldenshare/index_code_count"].value == 4
        assert result.metadata["goldenshare/daily_code_count"].value == 3
        assert result.metadata["goldenshare/source_confirmation"].value == "not_evaluated"
        sample = result.metadata["goldenshare/quote_coverage_samples"].value[0]
        assert sample["ts_code"] == "BK1754.DC" and sample["name"] == "板块一"
    with resource.connect() as connection:
        for reader in (batch_raw_dc_daily_lake_readiness, batch_silver_dc_daily_lake_readiness):
            status = reader(connection=connection, lake_root=tmp_path, expected_trade_dates=(DAY,),
                            registered_trade_days=(DAY,), duckdb_resource=resource).statuses_by_trade_date[DAY]
            assert status.ready and status.summary["awaiting_count"] == 1
    # The same physical day becomes blocked as soon as a prior trusted quote exists.
    write_history(tmp_path, "2026-07-13", ("BK0001.DC", "BK1754.DC"))
    with resource.connect() as connection:
        for reader in (batch_raw_dc_daily_lake_readiness, batch_silver_dc_daily_lake_readiness):
            status = reader(connection=connection, lake_root=tmp_path, expected_trade_dates=(DAY,),
                            registered_trade_days=(DAY,), duckdb_resource=resource).statuses_by_trade_date[DAY]
            assert not status.ready and status.summary["previously_observed_missing_count"] == 1


def test_member_terminal_source_drift_does_not_replace_target(tmp_path, monkeypatch):
    from tests.dc_board_quote_test_support import source_proof
    from tests.test_dc_board_raw_io import _source_result
    from tests.test_dc_board_source_freeze import START, observation
    frozen = observation(START - timedelta(days=1))
    proof = source_proof(_completion(), _source_result(), "raw_tushare_dc_member")
    calls = [0]
    def validate(**_):
        calls[0] += 1
        if calls[0] == 2:
            raise ValueError("source/history changed after freeze")
        return frozen
    monkeypatch.setattr("orchestrator.defs.assets.dc_board.revalidate_dc_board_source", validate)
    monkeypatch.setattr("orchestrator.defs.assets.dc_board.load_prod_dc_member_pairs", lambda **_: (("BK0001.DC", "000001.SZ"),))
    target = raw_dc_member_path(tmp_path, DAY)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing")
    with pytest.raises(ValueError, match="changed after freeze"):
        write_dc_member_partition(lake_root_path=tmp_path, duckdb_resource=IsolatedDuckDB(),
            prod_postgres=object(), tushare=_FakeTushare(lambda _, params, __: [_member_row(params["ts_code"])]),
            partition_key=DAY, candidate_codes=("BK0001.DC",), source_snapshot_config=proof, policy=_test_policy())
    assert target.read_bytes() == b"existing"
