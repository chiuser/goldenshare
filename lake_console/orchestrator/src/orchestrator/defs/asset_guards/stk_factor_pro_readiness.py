"""Stock-factor coverage inputs and native Dagster result readers."""

from __future__ import annotations

from datetime import date

import duckdb

# These read-only producers are shared with the existing bootstrap month path.
from orchestrator.defs.assets.stock_identity_map import (
    STOCK_IDENTITY_ALLOWED_CONFIDENCE,
    STOCK_IDENTITY_ALLOWED_SOURCES,
)
from orchestrator.defs.checks.stk_factor_pro import (
    factor_file_identity,
    factor_file_sha,
    factor_known_file_sha,
    relation_identifier,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import (
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
    SILVER_STOCK_LIFECYCLE_SCHEMA,
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_ACTIVE_RUN_STATUSES,
    StkFactorProCoverageCounts,
)
from orchestrator.tushare_download.contract_registry import content_digest

STK_FACTOR_PRO_COVERAGE_TABLES = tuple(
    "stk_factor_pro_coverage_" + suffix
    for suffix in (
        "missing", "extra", "mapping", "expected", "optional", "eligible",
        "listed", "suspend", "first_day", "actual", "actual_mapping",
        "combined_mapping", "actual_compared",
    )
)


def stk_factor_pro_invalid_code_sql(column: str) -> str:
    """The one existing stock-code rule shared by coverage and its inputs."""
    field = relation_identifier(column)
    return (
        f"({field} IS NULL OR NOT regexp_full_match("
        f"{field}, '[0-9]{{6}}\\.(SH|SZ|BJ)'))"
    )


def build_stk_factor_pro_coverage_keys(
    connection,
    *,
    target_trade_date: date,
    listed_relation: str,
    full_suspend_relation: str,
    optional_relation: str,
    actual_relation: str,
    identity_relation: str,
) -> StkFactorProCoverageCounts:
    if type(target_trade_date) is not date:
        raise ValueError("覆盖日期必须是DATE")
    relations = tuple(
        relation_identifier(value)
        for value in (
            listed_relation, full_suspend_relation, optional_relation, actual_relation
        )
    )
    identity = relation_identifier(identity_relation)
    for relation in relations:
        schema = tuple(
            (r[0], r[1]) for r in connection.execute(f"DESCRIBE {relation}").fetchall()
        )
        if schema != (("trade_date", "DATE"), ("ts_code", "VARCHAR")):
            raise ValueError("覆盖输入必须是本日DATE/VARCHAR代码关系")
        bad = connection.execute(
            f"SELECT count(*) FROM {relation} WHERE trade_date IS DISTINCT FROM ? OR "
            f"{stk_factor_pro_invalid_code_sql('ts_code')}",
            [target_trade_date],
        ).fetchone()[0]
        if bad:
            raise ValueError("覆盖输入含错日期或非法代码")
    schema = {r[0]: r[1] for r in connection.execute(f"DESCRIBE {identity}").fetchall()}
    if any(
        schema.get(name) != kind
        for name, kind in (
            ("source_ts_code", "VARCHAR"),
            ("latest_ts_code", "VARCHAR"),
            ("valid_from", "DATE"),
            ("valid_to", "DATE"),
        )
    ):
        raise ValueError("身份映射输入类型不符合现行合同")
    return _build_stk_factor_pro_coverage_keys(
        connection,
        target_trade_date=target_trade_date,
        listed_relation=relations[0],
        full_suspend_relation=relations[1],
        optional_relation=relations[2],
        actual_relation=relations[3],
        identity_relation=identity,
    )


def _build_stk_factor_pro_coverage_keys(
    connection,
    *,
    target_trade_date: date,
    listed_relation: str,
    full_suspend_relation: str,
    optional_relation: str,
    actual_relation: str,
    identity_relation: str,
) -> StkFactorProCoverageCounts:
    """Prepare the fixed-date expected keys, then compare the actual keys once."""
    keys = _prepare_stk_factor_pro_expected_keys(
        connection,
        target_trade_date=target_trade_date,
        listed_relation=listed_relation,
        full_suspend_relation=full_suspend_relation,
        optional_relation=optional_relation,
        identity_relation=identity_relation,
    )
    return compare_stk_factor_pro_coverage_keys(
        connection,
        target_trade_date=target_trade_date,
        actual_relation=actual_relation,
        identity_relation=identity_relation,
        **keys,
    )


def _prepare_stk_factor_pro_expected_keys(
    connection, *, target_trade_date, listed_relation, full_suspend_relation,
    optional_relation, identity_relation,
):
    relations = (listed_relation, full_suspend_relation, optional_relation)
    for name in STK_FACTOR_PRO_COVERAGE_TABLES:
        connection.execute(f"DROP TABLE IF EXISTS {name}")
    union = " UNION ".join(f"SELECT trade_date,ts_code FROM {r}" for r in relations)
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_mapping AS "
        f"SELECT k.trade_date,k.ts_code,count(i.source_ts_code) AS mappings,min(i.latest_ts_code) AS latest "
        f"FROM ({union}) k LEFT JOIN {identity_relation} i ON i.source_ts_code=k.ts_code "
        "AND k.trade_date>=i.valid_from AND (i.valid_to IS NULL OR k.trade_date<i.valid_to) "
        "GROUP BY k.trade_date,k.ts_code"
    )
    for relation, suffix in zip(
        relations, ("listed", "suspend", "first_day"), strict=True
    ):
        connection.execute(
            f"CREATE TEMP TABLE stk_factor_pro_coverage_{suffix} AS SELECT DISTINCT k.trade_date,m.latest AS ts_code "
            f"FROM {relation} k JOIN stk_factor_pro_coverage_mapping m USING(trade_date,ts_code)"
        )
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_eligible AS SELECT * FROM stk_factor_pro_coverage_listed EXCEPT SELECT * FROM stk_factor_pro_coverage_suspend"
    )
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_optional AS SELECT * FROM stk_factor_pro_coverage_eligible INTERSECT SELECT * FROM stk_factor_pro_coverage_first_day"
    )
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_expected AS SELECT * FROM stk_factor_pro_coverage_eligible EXCEPT SELECT * FROM stk_factor_pro_coverage_optional"
    )
    return {
        "expected_relation": "stk_factor_pro_coverage_expected",
        "optional_relation": "stk_factor_pro_coverage_optional",
        "basis_mapping_relation": "stk_factor_pro_coverage_mapping",
    }


