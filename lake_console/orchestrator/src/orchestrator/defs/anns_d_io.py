"""Columnar announcement candidates and immutable delivery evidence."""

import json
import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import (
    announcement_file_fingerprint,
    announcement_file_lock,
    announcement_fsync_directory,
    assert_safe_announcement_path,
)
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_COLUMNS_SQL,
    ANNOUNCEMENT_FIELDS,
    AnnouncementError,
    announcement_date,
    normalize_announcement_rows,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)


class AnnouncementStore:
    def __init__(self, root, staging, run_id, policy, control):
        if not run_id or not run_id.replace("-", "").replace("_", "").isalnum():
            raise AnnouncementError("announcement_invalid_run_id")
        self.root = assert_safe_announcement_path(root)
        self.staging = assert_safe_announcement_path(staging)
        self.policy, self.control = policy, control
        if not self.root.is_dir() or not self.staging.is_dir():
            raise AnnouncementError("announcement_volume_missing")
        if self.root == Path("/Volumes/datasource/data_lake") and self.staging != Path(
            "/Volumes/datasource/data_lake_staging"
        ):
            raise AnnouncementError("announcement_staging_root_contract")
        if "goldenshare-tushare-lake" in self.root.parts:
            raise AnnouncementError("announcement_retired_root")
        if self.staging == self.root or self.root in self.staging.parents:
            raise AnnouncementError("announcement_staging_inside_lake")
        self.device = self.root.stat().st_dev
        self.directory = self.staging / "anns_d" / f"run_id={run_id}"
        self.gate()
        self.directory.mkdir(parents=True, exist_ok=True)

    def gate(self):
        self.control.check()
        assert_safe_announcement_path(self.root)
        assert_safe_announcement_path(self.staging)
        if not self.root.is_dir() or not self.staging.is_dir():
            raise AnnouncementError("announcement_volume_missing")
        if (
            self.root.stat().st_dev != self.device
            or self.staging.stat().st_dev != self.device
        ):
            raise AnnouncementError("announcement_volume_changed")
        if self.root == Path("/Volumes/datasource/data_lake") and not os.path.ismount(
            "/Volumes/datasource"
        ):
            raise AnnouncementError("announcement_volume_not_mounted")
        if not os.access(self.root, os.W_OK) or not os.access(self.staging, os.W_OK):
            raise AnnouncementError("announcement_volume_not_writable")
        if shutil.disk_usage(self.staging).free < self.policy.min_free_reserve:
            raise AnnouncementError("announcement_disk_space")

    def target(self, day):
        announcement_date(day)
        from orchestrator.defs.paths import raw_anns_d_path

        return assert_safe_announcement_path(raw_anns_d_path(self.root, day))

    @contextmanager
    def connection(self):
        self.gate()
        settings = DuckDBConnectionSettings(
            temp_directory=self.directory / "spill",
            memory_limit=self.policy.duckdb_memory,
            threads=self.policy.duckdb_threads,
            max_temp_directory_size=self.policy.spill_limit,
        )
        with connect_configured_duckdb(settings) as connection:
            connection.execute("SET autoinstall_known_extensions=false")
            connection.execute("SET autoload_known_extensions=false")
            stopped = threading.Event()

            def observe():
                while not stopped.wait(0.1):
                    if self.control.cancelled():
                        connection.interrupt()
                        return
                    if time.monotonic() - self.control.last_report >= 5:
                        self.control.progress(phase="file_compute")

            monitor = threading.Thread(target=observe, daemon=True)
            monitor.start()
            try:
                yield connection
                self.control.check()
            except Exception:
                self.control.check()
                raise
            finally:
                stopped.set()
                monitor.join(timeout=1)

    def _candidate_path(self, path):
        path = assert_safe_announcement_path(path)
        if self.directory not in path.parents:
            raise AnnouncementError("announcement_candidate_outside_run")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_page(self, rows, path, control):
        path = self._candidate_path(path)
        rows = normalize_announcement_rows(rows)
        control.check()
        temporary = path.with_suffix(".partial.parquet")
        source_json = path.with_suffix(".input.json")
        # One bounded transport batch, not row-wise database insertion.
        with source_json.open("x", encoding="utf-8") as stream:
            json.dump(rows, stream, ensure_ascii=False, allow_nan=False)
        with self.connection() as connection:
            if rows:
                connection.read_json(
                    str(source_json),
                    format="array",
                    columns={field: "VARCHAR" for field in ANNOUNCEMENT_FIELDS},
                ).create_view("page_rows")
                sql = f"SELECT {ANNOUNCEMENT_COLUMNS_SQL} FROM page_rows"
            else:
                sql = (
                    "SELECT "
                    + ", ".join(
                        f"CAST(NULL AS VARCHAR) AS {field}"
                        for field in ANNOUNCEMENT_FIELDS
                    )
                    + " WHERE FALSE"
                )
            connection.execute(
                f"COPY ({sql}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(temporary)],
            )
        control.check()
        self.gate()
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        announcement_fsync_directory(path.parent)
        return path

    def _relation(self, connection, name, files):
        if not files:
            connection.execute(
                "CREATE OR REPLACE TEMP VIEW "
                + name
                + " AS SELECT "
                + ", ".join(
                    f"CAST(NULL AS VARCHAR) AS {field}" for field in ANNOUNCEMENT_FIELDS
                )
                + " WHERE FALSE"
            )
        else:
            for path in files:
                schema = connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                    [str(path)],
                ).fetchall()
                if [(row[0], row[1]) for row in schema] != [
                    (field, "VARCHAR") for field in ANNOUNCEMENT_FIELDS
                ]:
                    raise AnnouncementError("announcement_file_schema")
            connection.read_parquet(
                [str(path) for path in files], hive_partitioning=False
            ).create_view(name, replace=True)

    def audit_file(self, path, day):
        with self.connection() as connection:
            self._relation(connection, "candidate", [path])
            return self._audit_relation(connection, "candidate", day)

    def _audit_relation(self, connection, name, day):
        parsed = announcement_date(day).strftime("%Y%m%d")
        count, invalid, missing_url, missing_time = connection.execute(
            f"SELECT count(*),count(*) FILTER(WHERE ann_date IS NULL OR ann_date != ?),"
            f"count(*) FILTER(WHERE url IS NULL OR url=''),count(*) FILTER(WHERE rec_time IS NULL) FROM {name}",
            [parsed],
        ).fetchone()
        unique = connection.execute(
            f"SELECT count(*) FROM (SELECT DISTINCT {ANNOUNCEMENT_COLUMNS_SQL} FROM {name})"
        ).fetchone()[0]
        if invalid or count != unique:
            raise AnnouncementError("announcement_file_contract")
        return {
            "written_rows": count,
            "missing_url": missing_url,
            "missing_rec_time": missing_time,
        }

    def build_day(self, day, pages, *, bootstrap=False, month_connection=None):
        self.gate()
        target = self.target(day)
        baseline = announcement_file_fingerprint(target)
        candidate = self._candidate_path(
            self.directory
            / "candidates"
            / uuid.uuid4().hex
            / f"ann_date={day}"
            / "part-000.parquet"
        )
        with (
            self.connection()
            if month_connection is None
            else nullcontext(month_connection)
        ) as connection:
            if bootstrap and month_connection is not None and not pages:
                connection.execute(
                    "CREATE OR REPLACE TEMP VIEW source_pages AS SELECT * FROM announcement_month_rows"
                )
            else:
                self._relation(connection, "source_pages", pages)
            self._relation(connection, "existing", [target] if baseline else [])
            if baseline:
                self._audit_relation(connection, "existing", day)
            if bootstrap:
                connection.execute(
                    f"CREATE OR REPLACE TEMP TABLE incoming AS SELECT {ANNOUNCEMENT_COLUMNS_SQL} FROM source_pages WHERE ann_date=?",
                    [announcement_date(day).strftime("%Y%m%d")],
                )
            else:
                connection.execute(
                    f"CREATE OR REPLACE TEMP VIEW incoming AS SELECT {ANNOUNCEMENT_COLUMNS_SQL} FROM source_pages"
                )
            if bootstrap and baseline:
                conflicts = connection.execute(
                    "SELECT count(*) FROM ((SELECT * FROM existing EXCEPT SELECT * FROM incoming) UNION ALL (SELECT * FROM incoming EXCEPT SELECT * FROM existing))"
                ).fetchone()[0]
                if conflicts:
                    raise AnnouncementError("announcement_bootstrap_target_conflict")
            source_rows = connection.execute(
                "SELECT count(*) FROM incoming"
            ).fetchone()[0]
            existing_rows = connection.execute(
                "SELECT count(*) FROM existing"
            ).fetchone()[0]
            connection.execute(
                f"CREATE OR REPLACE TEMP VIEW merged AS SELECT DISTINCT {ANNOUNCEMENT_COLUMNS_SQL} FROM "
                f"(SELECT {ANNOUNCEMENT_COLUMNS_SQL} FROM existing UNION ALL SELECT {ANNOUNCEMENT_COLUMNS_SQL} FROM incoming)"
            )
            counts = self._audit_relation(connection, "merged", day)
            connection.execute(
                "COPY (SELECT "
                + ANNOUNCEMENT_COLUMNS_SQL
                + " FROM merged ORDER BY "
                + ANNOUNCEMENT_COLUMNS_SQL
                + ") TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",
                [str(candidate)],
            )
            self._relation(connection, "readback", [candidate])
            self._audit_relation(connection, "readback", day)
            delta = connection.execute(
                "SELECT count(*) FROM ((SELECT * FROM merged EXCEPT SELECT * FROM readback) "
                "UNION ALL (SELECT * FROM readback EXCEPT SELECT * FROM merged))"
            ).fetchone()[0]
            if delta:
                raise AnnouncementError("announcement_candidate_set_difference")
        self.gate()
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        announcement_fsync_directory(candidate.parent)
        return {
            **counts,
            "source_rows": source_rows,
            "existing_rows": existing_rows,
            "duplicate_rows": source_rows + existing_rows - counts["written_rows"],
            "new_unique_rows": counts["written_rows"] - existing_rows,
            "readback_rows": counts["written_rows"],
            "candidate": str(candidate),
            "baseline": baseline,
            "fingerprint": announcement_file_fingerprint(candidate),
        }

    def promote_day(self, day, evidence, checkpoint):
        target, candidate = self.target(day), Path(evidence["candidate"])
        self._candidate_path(candidate)
        with announcement_file_lock(
            self.staging / "anns_d" / "locks" / f"day-{day}.lock"
        ):
            self.gate()
            for page in evidence.get("source_pages", []):
                if announcement_file_fingerprint(page["path"]) != page["fingerprint"]:
                    raise AnnouncementError("announcement_delivery_source_changed")
            actual = announcement_file_fingerprint(target)
            if actual == evidence["fingerprint"]:
                checkpoint.save(phase="promoted", delivery=evidence)
                return "recovered"
            if actual != evidence["baseline"]:
                raise AnnouncementError("announcement_target_changed")
            if announcement_file_fingerprint(candidate) != evidence["fingerprint"]:
                raise AnnouncementError("announcement_candidate_changed")
            self.audit_file(candidate, day)
            checkpoint.save(phase="validated", delivery=evidence)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.gate()
            os.replace(candidate, target)
            announcement_fsync_directory(target.parent)
            checkpoint.save(phase="promoted", delivery=evidence)
            return "promoted"
