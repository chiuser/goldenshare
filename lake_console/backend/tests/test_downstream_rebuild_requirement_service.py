from __future__ import annotations

import pandas as pd

from lake_console.backend.app.services.downstream_rebuild_requirement_service import DownstreamRebuildRequirementService


def test_build_stk_mins_qfq_requirements_uses_explicit_freq_and_date_scope(tmp_path) -> None:
    requirements = DownstreamRebuildRequirementService(lake_root=tmp_path).build_stk_mins_qfq_requirements(
        source_publish_id="run-001",
        publish_partitions=[
            {"partition_key": "freq=30/trade_date=2026-03-02"},
            {"partition_key": "freq=60/trade_date=2026-03-03"},
        ],
    )

    assert [row["target_layer"] for row in requirements] == [
        "derived/stk_mins_by_date",
        "research/stk_mins_by_symbol_month",
        "indicator/*",
    ]
    assert requirements[0]["freqs"] == "90,120"
    assert requirements[1]["freqs"] == "30,60,90,120"
    assert requirements[2]["freqs"] == "30,60,90,120"
    assert {row["start_date"].isoformat() for row in requirements} == {"2026-03-02"}
    assert {row["end_date"].isoformat() for row in requirements} == {"2026-03-03"}
    assert {row["status"] for row in requirements} == {"pending"}
    assert all(row["requirement_id"].startswith("dsr_") for row in requirements)


def test_build_stk_mins_qfq_requirements_skips_derived_when_no_derived_source_freq(tmp_path) -> None:
    requirements = DownstreamRebuildRequirementService(lake_root=tmp_path).build_stk_mins_qfq_requirements(
        source_publish_id="run-002",
        publish_partitions=[{"partition_key": "freq=1/trade_date=2026-03-02"}],
    )

    assert [row["target_layer"] for row in requirements] == [
        "research/stk_mins_by_symbol_month",
        "indicator/*",
    ]
    assert {row["freqs"] for row in requirements} == {"1"}


def test_upsert_requirements_is_idempotent_by_requirement_id(tmp_path) -> None:
    service = DownstreamRebuildRequirementService(lake_root=tmp_path)
    requirements = service.build_stk_mins_qfq_requirements(
        source_publish_id="run-003",
        publish_partitions=[{"partition_key": "freq=30/trade_date=2026-03-02"}],
    )

    first = service.upsert_requirements(requirements=requirements, run_id="run-003")
    second = service.upsert_requirements(requirements=requirements, run_id="run-003")

    rows = pd.read_parquet(tmp_path / "manifest/downstream_rebuild_requirements/stk_mins.parquet", engine="pyarrow").to_dict(orient="records")
    assert first["written_rows"] == 3
    assert second["written_rows"] == 3
    assert len(rows) == 3
    assert len({row["requirement_id"] for row in rows}) == 3
