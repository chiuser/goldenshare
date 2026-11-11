"""Real period Raw -> native records -> Silver jobs on isolated files and instance.

Only HTTP and upstream acceptance are replaced. Lifecycle/identity/suspension
fixtures project the actual producer columns used here (DATE, BOOLEAN, VARCHAR).
The literal 21-column wire fixture in test_stock_period_silver_contracts follows
doc365; expected prices and code sets below are independent literals. This does
not claim to test the upstream lifecycle/suspension producers or real HTTP.
"""

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace as NS

import dagster as dg
import pytest
from dagster._core.events import DagsterEventType

from orchestrator.defs import (
    paths,
    stock_period_silver,
    stock_period_source,
    stock_period_update,
)
from orchestrator.defs.asset_guards.stock_period_delivery import (
    read_completion,
    silver_completion_consumed,
)
from orchestrator.defs.assets.stock_monthly import (
    raw_tushare_stk_period_bar_adj_month,
    silver_stock_monthly,
)
from orchestrator.defs.assets.stock_weekly import (
    raw_tushare_stk_period_bar_adj_week,
    silver_stock_weekly,
)
from orchestrator.defs.checks import (
    stock_monthly_checks,
    stock_period_silver_checks,
    stock_weekly_checks,
)
from orchestrator.defs.io.stock_period_raw import connection, execute, file_digest
from orchestrator.defs.io.stock_period_raw import target_path as raw_path
from orchestrator.defs.jobs.stock_monthly import (
    raw_stk_period_bar_adj_month_update_job,
    silver_stock_monthly_update_job,
)
from orchestrator.defs.jobs.stock_weekly import (
    raw_stk_period_bar_adj_week_update_job,
    silver_stock_weekly_update_job,
)
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.stock_period import FIELDS
from orchestrator.defs.run_contracts.stock_period_delivery import (
    COMPLETION_KEY,
    WORK_KEY,
)
from orchestrator.defs.run_contracts.stock_period_silver import check_names, target_path
from orchestrator.defs.source_readiness.stock_period import load_period_universe
from tests.test_stock_period_silver_contracts import literal_row, write_raw

A, S, N, I = "000001.SZ", "000002.SZ", "301393.SZ", "000003.SZ"
D = "2026-11-10"
NOW = datetime.fromisoformat("2026-11-10T20:00:00+08:00")


