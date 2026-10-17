"""Keep the retired Console out without treating ignored environments as source."""

import ast
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RETIRED_DIRS = (
    "lake_console/backend/",
    "lake_console/frontend/",
    "tests/lake_console/",
)
RETIRED_ENTRIES = {
    "lake_console/bin/lake-console",
    "scripts/local-lake-console.sh",
    "lake_console/config.local.example.toml",
}


def _source_files() -> list[Path]:
    # Deleted tracked files may still be in the index before commit. Ignored
    # venvs, node_modules, dist and local configuration are not retirement targets.
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        REPO_ROOT / name
        for name in sorted(set(result.stdout.decode().split("\0")) - {""})
        if (REPO_ROOT / name).is_file()
    ]


def _retired_imports(source: str) -> list[str]:
    modules = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
            modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    modules.append(arg.value)
    return [
        module
        for module in modules
        if module == "lake_console.backend"
        or module.startswith("lake_console.backend.")
    ]


def test_retired_console_has_no_versioned_or_new_source_files():
    remaining = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _source_files()
        if path.relative_to(REPO_ROOT).as_posix().startswith(RETIRED_DIRS)
        or path.relative_to(REPO_ROOT).as_posix() in RETIRED_ENTRIES
    ]
    assert remaining == []


def test_current_python_sources_do_not_import_retired_backend():
    issues = []
    for path in _source_files():
        if path.suffix == ".py":
            issues.extend(
                f"{path.relative_to(REPO_ROOT)}: {module}"
                for module in _retired_imports(path.read_text(encoding="utf-8"))
            )
    assert issues == []


@pytest.mark.parametrize(
    "source",
    [
        "import lake_console.backend.app.main",
        "from lake_console.backend.app import cli",
        "from lake_console import backend",
        "importlib.import_module('lake_console.backend.app.main')",
        "__import__('lake_console.backend.app.cli')",
    ],
)
def test_import_guard_rejects_retired_import_forms(source):
    assert _retired_imports(source)


@pytest.mark.parametrize(
    "source",
    [
        "from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot",
        "from src.foundation.clients.local_lake.stock_mins_reader import StockMinsLakeReader",
        "from orchestrator.defs.resources import ProdPostgresResource",
        "historical_reference = 'lake_console.backend.app.cli'",
    ],
)
def test_import_guard_preserves_current_modules_and_historical_text(source):
    assert _retired_imports(source) == []


def _is_runtime_source(relative: Path) -> bool:
    """Report JSON is data; executable files and runtime config remain guarded."""
    suffixes = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".mjs",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".sh",
    }
    if (
        relative.suffix not in suffixes
        or "tests" in relative.parts
        or ".test." in relative.name
        or (
            relative.parts[:2] == ("lake_console", "reports")
            and relative.suffix == ".json"
        )
    ):
        return False
    return relative.as_posix().startswith(
        (
            "src/",
            "qtf/",
            "scripts/",
            "frontend/",
            "wealth/",
            "lake_console/",
            ".github/",
        )
    )


def _runtime_reference_issues(relative: Path, source: str) -> list[str]:
    if not _is_runtime_source(relative):
        return []
    return [
        fragment
        for fragment in (
            "kopia",
            "lake_console.backend",
            "lake_console/backend",
            "lake_console/frontend",
            "local-lake-console.sh",
            "config.local.example.toml",
        )
        if fragment in source.lower()
    ]


@pytest.mark.parametrize(
    "relative,source,expected",
    [
        (
            "lake_console/reports/evidence.json",
            '{"cases":["test_no_kopia_reference"]}',
            [],
        ),
        (
            "lake_console/reports/history/evidence.json",
            '{"old_import":"lake_console.backend"}',
            [],
        ),
        (
            "lake_console/reports/run.py",
            "subprocess.run(['kopia','snapshot','create'])",
            ["kopia"],
        ),
        ("lake_console/reports/run.sh", "kopia snapshot create", ["kopia"]),
        ("lake_console/reports/run.mjs", "spawn('kopia', [])", ["kopia"]),
        (
            "lake_console/orchestrator/config.json",
            '{"command":"kopia snapshot create"}',
            ["kopia"],
        ),
        (".github/workflows/job.yaml", "run: kopia snapshot create", ["kopia"]),
        ("src/reports/config.json", '{"command":"kopia"}', ["kopia"]),
        ("lake_console/reports_backup/config.json", '{"command":"kopia"}', ["kopia"]),
        ("src/ops/config.json", '{"table":"ops.dataset_status_snapshot"}', []),
        ("lake_console/reports/run.yaml", "run: kopia snapshot create", ["kopia"]),
    ],
)
def test_runtime_reference_guard_separates_evidence_from_executable_sources(
    relative, source, expected
):
    assert _runtime_reference_issues(Path(relative), source) == expected


def test_current_runtime_and_versioned_config_have_no_legacy_console_or_kopia_reference():
    issues = []
    for path in _source_files():
        relative = path.relative_to(REPO_ROOT)
        if _is_runtime_source(relative):
            issues.extend(
                f"{relative}: {fragment}"
                for fragment in _runtime_reference_issues(
                    relative, path.read_text(encoding="utf-8")
                )
            )
    assert issues == []


def test_current_lake_consumers_and_clickhouse_tools_are_present():
    for name in (
        "src/foundation/clients/local_lake/stock_mins_reader.py",
        "src/foundation/clients/local_lake/major_index_mins_reader.py",
        "src/foundation/clients/local_lake/stock_nine_turn_reader.py",
        "src/foundation/clients/local_lake/index_nine_turn_reader.py",
        "src/foundation/clients/local_lake/major_index_turnover_reader.py",
        "src/foundation/clients/local_lake/stock_daily_trend_channel_reader.py",
        "src/ops/models/ops/dataset_status_snapshot.py",
        "lake_console/bin/lake-clickhouse-start",
        "lake_console/bin/lake-prod-clickhouse-tunnel",
        "lake_console/orchestrator/src/orchestrator/defs/assets/stock_suspend_confirmed.py",
        "lake_console/orchestrator/src/orchestrator/defs/stock_suspend_confirmed_contract.py",
    ):
        assert (REPO_ROOT / name).is_file(), name
    for name in (
        "lake_console/orchestrator/src/orchestrator/defs/corrections/suspend_full_day.py",
        "lake_console/orchestrator/src/orchestrator/defs/corrections/suspend_full_day_ranges.csv",
    ):
        with pytest.raises(FileNotFoundError):
            (REPO_ROOT / name).lstat()
