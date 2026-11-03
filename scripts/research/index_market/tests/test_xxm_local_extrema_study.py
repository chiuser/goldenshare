"""P5-09/10: saved evidence and an unexecuted notebook, without report writers."""
import ast
import json
from pathlib import Path

import pytest

from scripts.research.index_market.xxm import local_extrema_study as study


def test_changed_frozen_source_is_rejected(monkeypatch, tmp_path):
    case = study.CASES[0]
    path = tmp_path / case.path
    path.parent.mkdir(parents=True)
    path.write_text("[]")
    with pytest.raises(ValueError, match="frozen"):
        study.read_case(case, tmp_path)


def test_generated_scanner_sequence_has_literal_extrema_count():

    # Literal count only; memory/time measurement belongs to the separate study.
    from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import LocalExtremaScanner
    scanner = LocalExtremaScanner()
    count = 0
    for i in range(10_000):
        count += scanner.step(f"{i:09d}", (0, 1, 2, 1, 0)[i % 5]) is not None
    assert count == 3999 and scanner.count == 10_000


def test_protection_only_names_three_inputs_and_the_picture():
    expected = {case.path: case.sha256 for case in study.CASES}
    expected[study.IMAGE_PATH] = study.IMAGE_SHA256
    assert study.protected_files() == expected and len(expected) == 4
    assert all(name.startswith("reports/xxm/sources/") for name in expected)
    study.assert_protected(expected)


def test_wrong_identity_or_additional_code_path_is_not_accepted(monkeypatch):
    expected = study.protected_files()
    with monkeypatch.context() as guard:
        guard.setattr(study, "sha", lambda path: pytest.fail("must reject extra paths before reads"))
        with pytest.raises(ValueError):
            study.assert_protected({**expected, "src/unused.py": "digest"})
    calls = []
    def changed(path):
        calls.append(path)
        return "changed" if str(path).endswith(study.IMAGE_PATH) else expected[str(path.relative_to(study.ROOT))]
    monkeypatch.setattr(study, "sha", changed)
    with pytest.raises(ValueError, match="Changed"):
        study.assert_protected(expected)
    assert len(calls) == 4


def test_notebook_builder_does_no_io_or_execution(monkeypatch, tmp_path):
    out = tmp_path / "not-created"
    def fail(*args, **kwargs):
        raise AssertionError("notebook builder must not read, write or execute cells")
    with monkeypatch.context() as guard:
        guard.setattr(Path, "read_text", fail)
        guard.setattr(Path, "write_text", fail)
        guard.setattr("builtins.exec", fail)
        first, second = study.notebook(out), study.notebook(out)
    assert not out.exists()
    assert len(first["cells"]) == 8
    assert (first["nbformat"], first["nbformat_minor"]) == (4, 5)
    for cell in first["cells"]:
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None and cell["outputs"] == []
            ast.parse(cell["source"])
    first["cells"][0]["source"] = "changed"
    assert second["cells"][0]["source"].startswith("## tl;dr")
    joined = "\n".join(c["source"] for c in second["cells"])
    assert "from src.biz.services.wealth.market.index_detail_daily_wave.local_extrema import scan_values" in joined
    assert "saved['source'] == old_path" in joined and "result['source'] == new_path" in joined
    assert "del saved_values['source']" in joined


def test_retained_notebook_is_unexecuted_and_only_uses_current_imports():
    data = json.loads((study.ROOT / "reports/xxm/local-extrema/review.ipynb").read_text())
    assert len(data["cells"]) == 8
    for cell in data["cells"]:
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None and cell["outputs"] == []
            imports = [n.module for n in ast.walk(ast.parse(cell["source"])) if isinstance(n, ast.ImportFrom)]
            assert "scripts.research.index_market.xxm.local_extrema" not in imports
    assert "reports/xxm_local_extrema_trial_20261021_01" not in str(data)