def compare_stk_factor_pro_coverage_keys(
    connection, *, target_trade_date, expected_relation, optional_relation,
    actual_relation, identity_relation, basis_mapping_relation,
) -> StkFactorProCoverageCounts:
    """Reuse prepared E/F and basis identities; map only newly seen actual codes."""
    for suffix in (
        "missing", "extra", "actual_mapping", "combined_mapping", "actual",
        "actual_compared",
    ):
        connection.execute(f"DROP TABLE IF EXISTS stk_factor_pro_coverage_{suffix}")
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_actual_mapping AS "
        "SELECT k.trade_date,k.ts_code,count(i.source_ts_code) AS mappings,min(i.latest_ts_code) AS latest "
        f"FROM (SELECT DISTINCT trade_date,ts_code FROM {actual_relation}) k "
        f"LEFT JOIN {identity_relation} i ON i.source_ts_code=k.ts_code "
        "AND k.trade_date>=i.valid_from AND (i.valid_to IS NULL OR k.trade_date<i.valid_to) "
        f"WHERE NOT EXISTS (SELECT 1 FROM {basis_mapping_relation} b "
        "WHERE b.trade_date=k.trade_date AND b.ts_code=k.ts_code) "
        "GROUP BY k.trade_date,k.ts_code"
    )
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_combined_mapping AS "
        f"SELECT * FROM {basis_mapping_relation} UNION ALL "
        "SELECT * FROM stk_factor_pro_coverage_actual_mapping"
    )
    missing, ambiguous = connection.execute(
        "SELECT count(*) FILTER (WHERE mappings=0),count(*) FILTER (WHERE mappings>1 OR (mappings=1 AND "
        f"{stk_factor_pro_invalid_code_sql('latest')})) FROM stk_factor_pro_coverage_combined_mapping"
    ).fetchone()
    if missing or ambiguous:
        absent = tuple(
            r[0]
            for r in connection.execute(
                "SELECT ts_code FROM stk_factor_pro_coverage_combined_mapping WHERE mappings=0 ORDER BY ts_code LIMIT 20"
            ).fetchall()
        )
        conflict = tuple(
            r[0]
            for r in connection.execute(
                "SELECT ts_code FROM stk_factor_pro_coverage_combined_mapping WHERE mappings>1 OR "
                f"(mappings=1 AND {stk_factor_pro_invalid_code_sql('latest')}) "
                "ORDER BY ts_code LIMIT 20"
            ).fetchall()
        )
        return StkFactorProCoverageCounts(
            None,
            None,
            None,
            None,
            None,
            missing,
            ambiguous,
            absent,
            conflict,
            "身份映射缺失或不唯一，无法判断股票覆盖",
        )
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_actual AS SELECT DISTINCT k.trade_date,m.latest AS ts_code "
        f"FROM {actual_relation} k JOIN stk_factor_pro_coverage_combined_mapping m USING(trade_date,ts_code)"
    )
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_actual_compared AS SELECT * FROM stk_factor_pro_coverage_actual "
        f"EXCEPT SELECT * FROM {optional_relation}"
    )
    connection.execute(
        f"CREATE TEMP TABLE stk_factor_pro_coverage_missing AS SELECT * FROM {expected_relation} EXCEPT SELECT * FROM stk_factor_pro_coverage_actual_compared"
    )
    connection.execute(
        f"CREATE TEMP TABLE stk_factor_pro_coverage_extra AS SELECT * FROM stk_factor_pro_coverage_actual_compared EXCEPT SELECT * FROM {expected_relation}"
    )
    expected, actual, missing, extra = (
        connection.execute(
            f"SELECT count(*) FROM {name}"
        ).fetchone()[0]
        for name in (
            expected_relation, "stk_factor_pro_coverage_actual_compared",
            "stk_factor_pro_coverage_missing", "stk_factor_pro_coverage_extra",
        )
    )
    return StkFactorProCoverageCounts(
        expected,
        actual,
        expected - missing,
        missing,
        extra,
        0,
        0,
        (),
        (),
        "已按上市首日可选、全天停牌和有效身份计算覆盖",
    )


def read_stk_factor_pro_other_active_runs(
    instance, *, own_run_id=None, active_statuses=STK_FACTOR_PRO_ACTIVE_RUN_STATUSES
):
    """Two bounded queries; bootstrap has no own Dagster run to exclude."""
    import dagster as dg

    from orchestrator.defs.run_contracts.stk_factor_pro import (
        STK_FACTOR_PRO_WRITE_JOB_NAMES,
    )

    active = []
    for name in STK_FACTOR_PRO_WRITE_JOB_NAMES:
        records = instance.get_run_records(
            filters=dg.RunsFilter(job_name=name, statuses=active_statuses),
            limit=2,
        )
        active.extend(
            record.dagster_run
            for record in records
            if record.dagster_run.run_id != own_run_id
        )
    return tuple(sorted(active, key=lambda run: (run.job_name, run.run_id)))


def require_stk_factor_pro_no_other_active_runs(instance, *, own_run_id=None):
    import dagster as dg

    try:
        active = read_stk_factor_pro_other_active_runs(instance, own_run_id=own_run_id)
    except Exception as error:
        raise dg.Failure(
            "无法确认股票技术因子任务状态；保持自动更新停止，核实后重新发起",
            allow_retries=False,
        ) from error
    if active:
        sample = ", ".join(
            f"{run.job_name}/{run.run_id}/{run.status.value}" for run in active
        )
        raise dg.Failure(
            f"存在其他股票技术因子任务：{sample}；保持自动更新停止，处理完活动任务后重新发起",
            allow_retries=False,
        )


def read_stk_factor_pro_run(instance, run_id, *, known_pg):
    """A fixed run identity is obtained once; live cancel polling is separate."""
    key = ("run", run_id)
    if key not in known_pg:
        known_pg[key] = instance.get_run_by_id(run_id)
    run = known_pg[key]
    if run is None:
        raise ValueError(f"股票技术因子原任务不存在：{run_id}")
    return run


def _stk_factor_pro_run_target(run):
    from dagster._core.storage.tags import PARTITION_NAME_TAG

    from orchestrator.defs.run_contracts import stk_factor_pro as C

    if run.job_name == C.STK_FACTOR_PRO_UPDATE_JOB_NAME:
        config = run.run_config["ops"]["stk_factor_pro"]["config"]
        target = C.normalize_stk_factor_pro_trade_date(config["target_trade_date"])
        if run.tags.get(PARTITION_NAME_TAG) != target:
            raise ValueError("日更原任务分区与配置不符")
    elif run.job_name == C.STK_FACTOR_PRO_REPAIR_JOB_NAME:
        config = run.run_config["ops"]["repair_stk_factor_pro_history"]["config"]
        target = C.normalize_stk_factor_pro_trade_date(config["target_trade_date"])
    else:
        raise ValueError("不是股票技术因子日更或repair任务")
    return date.fromisoformat(target)


def read_stk_factor_pro_failure(instance, run_id, *, known_pg):
    """Read actual Failure metadata once; missing evidence never means retryable."""
    import dagster as dg

    read_stk_factor_pro_run(instance, run_id, known_pg=known_pg)
    key = ("failure", run_id)
    if key in known_pg:
        return known_pg[key]
    records = instance.event_log_storage.get_records_for_run(
        run_id, of_type=dg.DagsterEventType.STEP_FAILURE, limit=1, ascending=False
    ).records
    result = {"retryable": False, "failure_phase": None}
    if records:
        failure = records[
            0
        ].event_log_entry.dagster_event.step_failure_data.user_failure_data
        metadata = failure.metadata if failure is not None else {}
        values = {k: getattr(v, "value", v) for k, v in metadata.items()}
        phase = values.get("goldenshare/failure_phase")
        target = values.get("goldenshare/target_trade_date")
        if (
            phase in ("precheck", "day", "history")
            and type(values.get("goldenshare/retryable")) is bool
            and target
            == _stk_factor_pro_run_target(known_pg[("run", run_id)]).isoformat()
        ):
            result = {
                "retryable": values["goldenshare/retryable"],
                "failure_phase": phase,
            }
    known_pg[key] = result
    return result


def _stk_factor_pro_observation(instance, record, *, target, known_pg):
    import dagster as dg

    from orchestrator.defs.run_contracts import stk_factor_pro as C

    key = ("phase_result", record.storage_id)
    if key in known_pg:
        return known_pg[key]
    if (
        record.asset_key != dg.AssetKey(C.STK_FACTOR_PRO_RAW_ASSET_KEY)
        or record.partition_key != target.isoformat()
    ):
        raise ValueError("观察资产或分区不是原目标T")
    values = C.parse_stk_factor_pro_observation_metadata(
        record.event_log_entry.dagster_event.asset_observation_data.asset_observation.metadata
    )
    run_id = record.event_log_entry.run_id
    if values["producer_run_id"] != run_id or values["target_trade_date"] != target:
        raise ValueError("观察生产任务或目标日期不符")
    run = read_stk_factor_pro_run(instance, run_id, known_pg=known_pg)
    if _stk_factor_pro_run_target(run) != target:
        raise ValueError("观察任务配置不是原目标T")
    if run.job_name == C.STK_FACTOR_PRO_UPDATE_JOB_NAME:
        config = run.run_config["ops"]["stk_factor_pro"]["config"]
        if values["execution_day"].isoformat() != config["execution_day"] or any(
            values[name] != config.get(name)
            or type(values[name]) is not type(config.get(name))
            for name in ("purpose", "scheduled_slot")
        ):
            raise ValueError("观察用途/时点与原运行配置不符")
    elif values["purpose"] != "manual_repair":
        raise ValueError("repair观察用途错误")
    known_pg[("observation", record.storage_id)] = record
    known_pg[key] = values
    return values


