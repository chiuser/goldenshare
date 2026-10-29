from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    assert_expected_dates_registered,
    previous_expected_trade_date,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.io.stk_mins_qfq_publication import StkMinsQfqPublication
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import (
    silver_adj_factor_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_QFQ_NATIVE_FREQS,
    normalize_stk_mins_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    GoldStkMinsQfqDerivedDiagnostics,
    GoldStkMinsQfqFactorRepairPlan,
    GoldStkMinsQfqWriteResult,
    _create_replacement_rows_table,
    build_canonical_gold_stk_mins_qfq_diagnostics_sql_from_relation,
    build_canonical_gold_stk_mins_qfq_select_sql_from_relations,
    build_gold_stk_mins_qfq_factor_repair_plan,
    gold_stk_mins_qfq_source_freq,
    write_prepared_gold_stk_mins_qfq_rows_to_year_files,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger

LOGGER = DgStdoutLogger("stk_mins_qfq_factor_repair")


@dataclass(frozen=True)
class GoldStkMinsQfqFactorRepairCodeResult:
    ts_code: str
    rewritten_file_count: int
    rewritten_row_count: int
    write_results: tuple[GoldStkMinsQfqWriteResult, ...]


@dataclass(frozen=True)
class GoldStkMinsQfqFactorRepairResult:
    plan: GoldStkMinsQfqFactorRepairPlan
    repair_start_trade_date: str
    repair_end_trade_date: str
    selected_partition_count: int
    repaired_code_count: int
    skipped_code_count: int
    rewritten_file_count: int
    rewritten_row_count: int
    repaired_file_samples: tuple[str, ...]
    code_results: tuple[GoldStkMinsQfqFactorRepairCodeResult, ...]
    execution_model: str
    planned_batch_count: int
    executed_batch_count: int
    non_empty_batch_count: int
    derived_rewrite_required: bool
    derived_planned_batch_count: int
    derived_executed_batch_count: int
    derived_non_empty_batch_count: int
    derived_rewritten_file_count: int
    derived_rewritten_row_count: int
    derived_repaired_code_count: int
    derived_failed_code_count: int


@dataclass(frozen=True)
class GoldStkMinsQfqFactorRepairBatch:
    freq: int
    year: str
    partition_keys: tuple[str, ...]


def execute_gold_stk_mins_qfq_factor_repair(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    trade_date: str,
    expected_trade_dates: Sequence[str],
    registered_partition_keys: Sequence[str],
    freqs: Sequence[int | str] = STK_MINS_QFQ_NATIVE_FREQS,
    publication_id: str | None = None,
) -> GoldStkMinsQfqFactorRepairResult:
    normalized_trade_date = date.fromisoformat(trade_date).isoformat()
    expected_trade_dates = _normalize_expected_trade_dates(expected_trade_dates)
    if normalized_trade_date not in expected_trade_dates:
        raise dg.Failure(
            description=(
                "QFQ repair trade date is not in stock mins expected calendar: "
                f"trade_date={normalized_trade_date}."
            ),
            metadata={"trade_date": normalized_trade_date},
        )
    previous_trade_date = previous_expected_trade_date(
        expected_trade_dates,
        normalized_trade_date,
    )
    if previous_trade_date is None:
        raise dg.Failure(
            description=(
                "QFQ repair trade date has no previous expected trade date: "
                f"trade_date={normalized_trade_date}."
            ),
            metadata={"trade_date": normalized_trade_date},
        )
    selected_partition_keys = assert_expected_dates_registered(
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_partition_keys,
        partition_set_name=cn_a_stock_mins_silver_trade_days.name,
        start_trade_date=expected_trade_dates[0],
        end_trade_date=normalized_trade_date,
    )
    current_factor_path = silver_adj_factor_path(lake_root, normalized_trade_date)
    previous_factor_path = silver_adj_factor_path(lake_root, previous_trade_date)
    basic_path = silver_stock_basic_path(lake_root)
    lifecycle_path = silver_stock_lifecycle_path(lake_root)
    plan_input_paths = (current_factor_path, previous_factor_path, basic_path, lifecycle_path)
    plan_input_identities = _input_identities(plan_input_paths)
    plan = build_gold_stk_mins_qfq_factor_repair_plan(
        current_adj_factor_path=current_factor_path,
        previous_adj_factor_path=previous_factor_path,
        silver_stock_basic_path=basic_path,
        silver_stock_lifecycle_path=lifecycle_path,
        trade_date=normalized_trade_date,
        previous_trade_date=previous_trade_date,
    )
    _assert_inputs_unchanged(plan_input_paths, plan_input_identities)
    if not plan.can_execute_repair or not plan.repair_required:
        return GoldStkMinsQfqFactorRepairResult(
            plan=plan,
            repair_start_trade_date=selected_partition_keys[0],
            repair_end_trade_date=normalized_trade_date,
            selected_partition_count=len(selected_partition_keys),
            repaired_code_count=0,
            skipped_code_count=0,
            rewritten_file_count=0,
            rewritten_row_count=0,
            repaired_file_samples=(),
            code_results=(),
            execution_model="freq_year_batch",
            planned_batch_count=0,
            executed_batch_count=0,
            non_empty_batch_count=0,
            derived_rewrite_required=False,
            derived_planned_batch_count=0,
            derived_executed_batch_count=0,
            derived_non_empty_batch_count=0,
            derived_rewritten_file_count=0,
            derived_rewritten_row_count=0,
            derived_repaired_code_count=0,
            derived_failed_code_count=0,
        )

    normalized_freqs = tuple(normalize_stk_mins_freq(freq) for freq in freqs)
    as_of_adj_factor_path = silver_adj_factor_path(lake_root, normalized_trade_date)
    _require_existing_paths("as_of_adj_factor", (as_of_adj_factor_path,))

    batches = _build_repair_batches(
        freqs=normalized_freqs,
        selected_partition_keys=selected_partition_keys,
    )
    derived_target_freqs = _derived_target_freqs_for_native_freqs(normalized_freqs)
    write_results, derived_write_results = _execute_shared_source_repair(
        lake_root=lake_root,
        native_freqs=normalized_freqs,
        derived_freqs=derived_target_freqs,
        stock_codes=plan.repair_required_codes,
        selected_partition_keys=selected_partition_keys,
        as_of_adj_factor_path=as_of_adj_factor_path,
        publication_id=publication_id,
        plan_input_paths=plan_input_paths,
        plan_input_identities=plan_input_identities,
    )
    all_write_results = tuple(write_results) + derived_write_results
    code_results = _build_repair_code_results(
        repair_required_codes=plan.repair_required_codes,
        write_results=all_write_results,
    )
    repaired_file_samples = tuple(str(result.path) for result in write_results[:20])
    derived_repaired_codes = {
        write_result.ts_code for write_result in derived_write_results
    }
    derived_failed_code_count = (
        len(plan.repair_required_codes) - len(derived_repaired_codes)
        if derived_target_freqs
        else 0
    )

    return GoldStkMinsQfqFactorRepairResult(
        plan=plan,
        repair_start_trade_date=selected_partition_keys[0],
        repair_end_trade_date=normalized_trade_date,
        selected_partition_count=len(selected_partition_keys),
        repaired_code_count=len(
            _build_repair_code_results(
                repair_required_codes=plan.repair_required_codes,
                write_results=write_results,
            )
        ),
        skipped_code_count=0,
        rewritten_file_count=len(write_results),
        rewritten_row_count=sum(result.replacement_row_count for result in write_results),
        repaired_file_samples=repaired_file_samples,
        code_results=code_results,
        execution_model="freq_year_batch",
        planned_batch_count=len(batches),
        executed_batch_count=len(batches),
        non_empty_batch_count=len(_non_empty_batch_keys(write_results)),
        derived_rewrite_required=bool(derived_target_freqs),
        derived_planned_batch_count=len(derived_target_freqs)
        * len(_partition_keys_by_year(selected_partition_keys)),
        derived_executed_batch_count=len(derived_target_freqs)
        * len(_partition_keys_by_year(selected_partition_keys)),
        derived_non_empty_batch_count=len(_non_empty_batch_keys(derived_write_results)),
        derived_rewritten_file_count=len(derived_write_results),
        derived_rewritten_row_count=sum(
            result.replacement_row_count for result in derived_write_results
        ),
        derived_repaired_code_count=len(derived_repaired_codes),
        derived_failed_code_count=derived_failed_code_count,
    )


def _build_repair_batches(
    *,
    freqs: Sequence[int],
    selected_partition_keys: Sequence[str],
) -> tuple[GoldStkMinsQfqFactorRepairBatch, ...]:
    batches: list[GoldStkMinsQfqFactorRepairBatch] = []
    for freq in freqs:
        for year, year_partition_keys in _partition_keys_by_year(
            selected_partition_keys
        ).items():
            batches.append(
                GoldStkMinsQfqFactorRepairBatch(
                    freq=freq,
                    year=year,
                    partition_keys=year_partition_keys,
                )
            )
    return tuple(batches)


def _derived_target_freqs_for_native_freqs(freqs: Sequence[int]) -> tuple[int, ...]:
    normalized_freqs = {normalize_stk_mins_freq(freq) for freq in freqs}
    target_freqs: list[int] = []
    if 30 in normalized_freqs:
        target_freqs.append(90)
    if 60 in normalized_freqs:
        target_freqs.append(120)
    return tuple(target_freqs)


def _input_identities(paths: Sequence[Path]) -> tuple[tuple[int, ...], ...]:
    identities = []
    for path in paths:
        value = path.stat()
        identities.append((
            value.st_dev, value.st_ino, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns,
        ))
    return tuple(identities)


def _assert_inputs_unchanged(
    paths: Sequence[Path], identities: tuple[tuple[int, ...], ...],
) -> None:
    if _input_identities(paths) != identities:
        raise RuntimeError("QFQ factor repair inputs changed while preparing rows.")


def _load_repair_input(
    connection: duckdb.DuckDBPyConnection,
    *, table: str, paths: Sequence[Path], stock_codes: Sequence[str] = (),
) -> tuple[tuple[int, ...], ...]:
    identities = _input_identities(paths)
    path_list = ", ".join(duckdb_string(path) for path in paths)
    stock_filter = ""
    if stock_codes:
        values = ", ".join(duckdb_string(code) for code in stock_codes)
        stock_filter = f" WHERE CAST(ts_code AS VARCHAR) IN ({values})"
    connection.execute(
        f"CREATE TEMP TABLE {table} AS SELECT * FROM "
        f"read_parquet([{path_list}], hive_partitioning=false, union_by_name=true)"
        f"{stock_filter}"
    )
    _assert_inputs_unchanged(paths, identities)
    return identities


def _assert_repair_source_ready(
    connection: duckdb.DuckDBPyConnection,
    *, target_freq: int, partition_keys: Sequence[str], stock_codes: Sequence[str],
) -> None:
    row = connection.execute(
        build_canonical_gold_stk_mins_qfq_diagnostics_sql_from_relation(
            silver_relation_sql="SELECT * FROM qfq_repair_silver_input",
            target_freq=target_freq, partition_keys=partition_keys,
            stock_codes=stock_codes,
        )
    ).fetchone()
    if row is None:
        raise RuntimeError("Canonical Gold qfq source audit returned no row.")
    diagnostics = GoldStkMinsQfqDerivedDiagnostics(*(int(value) for value in row))
    if diagnostics.source_row_count == 0 or diagnostics.complete:
        return
    raise RuntimeError(
        "Canonical Gold qfq source windows are incomplete: "
        f"target_freq={target_freq}, source_freq={diagnostics.source_freq}, "
        f"source_rows={diagnostics.source_row_count}, "
        f"incomplete_windows={diagnostics.incomplete_window_count}, "
        f"exchange_mismatch_windows={diagnostics.exchange_mismatch_window_count}."
    )


def _execute_shared_source_repair(
    *, lake_root: Path, native_freqs: Sequence[int], derived_freqs: Sequence[int],
    stock_codes: Sequence[str], selected_partition_keys: Sequence[str],
    as_of_adj_factor_path: Path, publication_id: str | None,
    plan_input_paths: Sequence[Path],
    plan_input_identities: tuple[tuple[int, ...], ...],
) -> tuple[tuple[GoldStkMinsQfqWriteResult, ...], tuple[GoldStkMinsQfqWriteResult, ...]]:
    targets = tuple(native_freqs) + tuple(derived_freqs)
    if not targets:
        return (), ()
    native_results: list[GoldStkMinsQfqWriteResult] = []
    derived_results: list[GoldStkMinsQfqWriteResult] = []
    source_bytes = 0
    factor_bytes = 0
    with connect_configured_duckdb(temp_policy="existing_no_spill") as connection:
        as_of_identities = _load_repair_input(
            connection, table="qfq_repair_as_of_input", paths=(as_of_adj_factor_path,),
        )
        LOGGER.stdout(
            "factor_repair_as_of_loaded", file_count=1,
            stat_bytes=as_of_identities[0][2], target_code_count=len(stock_codes),
        )
        for year, year_dates in _partition_keys_by_year(selected_partition_keys).items():
            factor_paths = tuple(silver_adj_factor_path(lake_root, day) for day in year_dates)
            _require_existing_paths("silver_adj_factor", factor_paths)
            factor_identities = _load_repair_input(
                connection, table="qfq_repair_factor_input", paths=factor_paths,
            )
            factor_bytes += sum(item[2] for item in factor_identities)
            LOGGER.stdout(
                "factor_repair_year_factor_loaded", year=year,
                file_count=len(factor_paths), cumulative_stat_bytes=factor_bytes,
            )
            try:
                for source_freq in sorted({gold_stk_mins_qfq_source_freq(f) for f in targets}):
                    source_paths = tuple(
                        silver_stk_mins_path(lake_root, source_freq, day) for day in year_dates
                    )
                    _require_existing_paths("silver_stk_mins", source_paths)
                    source_identities = _load_repair_input(
                        connection, table="qfq_repair_silver_input",
                        paths=source_paths, stock_codes=stock_codes,
                    )
                    source_bytes += sum(item[2] for item in source_identities)
                    LOGGER.stdout(
                        "factor_repair_source_loaded", year=year, source_freq=source_freq,
                        file_count=len(source_paths), cumulative_stat_bytes=source_bytes,
                        target_code_count=len(stock_codes),
                    )
                    try:
                        for target_freq in targets:
                            if gold_stk_mins_qfq_source_freq(target_freq) != source_freq:
                                continue
                            _assert_repair_source_ready(
                                connection, target_freq=target_freq,
                                partition_keys=year_dates, stock_codes=stock_codes,
                            )
                            _assert_inputs_unchanged(plan_input_paths, plan_input_identities)
                            _assert_inputs_unchanged(factor_paths, factor_identities)
                            _assert_inputs_unchanged(source_paths, source_identities)
                            with StkMinsQfqPublication(
                                lake_root=lake_root, family="qfq", freq=target_freq,
                                trade_dates=year_dates, publication_id=publication_id,
                            ) as publication:
                                try:
                                    select_sql = build_canonical_gold_stk_mins_qfq_select_sql_from_relations(
                                        silver_relation_sql="SELECT * FROM qfq_repair_silver_input",
                                        trade_adj_factor_relation_sql="SELECT * FROM qfq_repair_factor_input",
                                        as_of_adj_factor_relation_sql="SELECT * FROM qfq_repair_as_of_input",
                                        target_freq=target_freq, partition_keys=year_dates,
                                        stock_codes=stock_codes,
                                    )
                                    _create_replacement_rows_table(connection, select_sql)
                                    _assert_inputs_unchanged(plan_input_paths, plan_input_identities)
                                    _assert_inputs_unchanged(factor_paths, factor_identities)
                                    _assert_inputs_unchanged(source_paths, source_identities)
                                    results = write_prepared_gold_stk_mins_qfq_rows_to_year_files(
                                        connection, publication=publication, lake_root=lake_root,
                                        freq=target_freq, replace_trade_dates=year_dates,
                                        allow_empty_replacement=True,
                                    )
                                finally:
                                    connection.execute("DROP TABLE IF EXISTS qfq_replacement_rows")
                            (native_results if target_freq in native_freqs else derived_results).extend(results)
                            LOGGER.stdout(
                                "factor_repair_target_completed", year=year, freq=target_freq,
                                output_file_count=len(results),
                                replacement_row_count=sum(r.replacement_row_count for r in results),
                                cumulative_source_stat_bytes=source_bytes,
                            )
                    finally:
                        connection.execute("DROP TABLE IF EXISTS qfq_repair_silver_input")
            finally:
                connection.execute("DROP TABLE IF EXISTS qfq_repair_factor_input")
    return tuple(native_results), tuple(derived_results)


def _require_existing_paths(label: str, paths: Sequence[Path]) -> None:
    missing_paths = tuple(path for path in paths if not path.exists())
    if missing_paths:
        samples = ", ".join(str(path) for path in missing_paths[:5])
        raise FileNotFoundError(f"Missing qfq repair {label} input files: {samples}")


def _build_repair_code_results(
    *,
    repair_required_codes: Sequence[str],
    write_results: Sequence[GoldStkMinsQfqWriteResult],
) -> tuple[GoldStkMinsQfqFactorRepairCodeResult, ...]:
    by_code: dict[str, list[GoldStkMinsQfqWriteResult]] = {
        code: [] for code in repair_required_codes
    }
    for write_result in write_results:
        by_code.setdefault(write_result.ts_code, []).append(write_result)

    code_results: list[GoldStkMinsQfqFactorRepairCodeResult] = []
    for stock_code in repair_required_codes:
        stock_write_results = tuple(by_code.get(stock_code, ()))
        if not stock_write_results:
            continue
        code_results.append(
            GoldStkMinsQfqFactorRepairCodeResult(
                ts_code=stock_code,
                rewritten_file_count=len(stock_write_results),
                rewritten_row_count=sum(
                    result.replacement_row_count for result in stock_write_results
                ),
                write_results=stock_write_results,
            )
        )
    return tuple(code_results)


def _non_empty_batch_keys(
    write_results: Sequence[GoldStkMinsQfqWriteResult],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                (write_result.path.parent.parent.parent.name, write_result.year)
                for write_result in write_results
            }
        )
    )


def _normalize_expected_trade_dates(
    expected_trade_dates: Sequence[str],
) -> tuple[str, ...]:
    normalized_trade_dates = tuple(
        sorted(
            {
                date.fromisoformat(str(trade_date).strip()).isoformat()
                for trade_date in expected_trade_dates
            }
        )
    )
    if not normalized_trade_dates:
        raise dg.Failure(
            description="QFQ repair expected trade date calendar is empty.",
            metadata={},
        )
    return normalized_trade_dates


def _partition_keys_by_year(partition_keys: Sequence[str]) -> dict[str, tuple[str, ...]]:
    years = sorted({partition_key[:4] for partition_key in partition_keys})
    return {
        year: tuple(
            partition_key
            for partition_key in partition_keys
            if partition_key[:4] == year
        )
        for year in years
    }
