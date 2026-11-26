"""Read one published general-index minute partition and audit its time keys."""

import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import gettempdir

import dagster as dg
import duckdb
from dagster._core.storage.tags import RUN_KEY_TAG

from orchestrator.defs.catalog.lake_assets import get_lake_asset_catalog_entry
from orchestrator.defs.checks.daily_audit_coverage import stat_version
from orchestrator.defs.daily_data_audit.evidence import (
    AUDIT_ASSET_TAG,
    AUDIT_PUBLICATION_TAG,
    BUSINESS_DATE_TAG,
    INDEX_MINUTE_JOB,
    INDEX_MINUTE_META,
    SHANGHAI,
    load_evidence,
    metadata,
    read_index_minute_result,
)
from orchestrator.defs.daily_data_audit.registry import AuditTarget
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_index_mins_path,
    silver_index_mins_path,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
    cn_a_derived_minute_target_times,
    cn_a_derived_minute_window_map_sql,
)
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_ASSET_FREQS,
    INDEX_MINS_DERIVED_FREQS,
    INDEX_MINS_FALLBACK_FREQS,
    fallback_target_times_for_index_mins_freq,
    index_mins_code_set_hash,
    source_freq_for_index_mins_derived_freq,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key

RAW_ASSETS = {f"raw_index_mins_{frequency}m" for frequency in INDEX_MINS_ASSET_FREQS}
SILVER_INPUTS = {
    **{
        f"silver_index_mins_{frequency}m": f"raw_index_mins_{frequency}m"
        for frequency in INDEX_MINS_ASSET_FREQS
    },
    **{
        f"silver_index_mins_{frequency}m": f"silver_index_mins_{source_freq_for_index_mins_derived_freq(frequency)[:-3]}m"
        for frequency in INDEX_MINS_DERIVED_FREQS
    },
}
INDEX_MINUTE_ASSETS = RAW_ASSETS | SILVER_INPUTS.keys()
INDEX_MINUTE_GOLD_INPUTS = {
    f"gold_index_mins_{target}m": f"silver_index_mins_{source}m"
    for target, source in CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET.items()
}
RULE_VERSION = "index_mins_time_keys_v1"
APPROVED_SOURCE_EMPTY = "source_probe_target_frequency_empty"


class IndexMinuteAuditConfig(dg.Config):
    asset_key: str
    business_date: str
    frequency: int
    target_version: str
    coverage_scope: str = "dataset"


def _frequency(asset_key):
    return int(asset_key.rsplit("_", 1)[-1][:-1])


def _scope(asset_key, day):
    day_text = day.isoformat()
    return {
        "asset_key": asset_key,
        "business_date": day_text,
        "partition_key": day_text,
        "as_of_date": day_text,
        "frequency": f"{_frequency(asset_key)}分钟",
        "coverage_scope": "dataset",
    }


def _asset_path(root, asset_key, day):
    frequency = f"{_frequency(asset_key)}min"
    path = raw_index_mins_path if asset_key in RAW_ASSETS else silver_index_mins_path
    return path(root, frequency, day.isoformat())


def _input_asset(asset_key, fields):
    if asset_key in RAW_ASSETS or fields.get("source_mode") != "derived_fallback":
        return SILVER_INPUTS.get(asset_key)
    if (
        _frequency(asset_key) in INDEX_MINS_FALLBACK_FREQS
        and fields.get("source_freq") == "5min"
        and fields.get("source_empty_reason") == APPROVED_SOURCE_EMPTY
        and fields.get("source_revision")
    ):
        return "raw_index_mins_5m"
    return None


def _audit_target(asset_key, day):
    entry = get_lake_asset_catalog_entry(asset_key)
    return AuditTarget(
        entry, day.isoformat(), day, True, entry.blocking_check_names, False, None
    )


def _delivery(instance, asset_key, day, observed_at):
    target = _audit_target(asset_key, day)
    return load_evidence(instance, (target,), day, observed_at).get(asset_key)


def _receipt(instance, publication, path, asset_key, day):
    run = instance.get_run_by_id(publication.run_id) if publication.run_id else None
    return _publication_receipt(run, path, asset_key, day)


