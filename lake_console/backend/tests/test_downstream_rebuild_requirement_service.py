from __future__ import annotations

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
