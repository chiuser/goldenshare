from __future__ import annotations

from pathlib import Path


def test_sync_v2_main_chain_does_not_contain_all_sentinel() -> None:
    sentinel = "_" * 2 + "ALL" + "_" * 2
    root = Path("src/foundation/services/sync_v2")
    offenders = [
        str(path)
        for path in root.rglob("*.py")
        if sentinel in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