def _stk_factor_pro_exact_observation(instance, reference, *, target, phase, known_pg):
    import dagster as dg

    from orchestrator.defs.run_contracts import stk_factor_pro as C

    key = ("observation", reference.storage_id)
    if key not in known_pg:
        records = instance.fetch_observations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(C.STK_FACTOR_PRO_RAW_ASSET_KEY),
                asset_partitions=[target.isoformat()],
                storage_ids=[reference.storage_id],
            ),
            limit=1,
            ascending=False,
        ).records
        if len(records) != 1:
            raise ValueError("明确引用的日/历史观察缺失")
        known_pg[key] = records[0]
    record = known_pg[key]
    if record.event_log_entry.run_id != reference.run_id:
        raise ValueError("观察引用storage_id与run不符")
    values = _stk_factor_pro_observation(
        instance, record, target=target, known_pg=known_pg
    )
    if values["phase"] != phase:
        raise ValueError("观察引用不是要求的日/历史阶段")
    return values


def read_stk_factor_pro_recorded_results(
    instance, *, target_trade_date, known_pg, exclude_run_id=None
):
    """Read one entry and its two direct phase references; never walk old chains."""
    import dagster as dg
    from dagster._core.storage.tags import PARTITION_NAME_TAG

    from orchestrator.defs.run_contracts import stk_factor_pro as C

    target = target_trade_date
    key = ("recorded_results", target)
    if key in known_pg:
        return known_pg[key]
    discovery = ("observations", target)
    if discovery not in known_pg:
        known_pg[discovery] = tuple(
            instance.fetch_observations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(C.STK_FACTOR_PRO_RAW_ASSET_KEY),
                    asset_partitions=[target.isoformat()],
                ),
                limit=1,
                ascending=False,
            ).records
        )
    records = known_pg[discovery]
    values = None
    result = C.empty_stk_factor_pro_recorded_results(target)
    day_values = history_values = None
    history_failure_observed_at = None
    if records:
        record = records[0]
        if record.event_log_entry.run_id == exclude_run_id:
            raise ValueError("必须在本run第一条观察之前读取既有结果")
        values = _stk_factor_pro_observation(
            instance, record, target=target, known_pg=known_pg
        )
        ref = C.StkFactorProResultRef(record.event_log_entry.run_id, record.storage_id)
        day_ref, history_ref = (
            values["prior_day_result"],
            values["prior_history_result"],
        )
        if values["phase"] == "day":
            day_ref, day_values = ref, values
        elif values["phase"] == "history":
            history_ref, history_values = ref, values
        if day_ref is not None and day_values is None:
            day_values = _stk_factor_pro_exact_observation(
                instance, day_ref, target=target, phase="day", known_pg=known_pg
            )
        if history_ref is not None and history_values is None:
            history_values = _stk_factor_pro_exact_observation(
                instance, history_ref, target=target, phase="history", known_pg=known_pg
            )
        pending, successful = (
            values["pending_plan_refs"],
            values["successful_publication_refs"],
        )
        history_failure = values["unresolved_history_failure_run_id"]
        if history_values is not None:
            producer = read_stk_factor_pro_run(
                instance, history_values["producer_run_id"], known_pg=known_pg
            )
            if (
                history_values["result"] == "completed"
                and producer.status == dg.DagsterRunStatus.SUCCESS
            ):
                completed = C.RecordRef(
                    producer.run_id,
                    "publication/history/publication-complete.json",
                    history_values["publication_complete_digest"],
                )
                successful = tuple(dict.fromkeys((*successful, completed)))
                pending = tuple(
                    p for p in pending if p != history_values["history_plan_ref"]
                )
                if history_values["recovery_of_run_id"] == history_failure:
                    history_failure = None
            elif producer.status in (
                dg.DagsterRunStatus.FAILURE,
                dg.DagsterRunStatus.CANCELED,
            ):
                history_failure = producer.run_id
                history_failure_observed_at = known_pg[
                    ("observation", history_ref.storage_id)
                ].event_log_entry.timestamp
        day_failure = values["unresolved_day_failure_run_id"]
        if (
            day_values is not None
            and day_values["result"] == "completed"
            and day_values["recovery_of_run_id"] == day_failure
        ):
            day_failure = None
        result = C.StkFactorProRecordedResults(
            target,
            day_ref,
            history_ref,
            values["history_plan_ref"],
            values["history_ranges_ref"],
            values["raw_coverage"]
            or (day_values["raw_coverage"] if day_values is not None else None),
            values["bootstrap_context"],
            pending,
            successful,
            day_failure,
            history_failure,
        )
    latest_key = ("latest_day_runs", target)
    if latest_key not in known_pg:
        native = tuple(
            instance.get_run_records(
                dg.RunsFilter(
                    job_name=C.STK_FACTOR_PRO_UPDATE_JOB_NAME,
                    tags={PARTITION_NAME_TAG: target.isoformat()},
                ),
                limit=2,
                ascending=False,
            )
        )
        known_pg[latest_key] = native
        for record in native:
            known_pg[("run", record.dagster_run.run_id)] = record.dagster_run
    latest_record = next(
        (r for r in known_pg[latest_key] if r.dagster_run.run_id != exclude_run_id),
        None,
    )
    if latest_record is not None and latest_record.dagster_run.status in (
        dg.DagsterRunStatus.FAILURE,
        dg.DagsterRunStatus.CANCELED,
    ):
        from dataclasses import replace

        latest = latest_record.dagster_run
        failure = read_stk_factor_pro_failure(
            instance, latest.run_id, known_pg=known_pg
        )
        is_history_failure = failure["failure_phase"] == "history"
        # A later successful recovery is already represented by the entry. Do not
        # revive its older failed producer from the separate latest-update query.
        recovery = history_values if is_history_failure else day_values
        recovered = (
            recovery is not None
            and recovery["result"] == "completed"
            and recovery["recovery_of_run_id"] == latest.run_id
            and (
                not is_history_failure
                or read_stk_factor_pro_run(
                    instance, recovery["producer_run_id"], known_pg=known_pg
                ).status
                == dg.DagsterRunStatus.SUCCESS
            )
        )
        if not recovered:
            if is_history_failure:
                ended_at = latest_record.end_time
                if ended_at is None:
                    ended_at = latest_record.update_timestamp.timestamp()
                if (
                    history_failure_observed_at is None
                    or ended_at > history_failure_observed_at
                ):
                    result = replace(
                        result, unresolved_history_failure_run_id=latest.run_id
                    )
            else:
                result = replace(result, unresolved_day_failure_run_id=latest.run_id)
    known_pg[key] = result
    return result


