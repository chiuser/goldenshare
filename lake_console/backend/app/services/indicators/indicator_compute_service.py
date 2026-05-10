from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.services.indicators.indicator_by_date_writer import IndicatorByDateWriter
from lake_console.backend.app.services.indicators.indicator_source_reader import (
    iter_stk_mins_research_source_batches,
    plan_stk_mins_research_source_batches,
    read_stk_mins_all_source_rows,
    read_stk_mins_source_rows,
)
from lake_console.backend.app.services.indicators.indicator_state_store import MacdStateStore
from lake_console.backend.app.services.indicators.macd_calculator import calculate_macd
from lake_console.backend.app.services.indicators.macd_spec import DEFAULT_MACD_PARAMS
from lake_console.backend.app.services.indicators.models import MacdState


class StkMinsIndicatorComputeService:
    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or print

    def compute_macd(
        self,
        *,
        mode: str,
        freq: int,
        start_date: date,
        end_date: date,
        ts_code: str | None = None,
        all_market: bool = False,
    ) -> dict[str, Any]:
        if mode not in {"full", "incremental"}:
            raise ValueError("mode 仅支持 full 或 incremental。")
        if all_market and ts_code:
            raise ValueError("all_market 与 ts_code 不能同时传。")
        if not all_market and not ts_code:
            raise ValueError("单股票模式必须传 ts_code。")
        run_id = _run_id("compute-stk-mins-macd")
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        ts_code_value = ts_code.strip() if ts_code else None
        scope = "all_market" if all_market else str(ts_code_value)

        self.progress(
            f"[indicator_macd] start run_id={run_id} mode={mode} scope={scope} "
            f"freq={freq} start_date={start_date.isoformat()} end_date={end_date.isoformat()}"
        )
        if all_market:
            return self._compute_macd_all_market(
                mode=mode,
                freq=freq,
                start_date=start_date,
                end_date=end_date,
                run_id=run_id,
                started_at=started_at,
                started=started,
            )
        return self._compute_macd_single_symbol(
            mode=mode,
            ts_code=str(ts_code_value),
            freq=freq,
            start_date=start_date,
            end_date=end_date,
            run_id=run_id,
            started_at=started_at,
            started=started,
        )

    def _compute_macd_single_symbol(
        self,
        *,
        mode: str,
        ts_code: str,
        freq: int,
        start_date: date,
        end_date: date,
        run_id: str,
        started_at: datetime,
        started: float,
    ) -> dict[str, Any]:
        source_rows = read_stk_mins_source_rows(
            lake_root=self.lake_root,
            ts_code=ts_code,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
        )
        if not source_rows:
            raise RuntimeError(
                f"没有读取到源分钟线行：ts_code={ts_code} freq={freq} "
                f"date_range={start_date.isoformat()}~{end_date.isoformat()}"
            )
        self.progress(f"[indicator_macd] source_rows={len(source_rows)}")

        state_store = MacdStateStore(lake_root=self.lake_root)
        initial_state = state_store.get_state(ts_code=ts_code, freq=freq)
        if mode == "incremental" and initial_state is None:
            raise RuntimeError(
                f"needs_bootstrap: 缺少 MACD state，需先执行 full：ts_code={ts_code} freq={freq}"
            )
        calculation = calculate_macd(
            source_rows,
            params=DEFAULT_MACD_PARAMS,
            initial_state=initial_state if mode == "incremental" else None,
        )
        if not calculation.rows:
            elapsed = time.monotonic() - started
            self.progress(
                f"[indicator_macd] no_op ts_code={ts_code} freq={freq} source_rows={len(source_rows)} "
                f"elapsed={round(elapsed, 3)}s"
            )
            return {
                "operation": "compute_stk_mins_indicator",
                "indicator": "macd",
                "params_key": DEFAULT_MACD_PARAMS.params_key,
                "mode": mode,
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "scope": "single",
                "ts_code": ts_code,
                "freq": freq,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "source_rows": len(source_rows),
                "indicator_rows": 0,
                "written_rows": 0,
                "state_updates": 0,
                "status": "no_op",
                "elapsed_seconds": round(elapsed, 3),
            }
        if calculation.final_state is None:
            raise RuntimeError("MACD 计算未生成 final_state。")
        if mode == "full" and initial_state is not None and initial_state.last_trade_time > calculation.final_state.last_trade_time:
            raise RuntimeError(
                "state_regression: 已有 MACD state 晚于本次 full 计算结果，"
                f"existing={initial_state.last_trade_time} computed={calculation.final_state.last_trade_time}"
            )

        write_summary = IndicatorByDateWriter(lake_root=self.lake_root).write_rows(
            calculation.rows,
            indicator="macd",
            params_key=DEFAULT_MACD_PARAMS.params_key,
            freq=freq,
            run_id=run_id,
        )
        merged_states = _merge_state(
            existing=state_store.load_states(params=DEFAULT_MACD_PARAMS),
            state=calculation.final_state,
        )
        state_summary = state_store.replace_states_after_result_write(
            merged_states,
            result_summary=write_summary,
            params=DEFAULT_MACD_PARAMS,
            run_id=run_id,
        )
        elapsed = time.monotonic() - started
        self.progress(
            f"[indicator_macd] done ts_code={ts_code} freq={freq} source_rows={len(source_rows)} "
            f"written={write_summary['written_rows']} state_updates=1 elapsed={round(elapsed, 3)}s"
        )
        return {
            "operation": "compute_stk_mins_indicator",
            "indicator": "macd",
            "params_key": DEFAULT_MACD_PARAMS.params_key,
            "mode": mode,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "scope": "single",
            "ts_code": ts_code,
            "freq": freq,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source_rows": len(source_rows),
            "indicator_rows": len(calculation.rows),
            "written_rows": write_summary["written_rows"],
            "state_updates": 1,
            "status": "success",
            "by_date_write": write_summary,
            "state_write": state_summary,
            "elapsed_seconds": round(elapsed, 3),
        }

    def _compute_macd_all_market(
        self,
        *,
        mode: str,
        freq: int,
        start_date: date,
        end_date: date,
        run_id: str,
        started_at: datetime,
        started: float,
    ) -> dict[str, Any]:
        state_store = MacdStateStore(lake_root=self.lake_root)
        existing_states = state_store.load_states(params=DEFAULT_MACD_PARAMS)
        source_rows_total = 0
        indicator_rows_total = 0
        state_updates: list[MacdState] = []
        processed_symbols = 0

        if mode == "full":
            return self._compute_macd_all_market_full_streaming(
                freq=freq,
                start_date=start_date,
                end_date=end_date,
                run_id=run_id,
                started_at=started_at,
                started=started,
                state_store=state_store,
            )
        else:
            writer_session = IndicatorByDateWriter(lake_root=self.lake_root).start_session(
                indicator="macd",
                params_key=DEFAULT_MACD_PARAMS.params_key,
                freq=freq,
                run_id=run_id,
            )
            source_rows = read_stk_mins_all_source_rows(
                lake_root=self.lake_root,
                freq=freq,
                start_date=start_date,
                end_date=end_date,
            )
            source_rows_total = len(source_rows)
            rows_by_symbol = _group_rows_by_symbol(source_rows)
            missing_states = [ts_code for ts_code in sorted(rows_by_symbol) if (ts_code, freq) not in existing_states]
            if missing_states:
                preview = ", ".join(missing_states[:10])
                raise RuntimeError(f"needs_bootstrap: 全市场增量存在缺失 state 的股票：{preview}")
            for index, (ts_code, rows) in enumerate(sorted(rows_by_symbol.items()), start=1):
                self.progress(f"[indicator_macd] symbol={index}/{len(rows_by_symbol)} ts_code={ts_code} rows={len(rows)}")
                calculation = calculate_macd(rows, params=DEFAULT_MACD_PARAMS, initial_state=existing_states[(ts_code, freq)])
                if not calculation.rows:
                    continue
                if calculation.final_state is None:
                    raise RuntimeError(f"MACD 计算未生成 final_state：ts_code={ts_code} freq={freq}")
                indicator_rows_total += writer_session.stage_rows(calculation.rows, part_label=f"symbol-{index:06d}")
                state_updates.append(calculation.final_state)
                processed_symbols += 1

        if indicator_rows_total <= 0:
            elapsed = time.monotonic() - started
            return {
                "operation": "compute_stk_mins_indicator",
                "indicator": "macd",
                "params_key": DEFAULT_MACD_PARAMS.params_key,
                "mode": mode,
                "scope": "all_market",
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "freq": freq,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "source_rows": source_rows_total,
                "indicator_rows": 0,
                "written_rows": 0,
                "state_updates": 0,
                "status": "no_op",
                "elapsed_seconds": round(elapsed, 3),
            }

        write_summary = writer_session.commit()
        merged_states = _merge_states(existing=existing_states, states=state_updates)
        state_summary = state_store.replace_states_after_result_write(
            merged_states,
            result_summary=write_summary,
            params=DEFAULT_MACD_PARAMS,
            run_id=run_id,
        )
        elapsed = time.monotonic() - started
        self.progress(
            f"[indicator_macd] done scope=all_market freq={freq} symbols={processed_symbols} "
            f"source_rows={source_rows_total} written={write_summary['written_rows']} "
            f"state_updates={len(state_updates)} elapsed={round(elapsed, 3)}s"
        )
        return {
            "operation": "compute_stk_mins_indicator",
            "indicator": "macd",
            "params_key": DEFAULT_MACD_PARAMS.params_key,
            "mode": mode,
            "scope": "all_market",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "freq": freq,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source_rows": source_rows_total,
            "indicator_rows": indicator_rows_total,
            "written_rows": write_summary["written_rows"],
            "state_updates": len(state_updates),
            "processed_symbols": processed_symbols,
            "status": "success",
            "by_date_write": write_summary,
            "state_write": state_summary,
            "elapsed_seconds": round(elapsed, 3),
        }

    def _compute_macd_all_market_full_streaming(
        self,
        *,
        freq: int,
        start_date: date,
        end_date: date,
        run_id: str,
        started_at: datetime,
        started: float,
        state_store: MacdStateStore,
    ) -> dict[str, Any]:
        existing_states = state_store.load_states(params=DEFAULT_MACD_PARAMS)
        regression_states = [
            state
            for (_state_ts_code, state_freq), state in existing_states.items()
            if state_freq == freq and state.last_trade_time.date() > end_date
        ]
        if regression_states:
            preview = ", ".join(f"{state.ts_code}:{state.last_trade_time.isoformat()}" for state in regression_states[:5])
            raise RuntimeError(
                "state_regression: 已有 MACD state 晚于本次 full 计算结束日期，"
                f"freq={freq} end_date={end_date.isoformat()} preview={preview}"
            )

        source_plan = plan_stk_mins_research_source_batches(
            lake_root=self.lake_root,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
        )
        if not source_plan.batches:
            raise RuntimeError("source research 未读取到任何可计算行。")
        self.progress(
            f"[indicator_macd] source_plan mode=full freq={freq} months={len(source_plan.months)} "
            f"batches={len(source_plan.batches)} files={source_plan.file_count}"
        )

        working_states = {key: state for key, state in existing_states.items() if key[1] != freq}
        writer = IndicatorByDateWriter(lake_root=self.lake_root)
        writer_session = None
        current_month: str | None = None
        month_source_rows = 0
        month_indicator_rows = 0
        month_processed_symbols = 0
        source_rows_total = 0
        indicator_rows_total = 0
        processed_symbols_total = 0
        committed_months: list[str] = []
        by_date_writes: list[dict[str, Any]] = []
        state_writes: list[dict[str, Any]] = []

        def commit_current_month() -> None:
            nonlocal writer_session
            nonlocal month_source_rows
            nonlocal month_indicator_rows
            nonlocal month_processed_symbols
            if current_month is None or writer_session is None or month_indicator_rows <= 0:
                writer_session = None
                month_source_rows = 0
                month_indicator_rows = 0
                month_processed_symbols = 0
                return
            write_summary = writer_session.commit()
            state_summary = state_store.replace_states_after_result_write(
                list(working_states.values()),
                result_summary=write_summary,
                params=DEFAULT_MACD_PARAMS,
                run_id=run_id,
            )
            by_date_writes.append(write_summary)
            state_writes.append(state_summary)
            committed_months.append(current_month)
            self.progress(
                f"[indicator_macd] checkpoint freq={freq} month={current_month} "
                f"source_rows={month_source_rows} written={write_summary['written_rows']} "
                f"symbols={month_processed_symbols} state_count={state_summary['state_count']}"
            )
            writer_session = None
            month_source_rows = 0
            month_indicator_rows = 0
            month_processed_symbols = 0

        for batch in iter_stk_mins_research_source_batches(
            lake_root=self.lake_root,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
            plan=source_plan,
        ):
            if current_month != batch.trade_month:
                commit_current_month()
                current_month = batch.trade_month
                writer_session = writer.start_session(
                    indicator="macd",
                    params_key=DEFAULT_MACD_PARAMS.params_key,
                    freq=freq,
                    run_id=run_id,
                )
                self.progress(f"[indicator_macd] month_start freq={freq} month={current_month}")
            if writer_session is None:
                raise RuntimeError("indicator writer session 未初始化。")

            rows_by_symbol = _group_rows_by_symbol(batch.rows)
            self.progress(
                f"[indicator_macd] batch={batch.batch_index}/{batch.batch_count} "
                f"freq={freq} month={batch.trade_month} bucket={batch.bucket} "
                f"symbols={len(rows_by_symbol)} source_rows={len(batch.rows)}"
            )
            source_rows_total += len(batch.rows)
            month_source_rows += len(batch.rows)
            staged_rows: list[dict[str, Any]] = []
            for ts_code, rows in sorted(rows_by_symbol.items()):
                calculation = calculate_macd(
                    rows,
                    params=DEFAULT_MACD_PARAMS,
                    initial_state=working_states.get((ts_code, freq)),
                )
                if calculation.final_state is None:
                    continue
                if calculation.rows:
                    staged_rows.extend(calculation.rows)
                    month_processed_symbols += 1
                    processed_symbols_total += 1
                working_states[(ts_code, freq)] = calculation.final_state
            staged_count = writer_session.stage_rows(staged_rows, part_label=f"bucket-{batch.bucket}") if staged_rows else 0
            month_indicator_rows += staged_count
            indicator_rows_total += staged_count
            self.progress(
                f"[indicator_macd] batch_done freq={freq} month={batch.trade_month} bucket={batch.bucket} "
                f"written={staged_count}"
            )
        commit_current_month()

        if indicator_rows_total <= 0:
            elapsed = time.monotonic() - started
            return {
                "operation": "compute_stk_mins_indicator",
                "indicator": "macd",
                "params_key": DEFAULT_MACD_PARAMS.params_key,
                "mode": "full",
                "scope": "all_market",
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "freq": freq,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "source_rows": source_rows_total,
                "indicator_rows": 0,
                "written_rows": 0,
                "state_updates": 0,
                "status": "no_op",
                "elapsed_seconds": round(elapsed, 3),
            }

        elapsed = time.monotonic() - started
        current_freq_state_count = len([key for key in working_states if key[1] == freq])
        self.progress(
            f"[indicator_macd] done scope=all_market mode=full freq={freq} "
            f"months={len(committed_months)} source_rows={source_rows_total} "
            f"written={indicator_rows_total} state_updates={current_freq_state_count} "
            f"elapsed={round(elapsed, 3)}s"
        )
        return {
            "operation": "compute_stk_mins_indicator",
            "indicator": "macd",
            "params_key": DEFAULT_MACD_PARAMS.params_key,
            "mode": "full",
            "scope": "all_market",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "freq": freq,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source_rows": source_rows_total,
            "indicator_rows": indicator_rows_total,
            "written_rows": indicator_rows_total,
            "state_updates": current_freq_state_count,
            "processed_symbols": processed_symbols_total,
            "committed_months": committed_months,
            "status": "success",
            "by_date_writes": by_date_writes,
            "state_writes": state_writes,
            "elapsed_seconds": round(elapsed, 3),
        }


def _merge_state(*, existing: dict[tuple[str, int], MacdState], state: MacdState) -> list[MacdState]:
    merged = dict(existing)
    merged[(state.ts_code, state.freq)] = state
    return list(merged.values())


def _merge_states(*, existing: dict[tuple[str, int], MacdState], states: Iterable[MacdState]) -> list[MacdState]:
    merged = dict(existing)
    for state in states:
        merged[(state.ts_code, state.freq)] = state
    return list(merged.values())


def _group_rows_by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["ts_code"])].append(row)
    return {ts_code: sorted(items, key=lambda item: item["trade_time"]) for ts_code, items in grouped.items()}


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{suffix}"
