"""Current materialization binds this exact file version; old capture proofs are irrelevant."""

from types import SimpleNamespace as NS

import dagster as dg
import pytest

from orchestrator.defs.io.stock_period_raw import file_version
from orchestrator.defs.stock_period_checks import verify_period_materialization


def record(path, partition="2026-10-16", rows=7, version=None, **extra):
    return NS(
        asset_materialization=dg.AssetMaterialization(
            asset_key="period",
            partition=partition,
            metadata={
                "dagster/uri": str(path),
                "dagster/row_count": rows,
                "goldenshare/period_file_version": dg.MetadataValue.json(
                    version or file_version(path)
                ),
                **extra,
            },
        )
    )


def test_same_file_version_and_row_count_suffice_without_old_materials(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"first")
    r = record(path, **{"goldenshare/old_proof": {"path": "/does-not-exist"}})
    assert verify_period_materialization(r, "2026-10-16", path, rows=7) == 7
    path.write_bytes(b"updated")
    with pytest.raises(ValueError, match="version"):
        verify_period_materialization(r, "2026-10-16", path, rows=7)
    assert (
        verify_period_materialization(record(path, rows=9), "2026-10-16", path, rows=9)
        == 9
    )


@pytest.mark.parametrize(
    "bad", ["partition", "path", "rows", "negative", "bool", "missing"]
)
def test_wrong_binding_refused(tmp_path, bad):
    p = tmp_path / "file"
    p.write_bytes(b"1")
    r = record(p)
    if bad == "partition":
        r = record(p, partition="2026-10-09")
    elif bad == "path":
        r.asset_materialization = dg.AssetMaterialization(
            asset_key="period",
            partition="2026-10-16",
            metadata={"dagster/uri": "/wrong", "dagster/row_count": 7},
        )
    elif bad == "rows":
        r = record(p, rows=8)
    elif bad == "negative":
        r = record(p, rows=-1)
    elif bad == "bool":
        r = record(p, rows=True)
    elif bad == "missing":
        r = None
    with pytest.raises(ValueError):
        verify_period_materialization(r, "2026-10-16", p, rows=7)