def read_stk_factor_pro_day_factor_shas(
    instance,
    *,
    prior,
    previous_trade_date,
    lake_root,
    staging_root,
    contract,
    known_pg,
    known_records,
):
    """Use only the plan of the still-valid daily publication."""
    import dagster as dg

    from orchestrator.defs.io.stk_factor_pro_candidates import (
        require_stk_factor_pro_safe_path,
    )
    from orchestrator.defs.io.stk_factor_pro_history import (
        read_stk_factor_pro_referenced_history_plan,
    )
    from orchestrator.defs.paths import (
        raw_stk_factor_pro_path,
        silver_stock_factor_pro_path,
    )

    day_ref = prior.day_result_ref
    if day_ref is None:
        return None
    day = prior.target_trade_date
    values = _stk_factor_pro_exact_observation(
        instance, day_ref, target=day, phase="day", known_pg=known_pg
    )
    if (
        values["result"] != "completed"
        or read_stk_factor_pro_run(instance, day_ref.run_id, known_pg=known_pg).job_name
        != C.STK_FACTOR_PRO_UPDATE_JOB_NAME
    ):
        return None
    published = values["raw_coverage"]
    source_digest = values["day_source_digest"]
    if published is None or source_digest is None:
        raise ValueError("有效日观察缺日发布依据")
    checks_key = ("day_publication_checks", day_ref.run_id)
    if checks_key not in known_pg:
        records = instance.get_records_for_run(
            day_ref.run_id,
            of_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION,
            limit=2,
            ascending=True,
        ).records
        checks = {}
        for record in records:
            event = record.event_log_entry.dagster_event.event_specific_data
            checks[event.asset_key.to_user_string()] = event
        known_pg[checks_key] = checks
    for asset, check_name, path in (
        (
            C.STK_FACTOR_PRO_RAW_ASSET_KEY,
            C.STK_FACTOR_PRO_RAW_CHECK_NAME,
            raw_stk_factor_pro_path(lake_root, str(day)),
        ),
        (
            C.STK_FACTOR_PRO_SILVER_ASSET_KEY,
            C.STK_FACTOR_PRO_SILVER_CHECK_NAME,
            silver_stock_factor_pro_path(lake_root, str(day)),
        ),
    ):
        check = known_pg[checks_key].get(asset)
        if check is None or not check.passed or not check.blocking:
            return None
        target = check.target_materialization_data
        if (
            check.check_name != check_name
            or check.partition != str(day)
            or target is None
            or target.run_id != day_ref.run_id
        ):
            return None
        require_stk_factor_pro_safe_path(path)
        metadata = {
            key: getattr(value, "value", value) for key, value in check.metadata.items()
        }
        sha = metadata.get("goldenshare/file_sha256")
        if (
            not sha
            or metadata.get("goldenshare/day_source_digest") != source_digest
            or factor_known_file_sha(path, known_records=known_records) != sha
        ):
            return None
        if asset == C.STK_FACTOR_PRO_RAW_ASSET_KEY:
            if (
                target.storage_id != published.raw_materialization_storage_id
                or sha != published.raw_file_sha256
            ):
                return None
        elif metadata.get("goldenshare/raw_sha256") != published.raw_file_sha256:
            return None
    reference = values["history_plan_ref"]
    if reference is None or reference.creator_run_id != day_ref.run_id:
        raise ValueError("有效日观察缺本次日更的历史计划引用")
    plan = read_stk_factor_pro_referenced_history_plan(
        staging_root=staging_root,
        target=day,
        contract=contract,
        reference=reference,
        known_records=known_records,
    )
    if plan.identity.previous_trade_date != previous_trade_date:
        raise ValueError("日更历史计划的前一交易日不符")
    return plan.factor_t_ref.file_sha256, plan.factor_p_ref.file_sha256


def _stk_factor_pro_update_input(run):
    from orchestrator.defs.run_contracts import stk_factor_pro as C

    config = run.run_config["ops"]["stk_factor_pro"]["config"]
    required = {"execution_day", "target_trade_date", "purpose", "scheduled_slot"}
    if (
        set(config) - C.STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA.keys()
        or not required <= config.keys()
    ):
        raise ValueError("原运行配置不符合七字段合同")
    return C.StkFactorProRunInput(
        date.fromisoformat(
            C.normalize_stk_factor_pro_trade_date(config["execution_day"])
        ),
        date.fromisoformat(
            C.normalize_stk_factor_pro_trade_date(config["target_trade_date"])
        ),
        config["purpose"],
        config["scheduled_slot"],
        config.get("bootstrap_operation_id"),
        config.get("expected_bootstrap_approval_digest"),
        config.get("expected_bootstrap_date_result_digest"),
    )


def resolve_stk_factor_pro_source_run(
    instance, current_run, run_input, *, known_pg, known_records
):
    import dagster as dg

    from orchestrator.defs.run_contracts import stk_factor_pro as C

    known_pg[("run", current_run.run_id)] = current_run
    parent_id = current_run.parent_run_id
    root_id = current_run.root_run_id
    if parent_id is None:
        if root_id is not None:
            raise ValueError("重执行有root却没有直接parent")
        return None
    root_id = root_id or parent_id
    originals = tuple(dict.fromkeys((parent_id, root_id)))
    for run_id in originals:
        run = read_stk_factor_pro_run(instance, run_id, known_pg=known_pg)
        if (
            run.job_name != C.STK_FACTOR_PRO_UPDATE_JOB_NAME
            or run.status
            not in (
                dg.DagsterRunStatus.SUCCESS,
                dg.DagsterRunStatus.FAILURE,
                dg.DagsterRunStatus.CANCELED,
            )
            or _stk_factor_pro_run_target(run) != run_input.target_trade_date
            or _stk_factor_pro_update_input(run) != run_input
        ):
            raise ValueError("重执行原任务身份、终态或七字段不一致")
    first_key = ("first_observation", parent_id)
    if first_key not in known_pg:
        known_pg[first_key] = tuple(
            instance.get_records_for_run(
                parent_id,
                of_type=dg.DagsterEventType.ASSET_OBSERVATION,
                limit=1,
                ascending=True,
            ).records
        )
    first = known_pg[first_key]
    values = (
        _stk_factor_pro_observation(
            instance, first[0], target=run_input.target_trade_date, known_pg=known_pg
        )
        if first
        else None
    )
    return C.StkFactorProSourceRun(
        parent_id,
        root_id,
        run_input,
        known_pg[("run", parent_id)].status.value,
        values["history_plan_ref"] if values is not None else None,
        values["history_ranges_ref"] if values is not None else None,
        values["bootstrap_context"]
        if values is not None and run_input.purpose == "bootstrap_supplement"
        else None,
    )


_GLOBALS = {
    "calendar": (silver_trade_calendar_path, SILVER_TRADE_CALENDAR_SCHEMA),
    "lifecycle": (silver_stock_lifecycle_path, SILVER_STOCK_LIFECYCLE_SCHEMA),
    "identity": (silver_stock_identity_map_path, SILVER_STOCK_IDENTITY_MAP_SCHEMA),
}
_PREFIX = "stk_factor_bootstrap_coverage_"


def _schema(connection, relation):
    return tuple(
        (r[0], r[1]) for r in connection.execute(f"DESCRIBE {relation}").fetchall()
    )


def _stat(path):
    try:
        return factor_file_identity(path)
    except FileNotFoundError:
        return None


def _invalid_code_reason(connection, table, column):
    predicate = stk_factor_pro_invalid_code_sql(column)
    count = connection.execute(
        f"SELECT count(*) FROM {table} WHERE {predicate}"
    ).fetchone()[0]
    if not count:
        return ""
    sample = tuple(
        r[0]
        for r in connection.execute(
            f"SELECT {column} FROM {table} WHERE {predicate} "
            f"ORDER BY {column} NULLS FIRST LIMIT 20"
        ).fetchall()
    )
    return f"{column}非法代码{count}行，样本{sample}"


def _validate_lifecycle(connection, table):
    code_reason = _invalid_code_reason(connection, table, "ts_code")
    required = ("ts_code", "symbol", "name", "exchange", "curr_type", "list_status")
    empty = " OR ".join(f"{name} IS NULL OR trim({name})=''" for name in required)
    invalid = connection.execute(
        f"SELECT count(*) FROM {table} WHERE {empty} OR is_cny_stock IS DISTINCT FROM true "
        "OR curr_type IS DISTINCT FROM 'CNY' OR list_date IS NULL "
        "OR (delist_date IS NOT NULL AND delist_date<list_date)"
    ).fetchone()[0]
    duplicates = connection.execute(
        f"SELECT count(*) FROM (SELECT ts_code FROM {table} GROUP BY ts_code HAVING count(*)>1)"
    ).fetchone()[0]
    rule_reason = (
        "生命周期必需字段、股票域、日期或唯一键不符" if invalid or duplicates else ""
    )
    return "; ".join(value for value in (code_reason, rule_reason) if value)


