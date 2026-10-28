"""LLD12 current-delivery SQL capacity, with real SDK/SQLite metadata.

The shared scenario supplies at most four real tiny producer files. Capacity
entries are explicitly synthetic metadata, not 100 source downloads or a claim
that 100 Parquet contents were verified. Only those virtual entries' stat values
are replaced by independent five-integer literals. All event storage SQL, ranking,
decoding, latest failures and bound materializations execute for real.
PostgreSQL dialect compilation is reported as compilation, not PG execution.
"""

from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import dagster as dg
import pytest
from sqlalchemy.dialects import postgresql

from orchestrator.defs import stock_period_update as update
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import digest, execution_id
from tests.test_stock_period_delivery_confirmation import (
    _emit,
    _emit_checks,
    _scenario,
)


def _capacity_receipt(case, counts, monkeypatch):
    old = raw.read_json(Path(case["old"]["path"]) / "manifest.json")
    items, versions, periods = [], {}, {}
    for frequency, count in counts.items():
        periods[frequency] = []
        for index in range(count):
            if frequency == "week":
                period = (date(2014, 1, 3) + timedelta(days=7 * index)).isoformat()
                relative = f"raw/tushare/stk_period_bar_adj_week/week_end={period}/part-000.parquet"
            else:
                period = f"{2014 + index // 12:04d}-{index % 12 + 1:02d}"
                # paths.raw_stock_monthly_path uses data.parquet for monthly Raw.
                relative = f"raw/tushare/stk_period_bar_adj_month/month={period}/data.parquet"
            # Contract-valid virtual metadata; physical file identity is the only replaced layer.
            version = [17, 2000 + len(items), 100, 3000 + len(items), 4000 + len(items)]
            target = str(case["root"] / relative)
            versions[target] = version
            periods[frequency].append(period)
            items.append({
                "freq": frequency, "period": period, "target": target,
                "version": version, "rows": 1, "sha256": f"{len(items) + 1:064x}",
                "target_preimage": None,
            })
    intent = {
        **old["identity"]["intent"], "frequencies": list(counts), "periods": periods,
        "request_id": f"capacity-{counts}",
    }
    identity = {**old["identity"], "intent": intent}
    run_id = execution_id(intent["request_id"])
    run = case["staging"] / "stock_period/runs" / run_id
    run.mkdir()
    complete = {"run_id": run_id, "files": items, "unit_asofs": {}}
    raw.atomic_json(run / "complete.json", complete)
    raw.atomic_json(run / "manifest.json", {
        **old, "phase": "files_complete", "identity": identity,
        "identity_hash": digest(identity), "file_receipt_hash": digest(complete),
    })
    result = {**complete, "path": str(run)}
    mats = _emit(case["instance"], result)
    real_stat = update._period_delivery_stat

    def capacity_stat(path):
        return versions[str(path)] if str(path) in versions else real_stat(path)

    monkeypatch.setattr(update, "_period_delivery_stat", capacity_stat)
    return result, mats