@pytest.fixture
def market(tmp_path, monkeypatch):
    (tmp_path / "instance").mkdir()
    root, staging = tmp_path / "lake", tmp_path / "staging"
    for part in ("raw", "silver", "gold"):
        (root / part).mkdir(parents=True)
    staging.mkdir()
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(
        stock_period_silver_checks, "DEFAULT_LAKE_STAGING_ROOT", str(staging)
    )
    lifecycle = paths.silver_stock_lifecycle_path(root)
    identity = paths.silver_stock_identity_map_path(root)
    suspension = paths.silver_stock_suspend_daily_path(root, D)
    calendar = paths.silver_trade_calendar_path(root)
    for path in (lifecycle, identity, suspension, calendar):
        path.parent.mkdir(parents=True, exist_ok=True)
    with connection(tmp_path / "fixture") as con:
        con.execute(
            """COPY (SELECT * FROM (VALUES
            ('000001.SZ','L',DATE '1991-04-03',NULL::DATE,true),
            ('000002.SZ','L',DATE '1991-01-29',NULL::DATE,true),
            ('301393.SZ','L',DATE '2026-11-10',NULL::DATE,true),
            ('000003.SZ','L',DATE '1991-07-03',NULL::DATE,true),
            ('000004.SZ','D',DATE '1991-01-01',DATE '2026-11-10',true),
            ('000005.SZ','L',DATE '2026-11-11',NULL::DATE,true)
        ) v(ts_code,list_status,list_date,delist_date,is_cny_stock)) TO ? (FORMAT PARQUET)""",
            [str(lifecycle)],
        )
        execute(
            con,
            "COPY (SELECT ts_code source_ts_code,ts_code latest_ts_code,'confirmed' confidence FROM read_parquet(?)) TO ? (FORMAT PARQUET)",
            [str(lifecycle), str(identity)],
        )
        con.execute(
            """COPY (SELECT * FROM (VALUES
            ('000002.SZ',DATE '2026-11-10','S',NULL::VARCHAR),
            ('000003.SZ',DATE '2026-11-10','S','10:00-10:30')
        ) v(ts_code,trade_date,suspend_type,suspend_timing)) TO ? (FORMAT PARQUET)""",
            [str(suspension)],
        )
        con.execute(
            "COPY (SELECT 'SSE' exchange,DATE '2026-11-10' trade_date,true is_open,NULL::DATE pretrade_date) TO ? (FORMAT PARQUET)",
            [str(calendar)],
        )
    state = {
        "price": "11.0000",
        "missing": None,
        "calls": [],
        "instance": None,
        "include_s": False,
    }

    class Wire:
        def __init__(self, *, fields=FIELDS, **kwargs):
            self.fields = fields

        def __call__(self, params, *, deadline=None):
            assert set(params) == {"freq", "trade_date", "limit", "offset"}
            state["calls"].append((dict(params), tuple(self.fields)))
            freq = params["freq"]
            rows = [
                literal_row(
                    A, params["trade_date"], freq, asof="20261110", qfq=state["price"]
                ),
                literal_row(
                    N, params["trade_date"], freq, asof="20261110", qfq="12.0000"
                ),
                literal_row(
                    I, params["trade_date"], freq, asof="20261110", qfq="13.0000"
                ),
            ]
            if state["include_s"]:
                rows.append(
                    literal_row(
                        S, params["trade_date"], freq, asof="20261110", qfq="4.0000"
                    )
                )
            rows = [row for row in rows if row[0] != state["missing"]]
            if tuple(self.fields) == FIELDS and state["instance"] is not None:
                active = state["instance"].get_runs(
                    filters=dg.RunsFilter(statuses=[dg.DagsterRunStatus.STARTED]),
                    limit=1,
                )
                observations = (
                    state["instance"]
                    .get_records_for_run(
                        active[0].run_id, of_type=DagsterEventType.ASSET_OBSERVATION
                    )
                    .records
                )
                assert any(
                    WORK_KEY in record.asset_observation.metadata
                    for record in observations
                ), "write plan must persist before source/COPY"
            projection = [
                [row[FIELDS.index(field)] for field in self.fields] for row in rows
            ]
            return json.dumps(
                {"code": 0, "data": {"fields": list(self.fields), "items": projection}}
            ).encode()

    monkeypatch.setattr(stock_period_source, "HttpPage", Wire)
    # Separate tests below exercise acceptance gating. Here only the already
    # accepted upstream is replaced; all code/date calculation and file IO run.
    gate = stock_period_update._period_inputs_ready
    monkeypatch.setattr(stock_period_update, "_period_inputs_ready", lambda *args: None)
    resource = LakeRootResource(root_path=str(root))
    assets = [
        raw_tushare_stk_period_bar_adj_week,
        raw_tushare_stk_period_bar_adj_month,
        silver_stock_weekly,
        silver_stock_monthly,
    ]
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names as raw_names,
    )

    checks = [
        getattr(stock_weekly_checks if freq == "week" else stock_monthly_checks, name)
        for freq in ("week", "month")
        for name in raw_names(freq)
    ]
    checks += [
        getattr(stock_period_silver_checks, name)
        for freq in ("week", "month")
        for name in check_names(freq)
    ]
    definitions = dg.Definitions(
        assets=assets,
        asset_checks=checks,
        jobs=[
            raw_stk_period_bar_adj_week_update_job,
            raw_stk_period_bar_adj_month_update_job,
            silver_stock_weekly_update_job,
            silver_stock_monthly_update_job,
        ],
        resources={"lake_root": resource},
    )
    return NS(
        root=root,
        staging=staging,
        state=state,
        resource=resource,
        defs=definitions,
        tmp=tmp_path,
        gate=gate,
    )


def raw_job(market, instance, freq, *, raise_on_error=True):
    period = "2026-11-13" if freq == "week" else "2026-11"
    instance.add_dynamic_partitions(
        "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months", [period]
    )
    return market.defs.resolve_job_def(
        f"raw_stk_period_bar_adj_{freq}_update_job"
    ).execute_in_process(
        instance=instance,
        partition_key=period,
        raise_on_error=raise_on_error,
        run_config={
            "ops": {
                f"raw_tushare_stk_period_bar_adj_{freq}": {
                    "config": {"automatic_intent_date": D}
                }
            }
        },
    )


