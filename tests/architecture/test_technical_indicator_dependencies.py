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
