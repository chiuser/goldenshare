import json
from pathlib import Path

import dagster as dg
import pandas as pd
import pytest
from pydantic import ValidationError

from orchestrator.defs.assets import stock_weekly as assets
from orchestrator.defs.checks import stock_weekly_checks as checks
from orchestrator.defs.jobs import stock_weekly as jobs
from orchestrator.defs.partitions import cn_a_stock_week_ends
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.configs import StockWeeklyRawConfig
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_asset_key,
    weekly_check_names,
    weekly_column_specs,
    weekly_job_name,
)
from orchestrator.defs.stock_weekly_point import deliver_stock_weekly_point

from .stock_weekly_capture_test_support import alternate_frame, prod_frame

SOURCES = tuple(StockWeeklySource)


def frame_for(source):
    if source is StockWeeklySource.ALTERNATE_WEEKLY:
        return alternate_frame()
    frame = prod_frame()
    for name, _, _ in weekly_column_specs(source):
        if name not in frame:
            frame[name] = "12.0001"
    return frame[[n for n, _, _ in weekly_column_specs(source)]]


def bind_delivery(monkeypatch, tmp_path, source, frame=None):
    calls = []
    frame = frame if frame is not None else frame_for(source)

    def fetch(worker, params, fields, max_rows, budget, cancel, *args):
        calls.append(params)
        return frame.copy()

    real = deliver_stock_weekly_point

    def deliver(*args, **kwargs):
        kwargs["staging_root"] = tmp_path / "staging"
        kwargs["fetch"] = fetch
        return real(*args, **kwargs)

    monkeypatch.setattr(assets, "deliver_stock_weekly_point", deliver)
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    return calls


def definition_for(tmp_path, source):
    asset = getattr(assets, weekly_asset_key(source))
    check_defs = [getattr(checks, n) for n in weekly_check_names(source)]
    job = getattr(jobs, weekly_job_name(source))
    definitions = dg.Definitions(
        assets=[asset],
        asset_checks=check_defs,
        jobs=[job],
        resources={
            "lake_root": LakeRootResource(root_path=str(tmp_path / "lake")),
            "tushare": TushareResource(token="offline-test"),
        },
    )
    return definitions, asset, check_defs


@pytest.mark.parametrize("source", SOURCES)
def test_actual_job_check_events_and_execution_partition(tmp_path, monkeypatch, source):
    calls = bind_delivery(monkeypatch, tmp_path, source)
    definitions, asset, check_defs = definition_for(tmp_path, source)
    codes = tmp_path / "codes.csv"
    codes.write_text("ts_code\n000005.SZ\n")
    config = (
        {"code_list_path": str(codes)}
        if source is StockWeeklySource.ALTERNATE_WEEKLY
        else {}
    )
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(cn_a_stock_week_ends.name, ["2020-02-28"])
        job = definitions.resolve_job_def(weekly_job_name(source))
        result = job.execute_in_process(
            instance=instance,
            partition_key="2020-02-28",
            run_config={"ops": {weekly_asset_key(source): {"config": config}}},
        )
        assert result.success
        evaluations = [
            e.event_specific_data
            for e in result.all_events
            if e.event_type_value == "ASSET_CHECK_EVALUATION"
        ]
        assert len(evaluations) == 3
        assert all(e.passed and e.partition == "2020-02-28" for e in evaluations)
        for name in weekly_check_names(source):
            history = instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(asset.key, name), limit=1
            )
            assert history[0].partition == "2020-02-28"
        assert job.asset_layer.executable_asset_keys == {asset.key}
        assert all(c.partitions_def == cn_a_stock_week_ends for c in check_defs)
    assert len(calls) == 1
    if source is StockWeeklySource.ALTERNATE_WEEKLY:
        assert calls[0] == {
            "ts_code": "000005.SZ",
            "start_date": "20200224",
            "end_date": "20200301",
        }
    else:
        assert calls[0] == {
            "trade_date": "20200228",
            "freq": "week",
            "limit": 6000,
            "offset": 0,
        }
    payload = json.loads(next((tmp_path / "staging").rglob("audit.json")).read_text())
    assert payload["stats"]["candidate_rows"] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"write_mode": "force"},
        {"force": True},
        {"fields": ["close"]},
        {"limit": 1},
        {"offset": 1},
    ],
)
def test_typed_config_forbids_force_and_source_fields(kwargs):
    with pytest.raises(ValidationError):
        StockWeeklyRawConfig(**kwargs)


def test_primary_code_filter_rejected_before_source(tmp_path):
    with pytest.raises(Exception, match="primary_code_list_forbidden"):
        deliver_stock_weekly_point(
            SOURCES[0],
            "2020-02-28",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "stage",
            worker=None,
            code_list_path=str(tmp_path / "codes.csv"),
        )
    assert not (tmp_path / "stage").exists()


