"""CLI for the read-only major-index nine-turn history final audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestrator.defs.bootstrap.major_index_nineturn_history_audit import (
    audit_major_index_nineturn_history,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-report", required=True)
    parser.add_argument("--checkpoint-path", required=True)
    parser.add_argument("--output-path", required=True)
    args = parser.parse_args()
    report = audit_major_index_nineturn_history(
        plan_report_path=Path(args.plan_report),
        checkpoint_path=Path(args.checkpoint_path),
        output_path=Path(args.output_path),
    )
    print(
        json.dumps(
            {
                "output_path": str(Path(args.output_path).resolve()),
                "plan_fingerprint": report["plan_fingerprint"],
                "should_stop": report["should_stop"],
                "stop_reasons": report["stop_reasons"],
                "expected_target_file_count": report[
                    "expected_target_file_count"
                ],
                "actual_target_file_count": report["actual_target_file_count"],
                "expected_row_count": report["expected_row_count"],
                "actual_row_count": report["actual_row_count"],
                "elapsed_ms": report["elapsed_ms"],
            },
            ensure_ascii=False,
        )
    )
    return int(bool(report["should_stop"]))


if __name__ == "__main__":
    raise SystemExit(main())
