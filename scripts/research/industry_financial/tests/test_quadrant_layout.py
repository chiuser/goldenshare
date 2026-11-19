"""Exercise native-pixel label placement without browser, source access or packages."""
from pathlib import Path
import subprocess
from scripts.research.industry_financial.sample_chapters import NODE


def test_quadrant_label_geometry_and_identity_cases():
    result = subprocess.run([NODE, '--test', '--test-reporter=tap', str(Path(__file__).with_name('quadrant_layout_cases.mjs'))],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '# pass 4' in result.stdout