def reference_for(instance, run_id):
    records = instance.get_records_for_run(
        run_id, of_type=DagsterEventType.ASSET_OBSERVATION
    ).records
    completion = next(
        record.asset_observation.metadata[COMPLETION_KEY].value
        for record in records
        if COMPLETION_KEY in record.asset_observation.metadata
    )
    return {
        key: completion[key] for key in ("producer_run_id", "freq", "upstream_batch_id")
    }


def price_rows(market, path):
    with connection(market.tmp / "read") as con:
        return dict(
            con.execute(
                "SELECT ts_code,close_qfq FROM read_parquet(?,hive_partitioning=false)",
                [str(path)],
            ).fetchall()
        )


@pytest.mark.parametrize("freq", ["week", "month"])
def test_real_raw_to_native_silver_jobs_and_consumption(market, freq):
    period = "2026-11-13" if freq == "week" else "2026-11"
    label = "20261113" if freq == "week" else "20261130"
    prior = raw_path(market.root, freq, period)
    with connection(market.tmp / "prior") as con:
        write_raw(
            con,
            prior,
            [
                literal_row(A, label, freq, asof="20261109", qfq="8.0000"),
                literal_row(S, label, freq, asof="20261106", qfq="4.0000"),
            ],
        )
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        market.state["instance"] = instance
        result = raw_job(market, instance, freq)
        assert result.success and len(result.get_asset_check_evaluations()) == 3
        reference = reference_for(instance, result.run_id)
        assert reference["producer_run_id"] == result.run_id
        with dg.build_sensor_context(instance=instance, resources={"lake_root":market.resource}) as raw_context:
            assert not stock_period_update.evaluate_daily_sensor(raw_context,NOW,freq=freq).run_requests
        assert len(market.state["calls"]) == 1  # A manual successful run also prevents an automatic duplicate.
        origin = read_completion(instance, reference, root=market.root)
        assert sorted(origin["items"]) == [(freq, period)]
        assert price_rows(market, prior) == {
            A: Decimal(11),
            S: Decimal(4),
            N: Decimal(12),
            I: Decimal(13),
        }
        with dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}
        ) as ctx:
            response = stock_period_silver.evaluate_update_sensor(ctx, freq=freq)
            assert len(response.run_requests) == 1
            request = response.run_requests[0]
            assert set(
                request.run_config["ops"][
                    "silver_stock_weekly" if freq == "week" else "silver_stock_monthly"
                ]["config"]
            ) == {"intent", "source_completion"}
            cursor = ctx.cursor
        silver = market.defs.resolve_job_def(request.job_name).execute_in_process(
            instance=instance,
            partition_key=request.partition_key,
            run_config=request.run_config,
            tags={"dagster/run_key": request.run_key},
        )
        assert silver.success and len(silver.get_asset_check_evaluations()) == 3
        assert price_rows(market, target_path(market.root, freq, period)) == {
            A: Decimal(11),
            S: Decimal(4),
            N: Decimal(12),
            I: Decimal(13),
        }
        assert silver_completion_consumed(
            instance, reference, [period], root=market.root, business_date=D
        )
        with dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}, cursor=cursor
        ) as ctx:
            response = stock_period_silver.evaluate_update_sensor(ctx, freq=freq)
            assert not response.run_requests
            assert "pending" not in json.loads(ctx.cursor)
        assert len(market.state["calls"]) == 1
        assert market.state["calls"][0][0]["trade_date"] == label
        assert not [
            p
            for p in market.staging.rglob("*.json")
            if p.name
            in {
                "baseline.json",
                "daily.json",
                "manifest.json",
                "complete.json",
                "execution.json",
            }
        ]


def test_universe_date_effective_and_intraday_still_required(market):
    actual = load_period_universe(market.root, D, "week")
    assert actual["required"] == {A, N, I} and actual["optional"] == {S}
    assert not paths.silver_stock_daily_path(market.root, D).exists()