def _validate_identity(connection, table, *, lifecycle_valid, lifecycle_table):
    code_reasons = tuple(
        _invalid_code_reason(connection, table, column)
        for column in ("source_ts_code", "latest_ts_code")
    )
    invalid = connection.execute(
        f"SELECT count(*) FROM {table} i WHERE source_ts_code IS NULL OR trim(source_ts_code)='' "
        "OR latest_ts_code IS NULL OR trim(latest_ts_code)='' OR valid_from IS NULL "
        "OR (valid_to IS NOT NULL AND valid_to<valid_from) "
        "OR identity_source IS NULL OR identity_source NOT IN (SELECT unnest(?::VARCHAR[])) "
        "OR confidence IS NULL OR confidence NOT IN (SELECT unnest(?::VARCHAR[]))",
        [
            sorted(STOCK_IDENTITY_ALLOWED_SOURCES),
            sorted(STOCK_IDENTITY_ALLOWED_CONFIDENCE),
        ],
    ).fetchone()[0]
    duplicates = connection.execute(
        f"SELECT count(*) FROM (SELECT source_ts_code FROM {table} GROUP BY source_ts_code HAVING count(*)>1)"
    ).fetchone()[0]
    rule_reason = (
        "身份映射字段、来源域、日期或唯一键不符" if invalid or duplicates else ""
    )
    # An unavailable lifecycle is already reported as lifecycle unknown. Its
    # absence must neither skip identity's own checks nor create a false error.
    missing_reference = (
        connection.execute(
            f"SELECT count(*) FROM {table} i WHERE NOT EXISTS "
            f"(SELECT 1 FROM {lifecycle_table} l WHERE l.ts_code=i.latest_ts_code)"
        ).fetchone()[0]
        if lifecycle_valid
        else 0
    )
    reference_reason = "身份映射生命周期引用不符" if missing_reference else ""
    # Producer seed completeness is checked by stock_identity_map_checks; this
    # consumer verifies the four approved physical inputs, not a fifth seed file.
    return "; ".join(
        value for value in (*code_reasons, rule_reason, reference_reason) if value
    )


def _validate_basis_rules(
    connection, *, table, kind, row_count, trade_date, lifecycle_valid, lifecycle_table
):
    if kind == "calendar":
        # Per-day duplicates/missing/NULL flags only invalidate that day.
        invalid = connection.execute(
            f"SELECT count(*) FROM {table} WHERE exchange IS NULL OR trim(exchange)='' "
            "OR trade_date IS NULL"
        ).fetchone()[0]
        return "日历含无法归属日期的行" if invalid else ""
    if kind == "lifecycle":
        return _validate_lifecycle(connection, table) if row_count else "生命周期为空"
    if kind == "identity":
        return (
            _validate_identity(
                connection,
                table,
                lifecycle_valid=lifecycle_valid,
                lifecycle_table=lifecycle_table,
            )
            if row_count
            else "身份映射为空"
        )
    code_reason = _invalid_code_reason(connection, table, "ts_code")
    invalid = connection.execute(
        f"SELECT count(*) FROM {table} WHERE trade_date IS DISTINCT FROM ? "
        "OR suspend_type IS NULL OR suspend_type NOT IN ('S','R') "
        "OR (suspend_timing IS NOT NULL AND trim(suspend_timing)='')",
        [trade_date],
    ).fetchone()[0]
    duplicates = connection.execute(
        f"SELECT count(*) FROM (SELECT ts_code,trade_date,suspend_type,coalesce(suspend_timing,'') "
        f"FROM {table} GROUP BY ALL HAVING count(*)>1)"
    ).fetchone()[0]
    # Nonempty producer timing remains intraday, without a new timing regex.
    rule_reason = (
        "最终停牌日期、类型、时段或业务键不符" if invalid or duplicates else ""
    )
    return "; ".join(value for value in (code_reason, rule_reason) if value)


def _basis_metadata(path, *, known_records):
    before = _stat(path)
    fact = known_records.get(path)
    if fact is not None:
        if fact[2] != before:
            raise ValueError("本地覆盖依据在首次读取后改变")
        return fact[1], before
    try:
        digest = factor_file_sha(path) if before is not None else None
    except OSError:
        known_records[path] = (None, None, before)
        raise
    if _stat(path) != before:
        raise ValueError("本地覆盖依据首次读取期间改变")
    known_records[path] = (None, digest, before)
    return digest, before


def _load_basis(
    connection,
    *,
    path,
    kind,
    trade_date,
    basis_inputs,
    known_records,
    lifecycle_file=None,
):
    previous = basis_inputs["files"].get(path)
    if previous is not None:
        try:
            _basis_metadata(path, known_records=known_records)
        except OSError:
            if previous["basis"].valid:
                raise
        return previous
    table = _PREFIX + (
        "probe_" + trade_date.strftime("%Y%m%d") if kind == "suspend" else kind
    )
    expected = (
        SILVER_STOCK_SUSPEND_DAILY_SCHEMA if kind == "suspend" else _GLOBALS[kind][1]
    )
    before = None
    try:
        digest, before = _basis_metadata(path, known_records=known_records)
    except OSError as error:
        before = known_records.get(path, (None, None, None))[2]
        basis = C.StkFactorProBootstrapBasisFile(
            kind, trade_date, None, None, None, False
        )
        fact = {
            "basis": basis,
            "reason": f"{kind}依据无法读取：{error}",
            "relation": None,
            "owned": False,
        }
        known_records[path] = (basis, None, before)
        basis_inputs["files"][path] = fact
        return fact
    schema_digest = row_count = None
    valid, reason, relation, owned = False, f"{kind}依据文件不存在", None, False
    try:
        if digest is not None:
            initial = known_records[path][0]
            if (
                isinstance(initial, tuple)
                and len(initial) == 3
                and (isinstance(initial[0], str) or initial[0] is None)
            ):
                relation, row_count, observed = initial
                if relation is None:
                    schema_digest = content_digest(observed)
                    if observed == tuple((c.name, c.type) for c in expected):
                        raise ValueError("已核覆盖依据的合法关系已释放，禁止重新回盘")
                    reason = f"{kind}依据无效：依据schema不符"
            else:
                try:
                    connection.execute(
                        f"CREATE TEMP TABLE {table} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
                    )
                except (
                    OSError,
                    duckdb.IOException,
                    duckdb.InvalidInputException,
                ) as error:
                    reason = f"{kind}依据文件无法读取：{error}"
                else:
                    owned, relation = True, table
                    observed = _schema(connection, relation)
                    row_count = connection.execute(
                        f"SELECT count(*) FROM {relation}"
                    ).fetchone()[0]
            if relation is not None:
                schema_digest = content_digest(observed)
                if observed != tuple((c.name, c.type) for c in expected):
                    reason = f"{kind}依据无效：依据schema不符"
                else:
                    invalid = _validate_basis_rules(
                        connection,
                        table=relation,
                        kind=kind,
                        row_count=row_count,
                        trade_date=trade_date,
                        lifecycle_valid=lifecycle_file is None
                        or lifecycle_file["basis"].valid,
                        lifecycle_table=lifecycle_file["relation"]
                        if lifecycle_file is not None
                        else None,
                    )
                    valid = not invalid
                    reason = f"{kind}依据无效：{invalid}" if invalid else ""
            if _stat(path) != before:
                raise ValueError("覆盖依据读取期间改变，本次停止")
        basis = C.StkFactorProBootstrapBasisFile(
            kind, trade_date, digest, schema_digest, row_count, valid
        )
        if relation is not None and not valid:
            if owned:
                owned = False
                connection.execute(f"DROP TABLE IF EXISTS {relation}")
            relation = None
        fact = {"basis": basis, "reason": reason, "relation": relation, "owned": owned}
        known_records[path] = (
            (relation, row_count, observed) if valid else basis,
            digest,
            before,
        )
        basis_inputs["files"][path] = fact
        return fact
    except BaseException as primary:
        if owned:
            try:
                connection.execute(f"DROP TABLE IF EXISTS {relation}")
            except BaseException as cleanup:  # noqa: BLE001 - retain the original failure/cancellation
                primary.add_note(f"覆盖依据清理同时失败：{type(cleanup).__name__}")
        raise


