"""Real publisher -> native event -> bound check; only networking is replaced."""

from dataclasses import replace

import dagster as dg
import pytest

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as G
from orchestrator.defs.io import stk_factor_pro_publication as P
from orchestrator.defs.io.stk_factor_pro_candidates import (
    release_stk_factor_pro_day_source,
)
from orchestrator.defs.io.stk_factor_pro_download import download_stk_factor_pro_day
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_test_support import (
    Downloader,
    connection,
    contract,
    identity,
    result,
    row,
)
from tests.test_stk_factor_pro_dagster_events import _isolated_instance
from tests.test_stk_factor_pro_publication import roots


def definition(tmp_path, *, fail_silver=False, bad_callback=False):
    lake, staging = roots(tmp_path)
    seen, pg, records = [], {}, {}
    parts = dg.DynamicPartitionsDefinition(name=C.STK_FACTOR_PRO_PARTITIONS)

    @dg.multi_asset(
        name="stk_factor_pro",
        specs=[
            dg.AssetSpec(C.STK_FACTOR_PRO_RAW_ASSET_KEY, skippable=True),
            dg.AssetSpec(C.STK_FACTOR_PRO_SILVER_ASSET_KEY, skippable=True),
        ],
        can_subset=True,
        partitions_def=parts,
        check_specs=[
            dg.AssetCheckSpec(name=name, asset=key, blocking=True, partitions_def=parts)
            for key, name in (
                (C.STK_FACTOR_PRO_RAW_ASSET_KEY, C.STK_FACTOR_PRO_RAW_CHECK_NAME),
                (C.STK_FACTOR_PRO_SILVER_ASSET_KEY, C.STK_FACTOR_PRO_SILVER_CHECK_NAME),
            )
        ],
    )
    def assets(context):
        with connection(tmp_path) as conn:
            source = download_stk_factor_pro_day(
                conn,
                identity=replace(identity(), creator_run_id=context.run_id),
                contract=contract(),
                downloader=Downloader(result((row(),))),
                check_cancel=lambda: None,
            )

            def attempted(day, layer):
                seen.append(layer)
                assert not (
                    staging
                    / "stk_factor_pro"
                    / context.run_id
                    / str(day)
                    / "publication"
                    / "day"
                    / str(day)
                    / layer
                    / "intent.json"
                ).exists()
                if bad_callback or fail_silver and layer == "silver":
                    raise OSError("publication callback failed")

            try:
                for item in P.publish_stk_factor_pro_day(
                    conn,
                    source=source,
                    lake_root=lake,
                    staging_root=staging,
                    check_cancel=lambda: None,
                    known_records=records,
                    on_publish_attempt=attempted,
                    on_raw_candidate=lambda **_: None,
                ):
                    yield from G.emit_stk_factor_pro_publications(
                        context,
                        completed=(item,),
                        lake_root=lake,
                        known_pg=pg,
                        known_records=records,
                        day_output=True,
                    )
            finally:
                release_stk_factor_pro_day_source(conn)

    return assets, lake, staging, seen, pg, records


@pytest.mark.parametrize(
    "failure,expected", [(False, ["raw", "silver"]), (True, ["raw"])]
)
def test_real_files_have_bound_events_and_raw_survives_silver_failure(
    tmp_path, failure, expected
):
    assets, _lake, _staging, seen, pg, _records = definition(
        tmp_path, fail_silver=failure
    )
    with _isolated_instance(tmp_path) as instance:
        instance.add_dynamic_partitions(C.STK_FACTOR_PRO_PARTITIONS, ["2026-10-16"])
        result_ = dg.materialize(
            [assets],
            instance=instance,
            partition_key="2026-10-16",
            raise_on_error=False,
        )
        assert result_.success is not failure, result_.failure_data_for_node(
            "stk_factor_pro"
        ).error.to_string()
        actual = [key[3] for key in pg if key[0] == "publication_events"]
        assert actual == expected
        for key in pg:
            if key[0] == "publication_events":
                material, check, audit = pg[key]
                assert (
                    check.event_log_entry.dagster_event.event_specific_data.target_materialization_data.storage_id
                    == material.storage_id
                )
                assert audit.path.exists()
        assert seen == ["raw", "silver"]


def test_callback_failure_precedes_intent_and_all_file_events(tmp_path):
    assets, lake, staging, seen, pg, _records = definition(tmp_path, bad_callback=True)
    with _isolated_instance(tmp_path) as instance:
        instance.add_dynamic_partitions(C.STK_FACTOR_PRO_PARTITIONS, ["2026-10-16"])
        result_ = dg.materialize(
            [assets],
            instance=instance,
            partition_key="2026-10-16",
            raise_on_error=False,
        )
        assert not result_.success and seen == ["raw"]
        assert not list(staging.rglob("intent.json"))
        assert not [key for key in pg if key[0] == "publication_events"]
        assert not list(lake.rglob("*.parquet"))
