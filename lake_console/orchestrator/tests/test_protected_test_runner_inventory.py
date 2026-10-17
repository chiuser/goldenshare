"""Independent current source inventory, not a copied list of launcher permissions."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).with_name("stock_suspend_confirmed_test_runner.py")
    spec = importlib.util.spec_from_file_location("protected_runner_inventory", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "scope", ["isolation", "adapter", "regression", "consumer", "root-guard"]
)
def test_each_explicit_source_permission_still_names_a_regular_file(runner, scope):
    paths = [runner.SOURCE / name for name in runner.source_files_for_scope(scope)]
    invalid = [str(path) for path in paths if not path.is_file() or path.is_symlink()]
    assert invalid == []


def test_consumer_discovery_covers_current_definitions_without_widening_permissions(
    runner,
):
    # Producer: actual defs discovery by the existing governance tests. The
    # launcher remains a reviewed literal tuple; this does not grant any permission.
    current = {
        p.relative_to(runner.SOURCE).as_posix()
        for p in (runner.SOURCE / "defs").rglob("*.py")
    }
    allowed = set(runner.source_files_for_scope("consumer"))
    assert current <= allowed, sorted(current - allowed)
    assert all(
        Path(name).suffix == ".py"
        and not Path(name).is_absolute()
        and ".." not in Path(name).parts
        for name in allowed
    )
    assert "defs/bootstrap/stock_period_history.py" in allowed
    assert "defs/bootstrap/stock_period_history_cli.py" in allowed
    # Independent facts from the committed 09ea909fd retirement, not derived
    # by silently filtering the permissions tuple with exists().
    retired = {
        "defs/bootstrap/stock_weekly_event_files.py",
        "defs/bootstrap/stock_weekly_event_instance.py",
        "defs/bootstrap/stock_weekly_events.py",
        "defs/bootstrap/stock_weekly_history.py",
        "defs/bootstrap/stock_weekly_adj_bootstrap.py",
        "defs/prod_db/stock_weekly.py",
    }
    assert allowed.isdisjoint(retired)


@pytest.mark.parametrize("kind", ["missing", "symlink"])
def test_policy_still_rejects_missing_or_symlink_source_before_runtime_access(
    runner, tmp_path, kind
):
    source = tmp_path / "source"
    source.mkdir()
    target = source / "module.py"
    if kind == "symlink":
        actual = tmp_path / "actual.py"
        actual.write_text("value = 1\n")
        target.symlink_to(actual)
    runner.SOURCE = source
    runner.RESOURCE_SOURCE_FILES = ("module.py",)

    def forbidden_runtime_access():
        pytest.fail("source rejection must precede runtime policy construction")

    runner.runtime_environment_identity = forbidden_runtime_access
    with pytest.raises(
        RuntimeError, match="Source allowlist must contain regular files"
    ):
        runner.policy_for(tmp_path, scope="isolation")
