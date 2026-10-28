"""Daily period backlog, adjacent factor notifications and direct asset execution."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.io.stock_period_raw import (
    atomic_json,
    check_cancel,
    connection,
    execute,
    process_memory_budget,
    read_json,
    safe_path,
)
from orchestrator.defs.run_contracts.stock_period import (
    DEFAULT_POLICY,
    VERSION,
    digest,
    execution_id,
    next_period,
    period_date,
    period_for,
)


def daily_periods(*, today, freq, completed_through, last_refresh=None):
    """One request per outstanding period, then current; no per-day price replay."""
    current = period_for(today, freq)
    if completed_through is None:
        raise ValueError("period_baseline_watermark_missing")
    output = []
    period = next_period(completed_through, freq)
    while period < current:
        output.append(period)
        period = next_period(period, freq)
    if last_refresh != today.isoformat():
        output.append(current)
    return list(dict.fromkeys(output))


class CalendarDays(list):
    def __init__(self, rows):
        normalized = [
            (day.isoformat() if isinstance(day, date) else str(day), opened)
            for day, opened in rows
        ]
        super().__init__(day for day, opened in normalized if opened == 1)
        self.covered = {day for day, _ in normalized}


def calendar_days(root, work, policy=DEFAULT_POLICY):
    from orchestrator.defs.paths import silver_trade_calendar_path

    with connection(work, policy) as con:
        return CalendarDays(
            con.execute(
                "SELECT trade_date,is_open FROM read_parquet(?) WHERE exchange='SSE' ORDER BY trade_date",
                [str(safe_path(silver_trade_calendar_path(root)))],
            ).fetchall()
        )


def period_bounds(period, freq):
    text = period_date(period, freq)
    end = date(int(text[:4]), int(text[4:6]), int(text[6:]))
    return (end - timedelta(days=4) if freq == "week" else end.replace(day=1)), end


def no_trading_period(period, freq, days):
    first, last = period_bounds(period, freq)
    if any(first.isoformat() <= d <= last.isoformat() for d in days):
        return False
    required = {
        (first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)
    }
    if not required.issubset(getattr(days, "covered", set())):
        raise ValueError("period_calendar_coverage_missing")
    return True


def source_final(period, freq, asof, today, days):
    if not asof:
        return False
    first, last = period_bounds(period, freq)
    observed = asof[:4] + "-" + asof[4:6] + "-" + asof[6:]
    required = {
        (first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)
    }
    if not required.issubset(getattr(days, "covered", set())):
        return False
    final = close_day(period, freq, days)
    return today.isoformat() >= final and observed >= final


def factor_changes(
    root,
    work,
    days,
    after,
    through,
    listed,
    policy=DEFAULT_POLICY,
    cancel=lambda: False,
    progress=lambda _: None,
):
    """Each unconsumed adjacent trading-day pair once; never compare complete price history."""
    from orchestrator.defs.paths import silver_adj_factor_path
    from orchestrator.defs.stock_daily_qfq import (
        build_stock_daily_qfq_factor_changed_codes_sql,
    )

    if after is None:
        raise ValueError("period_factor_watermark_missing")
    selected = [day for day in days if after < day <= through]
    changed = set()
    with connection(work, policy) as con:
        for day in selected:
            previous = days[days.index(day) - 1] if days.index(day) > 0 else None
            if previous is None:
                continue
            current_path = safe_path(silver_adj_factor_path(root, day))
            prior_path = safe_path(silver_adj_factor_path(root, previous))
            if not current_path.is_file() or not prior_path.is_file():
                raise ValueError("period_adjacent_factor_missing")
            changed.update(
                r[0]
                for r in execute(
                    con,
                    build_stock_daily_qfq_factor_changed_codes_sql(
                        current_adj_factor_path=current_path,
                        previous_adj_factor_path=prior_path,
                    ),
                    policy=policy,
                    cancel=cancel,
                    progress=progress,
                    stage="adjacent_factor_changes",
                ).fetchall()
            )
    return sorted(changed & set(listed))


def close_day(period, freq, days):
    anchor = period_date(period, freq)
    boundary = date(int(anchor[:4]), int(anchor[4:6]), int(anchor[6:]))
    first, _ = period_bounds(period, freq)
    candidates = [d for d in days if first.isoformat() <= d <= boundary.isoformat()]
    if not candidates:
        raise ValueError("period_calendar_no_trading_day")
    return candidates[-1]


def daily_state(staging):
    path = Path(staging) / "stock_period" / "daily.json"
    return read_json(path) if path.exists() else None


def daily_handoff_ready(state):
    return (
        isinstance(state, dict)
        and isinstance(state.get("factor_through"), str)
        and isinstance(state.get("last_refresh"), dict)
        and isinstance(state.get("completed_through"), dict)
        and all(isinstance(state["completed_through"].get(freq), str) for freq in ("week", "month"))
    )


def bootstrap_watermarks(today, days):
    # First baseline has no older debt; current periods are deliberately left open.
    result = {
        "factor_through": today.isoformat(),
        "last_refresh": {},
        "completed_through": {},
    }
    for freq in ("week", "month"):
        current = period_for(today, freq)
        if source_final(
            current, freq, today.strftime("%Y%m%d"), today, days
        ) or no_trading_period(current, freq, days):
            result["completed_through"][freq] = current
        else:
            day = date.fromisoformat(current if freq == "week" else current + "-01")
            prior = day - timedelta(days=7 if freq == "week" else 1)
            result["completed_through"][freq] = period_for(prior, freq)
    return result


def confirmed_retirements(root, work, removed, aliases):
    if not removed:
        return []
    from orchestrator.defs.paths import raw_stock_basic_path

    source_codes = sorted(
        set(removed) | {old for old, new in aliases.items() if new in removed}
    )
    with connection(work) as con:
        rows = con.execute(
            "SELECT ts_code FROM read_parquet(?) WHERE list_status='D' AND list_contains(?,ts_code)",
            [str(safe_path(raw_stock_basic_path(root))), source_codes],
        ).fetchall()
    return sorted({aliases.get(r[0], r[0]) for r in rows} & set(removed))


def _daily_work(
    staging, *, root, today, freq, listed, aliases, days, policy, cancel, progress
):
    state = daily_state(staging)
    pending = daily_periods(
        today=today,
        freq=freq,
        completed_through=state["completed_through"][freq],
        last_refresh=state["last_refresh"].get(freq),
    )
    holidays = [p for p in pending if no_trading_period(p, freq, days)]
    requested = [p for p in pending if p not in holidays]
    baseline = read_json(Path(staging) / "stock_period/baseline.json")
    if (
        not pending
        and state["factor_through"] >= today.isoformat()
        and set(baseline["listed"]) == set(listed)
    ):
        return None
    changed = set(
        factor_changes(
            root,
            Path(staging) / "stock_period/factors",
            days,
            state["factor_through"],
            today.isoformat(),
            listed,
            policy,
            cancel,
            progress,
        )
    )
    changed.update(set(listed) - set(baseline["listed"]))
    retired = confirmed_retirements(
        root,
        Path(staging) / "stock_period/scope",
        {
            c
            for c in baseline["listed"]
            if c not in listed and aliases.get(c, c) not in listed
        },
        aliases,
    )
    superseded = sorted(
        c for c in baseline["listed"] if c not in listed and aliases.get(c, c) in listed
    )
    if not (requested or changed or retired or superseded or holidays):
        return None
    intent = {
        "version": VERSION,
        "mode": "upsert" if requested else "history",
        "frequencies": ["week", "month"]
        if changed or retired or superseded
        else [freq],
        "codes": sorted(changed),
        "retired_codes": retired,
        "superseded_codes": superseded,
        "periods": {freq: requested},
        "asof": today.isoformat(),
        "request_id": digest(
            {"kind": "period_daily", "frequency": freq, "date": today.isoformat()}
        ),
        "period_cutoffs": {
            freq: {
                p: min(today.isoformat(), close_day(p, freq, days)).replace("-", "")
                for p in requested
            }
        },
    }
    return {
        "intent": intent,
        "listed": sorted(listed),
        "aliases": aliases,
        "confirmed_retired": retired,
        "frequency": freq,
        "pending": pending,
        "holidays": holidays,
        "consumed": False,
        "policy": policy.payload(),
    }


def _consume_daily_files(staging, work, result, days):
    path = Path(staging) / "stock_period/daily.json"
    state = daily_state(staging)
    intent, freq = work["intent"], work["frequency"]
    today = date.fromisoformat(intent["asof"])
    observations = result.get("unit_asofs", {}).get(freq, {})
    current = period_for(today, freq)
    if (
        observations.get(current)
        and observations[current] >= intent["asof"].replace("-", "")
        and state["last_refresh"].get(freq, "") <= intent["asof"]
    ):
        state["last_refresh"][freq] = intent["asof"]
        state.setdefault("last_source_asof", {})[freq] = observations[current]
    frontier = state["completed_through"][freq]
    for period in work["pending"]:
        if period != next_period(frontier, freq):
            break
        if period in work["holidays"] or source_final(
            period, freq, observations.get(period), today, days
        ):
            frontier = period
        else:
            break
    state["completed_through"][freq] = frontier
    state["factor_through"] = max(state["factor_through"], intent["asof"])
    work["consumed"] = True
    state.setdefault("pending_work", {})[execution_id(intent["request_id"])] = work
    baseline_path = Path(staging) / "stock_period/baseline.json"
    baseline = read_json(baseline_path)
    if state["factor_through"] > intent["asof"] and baseline["listed"] != work["listed"]:
        raise ValueError("period_daily_scope_would_regress")
    baseline["listed"] = work["listed"]
    atomic_json(baseline_path, baseline)
    atomic_json(path, state)


def _execute_daily_locked(
    *,
    root,
    staging,
    today,
    freq,
    listed,
    aliases,
    transport=None,
    policy=DEFAULT_POLICY,
    cancel=lambda: False,
    progress=lambda _: None,
    events=None,
    completion_events=None,
    confirm_delivery=None,
):
    """Close frozen work before planning another intent or reading factors."""
    from orchestrator.defs.bootstrap.stock_period_history import (
        completed_receipt,
        ordered_pending_work,
        replay_events,
        require_current_files,
        run_period,
    )
    from orchestrator.defs.run_contracts.stock_period import StockPeriodPolicy

    state = daily_state(staging)
    if not daily_handoff_ready(state):
        raise ValueError("period_daily_handoff_required")
    results = []
    days = None
    requested_id = execution_id(
        digest({"kind": "period_daily", "frequency": freq, "date": today.isoformat()})
    )

    def original_run_required(work):
        intent = work["intent"]
        if work.get("kind") == "history":
            raise ValueError(
                "period_original_history_required:"
                f"request_id={intent['request_id']}:execution={execution_id(intent['request_id'])}"
            )
        raise ValueError(
            "period_original_run_required:"
            f"job=raw_stk_period_bar_adj_{work['frequency']}_update_job:"
            f"asof={intent.get('asof')}:execution={execution_id(intent['request_id'])}"
        )

    def perform(work):
        nonlocal days
        check_cancel(cancel)
        intent = work["intent"]
        run_id = execution_id(intent["request_id"])
        work_policy = StockPeriodPolicy(**work["policy"])
        run = Path(staging) / "stock_period/runs" / run_id
        if work.get("kind") == "history":
            manifest_path = run / "manifest.json"
            if manifest_path.exists() and read_json(manifest_path).get("phase") in ("files_complete", "events_complete") and confirm_delivery is not None:
                confirmation = confirm_delivery(run)
                if confirmation["events_complete"]:
                    acknowledge_period_delivery(run, confirmation, root=root, staging=staging, cancel=cancel)
                    return True
            original_run_required(work)
        calendar_only = not (
            any(intent.get("periods", {}).values())
            or intent.get("codes")
            or intent.get("retired_codes")
            or intent.get("superseded_codes")
        )
        if calendar_only:
            days = days or calendar_days(
                root, Path(staging) / "stock_period/calendar", work_policy
            )
            _consume_daily_files(staging, work, {"unit_asofs": {}}, days)
            latest = daily_state(staging)
            latest.get("pending_work", {}).pop(run_id, None)
            atomic_json(Path(staging) / "stock_period/daily.json", latest)
            return True

        manifest = read_json(run / "manifest.json") if (run / "manifest.json").exists() else None
        files_complete = manifest is not None and manifest.get("phase") in (
            "files_complete", "events_complete"
        )
        if files_complete and not work["consumed"]:
            if run_id != requested_id:
                original_run_required(work)
            complete = completed_receipt(run, manifest, cancel=cancel)
            require_current_files(complete, cancel=cancel)
            days = days or calendar_days(
                root, Path(staging) / "stock_period/calendar", work_policy
            )
            _consume_daily_files(staging, work, complete, days)
        if files_complete and confirm_delivery is not None:
            confirmation = confirm_delivery(run)
            if confirmation["events_complete"]:
                if not work["consumed"] and confirmation["historical_only"]:
                    raise ValueError("period_delivery_unconsumed_history")
                if work["consumed"]:
                    acknowledge_period_delivery(
                        run, confirmation, root=root, staging=staging, cancel=cancel
                    )
                    complete = read_json(run / "complete.json")
                    results.append(
                        {
                            **complete,
                            "path": str(run),
                            "events_complete": True,
                            "historical_only": True,
                            "current_files": [],
                            "completions": {
                                f: evidence["completion"]
                                for f, evidence in confirmation["completion_evidence"].items()
                            },
                        }
                    )
                    return True
        if run_id != requested_id:
            # Only already-verified historical delivery may be acknowledged by
            # another date/frequency. Recover missing native steps in its own run.
            original_run_required(work)
        result = run_period(
            root=root,
            staging=staging,
            intent=intent,
            listed=set(work["listed"]),
            aliases=work["aliases"],
            confirmed_retired=work["confirmed_retired"],
            transport=transport,
            policy=work_policy,
            cancel=cancel,
            progress=progress,
            confirm_delivery=confirm_delivery,
        )
        if not work["consumed"]:
            if result.get("historical_only"):
                raise ValueError("period_delivery_unconsumed_history")
            days = days or calendar_days(
                root, Path(staging) / "stock_period/calendar", work_policy
            )
            _consume_daily_files(staging, work, result, days)
        if events is not None:
            result = replay_events(
                Path(result["path"]),
                root=root,
                staging=staging,
                events=events,
                completion_events=completion_events,
                confirm_delivery=confirm_delivery,
                cancel=cancel,
            )
            if result["events_complete"]:
                latest = daily_state(staging)
                pending = latest.get("pending_work", {}).get(run_id)
                if pending is not None and pending.get("consumed"):
                    latest["pending_work"].pop(run_id)
                    atomic_json(Path(staging) / "stock_period/daily.json", latest)
        results.append(result)
        return run_id not in daily_state(staging).get("pending_work", {})

    for work in ordered_pending_work(staging, state=state):
        if not perform(work):
            # The native materialization/checks run after the asset returns.
            # Do not prepare another date while that delivery is still pending.
            return results
        if execution_id(work["intent"]["request_id"]) == requested_id:
            # The frozen request has just been recovered. Replanning it would
            # redownload an already completed intent, especially after midnight.
            return results
    days = days or calendar_days(root, Path(staging) / "stock_period/calendar", policy)
    if today.isoformat() not in days:
        if results:
            return results
        raise ValueError("period_not_trading_day")
    work = _daily_work(
        staging,
        root=root,
        today=today,
        freq=freq,
        listed=listed,
        aliases=aliases,
        days=days,
        policy=policy,
        cancel=cancel,
        progress=progress,
    )
    if work is not None:
        latest = daily_state(staging)
        run_id = execution_id(work["intent"]["request_id"])
        if run_id not in latest.get("pending_work", {}):
            latest.setdefault("pending_work", {})[run_id] = work
            atomic_json(Path(staging) / "stock_period/daily.json", latest)
            perform(work)
    return results


def execute_daily(**kwargs):
    from orchestrator.defs.bootstrap.stock_period_history import roots, writer

    roots(kwargs["root"], kwargs["staging"])
    with writer(kwargs["staging"]):
        return _execute_daily_locked(**kwargs)


def _period_delivery_error(reason, run, saved, item=None):
    intent = saved["identity"]["intent"]
    frequency = item["freq"] if item else ",".join(intent["frequencies"])
    partition = item["period"] if item else "all"
    raise ValueError(
        f"{reason}: job=raw_stk_period_bar_adj_{frequency}_update_job "
        f"date={intent.get('asof', 'history')} partition={partition} run_id={run.name}"
    )


def _period_delivery_stat(path):
    from orchestrator.defs.io.stock_period_raw import file_version

    path = safe_path(Path(path))
    return file_version(path) if path.exists() else None


def _period_delivery_json(path, controls):
    path = safe_path(Path(path))
    before = _period_delivery_stat(path)
    value = read_json(path) if before is not None else None
    if _period_delivery_stat(path) != before:
        raise ValueError("period_delivery_control_changed")
    controls[str(path)] = {
        "kind": "json", "version": before,
        "digest": digest(value) if before is not None else None,
    }
    return value


def _period_delivery_assert_controls(controls, cancel):
    for path, expected in controls.items():
        check_cancel(cancel)
        version = _period_delivery_stat(path)
        if version != expected["version"]:
            raise ValueError("period_delivery_control_changed")
        # Initial content/hash belongs to this exact five-field file version.
        # Reuse it; rereading every complete.json before each small CP would
        # multiply metadata I/O without providing a new filesystem identity.


def _period_delivery_event_rows(instance, asset, *, period=None, since=None, event_id=None, kind=None):
    import sqlalchemy as sa
    from dagster._core.event_api import EventLogRecord
    from dagster._core.events.log import EventLogEntry
    from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
    from dagster._core.storage.event_log.sql_event_log import SqlEventLogStorage
    from dagster._serdes import deserialize_value

    storage = instance.event_log_storage
    if not isinstance(storage, SqlEventLogStorage):
        raise TypeError("period_event_storage_unsupported")
    predicate = [Events.c.asset_key == asset.to_string(), Events.c.dagster_event_type == kind]
    if period is not None:
        predicate.append(Events.c.partition == period)
    if event_id is not None:
        predicate.append(Events.c.id == event_id)
    if since is not None:
        latest = sa.select(sa.func.max(Events.c.id)).where(*predicate).correlate(None).scalar_subquery()
        predicate.append(sa.or_(Events.c.timestamp >= since, Events.c.id == latest))
    statement = sa.select(Events.c.id, Events.c.event).where(*predicate).order_by(Events.c.id)
    with storage.index_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [EventLogRecord(row["id"], deserialize_value(row["event"], EventLogEntry)) for row in rows]


def _period_delivery_current_evidence(instance, files):
    """Two collection queries for exact current units, independent of unit count."""
    import dagster as dg
    import sqlalchemy as sa
    from dagster._core.event_api import EventLogRecord
    from dagster._core.events.log import EventLogEntry
    from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
    from dagster._core.storage.event_log.sql_event_log import SqlEventLogStorage
    from dagster._serdes import deserialize_value

    from orchestrator.defs.asset_guards.stock_period_check_evidence import (
        decode_completed_check_row,
        latest_completed_checks_query,
    )
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names,
    )

    if not files:
        return {}
    storage = instance.event_log_storage
    if not isinstance(storage, SqlEventLogStorage):
        raise TypeError("period_event_storage_unsupported")
    by_asset = {}
    result = {}
    for item in files:
        asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{item['freq']}")
        by_asset.setdefault(asset, set()).add(item["period"])
        result[(asset.to_user_string(), item["period"])] = {"materialization": None, "checks": {}}
    predicates = [sa.and_(Events.c.asset_key == asset.to_string(), Events.c.partition.in_(sorted(periods)))
                  for asset, periods in by_asset.items()]
    latest_mats = (sa.select(sa.func.max(Events.c.id))
                   .where(Events.c.dagster_event_type == "ASSET_MATERIALIZATION", sa.or_(*predicates))
                   .group_by(Events.c.asset_key, Events.c.partition))
    selected_checks = latest_completed_checks_query(
        asset_check_names={asset: raw_check_names("week" if asset.to_user_string().endswith("_week") else "month")
                           for asset in by_asset},
        partition_keys=sorted({period for periods in by_asset.values() for period in periods}),
    )
    exact_check_pairs = [sa.and_(selected_checks.c.asset_key == asset.to_string(),
                                selected_checks.c.partition.in_(sorted(periods)))
                         for asset, periods in by_asset.items()]
    with storage.index_connection() as connection:
        materializations = connection.execute(
            sa.select(Events.c.id, Events.c.event).where(Events.c.id.in_(latest_mats))
        ).mappings().all()
        checks = connection.execute(sa.select(selected_checks).where(sa.or_(*exact_check_pairs))).mappings().all()
    for row in materializations:
        record = EventLogRecord(row["id"], deserialize_value(row["event"], EventLogEntry))
        materialization = record.asset_materialization
        key = (materialization.asset_key.to_user_string(), materialization.partition)
        if key not in result:
            raise ValueError("period_delivery_materialization_invalid")
        result[key]["materialization"] = record
    for row in checks:
        asset = dg.AssetKey.from_db_string(row["asset_key"])
        key = (asset.to_user_string(), row["partition"])
        if key not in result:
            raise ValueError("period_check_evidence_scope_invalid")
        result[key]["checks"][row["check_name"]] = decode_completed_check_row(
            row, asset_key=asset, check_name=row["check_name"], partition_key=row["partition"],
        )
    return result


def _period_delivery_metadata(record, key):
    return getattr(record.asset_materialization.metadata.get(key), "value", None)


def _period_delivery_mat_matches(record, item, notice):
    import dagster as dg

    mat = record.asset_materialization
    return (
        mat.asset_key == dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{item['freq']}")
        and mat.partition == item["period"]
        and _period_delivery_metadata(record, "dagster/uri") == item["target"]
        and _period_delivery_metadata(record, "dagster/row_count") == item["rows"]
        and type(_period_delivery_metadata(record, "dagster/row_count")) is int
        and _period_delivery_metadata(record, "goldenshare/period_file_version") == item["version"]
        and _period_delivery_metadata(record, "goldenshare/period_completion") == notice
    )


def _period_delivery_checks(instance, record, item, *, cutoff=None, prefetched=None):
    from orchestrator.defs.asset_guards.stock_period_check_evidence import (
        read_latest_completed_checks,
    )
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names,
    )

    names = raw_check_names(item["freq"])
    results = prefetched
    if results is None:
        results = read_latest_completed_checks(
            instance, asset_key=record.asset_materialization.asset_key,
            check_names=names, partition_key=item["period"], before_event_id=cutoff,
        )
    evidence = {}
    for name in names:
        if name not in results:
            continue
        check, evaluation_id, bound = results[name]
        evaluation = check.evaluation
        target = evaluation.target_materialization_data if evaluation else None
        if (
            evaluation is None or check.status.value != "SUCCEEDED"
            or not evaluation.passed or not evaluation.blocking
            or evaluation.asset_key != record.asset_materialization.asset_key
            or evaluation.partition != item["period"] or evaluation.check_name != name
            or target is None or bound is None or target.storage_id != bound.storage_id
            or target.run_id != bound.event_log_entry.run_id
            or target.timestamp != bound.event_log_entry.timestamp
        ):
            raise ValueError("period_delivery_checks_invalid")
        if target.storage_id != record.storage_id:
            preimage = item.get("target_preimage")
            if (
                preimage is not None and evaluation_id < record.storage_id
                and bound.storage_id < record.storage_id
                and bound.asset_materialization.asset_key == record.asset_materialization.asset_key
                and bound.asset_materialization.partition == item["period"]
                and _period_delivery_metadata(bound, "dagster/uri") == item["target"]
                and _period_delivery_metadata(bound, "goldenshare/period_file_version") == preimage
            ):
                continue  # An earlier valid check is not this new version's completed check.
            raise ValueError("period_delivery_checks_invalid")
        if target.run_id != record.event_log_entry.run_id or target.timestamp != record.event_log_entry.timestamp:
            raise ValueError("period_delivery_checks_invalid")
        evidence[name] = {
            "evaluation_event_storage_id": evaluation_id,
            "materialization_id": target.storage_id,
        }
    return evidence, len(evidence) == 3


def _period_delivery_notice(instance, asset, notice, cp, since):
    from orchestrator.defs.run_contracts.stock_period import COMPLETION_METADATA_KEY

    observation_id = cp.get("observation_id") if cp is not None else None
    if cp is not None and (
        cp.get("completion") != notice or type(observation_id) is not int or observation_id <= 0
    ):
        raise ValueError("period_delivery_checkpoint_changed")
    rows = _period_delivery_event_rows(
        instance, asset, kind="ASSET_OBSERVATION", event_id=observation_id,
        since=since if observation_id is None else None,
    )
    matches = []
    for record in rows:
        observation = record.asset_observation
        value = getattr(observation.metadata.get(COMPLETION_METADATA_KEY), "value", None)
        if value == notice:
            matches.append(record.storage_id)
        elif cp is not None or isinstance(value, dict) and (
            value.get("raw_execution_id") == notice["raw_execution_id"]
            and value.get("file_receipt_hash") == notice["file_receipt_hash"]
        ):
            raise ValueError("period_delivery_checkpoint_changed")
    if cp is not None and matches != [observation_id]:
        raise ValueError("period_delivery_checkpoint_changed")
    return {"completion": notice, "observation_id": min(matches)} if matches else None


def _period_delivery_successors(instance, run, saved, item, records, current, controls, receipt_cache, *, root, staging, cancel, current_checks=None):
    """Follow only explicit current materialization references backwards to this version."""
    from orchestrator.defs.bootstrap.stock_period_history import (
        check_devices,
        completed_receipt,
    )
    from orchestrator.defs.run_contracts.stock_period import (
        COMPLETION_METADATA_KEY,
        completion_notice,
        validate_completion_notice,
        verify_execution,
    )

    chain, seen = [], set()
    record = current
    while _period_delivery_metadata(record, "goldenshare/period_file_version") != item["version"]:
        check_cancel(cancel)
        value = _period_delivery_metadata(record, COMPLETION_METADATA_KEY)
        try:
            reference = validate_completion_notice(value, item["freq"])
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError("period_delivery_current_file_unknown") from error
        execution = reference["raw_execution_id"]
        if execution in seen or execution == run.name:
            _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
        seen.add(execution)
        successor = safe_path(Path(staging) / "stock_period/runs" / execution)
        cached = receipt_cache.get(execution)
        if cached is None:
            other_saved = _period_delivery_json(successor / "manifest.json", controls)
            if other_saved is None:
                _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
            verify_execution(other_saved, execution)
            check_devices(root, staging, other_saved["devices"])
            if other_saved["identity"]["root"] != str(root) or other_saved["phase"] not in ("files_complete", "events_complete"):
                _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
            payload = _period_delivery_json(successor / "complete.json", controls)
            if payload is None:
                _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
            complete = completed_receipt(successor, other_saved, cancel=cancel, complete=payload)
            cached = {
                "saved": other_saved,
                "items": {(entry["freq"], entry["period"]): entry for entry in complete["files"]},
                "counts": {frequency: sum(entry["freq"] == frequency for entry in complete["files"])
                           for frequency in {entry["freq"] for entry in complete["files"]}},
            }
            receipt_cache[execution] = cached
        else:
            # Cached content is reusable only while its original file identities hold.
            _period_delivery_assert_controls(
                {str(path): controls[str(path)] for path in
                 (successor / "manifest.json", successor / "complete.json")}, cancel,
            )
        other_saved = cached["saved"]
        if reference["file_receipt_hash"] != other_saved["file_receipt_hash"]:
            _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
        successor_item = cached["items"].get((item["freq"], item["period"]))
        if successor_item is None:
            _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
        expected_notice = completion_notice(reference, item["freq"], cached["counts"][item["freq"]])
        if value != expected_notice or not _period_delivery_mat_matches(record, successor_item, expected_notice):
            _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
        committed = _period_delivery_json(
            successor / "committed" / item["freq"] / (item["period"] + ".json"), controls,
        )
        if committed is None or any(committed.get(key) != successor_item.get(key)
                                    for key in ("freq", "period", "target", "version", "sha256", "rows", "target_preimage")):
            _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
        if successor_item["target"] != item["target"]:
            _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
        earliest = min(entry.storage_id for entry in records
                       if _period_delivery_mat_matches(entry, successor_item, expected_notice))
        chain.append({
            "raw_execution_id": execution, "file_receipt_hash": other_saved["file_receipt_hash"],
            "materialization_id": record.storage_id, "first_materialization_id": earliest,
            "item": successor_item, "record": record,
        })
        preimage = successor_item.get("target_preimage")
        predecessors = [entry for entry in records
                        if entry.storage_id < earliest
                        and _period_delivery_metadata(entry, "goldenshare/period_file_version") == preimage]
        if not predecessors:
            _period_delivery_error("period_delivery_history_missing", run, saved, item)
        record = max(predecessors, key=lambda entry: entry.storage_id)
    # Each intervening version must have genuine passing checks before the next version.
    for index, link in enumerate(chain):
        cutoff = None if index == 0 else chain[index - 1]["first_materialization_id"]
        checks, ready = _period_delivery_checks(
            instance, link["record"], link["item"], cutoff=cutoff,
            prefetched=current_checks if index == 0 else None,
        )
        if not ready:
            _period_delivery_error("period_delivery_history_missing", run, saved, item)
        link["checks"] = checks
    return record, list(reversed(chain))


def confirm_period_delivery(instance, run, *, root, staging, cancel=lambda: False, allowed_frequencies=None):
    """Read original delivery facts; never publish an event or touch lake contents."""
    import dagster as dg

    from orchestrator.defs.bootstrap.stock_period_history import (
        check_devices,
        completed_receipt,
        roots,
    )
    from orchestrator.defs.run_contracts.stock_period import (
        completion_notice,
        completion_reference,
        verify_execution,
    )

    root, staging = roots(root, staging)
    run = safe_path(Path(run))
    if run != staging / "stock_period/runs" / run.name:
        raise ValueError("period_event_run_path_invalid")
    controls = {}
    saved = _period_delivery_json(run / "manifest.json", controls)
    verify_execution(saved, run.name)
    check_devices(root, staging, saved["devices"])
    if saved["identity"]["root"] != str(root) or saved["phase"] not in ("files_complete", "events_complete"):
        _period_delivery_error("period_event_files_incomplete", run, saved)
    payload = _period_delivery_json(run / "complete.json", controls)
    if payload is None:
        _period_delivery_error("period_complete_receipt_changed", run, saved)
    complete = completed_receipt(run, saved, cancel=cancel, complete=payload)
    receipt_cache = {}
    allowed = {"week", "month"} if allowed_frequencies is None else set(allowed_frequencies)
    if not allowed or not allowed <= {"week", "month"}:
        raise ValueError("period_delivery_frequency_invalid")
    frequencies = {item["freq"] for item in complete["files"]}
    if not frequencies & allowed:
        raise ValueError("period_delivery_frequency_invalid")
    scope_complete = frequencies <= allowed
    daily_path = staging / "stock_period/daily.json"
    _period_delivery_json(daily_path, controls)
    notices = {freq: completion_notice(
        completion_reference(run.name, saved["file_receipt_hash"], freq), freq,
        sum(item["freq"] == freq for item in complete["files"]),
    ) for freq in frequencies & allowed}
    cps, completion_cps = {}, {}
    for item in complete["files"]:
        if item["freq"] not in allowed:
            continue
        check_cancel(cancel)
        key = (item["freq"], item["period"])
        cp_path = run / "events" / item["freq"] / (item["period"] + ".json")
        cps[key] = _period_delivery_json(cp_path, controls)
        if cps[key] is not None and cps[key] != {field: item[field] for field in ("version", "sha256")}:
            _period_delivery_error("period_delivery_checkpoint_changed", run, saved, item)
    for freq in notices:
        completion_cps[freq] = _period_delivery_json(run / "events/completion" / (freq + ".json"), controls)
    result = {
        "run_id": run.name, "identity_hash": saved["identity_hash"],
        "file_receipt_hash": saved["file_receipt_hash"], "files": complete["files"],
        "events_complete": False, "allowed_events_complete": False,
        "historical_only": False, "current_files": [],
        "file_evidence": {}, "completion_evidence": {}, "control_versions": controls,
        "reason": "ok", "allowed_frequencies": sorted(allowed),
    }
    closed = saved["phase"] == "events_complete"
    if closed and (any(value is None for value in cps.values())
                   or any(value is None for value in completion_cps.values())):
        _period_delivery_error("period_delivery_checkpoint_changed", run, saved)
    completed_at = datetime.fromisoformat(saved["files_completed_at"])
    if completed_at.tzinfo is None:
        _period_delivery_error("period_delivery_history_missing", run, saved)
    since = completed_at.astimezone(timezone.utc).replace(tzinfo=None)
    missing_events, missing_checks = False, False
    for freq, notice in notices.items():
        evidence = _period_delivery_notice(
            instance, dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}"), notice,
            completion_cps[freq], since,
        )
        if evidence is not None:
            result["completion_evidence"][freq] = evidence
        else:
            missing_events = True
    if closed:
        result["historical_only"] = True
        for item in complete["files"]:
            if item["freq"] in allowed:
                key = (item["freq"], item["period"])
                result["file_evidence"][key] = {"cp_source": str(run / "events" / item["freq"] / (item["period"] + ".json"))}
        if missing_events:
            _period_delivery_error("period_delivery_checkpoint_changed", run, saved)
        result["allowed_events_complete"] = True
        result["events_complete"] = scope_complete
        _period_delivery_assert_controls(controls, cancel)
        return result
    current_evidence = _period_delivery_current_evidence(
        instance, [item for item in complete["files"] if item["freq"] in allowed],
    )
    for item in complete["files"]:
        if item["freq"] not in allowed:
            continue
        check_cancel(cancel)
        key = (item["freq"], item["period"])
        current_version = _period_delivery_stat(item["target"])
        controls[item["target"]] = {"kind": "file", "version": current_version}
        if current_version is None:
            _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
        asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{item['freq']}")
        current = current_evidence[(asset.to_user_string(), item["period"])]
        if current_version != item["version"]:
            # Only genuinely replaced files need historical materializations.
            records = _period_delivery_event_rows(instance, asset, period=item["period"],
                                                  since=since, kind="ASSET_MATERIALIZATION")
        else:
            records = [current["materialization"]] if current["materialization"] is not None else []
            if (
                records
                and _period_delivery_metadata(records[-1], "goldenshare/period_file_version")
                == item["version"]
                and not _period_delivery_mat_matches(records[-1], item, notices[item["freq"]])
            ):
                _period_delivery_error("period_delivery_materialization_invalid", run, saved, item)
        originals = [entry for entry in records
                     if _period_delivery_metadata(entry, "goldenshare/period_completion") == notices[item["freq"]]]
        if any(not _period_delivery_mat_matches(entry, item, notices[item["freq"]]) for entry in originals):
            _period_delivery_error("period_delivery_materialization_invalid", run, saved, item)
        chain = []
        if current_version != item["version"]:
            result["historical_only"] = True
            if item["freq"] not in result["completion_evidence"]:
                _period_delivery_error("period_delivery_history_missing", run, saved, item)
            if not records or _period_delivery_metadata(records[-1], "goldenshare/period_file_version") != current_version:
                _period_delivery_error("period_delivery_current_file_unknown", run, saved, item)
            original, chain = _period_delivery_successors(
                instance, run, saved, item, records, records[-1], controls, receipt_cache,
                root=root, staging=staging, cancel=cancel, current_checks=current["checks"],
            )
            if not _period_delivery_mat_matches(original, item, notices[item["freq"]]):
                _period_delivery_error("period_delivery_history_missing", run, saved, item)
        else:
            result["current_files"].append(item)
            original = max(originals, key=lambda entry: entry.storage_id) if originals else None
            if original is not None and original.storage_id != records[-1].storage_id:
                _period_delivery_error("period_delivery_materialization_invalid", run, saved, item)
        if original is None:
            if records:
                # No matching original materialization is a missing event, but
                # existing failed/nonblocking/late wrong-bound results remain
                # real errors. Do not hide them behind the missing-event branch.
                _period_delivery_checks(instance, records[-1], item, prefetched=current["checks"])
            else:
                if current["checks"]:
                    _period_delivery_error("period_delivery_checks_invalid", run, saved, item)
            missing_events = True
            result["file_evidence"][key] = {"missing": "materialization"}
            continue
        cutoff = chain[0]["first_materialization_id"] if chain else None
        checks, ready = _period_delivery_checks(
            instance, original, item, cutoff=cutoff,
            prefetched=current["checks"] if cutoff is None else None,
        )
        if not ready:
            if chain:
                _period_delivery_error("period_delivery_history_missing", run, saved, item)
            missing_checks = True
        result["file_evidence"][key] = {
            "materialization_id": original.storage_id, "checks": checks,
            "before_event_id": cutoff,
            "successors": [{key: value for key, value in link.items() if key not in ("item", "record")}
                           for link in chain],
        }
    result["allowed_events_complete"] = not missing_events and not missing_checks
    result["events_complete"] = scope_complete and result["allowed_events_complete"]
    result["reason"] = (
        "missing_events" if missing_events else "missing_checks" if missing_checks else "ok"
    )
    _period_delivery_assert_controls(controls, cancel)
    return result


def _period_delivery_file_proven(evidence, item, *, closed=False, cp=None, current_version=None):
    """Validate the explicit per-file proof before accepting a scoped receipt."""
    import re

    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names,
    )

    if not isinstance(evidence, dict):
        return False
    if closed or "cp_source" in evidence:
        return closed and evidence == {"cp_source": str(cp)}
    materialization_id = evidence.get("materialization_id")
    successors = evidence.get("successors")
    if (
        type(materialization_id) is not int or materialization_id <= 0
        or not isinstance(successors, list) or any(not isinstance(link, dict) for link in successors)
    ):
        return False
    if "before_event_id" not in evidence:
        return False
    current_version = item["version"] if current_version is None else current_version
    cutoff = evidence["before_event_id"]
    if current_version == item["version"]:
        if successors or cutoff is not None:
            return False
    elif (
        not successors or type(cutoff) is not int or cutoff <= materialization_id
        or cutoff != successors[0].get("first_materialization_id")
    ):
        return False

    seen, previous = set(), materialization_id
    proofs = [(materialization_id, evidence.get("checks"), cutoff)]
    for index, link in enumerate(successors):
        if not isinstance(link, dict):
            return False
        execution, receipt_hash = link.get("raw_execution_id"), link.get("file_receipt_hash")
        first, materialization = link.get("first_materialization_id"), link.get("materialization_id")
        if (
            not isinstance(execution, str) or re.fullmatch(r"[0-9a-f]{64}", execution) is None
            or execution in seen or not isinstance(receipt_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", receipt_hash) is None
            or type(first) is not int or first <= previous
            or type(materialization) is not int or materialization < first
        ):
            return False
        seen.add(execution)
        previous = materialization
        following = successors[index + 1] if index + 1 < len(successors) else None
        if following is not None and not isinstance(following, dict):
            return False
        proofs.append((materialization, link.get("checks"),
                       following.get("first_materialization_id") if following is not None else None))
    names = set(raw_check_names(item["freq"]))
    for target, checks, cutoff in proofs:
        if not isinstance(checks, dict) or set(checks) != names:
            return False
        if any(
            not isinstance(value, dict)
            or type(value.get("evaluation_event_storage_id")) is not int
            or value["evaluation_event_storage_id"] <= 0
            or type(value.get("materialization_id")) is not int
            or value["materialization_id"] != target
            or (cutoff is not None and (type(cutoff) is not int
                                       or value["evaluation_event_storage_id"] >= cutoff))
            for value in checks.values()
        ):
            return False
    return True


def acknowledge_period_delivery(run, confirmation, *, root, staging, cancel=lambda: False):
    """Persist original receipts and phase before removing only the matching consumed work."""
    from orchestrator.defs.bootstrap.stock_period_history import (
        check_devices,
        completed_receipt,
        history_work_identity,
        roots,
        writer,
    )
    from orchestrator.defs.run_contracts.stock_period import (
        completion_notice,
        completion_reference,
        period_for,
        verify_execution,
    )

    root, staging = roots(root, staging)
    run = safe_path(Path(run))
    if run != staging / "stock_period/runs" / run.name:
        raise ValueError("period_event_run_path_invalid")
    with writer(staging):
        controls = {key: dict(value) for key, value in confirmation["control_versions"].items()}
        _period_delivery_assert_controls(controls, cancel)
        saved = read_json(run / "manifest.json")
        verify_execution(saved, run.name)
        if saved["identity"]["root"] != str(root):
            raise ValueError("period_delivery_control_changed")
        check_devices(root, staging, saved["devices"])
        complete = completed_receipt(run, saved, cancel=cancel)
        frequencies = {item["freq"] for item in complete["files"]}
        scope = confirmation.get("allowed_frequencies")
        if not isinstance(scope, (list, tuple, set)) or not set(scope) <= {"week", "month"}:
            raise ValueError("period_delivery_confirmation_invalid")
        allowed = set(scope) & frequencies
        selected = [item for item in complete["files"] if item["freq"] in allowed]
        full_batch = allowed == frequencies
        if (
            not allowed
            or confirmation.get("allowed_events_complete") is not True
            or type(confirmation.get("events_complete")) is not bool
            or confirmation["events_complete"] != full_batch
            or type(confirmation.get("historical_only")) is not bool
            or confirmation.get("run_id") != run.name
            or confirmation.get("identity_hash") != saved["identity_hash"]
            or confirmation.get("file_receipt_hash") != saved["file_receipt_hash"]
            or confirmation.get("files") != complete["files"]
            or not isinstance(confirmation.get("file_evidence"), dict)
            or set(confirmation["file_evidence"]) != {(item["freq"], item["period"]) for item in selected}
            or not isinstance(confirmation.get("completion_evidence"), dict)
            or set(confirmation["completion_evidence"]) != allowed
        ):
            raise ValueError("period_delivery_confirmation_invalid")
        closed = saved["phase"] == "events_complete"
        manifest_cache = {}

        def controlled_json(path):
            key = str(path)
            expected = controls.get(key)
            if not isinstance(expected, dict) or expected.get("kind") != "json" or expected.get("version") is None:
                raise ValueError("period_delivery_confirmation_invalid")
            _period_delivery_assert_controls({key: expected}, cancel)
            payload = read_json(path)
            if digest(payload) != expected.get("digest"):
                raise ValueError("period_delivery_confirmation_invalid")
            _period_delivery_assert_controls({key: expected}, cancel)
            return payload

        def verify_successors(evidence, item, current_version):
            version = item["version"]
            for link in evidence["successors"]:
                execution = link["raw_execution_id"]
                if execution == run.name:
                    raise ValueError("period_delivery_confirmation_invalid")
                successor = safe_path(staging / "stock_period/runs" / execution)
                manifest_path, complete_path = successor / "manifest.json", successor / "complete.json"
                if str(complete_path) not in controls:
                    raise ValueError("period_delivery_confirmation_invalid")
                _period_delivery_assert_controls({str(complete_path): controls[str(complete_path)]}, cancel)
                other_saved = manifest_cache.get(execution)
                if other_saved is None:
                    other_saved = controlled_json(manifest_path)
                    verify_execution(other_saved, execution)
                    check_devices(root, staging, other_saved["devices"])
                    if (
                        other_saved["identity"]["root"] != str(root)
                        or other_saved["phase"] not in ("files_complete", "events_complete")
                    ):
                        raise ValueError("period_delivery_confirmation_invalid")
                    manifest_cache[execution] = other_saved
                else:
                    _period_delivery_assert_controls({str(manifest_path): controls[str(manifest_path)]}, cancel)
                if (
                    link["file_receipt_hash"] != other_saved.get("file_receipt_hash")
                    or link["file_receipt_hash"] != controls[str(complete_path)].get("digest")
                ):
                    raise ValueError("period_delivery_confirmation_invalid")
                committed = controlled_json(successor / "committed" / item["freq"] / (item["period"] + ".json"))
                next_version = committed.get("version") if isinstance(committed, dict) else None
                if (
                    not isinstance(committed, dict)
                    or any(committed.get(key) != item[key] for key in ("freq", "period", "target"))
                    or committed.get("target_preimage") != version
                    or not isinstance(next_version, list) or len(next_version) != 5
                    or any(type(value) is not int or value < 0 for value in next_version)
                    or type(committed.get("rows")) is not int or committed["rows"] < 0
                    or not isinstance(committed.get("sha256"), str) or len(committed["sha256"]) != 64
                ):
                    raise ValueError("period_delivery_confirmation_invalid")
                version = next_version
            if version != current_version:
                raise ValueError("period_delivery_confirmation_invalid")

        historical = closed
        for item in selected:
            cp = run / "events" / item["freq"] / (item["period"] + ".json")
            current_version = None
            if not closed:
                target_control = controls.get(item["target"])
                current_version = target_control.get("version") if isinstance(target_control, dict) else None
                if (
                    not isinstance(target_control, dict) or target_control.get("kind") != "file"
                    or not isinstance(current_version, list) or len(current_version) != 5
                    or any(type(value) is not int or value < 0 for value in current_version)
                ):
                    raise ValueError("period_delivery_confirmation_invalid")
                historical = historical or current_version != item["version"]
            evidence = confirmation["file_evidence"][(item["freq"], item["period"])]
            if not _period_delivery_file_proven(
                evidence, item, closed=closed, cp=cp, current_version=current_version,
            ):
                raise ValueError("period_delivery_confirmation_invalid")
            if not closed:
                verify_successors(evidence, item, current_version)
        if confirmation["historical_only"] != historical:
            raise ValueError("period_delivery_confirmation_invalid")
        for freq in allowed:
            notice = completion_notice(
                completion_reference(run.name, saved["file_receipt_hash"], freq), freq,
                sum(item["freq"] == freq for item in complete["files"]),
            )
            evidence = confirmation["completion_evidence"][freq]
            if (
                not isinstance(evidence, dict) or evidence.get("completion") != notice
                or type(evidence.get("observation_id")) is not int or evidence["observation_id"] <= 0
            ):
                raise ValueError("period_delivery_confirmation_invalid")
        daily_path = staging / "stock_period/daily.json"
        daily = read_json(daily_path) if daily_path.exists() else None
        pending = (daily or {}).get("pending_work", {}).get(run.name)
        if (
            not closed and pending is None
            and saved["identity"]["intent"].get("mode") == "history"
            and saved["identity"]["intent"].get("asof") is None
        ):
            raise ValueError("period_history_registration_required")
        history_pending = pending is not None and pending.get("kind") == "history"
        if pending is not None:
            if pending.get("intent") != saved["identity"]["intent"]:
                raise ValueError("period_delivery_control_changed")
            if history_pending:
                if (
                    history_work_identity(pending) != saved["identity"]
                    or pending.get("devices") != saved["devices"]
                    or pending.get("started_at") != saved["started_at"]
                    or "consumed" in pending
                ):
                    raise ValueError("period_delivery_control_changed")
            elif pending.get("kind") is not None:
                raise ValueError("period_delivery_control_changed")
            elif confirmation["historical_only"] and pending.get("consumed") is not True:
                raise ValueError("period_delivery_consumption_missing")
            if not history_pending and pending.get("consumed") is True and pending["intent"].get("asof"):
                asof, freq = pending["intent"]["asof"], pending["frequency"]
                refresh_required = period_for(datetime.fromisoformat(asof).date(), freq) in pending["intent"].get("periods", {}).get(freq, ())
                if daily.get("factor_through", "") < asof or (
                    refresh_required and daily.get("last_refresh", {}).get(freq, "") < asof
                ):
                    raise ValueError("period_delivery_consumption_missing")

        common_paths = (
            str(run / "manifest.json"),
            str(run / "complete.json"),
            str(daily_path),
        )
        required = set(common_paths)
        required.update(str(run / "events" / item["freq"] / (item["period"] + ".json")) for item in selected)
        required.update(str(run / "events/completion" / (freq + ".json")) for freq in allowed)
        if not closed:
            required.update(item["target"] for item in selected)
        if not required <= controls.keys():
            raise ValueError("period_delivery_confirmation_invalid")

        def write_missing(path, payload, *, target=None, related_paths=()):
            key = str(path)
            _period_delivery_assert_controls({key: controls[key]}, cancel)
            actual = read_json(path) if path.exists() else None
            if actual is not None and actual != payload:
                raise ValueError("period_delivery_checkpoint_changed")
            if actual is None:
                related = set(common_paths) | {key} | set(related_paths)
                if target is not None:
                    related.add(target)
                _period_delivery_assert_controls(
                    {name: controls[name] for name in related if name in controls},
                    cancel,
                )
                atomic_json(path, payload)
                _period_delivery_json(path, controls)

        related_by_frequency = {freq: set() for freq in allowed}
        for item in selected:
            related = []
            evidence = confirmation["file_evidence"][(item["freq"], item["period"])]
            for link in (() if closed else evidence["successors"]):
                successor = staging / "stock_period/runs" / link["raw_execution_id"]
                related.extend(
                    str(path)
                    for path in (
                        successor / "manifest.json",
                        successor / "complete.json",
                        successor / "committed" / item["freq"] / (item["period"] + ".json"),
                    )
                )
            if not set(related) <= controls.keys():
                raise ValueError("period_delivery_confirmation_invalid")
            cp = run / "events" / item["freq"] / (item["period"] + ".json")
            related_by_frequency[item["freq"]].update(related)
            related_by_frequency[item["freq"]].add(str(cp))
            if not closed:
                related_by_frequency[item["freq"]].add(item["target"])
            write_missing(cp,
                          {key: item[key] for key in ("version", "sha256")},
                          target=item["target"], related_paths=related)
        for freq in allowed:
            notice = completion_notice(
                completion_reference(run.name, saved["file_receipt_hash"], freq), freq,
                sum(item["freq"] == freq for item in complete["files"]),
            )
            evidence = confirmation["completion_evidence"].get(freq)
            if evidence is None or evidence.get("completion") != notice or type(evidence.get("observation_id")) is not int or evidence["observation_id"] <= 0:
                raise ValueError("period_delivery_confirmation_invalid")
            for item in selected:
                if item["freq"] == freq:
                    cp = run / "events" / freq / (item["period"] + ".json")
                    _period_delivery_assert_controls({str(cp): controls[str(cp)]}, cancel)
                    if read_json(cp) != {key: item[key] for key in ("version", "sha256")}:
                        raise ValueError("period_delivery_checkpoint_changed")
            write_missing(run / "events/completion" / (freq + ".json"), evidence,
                          related_paths=related_by_frequency[freq])
        _period_delivery_assert_controls(controls, cancel)
        if not full_batch:
            return {"run_id": run.name, "allowed_events_complete": True,
                    "events_complete": False, "pending_removed": False}
        if saved["phase"] != "events_complete":
            atomic_json(run / "manifest.json", {**saved, "phase": "events_complete"})
            _period_delivery_json(run / "manifest.json", controls)
        _period_delivery_assert_controls(controls, cancel)
        latest = read_json(daily_path) if daily_path.exists() else None
        latest_pending = (latest or {}).get("pending_work", {}).get(run.name)
        removed = False
        if latest_pending is not None and (history_pending or latest_pending.get("consumed") is True):
            if latest_pending != pending:
                raise ValueError("period_delivery_control_changed")
            del latest["pending_work"][run.name]
            atomic_json(daily_path, latest)
            removed = True
        return {"run_id": run.name, "allowed_events_complete": True,
                "events_complete": True, "pending_removed": removed}


def report_file_events(instance, item, *, completion=None, write=True, context=None):
    """Report only validated immutable file versions; retry missing events without recompute."""
    import dagster as dg
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )

    from orchestrator.defs.io.stock_period_raw import file_version
    from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
    from orchestrator.defs.run_contracts.stock_monthly import (
        StockMonthlySource,
        monthly_check_names,
    )
    from orchestrator.defs.run_contracts.stock_period import FIELDS
    from orchestrator.defs.run_contracts.stock_weekly import (
        StockWeeklySource,
        weekly_check_names,
    )

    if file_version(item["target"]) != item["version"]:
        raise ValueError("period_event_file_changed")
    from orchestrator.defs.io.stock_period_raw import audit_file

    evidence = audit_file(Path(item["target"]).parents[4], item["freq"], item["period"])
    if evidence["rows"] != item["rows"] or evidence["sha256"] != item["sha256"]:
        raise ValueError("period_event_receipt_mismatch")
    freq = item["freq"]
    asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}")
    names = (
        weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED)
        if freq == "week"
        else monthly_check_names(StockMonthlySource.PRIMARY_ADJUSTED)
    )
    extra_metadata = {
        "goldenshare/period_file_version": dg.MetadataValue.json(item["version"])
    }
    if completion is not None:
        from orchestrator.defs.run_contracts.stock_period import (
            COMPLETION_METADATA_KEY,
            validate_completion_notice,
        )

        validate_completion_notice(completion, freq)
        extra_metadata[COMPLETION_METADATA_KEY] = dg.MetadataValue.json(completion)
    partition = item["period"]
    partset = "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months"
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[partition]), limit=1
    ).records
    record = records[0] if records else None
    from orchestrator.defs.asset_guards.stock_period_check_evidence import (
        read_latest_completed_checks,
    )

    try:
        checks = read_latest_completed_checks(
            instance, asset_key=asset, check_names=names, partition_key=partition
        )
    except ValueError:
        if not write:
            return False
        raise

    def matches_file(materialization, versions, *, exact_rows=False):
        if materialization is None:
            return False
        mat = materialization.asset_materialization
        metadata = mat.metadata
        return (
            mat.asset_key == asset
            and mat.partition == partition
            and getattr(metadata.get("dagster/uri"), "value", None) == item["target"]
            and getattr(
                metadata.get("goldenshare/period_file_version"), "value", None
            )
            in versions
            and (
                not exact_rows
                or getattr(metadata.get("dagster/row_count"), "value", None)
                == item["rows"]
            )
        )

    # Inspect every terminal result before adding partitions or emitting events.
    # A real later failure/misbinding must never be replaced by a synthetic pass.
    for check, event_id, bound in checks.values():
        evaluation = check.evaluation
        target = evaluation.target_materialization_data if evaluation else None
        valid = (
            check.status.value == "SUCCEEDED"
            and evaluation is not None
            and evaluation.passed
            and evaluation.blocking
            and target is not None
            and bound is not None
            and target.storage_id == bound.storage_id
            and target.run_id == bound.event_log_entry.run_id
            and target.timestamp == bound.event_log_entry.timestamp
        )
        if valid and record is not None and bound.storage_id == record.storage_id:
            valid = matches_file(
                bound, [item["version"], item.get("target_preimage")]
            )
        elif valid and record is not None and event_id < record.storage_id:
            valid = matches_file(
                bound, [item["version"], item.get("target_preimage")]
            ) and matches_file(record, [item["version"]], exact_rows=True)
        else:
            valid = False
        if not valid:
            if not write:
                return False
            raise ValueError("period_event_checks_invalid")

    fingerprint = (
        getattr(
            record.asset_materialization.metadata.get(
                "goldenshare/period_file_version"
            ),
            "value",
            None,
        )
        if record
        else None
    )
    if (
        completion is not None
        and fingerprint == item["version"]
        and getattr(
            record.asset_materialization.metadata.get(COMPLETION_METADATA_KEY),
            "value",
            None,
        )
        != completion
    ):
        if not write:
            return False
        raise ValueError("period_event_completion_mismatch")
    if record is not None and not matches_file(
        record, [item["version"], item.get("target_preimage")]
    ):
        if not write:
            return False
        raise ValueError("period_event_materialization_invalid")
    if fingerprint != item["version"]:
        if not write:
            return False
        instance.add_dynamic_partitions(partset, [partition])
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=asset,
                partition=partition,
                metadata=build_materialization_metadata(
                    uri=item["target"],
                    row_count=item["rows"],
                    observed_columns=FIELDS,
                    extra_metadata=extra_metadata,
                ),
            )
        )
        record = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[partition]),
            limit=1,
        ).records[0]
    if not matches_file(record, [item["version"]], exact_rows=True):
        if not write:
            return False
        raise ValueError("period_event_materialization_invalid")

    for name in names:
        selected = checks.get(name)
        evaluation = selected[0].evaluation if selected else None
        matched = (
            evaluation is not None
            and evaluation.partition == partition
            and evaluation.passed
            and evaluation.blocking
            and evaluation.target_materialization_data is not None
            and evaluation.target_materialization_data.storage_id == record.storage_id
        )
        if matched:
            continue
        if not write:
            return False
        if context is None:
            raise ValueError("period_event_real_run_required")
        from dagster._core.events import DagsterEvent, DagsterEventType

        op_context = getattr(context, "op_execution_context", context)
        instance.report_dagster_event(
            DagsterEvent(
                event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
                job_name=op_context.job_name,
                step_key=op_context.get_step_execution_context().step.key,
                event_specific_data=AssetCheckEvaluation(
                    asset_key=asset,
                    check_name=name,
                    partition=partition,
                    passed=True,
                    blocking=True,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=record.storage_id,
                        run_id=record.event_log_entry.run_id,
                        timestamp=record.event_log_entry.timestamp,
                    ),
                ),
            ),
            run_id=op_context.run_id,
        )
    return True


def report_completion_events(instance, completion):
    """One files-complete observation per frequency, never a passing check."""
    import dagster as dg

    from orchestrator.defs.run_contracts.stock_period import (
        COMPLETION_METADATA_KEY,
        validate_completion_notice,
    )

    validate_completion_notice(completion, completion["freq"])
    asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{completion['freq']}")
    instance.report_runless_asset_event(
        dg.AssetObservation(
            asset_key=asset,
            metadata={COMPLETION_METADATA_KEY: dg.MetadataValue.json(completion)},
        )
    )
    record = instance.fetch_observations(asset, limit=1).records[0]
    if record.asset_observation.metadata[COMPLETION_METADATA_KEY].value != completion:
        raise ValueError("period_completion_observation_mismatch")
    return record.storage_id


def _daily_intent_date(context, config):
    """An old manual run must not become a different date on re-execution."""
    if config.automatic_intent_date:
        return date.fromisoformat(config.automatic_intent_date)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    run = context.run
    parent = run.root_run_id or run.parent_run_id
    if parent:
        original = context.instance.get_run_record_by_id(parent)
        if (
            original is None
            or original.create_timestamp.astimezone(ZoneInfo("Asia/Shanghai")).date()
            != today
        ):
            raise ValueError(
                "period_daily_intent_date_required:use_frozen_asof_in_automatic_intent_date"
            )
    return today


def _current_period_anchor(instance, root, staging, freq, period):
    """A historical result cannot authorize materializing an unknown current file."""
    import dagster as dg

    from orchestrator.defs.bootstrap.stock_period_history import completed_receipt
    from orchestrator.defs.io.stock_period_raw import (
        audit_file,
        file_version,
        target_path,
    )
    from orchestrator.defs.run_contracts.stock_period import (
        COMPLETION_METADATA_KEY,
        validate_completion_notice,
    )

    target = target_path(root, freq, period)
    version = file_version(target)
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}"),
            asset_partitions=[period],
        ),
        limit=1,
    ).records
    if not records:
        raise ValueError("period_anchor_current_delivery_unknown")
    metadata = records[0].asset_materialization.metadata
    if (
        getattr(metadata.get("goldenshare/period_file_version"), "value", None)
        != version
        or getattr(metadata.get("dagster/uri"), "value", None) != str(target)
    ):
        raise ValueError("period_anchor_current_delivery_unknown")
    baseline = read_json(Path(staging) / "stock_period/baseline.json")
    owned = any(
        item["target"] == str(target) and item["version"] == version
        for item in baseline.get("files", [])
    )
    completion = getattr(metadata.get(COMPLETION_METADATA_KEY), "value", None)
    if completion is not None:
        reference = validate_completion_notice(completion, freq)
        run = Path(staging) / "stock_period/runs" / reference["raw_execution_id"]
        manifest = read_json(run / "manifest.json")
        complete = completed_receipt(run, manifest)
        if manifest["file_receipt_hash"] != reference["file_receipt_hash"]:
            raise ValueError("period_anchor_current_delivery_unknown")
        owned = any(
            item["target"] == str(target)
            and item["version"] == version
            and (item["freq"], item["period"]) == (freq, period)
            for item in complete["files"]
        )
    if not owned:
        raise ValueError("period_anchor_current_delivery_unknown")
    item = {
        "freq": freq,
        "period": period,
        "target": str(target),
        **audit_file(root, freq, period),
    }
    if not report_file_events(instance, item, completion=completion, write=False):
        raise ValueError("period_anchor_current_checks_missing")
    return item, completion


def deliver_asset(context, config, lake_root, freq):
    import dagster as dg

    from orchestrator.defs.bootstrap.stock_period_history import (
        frozen_history_work,
        load_scope,
        run_period,
    )
    from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
    from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
    from orchestrator.defs.run_contracts.stock_period import FIELDS, StockPeriodPolicy

    root = lake_root.root()
    staging = Path(DEFAULT_LAKE_STAGING_ROOT)
    today = _daily_intent_date(context, config) if config.intent == "daily" else None
    if today is not None and period_for(today, freq) != context.partition_key:
        raise ValueError("period_daily_partition_mismatch")
    lake_root.ensure_available_for_run()
    history_intent = {
        "version": VERSION, "mode": "history", "frequencies": ["week", "month"],
        "codes": sorted(set(config.stock_codes)), "request_id": config.request_id,
    } if config.intent == "history" else None
    frozen = frozen_history_work(root, staging, history_intent) if history_intent is not None else None
    if frozen is not None:
        listed, aliases = set(frozen["listed"]), frozen["aliases"]
    else:
        listed, aliases = load_scope(root, staging / "stock_period" / "scope")

    import time

    checked_at, cancelled = float("-inf"), False

    def cancel():
        nonlocal checked_at, cancelled
        if time.monotonic() - checked_at >= 2:
            checked_at = time.monotonic()
            run = context.instance.get_run_by_id(context.run.run_id)
            cancelled = run is not None and run.status in (
                dg.DagsterRunStatus.CANCELING,
                dg.DagsterRunStatus.CANCELED,
            )
        return cancelled

    def events(item, *, completion):
        return report_file_events(
            context.instance,
            item,
            completion=completion,
            write=(item["freq"], item["period"]) != (freq, context.partition_key),
            context=context,
        )

    def confirm_delivery(run):
        return confirm_period_delivery(
            context.instance, run, root=root, staging=staging, cancel=cancel
        )

    progress = lambda p: context.log.info(str(p))
    if config.intent == "history":
        results = [
            run_period(
                root=root,
                staging=staging,
                listed=listed,
                aliases=aliases,
                intent=history_intent,
                policy=StockPeriodPolicy(**frozen["policy"]) if frozen is not None else DEFAULT_POLICY,
                cancel=cancel,
                progress=progress,
                events=events,
                completion_events=lambda notice: report_completion_events(
                    context.instance, notice
                ),
                confirm_delivery=confirm_delivery,
            )
        ]
    else:
        results = execute_daily(
            root=root,
            staging=staging,
            today=today,
            freq=freq,
            listed=listed,
            aliases=aliases,
            cancel=cancel,
            progress=progress,
            events=events,
            completion_events=lambda notice: report_completion_events(
                context.instance, notice
            ),
            confirm_delivery=confirm_delivery,
        )
    items = [
        i
        for result in results
        if not result.get("historical_only")
        for i in result.get("current_files", result["files"])
        if (i["freq"], i["period"]) == (freq, context.partition_key)
    ]
    fallback_completion = None
    if not items:
        if config.intent == "history":
            raise ValueError("period_asset_anchor_not_written")
        current, fallback_completion = _current_period_anchor(
            context.instance, root, staging, freq, context.partition_key
        )
        items = [current]
    item = items[-1]
    completion = next(
        (
            r.get("completions", {}).get(freq)
            for r in reversed(results)
            if item in r["files"]
        ),
        fallback_completion,
    )
    extra = {"goldenshare/period_file_version": dg.MetadataValue.json(item["version"])}
    if completion is not None:
        from orchestrator.defs.run_contracts.stock_period import COMPLETION_METADATA_KEY

        extra[COMPLETION_METADATA_KEY] = dg.MetadataValue.json(completion)
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=item["target"],
            row_count=item["rows"],
            observed_columns=FIELDS,
            extra_metadata=extra,
        )
    )


def evaluate_daily_sensor(context, now, *, freq, staging_root=None):
    import dagster as dg

    from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
    from orchestrator.defs.run_contracts.configs import build_stock_period_run_config
    from orchestrator.defs.run_contracts.cursor_payloads import (
        build_cursor_details,
        cursor_runtime_state,
    )
    from orchestrator.defs.run_contracts.cursors import (
        build_sensor_cursor,
        load_sensor_cursor,
        sensor_cursor_details,
    )
    from orchestrator.defs.run_contracts.requests import build_run_request
    from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key

    staging = Path(staging_root or DEFAULT_LAKE_STAGING_ROOT)
    now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    if (now.hour, now.minute) < (19, 30):
        return dg.SensorResult(skip_reason=dg.SkipReason("尚未到上海时间19:30。"))
    asset = f"raw_tushare_stk_period_bar_adj_{freq}"
    job = f"raw_stk_period_bar_adj_{freq}_update_job"
    statuses = [
        dg.DagsterRunStatus.NOT_STARTED,
        dg.DagsterRunStatus.QUEUED,
        dg.DagsterRunStatus.STARTING,
        dg.DagsterRunStatus.STARTED,
        dg.DagsterRunStatus.CANCELING,
    ]
    for other in ("week", "month"):
        if context.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=f"raw_stk_period_bar_adj_{other}_update_job", statuses=statuses
            ),
            limit=1,
        ):
            return dg.SensorResult(
                skip_reason=dg.SkipReason("周/月Raw已有写者，保留原水位等待。")
            )
    baseline = staging / "stock_period" / "baseline.json"
    state = daily_state(staging)
    if (
        not baseline.exists()
        or read_json(baseline).get("status") != "ready"
        or not daily_handoff_ready(state)
    ):
        return dg.SensorResult(
            skip_reason=dg.SkipReason(
                "新源bootstrap尚未交接，保留旧cursor，不提交任务。"
            )
        )
    import tempfile

    from orchestrator.defs.duckdb_connection import (
        DuckDBConnectionSettings,
        connect_configured_duckdb,
    )
    from orchestrator.defs.paths import silver_trade_calendar_path

    with connect_configured_duckdb(
        DuckDBConnectionSettings(temp_directory=Path(tempfile.gettempdir()).resolve()),
        temp_policy="existing_no_spill",
    ) as con:
        open_today = con.execute(
            "SELECT count(*) FROM read_parquet(?) WHERE exchange='SSE' AND is_open=1 AND trade_date=?",
            [
                str(silver_trade_calendar_path(context.resources.lake_root.root())),
                now.date(),
            ],
        ).fetchone()[0]
    if not open_today:
        return dg.SensorResult(skip_reason=dg.SkipReason("非交易日，不请求周/月源。"))
    pending = daily_periods(
        today=now.date(),
        freq=freq,
        completed_through=state["completed_through"][freq],
        last_refresh=state["last_refresh"].get(freq),
    )
    if not pending and not state.get("pending_work"):
        return dg.SensorResult(
            skip_reason=dg.SkipReason("当天已刷新；周期完成水位保持独立。")
        )
    # One asset run processes deduplicated backlog before current. Anchor is always the current partition.
    anchor = period_for(now.date(), freq)
    partname = "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months"
    from orchestrator.defs.partitions import cn_a_stock_months, cn_a_stock_week_ends

    partitions = cn_a_stock_week_ends if freq == "week" else cn_a_stock_months
    request = build_run_request(
        run_key=build_asset_update_run_key(
            subject=asset, unit_id=now.date().isoformat()
        ),
        job_name=job,
        partition_key=anchor,
        run_config=build_stock_period_run_config(freq, now.date().isoformat()),
    )
    old = cursor_runtime_state(
        sensor_cursor_details(load_sensor_cursor(context.cursor))
    )
    details = build_cursor_details(
        sensor_name=f"raw_stock_{'weekly' if freq == 'week' else 'monthly'}_update_job_sensor",
        job_name=job,
        asset_family="stock_period",
        partition_set=partname,
        reason_code="direct_source_request",
        blocked_component="none",
        summary="先补欠账，再更新当前周期。",
        next_action="等待源交付及文件检查。",
        runtime_state={
            **old,
            "source_policy": VERSION,
            "direct_completed_through": state["completed_through"][freq],
        },
        evidence={
            "pending_periods": pending,
            "daily_intent_date": now.date().isoformat(),
        },
    )
    return dg.SensorResult(
        run_requests=[request],
        dynamic_partitions_requests=[partitions.build_add_request([anchor])],
        cursor=build_sensor_cursor(
            evaluated_at=now,
            decision="request_runs",
            target_date=anchor,
            selected_count=1,
            details=details,
        ),
    )


def handoff_bootstrap(
    *,
    root,
    staging,
    run,
    events,
    completion_events=None,
    confirm_delivery=None,
    transport=None,
    listed=None,
    aliases=None,
    through=None,
    now=None,
    runtime_rss_bytes=None,
    cancel=lambda: False,
    progress=lambda _: None,
):
    """One frozen catch-up intent for the actual capture interval, then ready."""
    from orchestrator.defs.bootstrap.stock_period_history import (
        load_scope,
        replay_events,
        require_pending_delivery_before_write,
        roots,
        run_period,
        verify_rss_resume,
        writer,
    )
    from orchestrator.defs.run_contracts.stock_period import (
        StockPeriodPolicy,
        verify_execution,
    )

    if runtime_rss_bytes is not None and (
        type(runtime_rss_bytes) is not int or runtime_rss_bytes <= 0
    ):
        raise ValueError("period_runtime_rss_limit_invalid")
    root, staging = roots(root, staging)
    with writer(staging), ExitStack() as execution:
        run = safe_path(run)
        parent = read_json(run / "manifest.json")
        verify_execution(parent, run.name)
        if parent["identity"]["intent"]["mode"] != "bootstrap" or parent["identity"][
            "root"
        ] != str(root):
            raise ValueError("period_handoff_parent_invalid")
        baseline_path = staging / "stock_period/baseline.json"
        baseline = read_json(baseline_path)
        statepath = staging / "stock_period/daily.json"
        prior = read_json(statepath) if statepath.exists() else {}
        if baseline.get("run_id") != run.name:
            raise ValueError("period_handoff_baseline_changed")
        if (
            baseline.get("status") == "ready"
            and prior.get("baseline_run_id") == run.name
            and daily_handoff_ready(prior)
        ):
            return prior
        if parent["phase"] != "events_complete":
            raise ValueError("period_handoff_events_incomplete")
        child_id = execution_id(parent["handoff"]["intent"]["request_id"]) if "handoff" in parent else None
        require_pending_delivery_before_write(
            staging, child_id, root=root, confirm_delivery=confirm_delivery, cancel=cancel
        )
        policy = StockPeriodPolicy(**parent["identity"]["policy"])
        if runtime_rss_bytes is not None:
            if "handoff" not in parent:
                raise ValueError("period_runtime_rss_handoff_invalid")
            child_id = execution_id(parent["handoff"]["intent"]["request_id"])
            child = read_json(
                safe_path(staging / "stock_period/runs" / child_id / "manifest.json")
            )
            verify_execution(child, child_id)
            verify_rss_resume(staging, child_id, child["identity"])
            execution.enter_context(
                process_memory_budget(policy, runtime_rss_bytes, progress=progress)
            )
        days = calendar_days(root, staging / "stock_period/calendar", policy)
        now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        now = now.astimezone(ZoneInfo("Asia/Shanghai"))
        released = [
            d
            for d in days
            if d < now.date().isoformat()
            or (d == now.date().isoformat() and (now.hour, now.minute) >= (19, 30))
        ]
        if not released:
            raise ValueError("period_handoff_calendar_missing")
        cutoff = through.isoformat() if through else released[-1]
        if cutoff not in released:
            raise ValueError("period_handoff_cutoff_not_released")
        if "handoff" not in parent:
            started = datetime.fromisoformat(parent["started_at"]).astimezone(
                ZoneInfo("Asia/Shanghai")
            )
            started_days = [
                d
                for d in days
                if d < started.date().isoformat()
                or (
                    d == started.date().isoformat()
                    and (started.hour, started.minute) >= (19, 30)
                )
            ]
            if not started_days or cutoff < started_days[-1]:
                raise ValueError("period_handoff_calendar_missing")
            begin = started_days[-1]
            if listed is None:
                listed, aliases = load_scope(
                    root, staging / "stock_period/scope", policy
                )
            aliases = aliases or {}
            original = set(parent["identity"]["listed"])
            changed = set(
                factor_changes(
                    root,
                    staging / "stock_period/factors",
                    days,
                    begin,
                    cutoff,
                    listed,
                    policy,
                    cancel,
                    progress,
                )
            ) | (set(listed) - original)
            retired = confirmed_retirements(
                root,
                staging / "stock_period/scope",
                {
                    c
                    for c in original
                    if c not in listed and aliases.get(c, c) not in listed
                },
                aliases,
            )
            superseded = sorted(
                c for c in original if c not in listed and aliases.get(c, c) in listed
            )
            unexplained = original - set(listed) - set(retired) - set(superseded)
            if unexplained:
                raise ValueError("period_handoff_scope_difference_unconfirmed")
            periods = {
                f: sorted(
                    {
                        period_for(date.fromisoformat(d), f)
                        for d in days
                        if begin <= d <= cutoff
                    }
                )
                for f in ("week", "month")
            }
            intent = {
                "version": VERSION,
                "mode": "upsert",
                "frequencies": ["week", "month"],
                "codes": sorted(changed),
                "retired_codes": retired,
                "superseded_codes": superseded,
                "periods": periods,
                "asof": cutoff,
                "bootstrap_parent": run.name,
                "request_id": digest(
                    {"kind": "period_handoff", "parent": run.name, "cutoff": cutoff}
                ),
                "period_cutoffs": {
                    f: {
                        p: min(cutoff, close_day(p, f, days)).replace("-", "")
                        for p in periods[f]
                    }
                    for f in periods
                },
            }
            parent["handoff"] = {
                "intent": intent,
                "listed": sorted(listed),
                "aliases": aliases,
                "confirmed_retired": retired,
                "begin": begin,
                "cutoff": cutoff,
            }
            atomic_json(run / "manifest.json", parent)
        work = parent["handoff"]
        cutoff = work["cutoff"]
        result = run_period(
            root=root,
            staging=staging,
            intent=work["intent"],
            listed=set(work["listed"]),
            aliases=work["aliases"],
            confirmed_retired=work["confirmed_retired"],
            transport=transport,
            policy=policy,
            runtime_rss_bytes=runtime_rss_bytes,
            cancel=cancel,
            progress=progress,
            confirm_delivery=confirm_delivery,
        )
        result = replay_events(
            Path(result["path"]),
            root=root,
            staging=staging,
            events=events,
            completion_events=completion_events,
            confirm_delivery=confirm_delivery,
            cancel=cancel,
        )
        if not result["events_complete"]:
            raise ValueError("period_handoff_events_incomplete")
        # The child verifies published current/ended periods and all scope/factor work.
        state = bootstrap_watermarks(date.fromisoformat(cutoff), days)
        state.update(
            baseline_run_id=run.name,
            handoff_cutoff=cutoff,
            last_refresh={f: cutoff for f in ("week", "month")},
        )
        if prior.get("baseline_run_id") == run.name:
            state["factor_through"] = max(
                state["factor_through"], prior.get("factor_through", "")
            )
            for f in ("week", "month"):
                state["completed_through"][f] = max(
                    state["completed_through"][f],
                    prior.get("completed_through", {}).get(f, ""),
                )
                state["last_refresh"][f] = max(
                    cutoff, prior.get("last_refresh", {}).get(f, "")
                )
        latest = read_json(statepath) if statepath.exists() else {}
        state["pending_work"] = latest.get("pending_work", {})
        atomic_json(statepath, state)
        baseline = read_json(baseline_path)
        baseline.update(status="ready", listed=work["listed"], handoff_cutoff=cutoff)
        atomic_json(baseline_path, baseline)
        parent["handoff_complete"] = True
        atomic_json(run / "manifest.json", parent)
        return state