def prepare_stk_factor_pro_coverage_inputs(
    connection, *, lake_root, trade_date, inherited_facts, known_records
):
    """Acquire one day's inputs, retaining common already-loaded relations."""
    calendar_path = silver_trade_calendar_path(lake_root)
    calendar = inherited_facts.get(calendar_path)
    if calendar is not None and trade_date in calendar.get("prepared_dates", {}):
        return calendar["prepared_dates"][trade_date]
    by_kind = {}
    for kind in ("calendar", "lifecycle", "identity", "suspend"):
        path = (
            silver_stock_suspend_daily_path(lake_root, trade_date.isoformat())
            if kind == "suspend"
            else _GLOBALS[kind][0](lake_root)
        )
        by_kind[kind] = _load_basis(
            connection,
            path=path,
            kind=kind,
            trade_date=trade_date if kind == "suspend" else None,
            basis_inputs={"files": inherited_facts},
            known_records=known_records,
            lifecycle_file=by_kind.get("lifecycle") if kind == "identity" else None,
        )
    issues = {
        kind: fact["reason"]
        for kind, fact in by_kind.items()
        if not fact["basis"].valid
    }
    is_open = None
    if by_kind["calendar"]["basis"].valid:
        flags = connection.execute(
            f"SELECT is_open FROM {by_kind['calendar']['relation']} WHERE exchange='SSE' AND trade_date=?",
            [trade_date],
        ).fetchall()
        if len(flags) != 1 or type(flags[0][0]) is not bool:
            issues["calendar"] = "日历本日缺失、重复或开市标志为空"
        else:
            is_open = flags[0][0]
    result = {
        "trade_date": trade_date,
        "is_open": is_open,
        "basis_files": tuple(by_kind[k]["basis"] for k in sorted(by_kind)),
        "unknown_input_kinds": tuple(sorted(issues)),
        "reason": "; ".join(issues[k] for k in sorted(issues)),
        "relations": {kind: fact["relation"] for kind, fact in by_kind.items()},
    }
    by_kind["calendar"].setdefault("prepared_dates", {})[trade_date] = result
    return result


def release_stk_factor_pro_coverage_keys(connection, *, coverage_inputs):
    """Release the current date's prepared comparisons with its connection."""
    coverage_inputs.pop("coverage_keys", None)
    errors = []
    for name in STK_FACTOR_PRO_COVERAGE_TABLES:
        try:
            connection.execute(f"DROP TABLE IF EXISTS {name}")
        except BaseException as error:  # noqa: BLE001 - release all owned relations.
            errors.append(error)
    if errors:
        for other in errors[1:]:
            errors[0].add_note(f"覆盖关系清理同时失败：{type(other).__name__}")
        raise errors[0]


def release_stk_factor_pro_coverage_inputs(
    connection, *, inherited_facts, trade_date=None
):
    """Release only relations owned by this preparation, once per relation."""
    errors = []
    for fact in inherited_facts.values():
        for day, prepared in fact.get("prepared_dates", {}).items():
            if (trade_date is None or day == trade_date) and "coverage_keys" in prepared:
                try:
                    release_stk_factor_pro_coverage_keys(
                        connection, coverage_inputs=prepared
                    )
                except BaseException as error:  # noqa: BLE001 - retain cleanup failures.
                    errors.append(error)
        if fact["owned"] and (
            trade_date is None or fact["basis"].trade_date == trade_date
        ):
            relation = fact["relation"]
            fact["owned"], fact["relation"] = False, None
            try:
                connection.execute(f"DROP TABLE IF EXISTS {relation}")
            except BaseException as error:  # noqa: BLE001 - attempt every owned cleanup
                errors.append(error)
    if errors:
        for other in errors[1:]:
            errors[0].add_note(f"覆盖依据清理同时失败：{type(other).__name__}")
        raise errors[0]


def _stk_factor_pro_file_result(
    instance,
    *,
    layer,
    target_trade_date,
    lake_root,
    known_pg,
    known_records,
    verified_audit=None,
):
    """Accept the producer's bound check; do not recreate a source comparison."""
    import dagster as dg
    from dagster._core.event_api import PartitionKeyFilter

    from orchestrator.defs.io.stk_factor_pro_candidates import (
        require_stk_factor_pro_safe_path,
    )
    from orchestrator.defs.paths import (
        raw_stk_factor_pro_path,
        silver_stock_factor_pro_path,
    )
    from orchestrator.defs.run_contracts.metadata import FILE_PATH_METADATA_KEY

    asset_name, check_name, path_function = (
        (
            C.STK_FACTOR_PRO_RAW_ASSET_KEY,
            C.STK_FACTOR_PRO_RAW_CHECK_NAME,
            raw_stk_factor_pro_path,
        )
        if layer == "raw"
        else (
            C.STK_FACTOR_PRO_SILVER_ASSET_KEY,
            C.STK_FACTOR_PRO_SILVER_CHECK_NAME,
            silver_stock_factor_pro_path,
        )
    )
    day = target_trade_date
    cache_key = ("validated_file_result", layer, day)
    if cache_key in known_pg:
        return known_pg[cache_key]
    path = path_function(lake_root, day.isoformat())
    require_stk_factor_pro_safe_path(path)
    asset = dg.AssetKey(asset_name)
    material_key = ("materialization", asset_name, day)
    if material_key not in known_pg:
        records = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[day.isoformat()]),
            limit=1,
        ).records
        known_pg[material_key] = records[0] if records else None
    material = known_pg[material_key]
    if material is None:
        raise ValueError(f"原日期{layer}缺物化记录")
    check_key = ("check_execution", asset_name, check_name, day)
    if check_key not in known_pg:
        checks = instance.event_log_storage.get_latest_asset_check_execution_by_key(
            (dg.AssetCheckKey(asset, check_name),),
            partition_filter=PartitionKeyFilter(key=day.isoformat()),
        )
        known_pg[check_key] = checks.get(dg.AssetCheckKey(asset, check_name))
    check = known_pg[check_key]
    evaluation = (
        check.event.dagster_event.event_specific_data
        if check is not None and check.event is not None
        else None
    )
    target = evaluation.target_materialization_data if evaluation is not None else None
    if (
        check is None
        or check.status.value != "SUCCEEDED"
        or not evaluation.passed
        or not evaluation.blocking
        or target is None
        or (target.storage_id, target.run_id, target.timestamp)
        != (material.storage_id, material.event_log_entry.run_id, material.timestamp)
        or evaluation.asset_key != asset
        or evaluation.partition != day.isoformat()
    ):
        raise ValueError(f"原日期{layer}检查未通过或绑定不符")
    metadata = material.event_log_entry.dagster_event.event_specific_data.materialization.metadata
    details = {k: getattr(v, "value", v) for k, v in metadata.items()}
    checked = {k: getattr(v, "value", v) for k, v in evaluation.metadata.items()}
    if verified_audit is not None:
        if (
            not verified_audit.passed
            or verified_audit.path != path
            or verified_audit.trade_date != day
            or verified_audit.layer != layer
        ):
            raise ValueError("当前audit与原目标文件不符")
        fact = known_records.get(path)
        if fact is None or fact[0] != verified_audit:
            raise ValueError("缺已发布文件的首次audit/摘要交接")
        sha = fact[1]
    else:
        sha = factor_known_file_sha(path, known_records=known_records)
    expected = {
        "goldenshare/file_sha256": sha,
        "goldenshare/contract_content_digest": C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST,
        "goldenshare/processing_version": C.STK_FACTOR_PRO_PROCESSING_VERSION,
        FILE_PATH_METADATA_KEY: str(path),
    }
    if sha is None or any(
        details.get(k) != v or checked.get(k) != v for k, v in expected.items()
    ):
        raise ValueError(f"原日期{layer}文件与物化/check摘要或合同不符")
    result = material, check, sha, details, checked
    known_pg[cache_key] = result
    return result


