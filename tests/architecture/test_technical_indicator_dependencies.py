"""Guard the frozen technical-indicator Foundation boundary (LLD §01/03/19)."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src/foundation/technical_indicators"


def test_kernel_has_no_reverse_or_dg_dependencies():
    forbidden = ("src.app", "src.biz", "src.ops", "src.platform", "src.operations", "qtf", "orchestrator", "lake_console")
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            imports = []
            if isinstance(node, ast.Import):
                imports = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports = [node.module]
            assert not any(name == prefix or name.startswith(prefix + ".") for name in imports for prefix in forbidden), path


def test_d1_import_requires_no_database_or_arrow():
    """Import in a fresh interpreter, blocking optional runtime imports explicitly."""
    import subprocess
    import sys

    code = '''
import sys
class RejectRuntimeImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'duckdb', 'pyarrow', 'orchestrator'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, RejectRuntimeImports())
import src.foundation.technical_indicators
import src.foundation.technical_indicators.discovery.catalog
import src.foundation.technical_indicators.configuration.settings
'''
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, timeout=5)


def test_d2_runtime_sql_resources_are_explicitly_declared_for_packaging():
    """Static LLD file declaration; this does not claim a wheel was built."""
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]
    assert "sql/*.sql" in patterns["src.foundation.technical_indicators.sources"]
    expected = {"stage_input.sql", "adjust_price.sql", "retain_history.sql"}
    assert {path.name for path in (PACKAGE / "sources/sql").glob("*.sql")} == expected


def test_d3_fixed_sql_resources_and_output_dependency_boundary():
    """Actual package files, not a claim that a wheel was built or installed."""
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]
    expected = {
        "calculation": {"smoothing_parameters.sql","rolling_mean.sql","bollinger_bands.sql",
                        "macd_first.sql","macd_segment.sql","kdj_window.sql","kdj_segment.sql"},
        "output": {"merge_batch.sql","retain_tail.sql","select_result.sql"},
    }
    for part, names in expected.items():
        assert "sql/*.sql" in patterns["src.foundation.technical_indicators."+part]
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