@contextmanager
def _count_storage_statements(storage, monkeypatch):
    original = storage.index_connection
    statements = []

    class TransparentConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, *args, **kwargs):
            statements.append(statement)
            return self.connection.execute(statement, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    @contextmanager
    def observed_connection(*args, **kwargs):
        with original(*args, **kwargs) as connection:
            yield TransparentConnection(connection)

    monkeypatch.setattr(storage, "index_connection", observed_connection)
    yield statements


@pytest.mark.parametrize("file_count", [2, 100])
def test_current_two_and_hundred_files_use_same_three_storage_queries(file_count, monkeypatch):
    with _scenario(successor=False) as case:
        result, mats = _capacity_receipt(case, {"week": file_count}, monkeypatch)
        before = len(case["requests"])
        with _count_storage_statements(case["instance"].event_log_storage, monkeypatch) as statements:
            confirmed = update.confirm_period_delivery(
                case["instance"], Path(result["path"]), root=case["root"], staging=case["staging"],
            )
        assert confirmed["events_complete"] is True and confirmed["historical_only"] is False
        assert len(confirmed["file_evidence"]) == len(confirmed["current_files"]) == file_count
        assert len(statements) == 3  # One notice + one latest-Mat collection + one latest-check collection.
        assert len(case["requests"]) == before
        for key, evidence in confirmed["file_evidence"].items():
            assert evidence["materialization_id"] == mats[key].storage_id
            assert len(evidence["checks"]) == 3
        # The actual executed SQLite expressions also compile for PG; this is not a PG run.
        compiled = [str(statement.compile(dialect=postgresql.dialect())).lower() for statement in statements]
        assert sum("row_number()" in statement for statement in compiled) == 1
        assert sum("max(event_logs.id)" in statement for statement in compiled) == 2
        assert "nulls first" in next(statement for statement in compiled if "row_number()" in statement)


def test_batch_latest_failed_does_not_become_missing_or_old_success(monkeypatch):
    with _scenario(successor=False) as case:
        result, mats = _capacity_receipt(case, {"week": 100}, monkeypatch)
        item = result["files"][0]
        _emit_checks(case["instance"], item, mats[("week", item["period"])], passed=False)
        with (
            _count_storage_statements(case["instance"].event_log_storage, monkeypatch) as statements,
            pytest.raises(ValueError, match="period_delivery_checks_invalid"),
        ):
            update.confirm_period_delivery(
                case["instance"], Path(result["path"]), root=case["root"], staging=case["staging"],
            )
        assert len(statements) == 3
        assert not (Path(result["path"]) / "events").exists()


def test_batch_late_wrong_target_is_not_a_missing_result(monkeypatch):
    with _scenario(successor=False) as case:
        result, mats = _capacity_receipt(case, {"week": 2}, monkeypatch)
        first, second = result["files"]
        _emit_checks(case["instance"], first, mats[("week", second["period"])], passed=True)
        with (
            _count_storage_statements(case["instance"].event_log_storage, monkeypatch) as statements,
            pytest.raises(ValueError, match="period_check_evidence_target_invalid"),
        ):
            update.confirm_period_delivery(
                case["instance"], Path(result["path"]), root=case["root"], staging=case["staging"],
            )
        assert len(statements) == 3
        assert not (Path(result["path"]) / "events").exists()


def test_batch_exact_asset_partition_pairs_ignore_corrupt_other_pair(monkeypatch):
    with _scenario(successor=False, frequencies=("week", "month")) as case:
        result, _ = _capacity_receipt(case, {"week": 1, "month": 1}, monkeypatch)
        # Intentionally corrupt data outside requested pairs: week asset + month partition.
        # Neither original producer nor expected business data uses this cross pair.
        from dagster._core.storage.event_log.schema import (
            AssetCheckExecutionsTable as Checks,
        )

        week_asset = dg.AssetKey("raw_tushare_stk_period_bar_adj_week")
        with case["instance"].event_log_storage.index_connection() as connection:
            connection.execute(Checks.insert().values(
                asset_key=week_asset.to_string(), partition="2014-01", run_id="outside-pair",
                check_name="raw_tushare_stk_period_bar_adj_week_file_contract_check",
                execution_status="FAILED", evaluation_event_storage_id=None,
            ))
        with _count_storage_statements(case["instance"].event_log_storage, monkeypatch) as statements:
            confirmed = update.confirm_period_delivery(
                case["instance"], Path(result["path"]), root=case["root"], staging=case["staging"],
            )
        assert confirmed["events_complete"] is True
        assert set(confirmed["file_evidence"]) == {("week", "2014-01-03"), ("month", "2014-01")}
        assert len(statements) == 4  # Two frequencies, still only two collection queries.


def test_two_frequencies_share_one_successor_receipt_read(monkeypatch):
    with _scenario(frequencies=("week", "month"), successor_frequencies=("week", "month")) as case:
        watched = {
            str(Path(case["old"]["path"]) / "complete.json"): 0,
            str(Path(case["new"]["path"]) / "complete.json"): 0,
            str(Path(case["new"]["path"]) / "manifest.json"): 0,
        }
        actual_read = raw.read_json

        def counted_read(path):
            if str(path) in watched:
                watched[str(path)] += 1
            return actual_read(path)

        monkeypatch.setattr(update, "read_json", counted_read)
        monkeypatch.setattr(history, "read_json", counted_read)
        confirmed = update.confirm_period_delivery(
            case["instance"], Path(case["old"]["path"]), root=case["root"], staging=case["staging"],
        )
        assert confirmed["events_complete"] is True and confirmed["historical_only"] is True
        assert len(confirmed["file_evidence"]) == 2
        assert set(watched.values()) == {1}


def test_cached_successor_json_version_change_refuses_second_unit(monkeypatch):
    with _scenario(frequencies=("week", "month"), successor_frequencies=("week", "month")) as case:
        successor = Path(case["new"]["path"])
        complete_path = successor / "complete.json"
        unchanged_content = raw.read_json(complete_path)
        actual_json = update._period_delivery_json
        changed = False

        def replace_after_first_unit(path, controls):
            nonlocal changed
            value = actual_json(path, controls)
            if Path(path) == successor / "committed/week/2026-10-23.json" and not changed:
                changed = True
                # Same contents, different filesystem identity: cached data must not be reused.
                raw.atomic_json(complete_path, unchanged_content)
            return value

        monkeypatch.setattr(update, "_period_delivery_json", replace_after_first_unit)
        with pytest.raises(ValueError, match="period_delivery_control_changed"):
            update.confirm_period_delivery(
                case["instance"], Path(case["old"]["path"]), root=case["root"], staging=case["staging"],
            )
        assert changed
        assert raw.read_json(case["staging"] / "stock_period/daily.json") == case["daily"]


@pytest.mark.parametrize("file_count", [2, 100])
@pytest.mark.parametrize("existing_receipts", [False, True])
def test_ack_control_stats_remain_linear(file_count, existing_receipts, monkeypatch):
    with _scenario(successor=False) as case:
        result, _ = _capacity_receipt(case, {"week": file_count}, monkeypatch)
        run = Path(result["path"])
        if existing_receipts:
            for item in result["files"]:
                raw.atomic_json(
                    run / "events/week" / (item["period"] + ".json"),
                    {key: item[key] for key in ("version", "sha256")},
                )
        confirmation = update.confirm_period_delivery(
            case["instance"], run, root=case["root"], staging=case["staging"]
        )
        actual_stat = update._period_delivery_stat
        calls = []

        def counted_stat(path):
            calls.append(str(path))
            return actual_stat(path)

        monkeypatch.setattr(update, "_period_delivery_stat", counted_stat)
        outcome = update.acknowledge_period_delivery(
            run, confirmation, root=case["root"], staging=case["staging"]
        )
        assert outcome["events_complete"] is True
        assert not outcome["pending_removed"]  # This capacity run has no daily work.
        # A linear bound independently rejects the former N * controls scan.
        # These are metadata stat calls, not a benchmark of 100 Parquet bodies.
        assert len(calls) <= 40 * file_count + 80


@pytest.mark.parametrize("file_count", [2, 100])
def test_partial_two_and_hundred_files_keep_three_queries_and_linear_receipt_stats(file_count, monkeypatch):
    with _scenario(successor=False) as case:
        result, _ = _capacity_receipt(case, {"week": file_count, "month": 1}, monkeypatch)
        run = Path(result["path"])
        daily = (case["staging"] / "stock_period/daily.json").read_bytes()
        manifest = (run / "manifest.json").read_bytes()
        with _count_storage_statements(case["instance"].event_log_storage, monkeypatch) as statements:
            confirmation = update.confirm_period_delivery(case["instance"], run,
                root=case["root"], staging=case["staging"], allowed_frequencies={"week"})
        assert len(statements) == 3
        assert confirmation["allowed_events_complete"] and not confirmation["events_complete"]
        assert len(confirmation["file_evidence"]) == file_count
        real_stat, calls = update._period_delivery_stat, []

        def counted(path):
            calls.append(str(path))
            assert "/events/month/" not in str(path)
            assert not str(path).endswith("/completion/month.json")
            return real_stat(path)

        monkeypatch.setattr(update, "_period_delivery_stat", counted)
        outcome = update.acknowledge_period_delivery(run, confirmation,
            root=case["root"], staging=case["staging"])
        assert outcome == {"run_id": run.name, "allowed_events_complete": True,
                           "events_complete": False, "pending_removed": False}
        assert len(calls) <= 40 * file_count + 80
        assert (run / "manifest.json").read_bytes() == manifest
        assert (case["staging"] / "stock_period/daily.json").read_bytes() == daily


def test_ack_binds_two_frequency_successor_proof_without_rereading_complete(monkeypatch):
    with _scenario(frequencies=("week", "month"), successor_frequencies=("week", "month")) as case:
        run, successor = Path(case["old"]["path"]), Path(case["new"]["path"])
        confirmation = update.confirm_period_delivery(case["instance"], run,
            root=case["root"], staging=case["staging"])
        watched = {successor / "manifest.json": 0, successor / "complete.json": 0,
                   successor / "committed/week/2026-10-23.json": 0,
                   successor / "committed/month/2026-10.json": 0}
        real_read = update.read_json

        def read(path):
            if Path(path) in watched:
                watched[Path(path)] += 1
            return real_read(path)

        monkeypatch.setattr(update, "read_json", read)
        outcome = update.acknowledge_period_delivery(run, confirmation,
            root=case["root"], staging=case["staging"])
        assert outcome["events_complete"] and outcome["pending_removed"]
        assert watched == {successor / "manifest.json": 1, successor / "complete.json": 0,
                           successor / "committed/week/2026-10-23.json": 1,
                           successor / "committed/month/2026-10.json": 1}