def test_delivery_evidence_missing_is_not_green(tmp_path, monkeypatch):
    source = SOURCES[0]
    bind_delivery(monkeypatch, tmp_path, source)
    definitions, _asset, _ = definition_for(tmp_path, source)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(cn_a_stock_week_ends.name, ["2020-02-28"])
        result = definitions.resolve_job_def(
            weekly_job_name(source)
        ).execute_in_process(instance=instance, partition_key="2020-02-28")
        assert result.success
    audit = next((tmp_path / "staging").rglob("audit.json"))
    payload = json.loads(audit.read_text())
    evidence = next(
        i for i in payload["source_evidence"] if i["path"].endswith("receipt.json")
    )
    Path(evidence["path"]).write_text("changed")
    with pytest.raises(Exception, match="delivery_evidence_changed"):
        checks.audit_weekly_file(
            source,
            "2020-02-28",
            tmp_path / "lake",
            delivery={"audit_path": str(audit), "audit_hash": payload["audit_hash"]},
        )


def test_existing_identical_replay_and_conflict(tmp_path):
    source = SOURCES[0]
    frame = frame_for(source)

    def fetch(*args):
        return frame.copy()

    first = deliver_stock_weekly_point(
        source,
        "2020-02-28",
        target_root=tmp_path / "lake",
        staging_root=tmp_path / "stage",
        worker=None,
        fetch=fetch,
    )
    second = deliver_stock_weekly_point(
        source,
        "2020-02-28",
        target_root=tmp_path / "lake",
        staging_root=tmp_path / "stage",
        worker=None,
        fetch=fetch,
    )
    assert first["rows"] == second["rows"] == 1
    before = Path(first["path"]).read_bytes()
    frame["close"] = "2.0000"
    with pytest.raises(Exception, match="raw_duplicate_key"):
        deliver_stock_weekly_point(
            source,
            "2020-02-28",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "stage",
            worker=None,
            fetch=fetch,
        )
    assert Path(first["path"]).read_bytes() == before


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("empty", "point_source_empty"),
        ("other_week", "source_week_mismatch"),
        ("duplicate", "source_duplicate_key"),
    ],
)
def test_invalid_point_delivery_never_promotes(tmp_path, mode, reason):
    frame = frame_for(SOURCES[0])
    if mode == "empty":
        frame = frame.iloc[:0]
    elif mode == "other_week":
        frame["trade_date"] = "20200221"
    else:
        frame = pd.concat([frame, frame], ignore_index=True)
    with pytest.raises(Exception, match=reason):
        deliver_stock_weekly_point(
            SOURCES[0],
            "2020-02-28",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "stage",
            worker=None,
            fetch=lambda *args: frame,
        )
    assert not list((tmp_path / "lake").rglob("*.parquet"))


def test_page_requests_offset_and_repeat_rejected(tmp_path, monkeypatch):
    from orchestrator.defs import stock_weekly_point as point
    from orchestrator.defs.run_contracts.stock_weekly import StockWeeklyPointPolicy

    monkeypatch.setattr(
        point,
        "StockWeeklyPointPolicy",
        lambda: StockWeeklyPointPolicy(page_limit=1, page_call_cap=3),
    )
    calls = []
    frame = frame_for(SOURCES[0])

    def fetch(worker, params, *args):
        calls.append(params.copy())
        return frame.copy() if len(calls) < 3 else frame.iloc[:0]

    with pytest.raises(Exception, match="raw_duplicate_key"):
        deliver_stock_weekly_point(
            SOURCES[0],
            "2020-02-28",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "stage",
            worker=None,
            fetch=fetch,
        )
    assert [p["offset"] for p in calls] == [0, 1, 2]
    assert all(p["freq"] == "week" and p["trade_date"] == "20200228" for p in calls)
    assert not list((tmp_path / "lake").rglob("*.parquet"))


def test_page_cap_and_code_cap_fail_closed(tmp_path, monkeypatch):
    from orchestrator.defs import stock_weekly_point as point
    from orchestrator.defs.run_contracts.stock_weekly import StockWeeklyPointPolicy

    monkeypatch.setattr(
        point,
        "StockWeeklyPointPolicy",
        lambda: StockWeeklyPointPolicy(page_limit=1, page_call_cap=1),
    )
    with pytest.raises(Exception, match="point_page_cap_exceeded"):
        deliver_stock_weekly_point(
            SOURCES[0],
            "2020-02-28",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "stage",
            worker=None,
            fetch=lambda *args: frame_for(SOURCES[0]),
        )
    codes = tmp_path / "codes.csv"
    codes.write_text("ts_code\n" + "\n".join(f"{i:06d}.SZ" for i in range(1, 22)))
    with pytest.raises(Exception, match="code_list"):
        deliver_stock_weekly_point(
            StockWeeklySource.ALTERNATE_WEEKLY,
            "2020-02-28",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "other-stage",
            worker=None,
            code_list_path=str(codes),
        )
    assert not (tmp_path / "other-stage").exists()


def test_source_columns_invalid_no_promotion(tmp_path):
    frame = frame_for(SOURCES[0]).drop(columns="freq")
    with pytest.raises(Exception, match="source_schema_mismatch"):
        deliver_stock_weekly_point(
            SOURCES[0],
            "2020-02-28",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "stage",
            worker=None,
            fetch=lambda *args: frame,
        )
    assert not list((tmp_path / "lake").rglob("*.parquet"))
