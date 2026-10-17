"""Actual import/file contracts in temporary projects, independent of production data."""

from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import moneyflow_history_supplement_code as code
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "repo/lake_console/orchestrator"
    files = {
        "src/orchestrator/__init__.py": "",
        "src/orchestrator/defs/__init__.py": "",
        "src/orchestrator/defs/bootstrap/__init__.py": "",
        "src/orchestrator/moneyflow_continuation/__init__.py": "",
        "src/orchestrator/defs/bootstrap/moneyflow_history_supplement.py": "from orchestrator.defs.shared import VALUE\n",
        "src/orchestrator/defs/bootstrap/moneyflow_history_source.py": "",
        "src/orchestrator/defs/bootstrap/daily_basic_event_instance.py": "",
        "src/orchestrator/moneyflow_continuation/state.py": "",
        "src/orchestrator/defs/shared.py": "VALUE = 1\n",
        "pyproject.toml": "# literal declaration\n",
        "uv.lock": "# literal lock\n",
        "src/orchestrator/seeds/market/major_indices.cn_a.csv": "ts_code\n000001.SH\n",
    }
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    script = root.parents[1] / "scripts/psql-remote.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    monkeypatch.setattr(code, "PROJECT", root)
    return root, {*files, "repo:scripts/psql-remote.sh"}


def test_literal_dependency_set_and_unrelated_cli_does_not_change_identity(project):
    root, expected = project
    before = code.supplement_code_identity()
    assert set(before) == expected
    foreign = (
        root / "src/orchestrator/defs/bootstrap/stock_adj_factor_history_repair_cli.py"
    )
    foreign.write_text("raise RuntimeError('must never import')\n")
    assert code.supplement_code_identity() == before
    foreign.write_text("# another task changed its CLI\n")
    assert code.supplement_code_identity() == before


@pytest.mark.parametrize(
    "name",
    [
        "src/orchestrator/defs/shared.py",
        "src/orchestrator/defs/__init__.py",
        "uv.lock",
        "repo:scripts/psql-remote.sh",
    ],
)
def test_real_dependency_changes_identity(project, name):
    root, _ = project
    before = code.supplement_code_identity()
    path = (
        root.parents[1] / "scripts/psql-remote.sh"
        if name.startswith("repo:")
        else root / name
    )
    path.write_text(path.read_text() + "\n# changed\n")
    after = code.supplement_code_identity()
    assert {key for key in before if before[key] != after[key]} == {name}


@pytest.mark.parametrize(
    "fault", ["missing", "relative", "symlink", "file_budget", "count_budget"]
)
def test_dependency_ambiguity_and_budget_refuse(project, fault):
    root, _ = project
    entry = root / "src/orchestrator/defs/bootstrap/moneyflow_history_supplement.py"
    if fault == "missing":
        entry.write_text("import orchestrator.defs.missing\n")
    elif fault == "relative":
        entry.write_text("from ..shared import VALUE\n")
    elif fault == "symlink":
        shared = root / "src/orchestrator/defs/shared.py"
        shared.unlink()
        shared.symlink_to(entry)
    elif fault == "file_budget":
        entry.write_bytes(b"#" * (2 * 1024**2 + 1))
    else:
        entry.write_text(
            "\n".join(f"import orchestrator.defs.extra_{i}" for i in range(151))
        )
        for i in range(151):
            (root / f"src/orchestrator/defs/extra_{i}.py").write_text("")
    with pytest.raises(MoneyflowContractError):
        code.supplement_code_identity()


def test_real_maintenance_closure_keeps_shared_catalog_and_excludes_factor_cli():
    actual = code.supplement_code_identity()
    assert "src/orchestrator/defs/catalog/lake_assets.py" in actual
    assert "src/orchestrator/defs/io/moneyflow_update_publication.py" in actual
    assert not any("stock_adj_factor_history_repair" in name for name in actual)
    assert Path(code.__file__).name == "moneyflow_history_supplement_code.py"