@pytest.mark.parametrize("freq", ["week", "month"])
def test_sensor_only_submits_after_exact_coverage_and_rechecks_later(market, freq):
    with (
        dg.DagsterInstance.ephemeral() as instance,
        dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}
        ) as ctx,
    ):
        market.state["missing"] = N
        assert not stock_period_update.evaluate_daily_sensor(
            ctx, NOW, freq=freq
        ).run_requests
        market.state["missing"] = None
        response = stock_period_update.evaluate_daily_sensor(ctx, NOW, freq=freq)
        assert len(response.run_requests) == 1
        request = response.run_requests[0]
        instance.create_run_for_job(
            market.defs.resolve_job_def(request.job_name),
            run_config=request.run_config,
            tags={"dagster/run_key": request.run_key},
        )
        count = len(market.state["calls"])
        assert not stock_period_update.evaluate_daily_sensor(
            ctx, NOW, freq=freq
        ).run_requests
        assert len(market.state["calls"]) == count
        assert all(
            fields == ("ts_code", "trade_date", "end_date")
            for _, fields in market.state["calls"]
        )


def test_formal_download_rechecks_coverage_before_replacement_and_reruns_fresh(market):
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        market.state["instance"] = instance
        first = raw_job(market, instance, "week")
        path = raw_path(market.root, "week", "2026-11-13")
        before = file_digest(path)
        market.state["missing"] = N
        failed = raw_job(market, instance, "week", raise_on_error=False)
        assert not failed.success and file_digest(path) == before
        market.state.update(missing=None, price="17.0000")
        second = raw_job(market, instance, "week")
        assert first.run_id != second.run_id and len(market.state["calls"]) == 3
        assert price_rows(market, path)[A] == Decimal(17)
        assert not raw_path(market.root, "month", "2026-11").exists()


def native_history_fixture(
    market,
    instance,
    *,
    skip_checks=False,
    periods=None,
    source_asof=D,
    price="5.0000",
    fault=None,
):
    """Tiny native multi-file producer, not the future factor repair implementation."""
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    from orchestrator.defs.asset_guards.stock_period_delivery import native_run_records
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names,
    )
    from orchestrator.defs.io.stock_period_raw import audit_file
    from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
    from orchestrator.defs.run_contracts.stock_period_delivery import (
        FILE_DELIVERY_KEY,
        delivery_completion,
        delivery_ref,
        delivery_work,
    )

    periods = periods or ["2026-11-06", "2026-11-13"]
    asset = dg.AssetKey("raw_tushare_stk_period_bar_adj_week")

    @dg.op(out={})
    def fixture_records(context):
        reference = delivery_ref(
            context.run_id, "week", "history_maintenance", D, periods
        )
        yield dg.AssetObservation(
            asset_key=asset,
            metadata={
                WORK_KEY: dg.MetadataValue.json(
                    delivery_work(
                        reference,
                        kind="history_maintenance",
                        business_date=D,
                        periods=periods,
                        stock_codes=[A],
                    )
                )
            },
        )
        for period in periods:
            with connection(market.tmp / "native_fixture") as con:
                rows = [
                    literal_row(
                        code,
                        period.replace("-", ""),
                        "week",
                        asof=source_asof.replace("-", ""),
                        qfq=quote,
                    )
                    for code, quote in [(A, price), (S, "4.0000"), (I, "13.0000")]
                ]
                if period == "2026-11-13":
                    rows.append(
                        literal_row(
                            N, "20261113", "week", asof="20261110", qfq="12.0000"
                        )
                    )
                write_raw(con, raw_path(market.root, "week", period), rows)
            facts = audit_file(market.root, "week", period)
            yield dg.AssetMaterialization(
                asset_key=asset,
                partition=period,
                metadata=build_materialization_metadata(
                    uri=str(raw_path(market.root, "week", period)),
                    row_count=facts["rows"],
                    observed_columns=FIELDS,
                    extra_metadata={
                        FILE_DELIVERY_KEY: dg.MetadataValue.json(reference),
                        "goldenshare/period_file_version": dg.MetadataValue.json(
                            facts["version"]
                        ),
                        "goldenshare/business_date": D,
                        "goldenshare/source_asof": (
                            None
                            if fault == "missing_asof"
                            else "2099-01-01"
                            if fault == "future_asof"
                            else source_asof
                        ),
                        "goldenshare/rewritten": True,
                    },
                ),
            )
        mats = {
            record.asset_materialization.partition: record
            for record in native_run_records(
                instance, [context.run_id], ["ASSET_MATERIALIZATION"]
            )
        }
        if not skip_checks:
            for period in periods:
                mat = mats[period]
                for name in raw_check_names("week"):
                    yield AssetCheckEvaluation(
                        asset_key=asset,
                        check_name=name,
                        partition=period,
                        passed=True,
                        blocking=True,
                        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                            storage_id=mat.storage_id + int(fault == "binding"),
                            run_id=context.run_id,
                            timestamp=mat.event_log_entry.timestamp,
                        ),
                    )
        yield dg.AssetObservation(
            asset_key=asset,
            metadata={
                COMPLETION_KEY: dg.MetadataValue.json(
                    delivery_completion(
                        reference,
                        kind="history_maintenance",
                        business_date=D,
                        periods=periods,
                    )
                )
            },
        )

    @dg.job
    def native_fixture_job():
        fixture_records()

    return native_fixture_job.execute_in_process(instance=instance)