def _publication_receipt(run, path, asset_key, day):
    if run is None or run.status != dg.DagsterRunStatus.SUCCESS:
        return None
    dataset = "raw_index_mins" if asset_key in RAW_ASSETS else "silver_index_mins"
    target_hash = hashlib.sha256(str(path).encode()).hexdigest()
    run_hash = hashlib.sha256((run.root_run_id or run.run_id).encode()).hexdigest()
    receipt_path = (
        Path(DEFAULT_LAKE_STAGING_ROOT)
        / "minute_partitions"
        / dataset
        / f"target={target_hash}"
        / f"run_id={run_hash}"
        / "receipt.json"
    )
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, ValueError):
        return None
    fields = receipt.get("inputs", {})
    if (
        receipt.get("status") == "promoted"
        and receipt.get("target") == str(path)
        and fields.get("dataset") == dataset
        and fields.get("date") == day.isoformat()
        and fields.get("freq") == _frequency(asset_key)
        and isinstance(receipt.get("sha256"), str)
    ):
        return receipt
    return None


def _file_version(path, cache):
    if path not in cache:
        try:
            cache[path] = stat_version(path)
        except OSError:
            cache[path] = None
    return cache[path]


def matching_index_minute_result(
    instance, asset_key, day, publication, observed_at, root, cache
):
    if publication is None or not publication.run_id:
        return None
    stored = read_index_minute_result(
        instance, day, asset_key, publication.run_id, observed_at
    )
    if stored is None:
        return None
    _, result = stored
    if (
        result["scope"] != _scope(asset_key, day)
        or result["target_publication_run_id"] != publication.run_id
        or result["version"]["rule_version"] != RULE_VERSION
    ):
        return None
    files = result["files"]
    input_key = _input_asset(asset_key, metadata(publication.asset_materialization))
    if result["completeness"]["status"] in {"complete", "gap"} and (
        (asset_key in SILVER_INPUTS and input_key is None)
        or set(files) != ({asset_key, input_key} if input_key else {asset_key})
        or not result["version"]["target_version"]
    ):
        return None
    for key, version in files.items():
        if (
            key not in (asset_key, input_key)
            or _file_version(_asset_path(root, key, day), cache) != version
        ):
            return None
    return stored


def index_minute_audit_requests(instance, day, observed_at, root):
    targets = tuple(_audit_target(key, day) for key in sorted(INDEX_MINUTE_ASSETS))
    evidence = load_evidence(instance, targets, day, observed_at)
    publications = {}
    for target in targets:
        delivery = evidence.get(target.asset_key)
        if delivery and delivery.materialization and delivery.materialization.run_id and all(
            name in delivery.checks and delivery.checks[name].evaluation.passed
            for name in target.check_names
        ):
            publications[target.asset_key] = delivery.materialization
    run_ids = {publication.run_id for publication in publications.values()}
    if not run_ids:
        return []
    runs = {
        run.run_id: run for run in instance.get_runs(
            filters=dg.RunsFilter(run_ids=list(run_ids), statuses=[dg.DagsterRunStatus.SUCCESS]),
            limit=len(run_ids),
        )
    }
    identities = {}
    results = {
        key: stored[1] for key, publication in publications.items()
        if publication.run_id in runs
        and (stored := matching_index_minute_result(
            instance, key, day, publication, observed_at, root, identities,
        )) is not None
    }
    requests = []
    for key, publication in publications.items():
        if results.get(key, {}).get("completeness", {}).get("status") in {"complete", "gap"}:
            continue
        path = _asset_path(root, key, day)
        receipt = _publication_receipt(runs.get(publication.run_id), path, key, day)
        if receipt is None or _file_version(path, identities) is None:
            continue
        input_key = _input_asset(key, metadata(publication.asset_materialization))
        if key in SILVER_INPUTS:
            upstream = results.get(input_key)
            if not upstream or upstream["completeness"]["status"] != "complete":
                continue
            source = _asset_path(root, input_key, day)
            if receipt["inputs"].get("sources", {}).get(str(source)) != upstream["files"][input_key]:
                continue
        digest = receipt["sha256"]
        config = IndexMinuteAuditConfig(
            asset_key=key, business_date=day.isoformat(), frequency=_frequency(key),
            target_version=digest,
        )
        requests.append(build_run_request(
            run_key=build_asset_update_run_key(
                subject=INDEX_MINUTE_JOB,
                unit_id=f"{day}:{key}:{publication.run_id}:{digest}",
            ),
            run_config=dg.RunConfig(ops={"audit_index_minute": config}).to_config_dict(),
        ))
    if not requests:
        return []
    submitted = {
        run.tags.get(RUN_KEY_TAG) for run in instance.get_runs(
            filters=dg.RunsFilter(
                job_name=INDEX_MINUTE_JOB,
                tags={RUN_KEY_TAG: [request.run_key for request in requests]},
            ),
            limit=len(requests),
        )
    }
    return [request for request in requests if request.run_key not in submitted]


