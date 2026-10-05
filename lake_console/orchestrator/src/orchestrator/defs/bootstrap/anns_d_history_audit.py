"""Month-level set reconciliation, partition paths and immutable evidence."""

from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import (
    announcement_file_fingerprint,
    assert_safe_announcement_path,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_COLUMNS_SQL,
    AnnouncementError,
)
from orchestrator.defs.bootstrap.anns_d_history_plan import seal_history_document


def history_candidate_paths(month, store, checkpoint, *, formal=False):
    paths = []
    evidence = checkpoint.document
    if not evidence.get("capture_complete") or set(evidence.get("deliveries", {})) != {
        d["day"] for d in month["days"]
    }:
        raise AnnouncementError("announcement_history_not_built")
    for day in month["days"]:
        delivery = evidence["deliveries"][day["day"]]
        path = store.target(day["day"]) if formal else Path(delivery["candidate"])
        if not path.exists() and not formal:
            path = store.target(day["day"])
        assert_safe_announcement_path(path)
        if path != store.target(day["day"]) and store.directory not in path.parents:
            raise AnnouncementError("announcement_candidate_outside_staging")
        if announcement_file_fingerprint(path) != delivery["fingerprint"]:
            raise AnnouncementError("announcement_history_candidate_changed")
        if delivery["source_rows"] != day["source_rows"]:
            raise AnnouncementError("announcement_history_day_source_count")
        paths.append(path)
    return paths


def audit_announcement_history_month(plan, month, store, checkpoint, *, formal=False):
    paths = history_candidate_paths(month, store, checkpoint, formal=formal)
    pages = checkpoint.document["pages"]
    for page in pages:
        path = assert_safe_announcement_path(page["path"])
        if (
            store.directory not in path.parents
            or announcement_file_fingerprint(path) != page["fingerprint"]
        ):
            raise AnnouncementError("announcement_history_source_changed")
    if checkpoint.document["source_rows"] != month["source_rows"]:
        raise AnnouncementError("announcement_history_source_count")
    snapshots = {str(path): announcement_file_fingerprint(path) for path in paths}
    with store.connection() as connection:
        store._relation(connection, "history_source", [Path(p["path"]) for p in pages])
        store._relation(connection, "history_output", paths)
        connection.read_parquet(
            [str(path) for path in paths], hive_partitioning=False, filename=True
        ).create_view("history_output_files", replace=True)
        invalid = connection.execute(
            "SELECT count(*) FROM history_output_files WHERE ann_date IS NULL OR "
            "ann_date != replace(regexp_extract(filename, '/ann_date=([^/]+)/', 1), '-', '')"
        ).fetchone()[0]
        difference = connection.execute(
            f"SELECT count(*) FROM ((SELECT DISTINCT {ANNOUNCEMENT_COLUMNS_SQL} FROM history_source EXCEPT SELECT {ANNOUNCEMENT_COLUMNS_SQL} FROM history_output) "
            f"UNION ALL (SELECT {ANNOUNCEMENT_COLUMNS_SQL} FROM history_output EXCEPT SELECT DISTINCT {ANNOUNCEMENT_COLUMNS_SQL} FROM history_source))"
        ).fetchone()[0]
        source_rows = connection.execute(
            "SELECT count(*) FROM history_source"
        ).fetchone()[0]
        rows, unique = connection.execute(
            f"SELECT (SELECT count(*) FROM history_output), (SELECT count(*) FROM (SELECT DISTINCT {ANNOUNCEMENT_COLUMNS_SQL} FROM history_output))"
        ).fetchone()
        if (
            invalid
            or difference
            or rows != unique
            or source_rows != month["source_rows"]
        ):
            raise AnnouncementError("announcement_history_set_reconciliation")
        missing_url, missing_rec_time = connection.execute(
            "SELECT count(*) FILTER(WHERE url IS NULL OR url=''), count(*) FILTER(WHERE rec_time IS NULL) FROM history_output"
        ).fetchone()
        source_days = dict(
            connection.execute(
                "SELECT ann_date, count(*) FROM history_source GROUP BY ann_date LIMIT 32"
            ).fetchall()
        )
        for day in month["days"]:
            if source_days.get(day["day"].replace("-", ""), 0) != day["source_rows"]:
                raise AnnouncementError("announcement_history_day_source_count")
    for path in paths:
        if announcement_file_fingerprint(path) != snapshots[str(path)]:
            raise AnnouncementError("announcement_history_candidate_changed")
    for page in pages:
        if announcement_file_fingerprint(page["path"]) != page["fingerprint"]:
            raise AnnouncementError("announcement_history_source_changed")
    return seal_history_document(
        {
            "kind": "anns_d_history_audit",
            "plan_fingerprint": plan["fingerprint"],
            "month": month["month"],
            "formal": formal,
            "passed": True,
            "files": snapshots,
            "source_rows": source_rows,
            "written_rows": rows,
            "duplicate_rows": source_rows - rows,
            "missing_url": missing_url,
            "missing_rec_time": missing_rec_time,
            "rejected_rows": 0,
            "days": len(paths),
            "set_difference_rows": difference,
        }
    )
