"""Pure coverage computation. File/Dagster readiness belongs to later batches."""

from __future__ import annotations

from datetime import date

from orchestrator.defs.checks.stk_factor_pro import relation_identifier
from orchestrator.defs.run_contracts.stk_factor_pro import StkFactorProCoverageCounts


def build_stk_factor_pro_coverage_keys(
    connection,
    *,
    target_trade_date: date,
    listed_relation: str,
    full_suspend_relation: str,
    actual_relation: str,
    identity_relation: str,
) -> StkFactorProCoverageCounts:
    if type(target_trade_date) is not date:
        raise ValueError("覆盖日期必须是DATE")
    relations = tuple(
        relation_identifier(value)
        for value in (listed_relation, full_suspend_relation, actual_relation)
    )
    identity = relation_identifier(identity_relation)
    outputs = ("stk_factor_pro_coverage_missing", "stk_factor_pro_coverage_extra")
    internals = (
        "stk_factor_pro_coverage_mapping",
        "stk_factor_pro_coverage_expected",
        "stk_factor_pro_coverage_listed",
        "stk_factor_pro_coverage_suspend",
        "stk_factor_pro_coverage_actual",
    )
    for name in (*outputs, *internals):
        connection.execute(f"DROP TABLE IF EXISTS {name}")
    for relation in relations:
        schema = tuple(
            (r[0], r[1]) for r in connection.execute(f"DESCRIBE {relation}").fetchall()
        )
        if schema != (("trade_date", "DATE"), ("ts_code", "VARCHAR")):
            raise ValueError("覆盖输入必须是本日DATE/VARCHAR代码关系")
        bad = connection.execute(
            f"SELECT count(*) FROM {relation} WHERE trade_date IS DISTINCT FROM ? OR ts_code IS NULL "
            "OR NOT regexp_full_match(ts_code, '[0-9]{6}\\.(SH|SZ|BJ)')",
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
    union = " UNION ".join(f"SELECT trade_date,ts_code FROM {r}" for r in relations)
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_mapping AS "
        f"SELECT k.trade_date,k.ts_code,count(i.source_ts_code) AS mappings,min(i.latest_ts_code) AS latest "
        f"FROM ({union}) k LEFT JOIN {identity} i ON i.source_ts_code=k.ts_code "
        "AND k.trade_date>=i.valid_from AND (i.valid_to IS NULL OR k.trade_date<i.valid_to) "
        "GROUP BY k.trade_date,k.ts_code"
    )
    missing, ambiguous = connection.execute(
        "SELECT count(*) FILTER (WHERE mappings=0),count(*) FILTER (WHERE mappings>1 OR (mappings=1 AND "
        "(latest IS NULL OR NOT regexp_full_match(latest,'[0-9]{6}\\.(SH|SZ|BJ)')))) FROM stk_factor_pro_coverage_mapping"
    ).fetchone()
    if missing or ambiguous:
        absent = tuple(
            r[0]
            for r in connection.execute(
                "SELECT ts_code FROM stk_factor_pro_coverage_mapping WHERE mappings=0 ORDER BY ts_code LIMIT 20"
            ).fetchall()
        )
        conflict = tuple(
            r[0]
            for r in connection.execute(
                "SELECT ts_code FROM stk_factor_pro_coverage_mapping WHERE mappings>1 OR (mappings=1 AND (latest IS NULL OR NOT regexp_full_match(latest,'[0-9]{6}\\.(SH|SZ|BJ)'))) ORDER BY ts_code LIMIT 20"
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
    for relation, suffix in zip(
        relations, ("listed", "suspend", "actual"), strict=True
    ):
        connection.execute(
            f"CREATE TEMP TABLE stk_factor_pro_coverage_{suffix} AS SELECT DISTINCT k.trade_date,m.latest AS ts_code "
            f"FROM {relation} k JOIN stk_factor_pro_coverage_mapping m USING(trade_date,ts_code)"
        )
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_expected AS SELECT * FROM stk_factor_pro_coverage_listed EXCEPT SELECT * FROM stk_factor_pro_coverage_suspend"
    )
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_missing AS SELECT * FROM stk_factor_pro_coverage_expected EXCEPT SELECT * FROM stk_factor_pro_coverage_actual"
    )
    connection.execute(
        "CREATE TEMP TABLE stk_factor_pro_coverage_extra AS SELECT * FROM stk_factor_pro_coverage_actual EXCEPT SELECT * FROM stk_factor_pro_coverage_expected"
    )
    expected, actual, missing, extra = (
        connection.execute(
            f"SELECT count(*) FROM stk_factor_pro_coverage_{name}"
        ).fetchone()[0]
        for name in ("expected", "actual", "missing", "extra")
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
        "已按上市、全天停牌和有效身份计算覆盖",
    )


def read_stk_factor_pro_other_active_runs(instance, *, own_run_id=None):
    """Two bounded queries; bootstrap has no own Dagster run to exclude."""
    import dagster as dg

    from orchestrator.defs.run_contracts.stk_factor_pro import (
        STK_FACTOR_PRO_ACTIVE_RUN_STATUSES,
        STK_FACTOR_PRO_WRITE_JOB_NAMES,
    )

    active = []
    for name in STK_FACTOR_PRO_WRITE_JOB_NAMES:
        records = instance.get_run_records(
            filters=dg.RunsFilter(
                job_name=name, statuses=STK_FACTOR_PRO_ACTIVE_RUN_STATUSES
            ),
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
