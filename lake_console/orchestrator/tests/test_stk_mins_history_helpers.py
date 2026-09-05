import ast
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator.defs.bootstrap import stk_mins_silver_history as history
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    raw_stk_mins_path,
    silver_stk_mins_path,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS


def _touch_partitions(root: Path, dates: tuple[str, ...], path_builder) -> None:
    for freq in STK_MINS_FREQS:
        for date in dates:
            path = path_builder(root, freq, date)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()


def test_raw_discovery_preserves_sorted_five_frequency_file_contract(tmp_path):
    _touch_partitions(tmp_path, ("2026-09-04", "2026-09-02"), raw_stk_mins_path)
    for freq in STK_MINS_FREQS:
        other = raw_stk_mins_path(tmp_path, freq, "2026-09-03")
        other.parent.mkdir(parents=True)
        other.with_name("part-001.parquet").touch()
        other.mkdir()  # A directory named part-000.parquet is not a file.
    assert history.discover_raw_stk_mins_partitions(tmp_path) == {
        freq: ("2026-09-02", "2026-09-04") for freq in (1, 5, 15, 30, 60)
    }
    assert history.all_raw_stk_mins_partition_keys(tmp_path) == (
        "2026-09-02",
        "2026-09-04",
    )


def test_empty_raw_scope_stays_empty_without_creating_root(tmp_path):
    root = tmp_path / "missing"
    assert history.discover_raw_stk_mins_partitions(root) == {
        freq: () for freq in (1, 5, 15, 30, 60)
    }
    assert history.all_raw_stk_mins_partition_keys(root) == ()
    assert not root.exists()


def test_raw_helper_defaults_keep_formal_root_without_scanning_it():
    for helper in (
        history.discover_raw_stk_mins_partitions,
        history.all_raw_stk_mins_partition_keys,
    ):
        assert inspect.signature(helper).parameters["lake_root"].default == Path(
            DEFAULT_LAKE_ROOT
        )


@pytest.mark.parametrize("freq", (1, 5, 15, 30, 60))
@pytest.mark.parametrize("difference", ("missing", "extra"))
def test_raw_alignment_rejects_each_frequency_difference(tmp_path, freq, difference):
    dates = ("2026-09-02", "2026-09-04")
    _touch_partitions(tmp_path, dates, raw_stk_mins_path)
    if difference == "missing":
        raw_stk_mins_path(tmp_path, freq, dates[0]).unlink()
    else:
        extra = raw_stk_mins_path(tmp_path, freq, "2026-09-03")
        extra.parent.mkdir(parents=True)
        extra.touch()
    for helper in (
        history.all_raw_stk_mins_partition_keys,
        lambda root: history.plan_stk_mins_silver_history(lake_root=root),
    ):
        with pytest.raises(ValueError, match="partition sets are not aligned by freq"):
            helper(tmp_path)


def test_alignment_keeps_error_payload_and_none_return():
    aligned = {freq: ("2026-09-02",) for freq in (1, 5, 15, 30, 60)}
    assert history._validate_stk_mins_partition_alignment(aligned) is None
    with pytest.raises(ValueError) as exc:
        history._validate_stk_mins_partition_alignment({**aligned, 5: ("2026-09-04",)})
    assert str(exc.value) == (
        "stk_mins partition sets are not aligned by freq: "
        "{5: {'missing_from_freq': ['2026-09-02'], 'extra_in_freq': ['2026-09-04']}}"
    )


def test_silver_selection_keeps_date_filter_and_alignment(tmp_path):
    dates = ("2013-12-31", "2014-01-02", "2014-01-03")
    _touch_partitions(tmp_path, dates, silver_stk_mins_path)
    assert history.all_silver_partition_keys(tmp_path, end_date="2014-01-02") == (
        "2014-01-02",
    )
    silver_stk_mins_path(tmp_path, 60, "2013-12-31").unlink()
    with pytest.raises(ValueError, match="partition sets are not aligned by freq"):
        history.all_silver_partition_keys(tmp_path, end_date="2014-01-02")


def test_silver_plan_keeps_explicit_selection_and_missing_input_counts(tmp_path):
    _touch_partitions(tmp_path, ("2013-12-31", "2014-01-02"), raw_stk_mins_path)
    with patch.object(history, "write_silver_stk_mins_partition") as writer:
        default_plan = history.plan_stk_mins_silver_history(lake_root=tmp_path)
        explicit_plan = history.plan_stk_mins_silver_history(
            lake_root=tmp_path, partition_keys=("2013-12-31", "2013-12-31")
        )
        with pytest.raises(
            ValueError, match="Requested stk_mins raw partitions are missing"
        ):
            history.plan_stk_mins_silver_history(
                lake_root=tmp_path, partition_keys=("2026-09-04",)
            )
        writer.assert_not_called()
    assert default_plan.selected_partition_keys == ("2014-01-02",)
    assert explicit_plan.selected_partition_keys == ("2013-12-31",)
    assert default_plan.raw_partition_counts == {freq: 2 for freq in (1, 5, 15, 30, 60)}
    assert default_plan.planned_write_count == 5
    assert default_plan.missing_input_count == 5
    assert not (tmp_path / "silver").exists()


@pytest.mark.parametrize(
    "module_name",
    (
        "stk_mins_history_check_events",
        "stk_mins_silver_history",
        "stk_mins_silver_bootstrap_events",
        "stk_mins_qfq_bootstrap_events",
        "stk_mins_qfq_derived_bootstrap_events",
        "stk_mins_qfq_macd_kdj_baseline_events",
    ),
)
def test_retained_history_helpers_do_not_import_migration(module_name):
    path = Path("src/orchestrator/defs/bootstrap") / f"{module_name}.py"
    source = path.read_text()
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    assert not any("stk_mins_migration" in name for name in imports)
    assert "_validate_backup_partition_alignment" not in source
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_check_success_count"
        for node in ast.walk(tree)
    )
