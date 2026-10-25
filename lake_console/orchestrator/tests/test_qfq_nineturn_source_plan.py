import os
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

import duckdb

from orchestrator.defs import qfq_nineturn as nineturn_module
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_nineturn_path,
    gold_stk_mins_qfq_path,
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.qfq_nineturn import (
    _nineturn_file_identity,
    build_gold_stk_mins_qfq_nineturn_partition_select_sql,
    plan_gold_stk_mins_qfq_nineturn_source,
    plan_gold_stock_daily_qfq_nineturn_source,
    validate_minute_nineturn_source_plan,
)

TARGET_DATE = "2026-08-07"
MINUTE_DATE = "2026-10-22"
PREVIOUS_DATE = "2026-10-21"


def _bar_time(year, month, day, hour, minute=0):
    # Gold's TIMESTAMP contract stores the explicit Shanghai wall clock without tzinfo.
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def _test_connection_config(root: Path) -> dict[str, str]:
    work = root / "duckdb_work"
    work.mkdir()
    return {
        "temp_directory": str(work),
        "max_temp_directory_size": "0B",
        "memory_limit": "256MB",
        "threads": "1",
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
    }


def _write_minute_source(connection, root, code, year, bars, *, freq=60):
    """Full eleven-column producer contract from GOLD_STK_MINS_QFQ_SCHEMA."""
    path = gold_stk_mins_qfq_path(root, freq, code, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        f"('{code}'::VARCHAR, {freq}::INTEGER, DATE '{time.date().isoformat()}', "
        f"TIMESTAMP '{time.isoformat(sep=' ')}', {price}::DOUBLE, "
        f"{price + .5}::DOUBLE, {price - .5}::DOUBLE, {price}::DOUBLE, "
        "100.0::DOUBLE, 1000.0::DOUBLE, 'SZ'::VARCHAR)"
        for time, price in bars
    )
    connection.execute(
        f"COPY (SELECT * FROM (VALUES {values}) AS rows("
        "ts_code,freq,trade_date,trade_time,open,high,low,close,vol,amount,exchange)) "
        f"TO '{path}' (FORMAT PARQUET)"
    )
    return path


def _write_minute_seed(connection, root, *, code="000001.SZ", freq=60):
    """Current eight-column nine-turn seed; literal prior up_count is eight."""
    path = gold_stk_mins_qfq_nineturn_path(root, freq, PREVIOUS_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        "COPY (SELECT "
        f"'{code}'::VARCHAR AS ts_code, {freq}::INTEGER AS freq, "
        f"DATE '{PREVIOUS_DATE}' AS trade_date, "
        f"TIMESTAMP '{PREVIOUS_DATE} 15:00:00' AS trade_time, "
        "8::INTEGER AS up_count, 0::INTEGER AS down_count, "
        "NULL::VARCHAR AS nine_up_turn, NULL::VARCHAR AS nine_down_turn) "
        f"TO '{path}' (FORMAT PARQUET)"
    )
    return path


def _minute_fixture(connection, root, *, freq=60, seeded=True, prior_year=2025):
    previous = _write_minute_source(
        connection, root, "000001.SZ", prior_year,
        [(_bar_time(prior_year, 12, day, 15), float(index + 1)) for index, day in enumerate((24, 25, 26, 29))],
        freq=freq,
    )
    current = _write_minute_source(
        connection, root, "000001.SZ", 2026,
        [(_bar_time(2026, 10, 22, 15), 10.0)], freq=freq,
    )
    seed = _write_minute_seed(connection, root, freq=freq) if seeded else None
    return previous, current, seed


class _ObservedConnection:
    """Run genuine SQL, injecting only the requested post-fetch file mutation."""
    def __init__(self, connection, after_fetch):
        self.connection = connection
        self.after_fetch = after_fetch
        self.queries = 0

    def execute(self, sql):
        self.queries += 1
        result = self.connection.execute(sql)
        number = self.queries
        callback = self.after_fetch

        class Result:
            def fetchall(self):
                rows = result.fetchall()
                callback(number)
                return rows

            def fetchone(self):
                row = result.fetchone()
                callback(number)
                return row

        return Result()


