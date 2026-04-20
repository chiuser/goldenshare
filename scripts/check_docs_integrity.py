#!/usr/bin/env python3
"""Lightweight integrity checks for docs/.

Checks:
1. No dead absolute markdown links in docs/*.md.
2. No .DS_Store noise files in docs/.
3. docs/sources/tushare/docs_index.csv local_path entries point to real files.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
TUSHARE_INDEX = DOCS_DIR / "sources" / "tushare" / "docs_index.csv"
ABS_LINK_RE = re.compile(r"\]\((/Users/congming/github/goldenshare/[^)#]+)\)")


@dataclass
class CheckResult:
    name: str
    issues: list[str]

    @property
    def ok(self) -> bool:
        return not self.issues


def check_dead_absolute_links() -> CheckResult:
    issues: list[str] = []
    for md_file in sorted(DOCS_DIR.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        for match in ABS_LINK_RE.finditer(text):
            target = Path(match.group(1))
            if not target.exists():
                issues.append(f"{md_file}: missing link target -> {target}")
    return CheckResult("dead-absolute-links", issues)


def check_ds_store_noise() -> CheckResult:
    files = sorted(DOCS_DIR.rglob(".DS_Store"))
    issues = [str(path) for path in files]
    return CheckResult("ds-store-noise", issues)


def check_tushare_index_consistency() -> CheckResult:
    issues: list[str] = []
    if not TUSHARE_INDEX.exists():
        return CheckResult(
            "tushare-index-consistency",
            [f"missing index file: {TUSHARE_INDEX}"],
        )

    seen_local_paths: dict[str, int] = {}
    with TUSHARE_INDEX.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_fields = {"doc_id", "local_path"}
        if not required_fields.issubset(set(reader.fieldnames or [])):
            issues.append(
                f"{TUSHARE_INDEX}: missing required headers {sorted(required_fields)}"
            )
            return CheckResult("tushare-index-consistency", issues)

        for line_no, row in enumerate(reader, start=2):
            doc_id = (row.get("doc_id") or "").strip()
            local_path = (row.get("local_path") or "").strip()
            if not local_path:
                issues.append(f"{TUSHARE_INDEX}:{line_no}: empty local_path (doc_id={doc_id})")
                continue

            seen_local_paths[local_path] = seen_local_paths.get(local_path, 0) + 1
            target = TUSHARE_INDEX.parent / local_path
            if not target.exists():
                issues.append(
                    f"{TUSHARE_INDEX}:{line_no}: local_path not found: {local_path}"
                )
            elif target.suffix.lower() != ".md":
                issues.append(
                    f"{TUSHARE_INDEX}:{line_no}: local_path is not a markdown file: {local_path}"
                )

    for local_path, count in sorted(seen_local_paths.items()):
        if count > 1:
            issues.append(
                f"{TUSHARE_INDEX}: duplicate local_path {local_path!r} appears {count} times"
            )

    return CheckResult("tushare-index-consistency", issues)


def main() -> int:
    checks = [
        check_dead_absolute_links(),
        check_ds_store_noise(),
        check_tushare_index_consistency(),
    ]

    has_failure = False
    for result in checks:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}")
        for issue in result.issues:
            print(f"  - {issue}")
        if not result.ok:
            has_failure = True

    if has_failure:
        print("\nDocs integrity check failed.")
        return 1
    print("\nDocs integrity check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
