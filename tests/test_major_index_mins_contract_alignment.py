from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FOUNDATION_CONTRACT = (
    REPOSITORY_ROOT
    / "src/foundation/clients/local_lake/major_index_mins_contract.py"
)
ORCHESTRATOR_CONTRACT = (
    REPOSITORY_ROOT
    / "lake_console/orchestrator/src/orchestrator/defs/run_contracts/major_index_mins_technical.py"
)


def _literal_assignments(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments: dict[str, object] = {}
    for node in tree.body:
        name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                name = target.id
                value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        if name is None or value is None:
            continue
        try:
            assignments[name] = ast.literal_eval(value)
        except (ValueError, TypeError):
            continue
    return assignments


def test_foundation_reader_contract_matches_orchestrator_gold_contract() -> None:
    foundation = _literal_assignments(FOUNDATION_CONTRACT)
    orchestrator = _literal_assignments(ORCHESTRATOR_CONTRACT)

    assert foundation["SUPPORTED_INDEX_MINUTE_FREQS"] == orchestrator[
        "MAJOR_INDEX_MINS_TECHNICAL_FREQS"
    ]
    assert foundation["GOLD_INDICATOR_COLUMN_SPECS"] == tuple(
        (name, type_name)
        for name, type_name, _description in orchestrator[
            "GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_SPECS"
        ]
    )
    assert foundation["GOLD_PARAMS_KEY"] == orchestrator["PARAMS_KEY"]
    assert foundation["GOLD_INDICATOR_VERSION"] == orchestrator[
        "INDICATOR_VERSION"
    ]


def test_production_runtime_does_not_import_orchestrator_contract() -> None:
    forbidden_imports = (
        "lake_console.orchestrator",
        "orchestrator.defs.run_contracts.major_index_mins_technical",
    )
    violations: list[str] = []
    for path in (REPOSITORY_ROOT / "src").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for forbidden in forbidden_imports:
            if forbidden in source:
                violations.append(f"{path.relative_to(REPOSITORY_ROOT)}: {forbidden}")

    assert violations == []