def _minute_times(day, frequency):
    step = timedelta(minutes=frequency)
    morning = datetime.combine(day, time(9, 30))
    afternoon = datetime.combine(day, time(13))
    return [
        *(morning + offset * step for offset in range(120 // frequency + 1)),
        *(afternoon + offset * step for offset in range(1, 120 // frequency + 1)),
    ]


def _stage_keys(connection, table, path, read_volume):
    connection.execute(
        f"""
        CREATE TEMP TABLE {table} AS
        SELECT upper(trim(ts_code)) AS ts_code, freq, trade_time
        FROM read_parquet(?, hive_partitioning=false)
    """,
        [str(path)],
    )
    read_volume["key_rows"] += connection.execute(
        f"SELECT count(*) FROM {table}"
    ).fetchone()[0]
    read_volume["key_files"] += 1


def _compare_keys(connection, expected_sql, parameters):
    query = f"""
        WITH expected AS MATERIALIZED ({expected_sql}), actual AS (
          SELECT ts_code, freq, trade_time, count(*) AS occurrences FROM target_keys GROUP BY ALL
        ), issues AS (
          SELECT 'missing' AS issue, expected.*, 1 AS n FROM expected
          ANTI JOIN actual USING (ts_code, freq, trade_time)
          UNION ALL
          SELECT 'extra', actual.ts_code, actual.freq, actual.trade_time, 1 FROM actual
          ANTI JOIN expected USING (ts_code, freq, trade_time)
          UNION ALL
          SELECT 'duplicate', ts_code, freq, trade_time, occurrences - 1 FROM actual
          WHERE occurrences > 1
        ), ranked AS (
          SELECT *, row_number() OVER (PARTITION BY issue ORDER BY ts_code, freq, trade_time) AS rank
          FROM issues
        )
        SELECT (SELECT count(*) FROM expected), (SELECT count(*) FROM target_keys),
          coalesce(sum(n) FILTER (WHERE issue = 'missing'), 0),
          coalesce(sum(n) FILTER (WHERE issue = 'extra'), 0),
          coalesce(sum(n) FILTER (WHERE issue = 'duplicate'), 0),
          coalesce(list(struct_pack(issue := issue, ts_code := ts_code, freq := freq,
            trade_time := CAST(trade_time AS VARCHAR)) ORDER BY issue, rank)
            FILTER (WHERE rank <= 10), [])
        FROM ranked
    """
    return connection.execute(query, parameters).fetchone()


def _expected_raw(connection, fields, day, frequency):
    codes = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT ts_code FROM target_keys WHERE ts_code IS NOT NULL AND ts_code <> ''"
        ).fetchall()
    ]
    pool_hash = fields.get("active_pool_hash")
    if (
        not codes
        or not pool_hash
        or len(codes) != fields.get("expected_code_count")
        or len(codes) != fields.get("returned_code_count")
        or fields.get("missing_code_count") != 0
        or fields.get("extra_code_count") != 0
        or index_mins_code_set_hash(codes) != pool_hash
    ):
        return None
    return (
        """SELECT ts_code, ? AS freq, trade_time
        FROM unnest(?::VARCHAR[]) codes(ts_code)
        CROSS JOIN unnest(?::TIMESTAMP[]) times(trade_time)""",
        [f"{frequency}min", codes, _minute_times(day, frequency)],
    )


def _expected_silver(connection, day, frequency, source_frequency, fallback):
    if frequency == source_frequency:
        return "SELECT DISTINCT ts_code, freq, trade_time FROM source_keys", []
    if fallback:
        target_times = fallback_target_times_for_index_mins_freq(frequency)
    else:
        missing_window_input = connection.execute(f"""
            WITH window_map AS ({cn_a_derived_minute_window_map_sql(frequency)})
            SELECT 1
            FROM (SELECT DISTINCT ts_code FROM source_keys) codes
            CROSS JOIN (SELECT DISTINCT source_time FROM window_map) needed
            ANTI JOIN source_keys actual
              ON codes.ts_code = actual.ts_code AND needed.source_time::TIME = actual.trade_time::TIME
            LIMIT 1
        """).fetchone()
        if missing_window_input:
            return None
        target_times = cn_a_derived_minute_target_times(frequency)
    times = [datetime.combine(day, time.fromisoformat(clock)) for clock in target_times]
    return (
        """SELECT ts_code, ? AS freq, trade_time
        FROM (SELECT DISTINCT ts_code FROM source_keys) codes
        CROSS JOIN unnest(?::TIMESTAMP[]) times(trade_time)""",
        [f"{frequency}min", times],
    )


def _result(asset_key, day, publication):
    return {
        "scope": _scope(asset_key, day),
        "target_publication_run_id": publication.run_id if publication else None,
        "version": {"target_version": None, "rule_version": RULE_VERSION, "inputs": []},
        "files": {},
        "read_volume": {"key_files": 0, "key_rows": 0, "sha256_bytes": 0},
        "completeness": {
            "status": "pending",
            "reason": {"code": "not_verified", "message": "缺少同版正式发布或发布凭证"},
            "checked_at": None,
            "expected_count": None,
            "actual_count": None,
            "missing_count": None,
            "extra_count": None,
            "samples": [],
            "exceptions": [],
            "components": [],
        },
    }


def _pending(result, code, message):
    result["completeness"]["reason"] = {"code": code, "message": message}
    return result


def _audit_partition(instance, config, day, observed_at):
    asset_key, frequency = config.asset_key, config.frequency
    delivery = _delivery(instance, asset_key, day, observed_at)
    publication = delivery.materialization if delivery else None
    result = _result(asset_key, day, publication)
    if publication is None:
        return result
    root = Path(DEFAULT_LAKE_ROOT)
    path = _asset_path(root, asset_key, day)
    previous = matching_index_minute_result(
        instance,
        asset_key,
        day,
        publication,
        observed_at,
        root,
        {},
    )
    if previous:
        _, verified = previous
        if verified["completeness"]["status"] in {"complete", "gap"}:
            if verified["version"]["target_version"] != config.target_version:
                raise dg.Failure("请求版本与当前已核验的正式产出不一致")
            return {**verified, "read_volume": result["read_volume"]}
    receipt = _receipt(instance, publication, path, asset_key, day)
    if receipt is None:
        return result
    if receipt["sha256"] != config.target_version:
        raise dg.Failure("请求版本与当前正式发布凭证不一致")
    fields = metadata(publication.asset_materialization)
    input_key = _input_asset(asset_key, fields)
    fallback = fields.get("source_mode") == "derived_fallback"
    if (asset_key in SILVER_INPUTS and input_key is None) or (
        fallback
        and any(
            fields.get(field) != receipt["result"].get(field)
            for field in ("source_mode", "source_empty_reason", "source_revision")
        )
    ):
        return _pending(result, "reference_missing", "缺少同版历史源全空及替代输入凭证")
    if input_key:
        source_path = _asset_path(root, input_key, day)
        source_delivery = _delivery(instance, input_key, day, observed_at)
        source_publication = (
            source_delivery.materialization if source_delivery else None
        )
        stored = matching_index_minute_result(
            instance,
            input_key,
            day,
            source_publication,
            observed_at,
            root,
            {},
        )
        if stored is None:
            return _pending(result, "upstream_pending", "等待本次实际输入的齐备核验")
        _, upstream = stored
        input_identity = upstream["files"].get(input_key)
        if (
            receipt["inputs"]["sources"].get(str(source_path)) != input_identity
            or input_identity is None
        ):
            return _pending(
                result, "version_mismatch", "发布凭证的输入与已核验的上游版本不一致"
            )
        status = upstream["completeness"]["status"]
        if status != "complete":
            reason = "upstream_gap" if status == "gap" else "upstream_pending"
            message = (
                "本次实际输入有缺口"
                if status == "gap"
                else "等待本次实际输入的齐备核验"
            )
            return _pending(result, reason, message)
        result["files"][input_key] = input_identity
        result["active_pool_hash"] = upstream.get("active_pool_hash")
        result["version"]["inputs"].append(
            {
                "asset_key": input_key,
                "scope": upstream["scope"],
                "target_version": upstream["version"]["target_version"],
            }
        )
    else:
        result["active_pool_hash"] = fields.get("active_pool_hash")
        if result["active_pool_hash"] != receipt["result"].get("active_pool_hash"):
            return _pending(result, "version_mismatch", "发布凭证与本次应有名单不一致")

    try:
        target_identity = stat_version(path)
        if target_identity is None:
            return _pending(result, "version_mismatch", "当前正式文件不存在")
        settings = DuckDBConnectionSettings(temp_directory=Path(gettempdir()).resolve())
        with connect_configured_duckdb(
            settings, temp_policy="existing_no_spill"
        ) as connection:
            if input_key:
                _stage_keys(
                    connection, "source_keys", source_path, result["read_volume"]
                )
                expected = _expected_silver(
                    connection, day, frequency, _frequency(input_key), fallback
                )
                if expected is None:
                    return _pending(
                        result, "upstream_gap", "本次实际输入缺少合成所需时点"
                    )
            with path.open("rb") as stream:
                actual_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            result["read_volume"]["sha256_bytes"] = target_identity[2]
            if actual_sha256 != receipt["sha256"]:
                return _pending(
                    result, "version_mismatch", "当前文件与该次正式发布凭证不一致"
                )
            result["files"][asset_key] = target_identity
            result["version"]["target_version"] = actual_sha256
            _stage_keys(connection, "target_keys", path, result["read_volume"])
            if not input_key:
                expected = _expected_raw(connection, fields, day, frequency)
                if expected is None:
                    return _pending(
                        result, "not_verified", "实有指数代码无法与当次应有名单匹配"
                    )
                result["version"]["inputs"].append(
                    {
                        "asset_key": "通用指数分钟线当次激活名单",
                        "scope": result["scope"],
                        "target_version": result["active_pool_hash"],
                    }
                )
            expected_count, actual_count, missing, extra, duplicates, samples = (
                _compare_keys(connection, *expected)
            )
        if any(
            stat_version(_asset_path(root, key, day)) != identity
            for key, identity in result["files"].items()
        ):
            result["files"].clear()
            result["version"]["target_version"] = None
            return _pending(result, "version_mismatch", "核验期间文件版本已变更")
    except (OSError, duckdb.Error):
        return _pending(result, "not_verified", "无法读取同版文件的分钟键")

    gap = bool(missing or extra or duplicates)
    result["completeness"].update(
        status="gap" if gap else "complete",
        reason={
            "code": "missing_or_extra_keys" if gap else "published_coverage",
            "message": f"缺少 {missing} 根，多出 {extra} 根，重复 {duplicates} 根"
            if gap
            else "当次应有指数及分钟时点全部匹配",
        },
        expected_count=expected_count,
        actual_count=actual_count,
        missing_count=missing,
        extra_count=extra,
        samples=samples,
        exceptions=[{"type": "source_empty_fallback", "source": input_key}]
        if fallback
        else [],
    )
    return result


@dg.op(out=dg.Out(dg.Nothing))
def audit_index_minute(context: dg.OpExecutionContext, config: IndexMinuteAuditConfig):
    if (
        config.asset_key not in INDEX_MINUTE_ASSETS
        or config.frequency != _frequency(config.asset_key)
        or config.coverage_scope != "dataset"
    ):
        raise dg.Failure("不支持该资产、频度或核验范围")
    day = date.fromisoformat(config.business_date)
    result = _audit_partition(context.instance, config, day, datetime.now(SHANGHAI))
    tags = {BUSINESS_DATE_TAG: day.isoformat(), AUDIT_ASSET_TAG: config.asset_key}
    if publication_run_id := result["target_publication_run_id"]:
        tags[AUDIT_PUBLICATION_TAG] = publication_run_id
    context.instance.add_run_tags(context.run_id, tags)
    if result["completeness"]["checked_at"] is None:
        result["completeness"]["checked_at"] = datetime.now(SHANGHAI).isoformat()
    context.add_output_metadata({INDEX_MINUTE_META: dg.MetadataValue.json(result)})


@dg.job(name=INDEX_MINUTE_JOB)
def daily_data_audit_index_minute_job():
    audit_index_minute()