def test_success_without_original_checks_is_not_complete(market):
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        result = native_history_fixture(market, instance, skip_checks=True)
        assert result.success
        with pytest.raises(ValueError, match="period_delivery_checks_incomplete"):
            read_completion(
                instance, reference_for(instance, result.run_id), root=market.root
            )


def test_silver_multi_file_failure_then_full_manual_rerun_closes_pending(
    market, monkeypatch
):
    from orchestrator.defs.io import stock_period_raw as io

    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        producer = native_history_fixture(market, instance)
        reference = reference_for(instance, producer.run_id)
        instance.add_dynamic_partitions(
            "cn_a_stock_week_ends", ["2026-11-06", "2026-11-13"]
        )
        with dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}
        ) as ctx:
            request = stock_period_silver.evaluate_update_sensor(
                ctx, freq="week"
            ).run_requests[0]
            cursor = ctx.cursor
        original, calls = io.publish_period, []

        def fail_after_first_publish(item, **kwargs):
            result = original(item, **kwargs)
            calls.append(item["period"])
            if len(calls) == 1:
                raise RuntimeError("test interruption after atomic replacement")
            return result

        monkeypatch.setattr(io, "publish_period", fail_after_first_publish)
        job = market.defs.resolve_job_def("silver_stock_weekly_update_job")
        failed = job.execute_in_process(
            instance=instance,
            partition_key=request.partition_key,
            run_config=request.run_config,
            tags={"dagster/run_key": request.run_key},
            raise_on_error=False,
        )
        assert not failed.success and calls == ["2026-11-06"]
        # Full manual rerun, with neither automatic run key nor a custom resume ID.
        success = job.execute_in_process(
            instance=instance,
            partition_key=request.partition_key,
            run_config=request.run_config,
        )
        assert success.success and calls == ["2026-11-06", "2026-11-06", "2026-11-13"]
        checks = success.get_asset_check_evaluations()
        assert len(checks) == 6 and all(
            check.passed and check.blocking for check in checks
        )
        assert silver_completion_consumed(
            instance,
            reference,
            ["2026-11-06", "2026-11-13"],
            root=market.root,
            business_date=D,
        )
        with dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}, cursor=cursor
        ) as ctx:
            assert not stock_period_silver.evaluate_update_sensor(
                ctx, freq="week"
            ).run_requests
            assert "pending" not in json.loads(ctx.cursor)


@pytest.mark.parametrize("fault", ["missing_asof", "future_asof", "binding"])
def test_native_delivery_refuses_missing_future_asof_or_wrong_check_binding(
    market, fault
):
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        producer = native_history_fixture(market, instance, fault=fault)
        with pytest.raises(ValueError, match="(source_asof|checks_incomplete)"):
            read_completion(
                instance, reference_for(instance, producer.run_id), root=market.root
            )


def test_silver_uses_actual_successor_with_each_files_date_and_original_intent(market):
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        original = native_history_fixture(market, instance)
        reference = reference_for(instance, original.run_id)
        successor = native_history_fixture(
            market,
            instance,
            periods=["2026-11-13"],
            source_asof="2026-11-11",
            price="7.0000",
        )
        later = reference_for(instance, successor.run_id)
        units, _ = stock_period_silver.resolve_update_sources(
            market.root, "week", reference, instance
        )
        assert [(unit["period"], unit["asof"]) for unit in units] == [
            ("2026-11-06", D),
            ("2026-11-13", "2026-11-11"),
        ]
        assert (
            units[0]["source_completion"] == reference
            and units[1]["source_completion"] == later
        )
        instance.add_dynamic_partitions(
            "cn_a_stock_week_ends", ["2026-11-06", "2026-11-13"]
        )
        result = market.defs.resolve_job_def(
            "silver_stock_weekly_update_job"
        ).execute_in_process(
            instance=instance,
            partition_key="2026-11-13",
            run_config={
                "ops": {
                    "silver_stock_weekly": {
                        "config": {"intent": "update", "source_completion": reference}
                    }
                }
            },
        )
        assert result.success and price_rows(
            market, target_path(market.root, "week", "2026-11-13")
        )[A] == Decimal(7)
        assert silver_completion_consumed(
            instance,
            reference,
            ["2026-11-06", "2026-11-13"],
            root=market.root,
            business_date=D,
        )


