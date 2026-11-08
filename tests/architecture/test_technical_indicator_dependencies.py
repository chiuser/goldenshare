"""Guard the shared calculation package and its callers."""

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "packages/technical_indicators"
PACKAGE = PROJECT / "src/goldenshare_technical_indicators"


def test_kernel_has_no_reverse_or_dg_dependencies():
    assert (PACKAGE / "service.py").is_file()
    assert (PACKAGE / "xxm/calculator.py").is_file()
    forbidden = {"src", "qtf", "orchestrator", "lake_console"}
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            imports = []
            if isinstance(node, ast.Import):
                imports = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports = [node.module]
            roots = {name.split(".", 1)[0] for name in imports}
            assert roots.isdisjoint(forbidden), path
            if path.is_relative_to(PACKAGE / "xxm"):
                assert roots <= sys.stdlib_module_names, path


def test_d1_import_requires_no_database_or_arrow():
    """Import in a fresh interpreter, blocking optional runtime imports explicitly."""
    import subprocess
    import sys

    code = '''
import sys
class RejectRuntimeImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'duckdb', 'pyarrow', 'orchestrator', 'src'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, RejectRuntimeImports())
import goldenshare_technical_indicators
import goldenshare_technical_indicators.discovery.catalog
import goldenshare_technical_indicators.configuration.settings
from goldenshare_technical_indicators.service import TechnicalIndicatorService
from goldenshare_technical_indicators.xxm import XxmCalculator
'''
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, timeout=5)


def test_d2_runtime_sql_resources_are_explicitly_declared_for_packaging():
    """Static LLD file declaration; this does not claim a wheel was built."""
    import tomllib

    config = tomllib.loads((PROJECT / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]
    assert "sql/*.sql" in patterns["goldenshare_technical_indicators.sources"]
    expected = {"stage_input.sql", "adjust_price.sql", "retain_history.sql"}
    assert {path.name for path in (PACKAGE / "sources/sql").glob("*.sql")} == expected


def test_d3_fixed_sql_resources_and_output_dependency_boundary():
    """Actual package files, not a claim that a wheel was built or installed."""
    import tomllib

    config = tomllib.loads((PROJECT / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]
    expected = {
        "calculation": {"smoothing_parameters.sql","rolling_mean.sql","bollinger_bands.sql",
                        "macd_first.sql","macd_segment.sql","kdj_window.sql","kdj_segment.sql",
                        "macd_warmup.sql","kdj_warmup.sql"},
        "output": {"merge_batch.sql","select_result.sql"},
    }
    for part, names in expected.items():
        assert "sql/*.sql" in patterns["goldenshare_technical_indicators."+part]
        assert {path.name for path in (PACKAGE/part/"sql").glob("*.sql")} == names
    # Output accepts a small immutable description, never the private plan.
    for name in ("contracts.py","collector.py","result.py"):
        tree = ast.parse((PACKAGE/"output"/name).read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                assert not any(word in (node.module or "").split(".") for word in ("dependencies","registry","engine"))
                assert all(alias.name!="CalculationPlan" for alias in node.names)
    # Product calculation and output code must not contain the removed page-
    # probing fields; ordinary indicator lookback is a separate requirement.
    for part in (PACKAGE/"contracts.py",PACKAGE/"output"):
        paths = part.rglob("*.py") if part.is_dir() else (part,)
        for path in paths:
            text = path.read_text()
            assert "has_more" not in text and "next_before" not in text


def test_indicator_dependency_boundaries():
    helpers = Path(__file__).resolve().parents[1] / "app/technical_indicators"
    # Only the fixture-free helper module is made importable; it starts no
    # calculation, control thread or source read at import time.
    original = tuple(sys.path)
    try:
        sys.path.insert(0, str(helpers))
        from test_admission import light_case
    finally:
        sys.path[:] = original
    with light_case("test_indicator_dependency_boundaries"):
        root = Path(__file__).resolve().parents[2]
        folders = (
            (root / "src/app/runtime/technical_indicators", ("src.biz", "src.ops", "qtf", "orchestrator", "src.platform", "src.operations", "lake_console")),
        )
        for folder, banned in folders:
            for path in folder.rglob("*.py"):
                tree = ast.parse(path.read_text())
                for node in ast.walk(tree):
                    modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                               else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                    assert not any(module == prefix or module.startswith(prefix+".")
                                   for module in modules for prefix in banned), path
        package = root / "src/app/runtime/technical_indicators"
        assert {path.name for path in package.glob("*.py")} == {
            "__init__.py", "admission.py", "composition.py", "execution.py", "response.py",
        }