def _write_daily_source(connection, root: Path, trade_date: str, ts_code: str) -> None:
    path = gold_stock_daily_qfq_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT '{ts_code}'::VARCHAR AS ts_code,
            DATE '{trade_date}' AS trade_date,
            10.0::DOUBLE AS close
        ) TO '{path}' (FORMAT PARQUET)
        """
    )


def _write_previous_seed(connection, root: Path, trade_date: str, ts_code: str) -> None:
    path = gold_stock_daily_qfq_nineturn_path(root, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT '{ts_code}'::VARCHAR AS ts_code,
            DATE '{trade_date}' AS trade_date,
            1::INTEGER AS up_count,
            0::INTEGER AS down_count,
            NULL::VARCHAR AS nine_up_turn,
            NULL::VARCHAR AS nine_down_turn
        ) TO '{path}' (FORMAT PARQUET)
        """
    )


class QfqNineturnSourcePlanTests(unittest.TestCase):
    def test_daily_plan_uses_seeded_bounded_context_without_fallback(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            dates = tuple(
                (date(2026, 8, 2) + timedelta(days=offset)).isoformat()
                for offset in range(6)
            )
            for trade_date in dates:
                _write_daily_source(connection, root, trade_date, "000001.SZ")
            _write_previous_seed(connection, root, dates[-2], "000001.SZ")

            plan = plan_gold_stock_daily_qfq_nineturn_source(
                connection,
                lake_root=root,
                partition_key=TARGET_DATE,
                previous_trade_date=dates[-2],
            )

        self.assertEqual(plan.source_row_count, 1)
        self.assertEqual(plan.fallback_codes, ())
        self.assertEqual(plan.fallback_source_paths, ())
        self.assertEqual(plan.previous_partition_path.name, "part-000.parquet")
        self.assertIsNone(plan.input_file_identities)
        self.assertEqual(plan.history_candidate_codes, ())

    def test_daily_plan_selects_only_old_code_without_seed_for_fallback(self) -> None:
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            dates = tuple(
                (date(2026, 8, 2) + timedelta(days=offset)).isoformat()
                for offset in range(6)
            )
            for trade_date in dates:
                _write_daily_source(connection, root, trade_date, "000001.SZ")
            _write_previous_seed(connection, root, dates[-2], "000002.SZ")

            plan = plan_gold_stock_daily_qfq_nineturn_source(
                connection,
                lake_root=root,
                partition_key=TARGET_DATE,
                previous_trade_date=dates[-2],
            )

        self.assertEqual(plan.fallback_codes, ("000001.SZ",))
        self.assertEqual(len(plan.fallback_source_paths), 6)


class MinuteQfqNineturnSourcePlanTests(unittest.TestCase):
    def _plan(self, connection, root, *, freq=60, previous=PREVIOUS_DATE):
        return plan_gold_stk_mins_qfq_nineturn_source(
            connection,
            lake_root=root,
            freq=freq,
            partition_key=MINUTE_DATE,
            previous_trade_date=previous,
        )

    def _validate(self, root, plan, *, freq=60):
        validate_minute_nineturn_source_plan(
            lake_root=root, freq=freq, partition_key=MINUTE_DATE, source_plan=plan
        )

    def test_four_frequencies_keep_two_year_sources_and_literal_seed_result(self):
        for freq in (30, 60, 90, 120):
            with (
                self.subTest(freq=freq),
                TemporaryDirectory() as directory,
                duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
            ):
                root = Path(directory)
                prior, current, seed = _minute_fixture(connection, root, freq=freq)
                ignored = _write_minute_source(
                    connection, root, "000001.SZ", 2024,
                    [(_bar_time(2024, 10, 21, 15), 2.0)], freq=freq,
                )
                plan = self._plan(connection, root, freq=freq)
                self.assertEqual(plan.source_paths, tuple(sorted((prior, current))))
                self.assertEqual(plan.fallback_codes, ())
                self.assertEqual(plan.history_candidate_codes, ())
                self.assertEqual(plan.previous_partition_path, seed)
                self.assertEqual(plan.source_row_count, 1)
                self.assertEqual(
                    plan.input_file_identities,
                    tuple(sorted((p, _nineturn_file_identity(p)) for p in (prior, current, seed))),
                )
                self.assertNotIn(ignored, dict(plan.input_file_identities))
                self.assertNotIn(seed, plan.fingerprint_source_paths)
                self._validate(root, plan, freq=freq)
                rows = connection.execute(
                    build_gold_stk_mins_qfq_nineturn_partition_select_sql(
                        source_paths=plan.source_paths,
                        freq=freq,
                        target_trade_date=MINUTE_DATE,
                        previous_partition_path=plan.previous_partition_path,
                    )
                ).fetchall()
                # Four increasing prior bars, current close 10, and literal seed 8 => +9.
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][4:], (9, 0, "+9", None))
                self.assertEqual(
                    [
                        row[1]
                        for row in connection.execute(
                            f"DESCRIBE SELECT * FROM read_parquet('{current}', hive_partitioning=false)"
                        ).fetchall()
                    ],
                    ["VARCHAR", "INTEGER", "DATE", "TIMESTAMP", *(["DOUBLE"] * 6), "VARCHAR"],
                )

    def test_missing_whole_previous_partition_fails_before_query(self):
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            _minute_fixture(connection, root, seeded=False)
            observed = _ObservedConnection(connection, lambda _number: None)
            with self.assertRaises(FileNotFoundError):
                self._plan(observed, root)
            self.assertEqual(observed.queries, 0)

    def test_old_code_without_seed_uses_its_full_history(self):
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            history, current, _seed = _minute_fixture(connection, root, seeded=False, prior_year=2014)
            plan = self._plan(connection, root, previous=None)
            self.assertEqual(plan.source_paths, (current,))
            self.assertEqual(plan.fallback_codes, ("000001.SZ",))
            self.assertEqual(plan.history_candidate_codes, ("000001.SZ",))
            self.assertIn(history, dict(plan.input_file_identities))
            self.assertIn(history, plan.fallback_source_paths)
            rows = connection.execute(
                build_gold_stk_mins_qfq_nineturn_partition_select_sql(
                    source_paths=plan.source_paths, freq=60, target_trade_date=MINUTE_DATE,
                    fallback_source_paths=plan.fallback_source_paths,
                    fallback_codes=plan.fallback_codes,
                )
            ).fetchall()
            self.assertEqual(rows[0][4:], (1, 0, None, None))

    def test_each_planner_query_checks_source_and_seed_immediately(self):
        for query_number in (1, 2):
            for changed_input in ("source", "seed"):
                with (
                    self.subTest(query=query_number, changed=changed_input),
                    TemporaryDirectory() as directory,
                    duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
                ):
                    root = Path(directory)
                    _prior, current, seed = _minute_fixture(connection, root)
                    changed = current if changed_input == "source" else seed

                    def change_after_read(number, *, expected_query=query_number, changed_path=changed):
                        if number == expected_query:
                            value = changed_path.stat()
                            os.utime(changed_path, ns=(value.st_atime_ns, value.st_mtime_ns + 1000))

                    observed = _ObservedConnection(connection, change_after_read)
                    with self.assertRaisesRegex(ValueError, "input file changed"):
                        self._plan(observed, root)
                    self.assertEqual(observed.queries, query_number)

    def test_fallback_overlap_cannot_replace_the_first_identity(self):
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            _prior, current, _seed = _minute_fixture(connection, root, seeded=False)
            original = nineturn_module._bounded_candidate_codes

            def change_between_queries_and_history(*args, **kwargs):
                result = original(*args, **kwargs)
                value = current.stat()
                os.utime(current, ns=(value.st_atime_ns, value.st_mtime_ns + 1000))
                return result

            with (
                patch.object(nineturn_module, "_bounded_candidate_codes", side_effect=change_between_queries_and_history),
                self.assertRaisesRegex(ValueError, "changed before history query"),
            ):
                self._plan(connection, root, previous=None)

    def test_probed_history_without_final_fallback_is_protected(self):
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            history = _write_minute_source(
                connection, root, "000001.SZ", 2014,
                [(_bar_time(2014, 10, 21, 15), 2.0)],
            )
            _write_minute_source(
                connection, root, "000001.SZ", 2026,
                [(_bar_time(2026, 10, 22, 15), 10.0)],
            )
            plan = self._plan(connection, root, previous=None)
            self.assertEqual(plan.fallback_codes, ())
            self.assertEqual(plan.history_candidate_codes, ("000001.SZ",))
            self.assertNotIn(history, plan.fingerprint_source_paths)
            self.assertIn(history, dict(plan.input_file_identities))
            value = history.stat()
            os.utime(history, ns=(value.st_atime_ns, value.st_mtime_ns + 1000))
            with self.assertRaisesRegex(ValueError, "input file changed"):
                self._validate(root, plan)

    def test_history_changes_during_probe_fail_before_return(self):
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            history, _current, _seed = _minute_fixture(connection, root, seeded=False, prior_year=2014)

            def change_history(number):
                if number == 3:
                    value = history.stat()
                    os.utime(history, ns=(value.st_atime_ns, value.st_mtime_ns + 1000))

            observed = _ObservedConnection(connection, change_history)
            with self.assertRaisesRegex(ValueError, "input file changed"):
                self._plan(observed, root, previous=None)
            self.assertEqual(observed.queries, 3)

    def test_new_normal_source_file_is_not_ignored(self):
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            _minute_fixture(connection, root)
            plan = self._plan(connection, root)
            _write_minute_source(connection, root, "000002.SZ", 2026, [(_bar_time(2026, 10, 22, 15), 4.0)])
            with self.assertRaisesRegex(ValueError, "normal source path set changed"):
                self._validate(root, plan)

    def test_new_history_file_for_a_probed_code_is_not_ignored(self):
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            _write_minute_source(connection, root, "000001.SZ", 2026, [(_bar_time(2026, 10, 22, 15), 4.0)])
            plan = self._plan(connection, root, previous=None)
            self.assertEqual(plan.fallback_codes, ())
            _write_minute_source(connection, root, "000001.SZ", 2014, [(_bar_time(2014, 10, 21, 15), 3.0)])
            with self.assertRaisesRegex(ValueError, "candidate history path set changed"):
                self._validate(root, plan)

    def test_missing_identity_and_unsafe_candidate_scope_are_rejected(self):
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            _minute_fixture(connection, root, seeded=False)
            plan = self._plan(connection, root, previous=None)
            with self.assertRaisesRegex(ValueError, "requires frozen input identities"):
                self._validate(root, replace(plan, input_file_identities=None))
            for codes in (("../outside",), ("000001.SZ*",), ("?",), ("[ab]",), ("x\\y",), ("",), (" code",), (123,)):
                with self.subTest(codes=codes), self.assertRaisesRegex(ValueError, "history candidates"):
                    self._validate(root, replace(plan, history_candidate_codes=codes))
            for codes in (("000001.SZ", "000001.SZ"), (" 000001.SZ",), ("",)):
                with self.subTest(fallback=codes), self.assertRaisesRegex(ValueError, "normalized and unique"):
                    self._validate(root, replace(plan, fallback_codes=codes))

    def test_input_paths_reject_other_scope_symlinks_and_nonfiles(self):
        with (
            TemporaryDirectory() as directory,
            duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
        ):
            root = Path(directory)
            _prior, current, _seed = _minute_fixture(connection, root)
            plan = self._plan(connection, root)
            other = root / "other.parquet"
            other.write_bytes(b"not an input")
            records = tuple(sorted((*plan.input_file_identities, (other, _nineturn_file_identity(other)))))
            with self.assertRaisesRegex(ValueError, "outside its QFQ scope"):
                self._validate(root, replace(plan, input_file_identities=records))
            with self.assertRaisesRegex(ValueError, "regular file"):
                _nineturn_file_identity(root)
            with self.assertRaisesRegex(ValueError, "absolute"):
                _nineturn_file_identity(Path("relative.parquet"))
            current.unlink()
            current.symlink_to(other)
            with self.assertRaisesRegex(ValueError, "symlink"):
                self._validate(root, plan)

    def test_fallback_limit_applies_to_actual_history_not_new_candidates(self):
        for count, has_history in ((500, True), (501, True), (501, False)):
            with (
                self.subTest(count=count, history=has_history),
                TemporaryDirectory() as directory,
                duckdb.connect(":memory:", config=_test_connection_config(Path(directory))) as connection,
            ):
                root = Path(directory)
                for index in range(count):
                    bars = [(_bar_time(2026, 10, 22, 15), 10.0)]
                    if has_history:
                        bars = [
                            (_bar_time(2026, 10, 21, hour, minute), float(index + 1))
                            for index, (hour, minute) in enumerate(((10, 30), (11, 30), (14, 0), (15, 0)))
                        ] + bars
                    _write_minute_source(connection, root, f"{index:06d}.SZ", 2026, bars)
                plan = self._plan(connection, root, previous=None)
                self.assertEqual(len(plan.history_candidate_codes), count)
                self.assertEqual(len(plan.fallback_codes), count if has_history else 0)
                self.assertEqual(plan.source_row_count, count)
                kwargs = {
                    "source_paths": plan.source_paths, "freq": 60, "target_trade_date": MINUTE_DATE,
                    "fallback_source_paths": plan.fallback_source_paths, "fallback_codes": plan.fallback_codes,
                }
                if count == 501 and has_history:
                    with self.assertRaisesRegex(ValueError, "exceeds the daily-run limit"):
                        build_gold_stk_mins_qfq_nineturn_partition_select_sql(**kwargs)
                else:
                    self.assertIn("combined_output", build_gold_stk_mins_qfq_nineturn_partition_select_sql(**kwargs))


if __name__ == "__main__":
    unittest.main()