def test_accepted_lifecycle_and_final_suspend_are_required_before_source(
    market, monkeypatch
):
    from orchestrator.defs.sensors import readiness

    flags = {"life": False, "suspend": False}
    monkeypatch.setattr(stock_period_update, "_period_inputs_ready", market.gate)
    monkeypatch.setattr(
        readiness,
        "silver_stock_lifecycle_ready_for_trade_date",
        lambda instance, day: NS(ready=flags["life"], reason="fixture acceptance"),
    )

    def final_status(instance, spec, *, partition_key):
        assert (
            spec.asset_key == dg.AssetKey("silver_stock_suspend_daily")
            and partition_key == D
        )
        return NS(ready=flags["suspend"], reason="fixture acceptance")

    monkeypatch.setattr(readiness, "asset_readiness_status", final_status)
    with (
        dg.DagsterInstance.ephemeral() as instance,
        dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}
        ) as ctx,
    ):
        assert not stock_period_update.evaluate_daily_sensor(
            ctx, NOW, freq="week"
        ).run_requests
        assert not market.state["calls"]
        flags["life"] = True
        assert not stock_period_update.evaluate_daily_sensor(
            ctx, NOW, freq="week"
        ).run_requests
        assert not market.state["calls"]
        flags["suspend"] = True
        assert (
            len(
                stock_period_update.evaluate_daily_sensor(
                    ctx, NOW, freq="week"
                ).run_requests
            )
            == 1
        )


def test_accepted_empty_final_suspend_partition_is_usable(market):
    path = paths.silver_stock_suspend_daily_path(market.root, D)
    with connection(market.tmp / "empty_suspend") as con:
        con.execute(
            "COPY (SELECT NULL::VARCHAR ts_code,NULL::DATE trade_date,NULL::VARCHAR suspend_type,NULL::VARCHAR suspend_timing WHERE false) TO ? (FORMAT PARQUET)",
            [str(path)],
        )
    universe = load_period_universe(market.root, D, "month")
    assert universe["required"] == {A, S, N, I} and not universe["optional"]
    market.state["include_s"] = True
    with (
        dg.DagsterInstance.ephemeral() as instance,
        dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}
        ) as ctx,
    ):
        assert (
            len(
                stock_period_update.evaluate_daily_sensor(
                    ctx, NOW, freq="month"
                ).run_requests
            )
            == 1
        )


def test_daily_ignores_legacy_json_and_preserves_history_and_newer_current_row(market):
    control = market.staging / "stock_period"
    control.mkdir()
    for name in ("baseline.json", "daily.json"):
        (control / name).write_text("invalid legacy JSON must not be read")
    historical = raw_path(market.root, "week", "2026-11-06")
    monthly = raw_path(market.root, "month", "2026-10")
    current = raw_path(market.root, "week", "2026-11-13")
    with connection(market.tmp / "protected") as con:
        write_raw(
            con,
            historical,
            [literal_row(A, "20261106", "week", asof="20261106", qfq="1.0000")],
        )
        write_raw(
            con,
            monthly,
            [literal_row(A, "20261031", "month", asof="20261030", qfq="2.0000")],
        )
        write_raw(
            con,
            current,
            [literal_row(A, "20261113", "week", asof="20261111", qfq="15.0000")],
        )
    before = {str(path): file_digest(path) for path in (historical, monthly)}
    with dg.DagsterInstance.local_temp(
        str(market.tmp / "instance"), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        assert raw_job(market, instance, "week").success
    assert price_rows(market, current)[A] == Decimal(15)
    assert before == {str(path): file_digest(path) for path in (historical, monthly)}
    assert (
        control / "daily.json"
    ).read_text() == "invalid legacy JSON must not be read"