def evaluate_stk_factor_pro_raw_coverage(
    instance,
    connection,
    *,
    lake_root,
    target_trade_date,
    known_pg,
    known_records,
    calculated,
    verified_raw_audit=None,
):
    from orchestrator.defs.paths import raw_stk_factor_pro_path

    day = target_trade_date
    digests = tuple(
        known_records.get(path, (None, None, None))[1]
        for path in (
            silver_stock_lifecycle_path(lake_root),
            silver_stock_suspend_daily_path(lake_root, str(day)),
            silver_stock_identity_map_path(lake_root),
        )
    )
    path = raw_stk_factor_pro_path(lake_root, str(day))
    material = check = None
    sha, reason = known_records.get(path, (None, None, None))[1], ""
    try:
        material, check, sha, _, _ = _stk_factor_pro_file_result(
            instance,
            layer="raw",
            target_trade_date=day,
            lake_root=lake_root,
            known_pg=known_pg,
            known_records=known_records,
            verified_audit=verified_raw_audit,
        )
    except (ValueError, OSError) as error:
        reason = str(error)
    passed = material is not None and check is not None and not reason
    prior = known_pg.get(("recorded_results", day))
    coverage = prior.raw_coverage if prior is not None else None
    if calculated is None:
        if (
            not passed
            or coverage is None
            or coverage.coverage_rule_version != C.STK_FACTOR_PRO_COVERAGE_RULE_VERSION
            or (
                coverage.raw_file_sha256,
                coverage.lifecycle_file_sha256,
                coverage.suspend_file_sha256,
                coverage.identity_file_sha256,
            )
            != (sha, *digests)
        ):
            raise ValueError("新覆盖缺首次集合计算结果；禁止隐式重算")
        from dataclasses import replace

        return replace(
            coverage,
            raw_materialization_storage_id=material.storage_id,
            raw_check_storage_id=check.id,
        )
    counts = calculated["coverage_counts"]
    missing = counts.missing_count if counts is not None else None
    ref = calculated["missing_codes_ref"]
    if isinstance(ref, C.StkFactorProBootstrapCodesRef):
        ref = C.RecordRef(ref.creator_run_id, ref.relative_path, ref.file_sha256)
    extra = counts.extra_count if counts is not None else None
    complete = (
        (None if missing is None or extra is None else missing == 0 and extra == 0)
        if passed else False
    )
    return C.StkFactorProRawCoverage(
        day,
        complete,
        passed,
        sha,
        *digests,
        counts.expected_count if counts is not None else None,
        counts.actual_count if counts is not None else None,
        missing,
        extra,
        C.STK_FACTOR_PRO_COVERAGE_RULE_VERSION,
        calculated["missing_sample_codes"],
        reason or calculated["reason"],
        material.storage_id if passed else None,
        check.id if passed else None,
        ref,
    )


def require_stk_factor_pro_history_raw(coverage):
    import dagster as dg

    if coverage.complete is not True or not coverage.raw_check_passed:
        raise dg.Failure(
            f"原日期数据缺失：{coverage.target_trade_date}；请管理员处理原日期数据后重试历史repair。",
            metadata={
                "goldenshare/retryable": False,
                "goldenshare/failure_phase": "history",
                "goldenshare/target_trade_date": str(coverage.target_trade_date),
                "goldenshare/source_error_code": None,
                "goldenshare/summary": coverage.reason,
                "goldenshare/raw_coverage_complete": coverage.complete,
                "goldenshare/raw_check_passed": coverage.raw_check_passed,
                "goldenshare/expected_count": coverage.expected_count,
                "goldenshare/actual_count": coverage.actual_count,
                "goldenshare/missing_count": coverage.missing_count,
                "goldenshare/extra_count": coverage.extra_count,
                "goldenshare/coverage_rule_version": coverage.coverage_rule_version,
                "goldenshare/missing_sample_codes": dg.MetadataValue.json(
                    list(coverage.missing_sample_codes)
                ),
                "goldenshare/raw_file_sha256": coverage.raw_file_sha256,
                "goldenshare/next_action": "请管理员处理原日期数据后重试历史repair。",
            },
            allow_retries=False,
        )


def evaluate_stk_factor_pro_target_silver(
    instance,
    *,
    lake_root,
    raw_coverage,
    known_pg,
    known_records,
    verified_silver_audit=None,
):
    day = raw_coverage.target_trade_date
    raw_sha = raw_coverage.raw_file_sha256
    if raw_sha is None:
        raise ValueError("Silver核验缺原T Raw摘要")
    result = (day, False, None, raw_sha, None, None, None)
    try:
        require_stk_factor_pro_history_raw(raw_coverage)
        material, check, sha, metadata, checked = _stk_factor_pro_file_result(
            instance,
            layer="silver",
            target_trade_date=day,
            lake_root=lake_root,
            known_pg=known_pg,
            known_records=known_records,
            verified_audit=verified_silver_audit,
        )
        if (
            metadata.get("goldenshare/raw_sha256") != raw_sha
            or checked.get("goldenshare/raw_sha256") != raw_sha
        ):
            raise ValueError("Silver对应的Raw已过期")
        return C.StkFactorProTargetSilver(
            day,
            True,
            sha,
            raw_sha,
            raw_sha,
            material.storage_id,
            check.id,
            "通过已有Silver文件检查",
        )
    except (ValueError, OSError) as error:
        return C.StkFactorProTargetSilver(*result, str(error))


def require_stk_factor_pro_history_silver(result):
    import dagster as dg

    if not result.ready:
        raise dg.Failure(
            f"原日期Silver不可用：{result.target_trade_date}；请管理员先处理原日期Silver后重试历史repair。",
            metadata={
                "goldenshare/retryable": False,
                "goldenshare/failure_phase": "history",
                "goldenshare/target_trade_date": str(result.target_trade_date),
                "goldenshare/source_error_code": None,
                "goldenshare/summary": result.reason,
                "goldenshare/target_silver": dg.MetadataValue.json(
                    C.stk_factor_pro_record_to_dict(result)
                ),
                "goldenshare/next_action": "请管理员先处理原日期Silver后重试历史repair。",
            },
            allow_retries=False,
        )


def calculate_stk_factor_pro_coverage(connection, *, coverage_inputs, raw_relation):
    """Project existing verified relations and compute this input version once."""
    from orchestrator.defs.duckdb_sql import BJ_MARKET_OPEN_DATE

    counts = None
    if not coverage_inputs["unknown_input_kinds"]:
        day, relations = coverage_inputs["trade_date"], coverage_inputs["relations"]
        actual = "stk_factor_pro_coverage_actual_input"
        names = [actual]
        primary = None
        try:
            if "coverage_keys" not in coverage_inputs:
                listed, suspended, optional = (
                    "stk_factor_pro_coverage_listed_input",
                    "stk_factor_pro_coverage_suspend_input",
                    "stk_factor_pro_coverage_optional_input",
                )
                names.extend((listed, suspended, optional))
                connection.execute(
                    f"CREATE TEMP TABLE {listed} AS SELECT ?::DATE trade_date,ts_code FROM {relations['lifecycle']} "
                    "WHERE list_date<=? AND (delist_date IS NULL OR ?<delist_date) "
                    "AND (NOT ends_with(ts_code,'.BJ') OR ?>=CAST(? AS DATE))",
                    [day, day, day, day, BJ_MARKET_OPEN_DATE],
                )
                connection.execute(
                    f"CREATE TEMP TABLE {suspended} AS SELECT DISTINCT trade_date,ts_code FROM {relations['suspend']} "
                    "WHERE trade_date=? AND suspend_type='S' AND suspend_timing IS NULL",
                    [day],
                )
                connection.execute(
                    f"CREATE TEMP TABLE {optional} AS SELECT ?::DATE trade_date,ts_code "
                    f"FROM {relations['lifecycle']} WHERE list_date=?",
                    [day, day],
                )
                coverage_inputs["coverage_keys"] = _prepare_stk_factor_pro_expected_keys(
                    connection,
                    target_trade_date=day,
                    listed_relation=listed,
                    full_suspend_relation=suspended,
                    optional_relation=optional,
                    identity_relation=relations["identity"],
                )
            if raw_relation is None:
                connection.execute(
                    f"CREATE TEMP TABLE {actual}(trade_date DATE,ts_code VARCHAR)"
                )
            else:
                connection.execute(
                    f"CREATE TEMP TABLE {actual} AS SELECT strptime(trade_date,'%Y%m%d')::DATE trade_date,ts_code FROM {relation_identifier(raw_relation)}"
                )
            counts = compare_stk_factor_pro_coverage_keys(
                connection,
                target_trade_date=day,
                actual_relation=actual,
                identity_relation=relations["identity"],
                **coverage_inputs["coverage_keys"],
            )
        except BaseException as error:
            primary = error
            raise
        finally:
            failures = []
            for name in names:
                try:
                    connection.execute(f"DROP TABLE IF EXISTS {name}")
                except BaseException as error:  # noqa: BLE001 - release all owned inputs and retain the business error
                    failures.append(error)
            if failures:
                reported = primary if primary is not None else failures[0]
                for error in failures:
                    reported.add_note(f"覆盖计算清理同时失败：{type(error).__name__}")
                if primary is None:
                    raise reported
    return {
        "coverage_counts": counts,
        "unknown_input_kinds": coverage_inputs["unknown_input_kinds"]
        or (
            ("identity",)
            if counts is not None and counts.expected_count is None
            else ()
        ),
        "reason": coverage_inputs["reason"]
        or (counts.reason if counts is not None else "覆盖依据未知"),
        "missing_codes_ref": None,
        "extra_codes_ref": None,
        "missing_sample_codes": (),
        "extra_sample_codes": (),
    }


def emit_stk_factor_pro_publications(
    context,
    *,
    completed,
    lake_root,
    known_pg,
    known_records,
    day_output=False,
    source_metadata=None,
):
    """Yield real file facts, then bind checks to the persisted materializations."""
    import dagster as dg
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )
    from dagster._core.event_api import PartitionKeyFilter

    from orchestrator.defs.paths import raw_stk_factor_pro_path
    from orchestrator.defs.run_contracts import stk_factor_pro as C
    from orchestrator.defs.run_contracts.metadata import FILE_PATH_METADATA_KEY

    files = tuple(
        (target, audit) for target, audit in completed if not target.skip_no_file
    )
    if not files:
        return
    metadata = {}
    expected = {}
    for target, audit in files:
        if audit is None or not audit.passed or audit.file_sha256 != target.file_sha256:
            raise ValueError("发布事件缺本次真实文件audit")
        asset_name, check_name = (
            (C.STK_FACTOR_PRO_RAW_ASSET_KEY, C.STK_FACTOR_PRO_RAW_CHECK_NAME)
            if target.layer == "raw"
            else (C.STK_FACTOR_PRO_SILVER_ASSET_KEY, C.STK_FACTOR_PRO_SILVER_CHECK_NAME)
        )
        key = dg.AssetKey(asset_name), str(target.trade_date)
        values = {
            FILE_PATH_METADATA_KEY: str(audit.path),
            "goldenshare/file_sha256": audit.file_sha256,
            "goldenshare/contract_content_digest": C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST,
            "goldenshare/processing_version": C.STK_FACTOR_PRO_PROCESSING_VERSION,
            "dagster/row_count": audit.row_count,
        }
        if target.layer == "silver":
            raw = raw_stk_factor_pro_path(lake_root, str(target.trade_date))
            if raw not in known_records:
                raise ValueError("Silver事件缺本次对应Raw摘要")
            values["goldenshare/raw_sha256"] = known_records[raw][1]
        values.update(source_metadata or {})
        values["goldenshare/comparison"] = dg.MetadataValue.json(
            C.stk_factor_pro_record_to_dict(audit.comparison)
        )
        metadata[key] = values
        expected[key] = target, audit, check_name
        if day_output:
            yield dg.MaterializeResult(asset_key=key[0], metadata=values)
        else:
            yield dg.AssetMaterialization(
                asset_key=key[0], partition=key[1], metadata=values
            )
    mats = context.instance.get_records_for_run(
        context.run.run_id,
        of_type=dg.DagsterEventType.ASSET_MATERIALIZATION,
        ascending=False,
        limit=len(files),
    ).records
    by_key = {(r.asset_key, r.partition_key): r for r in mats}
    if set(by_key) != set(expected):
        raise ValueError("本批真实物化未保存或目标不符")
    for key, (target, audit, check_name) in expected.items():
        material = by_key[key]
        saved = material.event_log_entry.dagster_event.event_specific_data.materialization.metadata
        if material.event_log_entry.run_id != context.run.run_id or any(
            getattr(saved.get(k), "value", saved.get(k)) != getattr(v, "value", v)
            for k, v in metadata[key].items()
        ):
            raise ValueError("本批真实物化内容与已发布audit不符")
        known_pg[("materialization", key[0].to_user_string(), target.trade_date)] = (
            material
        )
        if day_output:
            yield dg.AssetCheckResult(
                asset_key=key[0],
                check_name=check_name,
                passed=True,
                severity=dg.AssetCheckSeverity.ERROR,
                metadata=metadata[key],
            )
        else:
            yield AssetCheckEvaluation(
                asset_key=key[0],
                check_name=check_name,
                passed=True,
                partition=key[1],
                blocking=True,
                severity=dg.AssetCheckSeverity.ERROR,
                metadata=metadata[key],
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=material.storage_id,
                    run_id=context.run.run_id,
                    timestamp=material.timestamp,
                ),
            )
    checks = context.instance.get_records_for_run(
        context.run.run_id,
        of_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION,
        ascending=False,
        limit=len(files),
    ).records
    check_events = {
        (
            r.event_log_entry.dagster_event.event_specific_data.asset_key,
            r.event_log_entry.dagster_event.event_specific_data.partition,
        ): r
        for r in checks
    }
    if set(check_events) != set(expected):
        raise ValueError("本批真实文件check未保存")
    for key, (target, audit, check_name) in expected.items():
        event = check_events[key]
        evaluation = event.event_log_entry.dagster_event.event_specific_data
        material = by_key[key]
        bound = evaluation.target_materialization_data
        if (
            not evaluation.passed
            or bound is None
            or (bound.storage_id, bound.run_id, bound.timestamp)
            != (material.storage_id, context.run.run_id, material.timestamp)
        ):
            raise ValueError("本批文件check与物化绑定不符")
        known_pg[
            ("publication_events", context.run.run_id, target.trade_date, target.layer)
        ] = (material, event, audit)
    # Execution ids have a separate namespace from event storage ids. One query
    # per actual date includes both keys, then downstream readers reuse it.
    for day in dict.fromkeys(target.trade_date for target, _audit in files):
        keys = tuple(
            dg.AssetCheckKey(key[0], item[2])
            for key, item in expected.items()
            if item[0].trade_date == day
        )
        executions = (
            context.instance.event_log_storage.get_latest_asset_check_execution_by_key(
                keys, partition_filter=PartitionKeyFilter(key=str(day))
            )
        )
        for check_key, record in executions.items():
            known_pg[
                (
                    "check_execution",
                    check_key.asset_key.to_user_string(),
                    check_key.name,
                    day,
                )
            ] = record
