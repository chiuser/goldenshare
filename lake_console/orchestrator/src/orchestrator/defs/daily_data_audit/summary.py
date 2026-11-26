import json
from datetime import date, datetime, time, timedelta

from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_ASSET
from orchestrator.defs.catalog.lake_assets import (
    RAW_NAMECHANGE_CHECKS,
    SILVER_STOCK_DAILY_CHECKS,
)
from orchestrator.defs.daily_data_audit.evidence import (
    SHANGHAI,
    DeliveryEvidence,
    metadata,
)
from orchestrator.defs.daily_data_audit.registry import (
    DAILY_SNAPSHOTS,
    DELIVERY_DATE_FIELDS,
    ETF_COVERAGE_CHECK,
    SILVER_INDEX_PERIOD,
    AuditTarget,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
)
from orchestrator.defs.run_contracts.index_period import INDEX_PERIOD_COVERAGE_RULE
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
    MAJOR_INDEX_MINS_SILVER_ASSET_KEYS,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    major_index_mins_technical_state_asset_key,
)
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_ASSET,
)

STATUSES = ("complete", "gap", "pending", "not_applicable")
CALENDAR_RAW = "raw_tushare_trade_calendar"
CALENDAR_SILVER = "silver_trade_calendar"
DC_CLASSIFICATION = {"raw_tushare_dc_index", "silver_dc_index"}
INDEX_BASIC = {"raw_tushare_index_basic", "silver_index_basic"}
STOCK_DAILY_SILVER = "silver_stock_daily"
STOCK_DAILY_QFQ_GOLD = "gold_stock_daily_qfq"
LOCAL_TECHNICAL = "ch_dc_daily_technical"
STOCK_BASIC_RAW = "raw_tushare_stock_basic"
PUBLICATION_CHECK_REASONS = {
    "silver_dc_industry_hierarchy": "当次行业层级快照通过固定基线与分类参照对账",
    "raw_tushare_stock_daily": "当次股票日线通过当前上市且应交易股票的覆盖检查",
    STOCK_DAILY_SILVER: "当次股票日线通过生命周期及应交易股票的覆盖检查",
    "raw_index_daily": "当次指数日线通过登记指数名单的覆盖检查",
    STRUCTURE_ASSET: "当日量化结构计算完成，原 Check 通过",
    "silver_dc_member": "现有生产 Check 通过",
    "gold_market_major_indices_daily": "当次主要指数日线通过固定名单覆盖检查",
    "raw_tushare_idx_factor_pro": "当次指数技术因子通过有效指数名单的覆盖检查",
    **dict.fromkeys(
        (*MAJOR_INDEX_MINS_SILVER_ASSET_KEYS, *MAJOR_INDEX_MINS_GOLD_ASSET_KEYS),
        "当次主要指数分钟线通过适用名单及本频度时点检查",
    ),
    **dict.fromkeys(
        (major_index_mins_technical_state_asset_key(freq) for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS),
        "当次主要指数分钟技术指标状态通过名单、最后时点及连续性检查",
    ),
}
STOCK_MINUTE_QFQ_INPUTS = {
    f"gold_stk_mins_qfq_{target}m": f"silver_stk_mins_{source}m"
    for target, source in CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET.items()
}
STOCK_MINUTE_SILVER_INPUTS = {
    f"silver_stk_mins_{freq}m": (
        ("raw_stk_mins_1m",)
        if freq == 1
        else (f"raw_stk_mins_{freq}m", "raw_stk_mins_1m")
    )
    for freq in (1, 5, 15, 30, 60)
}
MACD_KDJ_INDICATOR_INPUTS = {
    f"gold_stk_mins_qfq_macd_kdj_{freq}m": f"gold_stk_mins_qfq_{freq}m"
    for freq in CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET
}
MACD_KDJ_STATE_INPUTS = {
    f"gold_stk_mins_qfq_macd_kdj_state_{freq}m": f"gold_stk_mins_qfq_macd_kdj_{freq}m"
    for freq in CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET
}
RAW_INDEX_PERIOD = {"raw_index_weekly", "raw_index_monthly"}
RAW_ETF_BASIC = "raw_tushare_etf_basic"
SILVER_ETF_BASIC = "silver_etf_basic"
RAW_STOCK_FACTOR = "raw_tushare_stk_factor_pro"
SILVER_STOCK_FACTOR = "silver_stock_factor_pro"
CONFIRMED_SUSPEND = "silver_stock_suspend_confirmed"
RAW_DAILY_BASIC = "raw_tushare_daily_basic"
MONEYFLOW_SILVER_INPUTS = {
    f"silver_{dataset}": f"raw_tushare_{dataset}"
    for dataset in (
        "moneyflow",
        "moneyflow_ths",
        "moneyflow_dc",
        "moneyflow_cnt_ths",
        "moneyflow_ind_ths",
        "moneyflow_ind_dc",
        "moneyflow_mkt_dc",
    )
}
ETF_DAILY_INPUTS = {
    "silver_etf_daily": "raw_tushare_fund_daily",
    "silver_etf_adj_factor": "raw_tushare_fund_adj",
}


def _reason(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, SHANGHAI).isoformat()


def _iso_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def materialization_fields(evidence: DeliveryEvidence) -> dict:
    record = evidence.materialization
    return metadata(record.asset_materialization) if record else {}


def _actual_date(target: AuditTarget, materialization: dict) -> str | None:
    if target.asset_key in SILVER_INDEX_PERIOD:
        return _iso_date(materialization.get("trade_date"))
    if not target.exact_as_of:
        return _iso_date(target.partition)
    for field in DELIVERY_DATE_FIELDS:
        actual = _iso_date(materialization.get(field))
        if actual:
            return actual
    return None


def _target_version(details: dict) -> str | None:
    if version := details.get("period_file_version"):
        return json.dumps(version, separators=(",", ":"))
    for key in (
        "file_sha256",
        "sha256",
        "content_hash",
        "silver_sha256",
        "silver_content_hash",
    ):
        value = details.get(key)
        if isinstance(value, str) and len(value) == 64:
            return value
    if version := details.get("audit_file_version"):
        return json.dumps(version, separators=(",", ":"))
    return None


def _published_version(key: str, details: dict) -> str | None:
    if key == RAW_ETF_BASIC:
        return details.get("raw_snapshot_hash")
    if key == CONFIRMED_SUSPEND:
        return details.get("confirmed_fact_logical_sha256")
    # The writer mirrors and atomically publishes the normalized source rows.
    if (
        key.startswith("raw_major_index_mins_")
        and details.get("write_mode") == "staged_atomic_replace"
    ):
        return details.get("source_revision")
    return _target_version(details)


def _publication_ref(record, version: str | None) -> dict:
    return {
        "type": "materialization",
        "run_id": record.run_id,
        "record_id": record.storage_id,
        "target_version": version,
    }


def _check_ref(name, record, target_version) -> dict:
    fields = metadata(record.evaluation)
    return {
        "type": "check",
        "check_name": name,
        "run_id": record.run_id,
        "record_id": record.id,
        "target_version": target_version,
        "passed": record.evaluation.passed,
        "message": fields.get("conclusion")
        or fields.get("reason_code")
        or record.evaluation.description,
    }


def _component(name, status, reason):
    return {"name": name, "status": status, "reason": reason}


def _update(target, day, observed_at, record, actual):
    expected_date = target.expected_date.isoformat() if target.expected_date else None
    deadline = datetime.combine(day + timedelta(days=1), time.min, SHANGHAI)
    published = record and (not target.exact_as_of or actual == expected_date)
    if target.requires_update is False:
        status, reason = "not_required", _reason("not_required", "所选日无需更新")
    elif published and (not target.exact_as_of or actual):
        status, reason = "updated", _reason("published", "已有适用交付记录")
    elif target.requires_update is None or expected_date is None or record is not None:
        status, reason = (
            "unknown",
            _reason("delivery_unverified", "暂无法确认所选日的应更条件或实际交付"),
        )
    elif observed_at < deadline:
        status, reason = "not_due", _reason("not_due", "截至观察时间仍在更新窗口")
    else:
        status, reason = (
            "overdue",
            _reason("overdue", "已过次日零点，未找到应有的交付记录"),
        )
    return {
        "status": status,
        "expected_date": expected_date,
        "published_at": _timestamp(record.timestamp) if published else None,
        "deadline_at": deadline.isoformat() if target.requires_update else None,
        "reason": reason,
    }


def _index_basic_proof(bundle, name, coverage):
    fields = metadata(bundle.checks[name].evaluation).get("index_basic_coverage") or {}
    published = bundle.materialization
    return fields == {
        **coverage,
        "materialization_id": published.storage_id,
        "materialization_run_id": published.run_id,
    }


def _index_period_proof(scope, details, check, target_version):
    publication = details.get("index_period_coverage") or {}
    version = publication.get("version") or {}
    inputs = version.get("inputs") or []
    if (
        check is None
        or not check.evaluation.passed
        or publication.get("scope") != scope
        or version.get("target_version") != target_version
        or version.get("rule_version") != INDEX_PERIOD_COVERAGE_RULE
        or not inputs
        or any(not item.get("target_version") for item in inputs)
    ):
        return None
    coverage = metadata(check.evaluation).get("index_period_coverage") or {}
    if (
        coverage.get("scope") == scope
        and coverage.get("version") == version
        and coverage.get("passed") is True
    ):
        return coverage
    return None


def _local_technical_proof(bundle, details):
    check = bundle.checks.get(f"{LOCAL_TECHNICAL}_core_check")
    if check is None:
        return None
    coverage = metadata(check.evaluation).get("local_key_coverage")
    if (
        coverage
        and coverage.get("materialization_id") == bundle.materialization.storage_id
        and coverage.get("source_file_version") == details.get("source_file_version")
    ):
        return coverage
    return None


def _production_coverage(bundle, details):
    version = details.get("audit_file_version")
    if not version:
        return None
    for check in bundle.checks.values():
        if not check.evaluation.passed:
            continue
        coverage = metadata(check.evaluation).get("audit_coverage")
        if coverage and coverage.get("file_version") == version:
            return coverage
    return None


def _checks_passed(names, checks):
    return bool(names) and all(
        name in checks and checks[name].evaluation.passed for name in names
    )


def _stock_snapshot_input_matches(asset, input_version, rows):
    if asset == "股票身份映射规则":
        return True
    source = rows.get(asset)
    if not source or source["version"]["target_version"] != input_version:
        return False
    if asset == "raw_tushare_namechange":
        passed = {
            proof["check_name"]
            for proof in source["completeness"]["evidence"]
            if proof["type"] == "check" and proof["passed"]
        }
        return source["update"]["status"] == "updated" and passed.issuperset(
            RAW_NAMECHANGE_CHECKS
        )
    return source["completeness"]["status"] == "complete"


def _moneyflow_source(key, details, bundle, rows):
    raw = rows.get(MONEYFLOW_SILVER_INPUTS[key])
    check = bundle.checks.get(f"{key}_standardization_check")
    if (
        raw
        and check
        and check.evaluation.passed
        and check.run_id == bundle.materialization.run_id
        and details.get("raw_sha256")
        and details["raw_sha256"] == raw["version"]["target_version"]
    ):
        return raw
    return None


def _reuse(target, day, actual, details, bundle, rows):
    key = target.asset_key
    proofs = bundle.checks
    checks_passed = _checks_passed(target.check_names, proofs)
    if not checks_passed:
        return None
    if key == CALENDAR_RAW and details.get(
        "calendar_start_date", ""
    ) <= day.isoformat() <= details.get("calendar_end_date", ""):
        return _reason("published_coverage", "上交所已发布区间的自然日连续且唯一"), []
    if key == CALENDAR_SILVER:
        raw_version = details.get("raw_sha256")
        raw = rows.get(CALENDAR_RAW)
        if (
            raw
            and raw["completeness"]["status"] == "complete"
            and raw_version == raw["version"]["target_version"]
        ):
            return _reason("published_coverage", "已与核验通过的 Raw 日历逐日核对"), [
                {
                    "asset_key": CALENDAR_RAW,
                    "target_version": raw_version,
                    "scope": raw["scope"],
                },
            ]
    if key in INDEX_BASIC and actual == day.isoformat():
        coverage = details.get("index_basic_coverage", {})
        if coverage.get("passed") is not True:
            return None
        if key == "raw_tushare_index_basic":
            if _index_basic_proof(bundle, "raw_index_basic_contract_check", coverage):
                return _reason(
                    "check_passed", "所选日已完成源响应分页和候选快照对账"
                ), []
        else:
            raw = rows.get("raw_tushare_index_basic")
            if (
                raw
                and raw["completeness"]["status"] == "complete"
                and _index_basic_proof(
                    bundle, "silver_index_basic_lifecycle_domain_check", coverage
                )
                and coverage.get("raw_sha256") == raw["version"]["target_version"]
            ):
                return _reason(
                    "check_passed", "所选日的指数基础信息通过同批来源及生命周期对账"
                ), [_input(raw)]
    if key == RAW_ETF_BASIC:
        return _reason("check_passed", "ETF 基础信息的源快照已通过正式内容指纹检查"), []
    if key == SILVER_ETF_BASIC:
        raw = rows.get(RAW_ETF_BASIC)
        if (
            raw
            and raw["completeness"]["status"] == "complete"
            and details.get("raw_snapshot_hash") == raw["version"]["target_version"]
        ):
            return _reason(
                "check_passed", "按同一版 ETF 基础信息完成筛选和内容指纹对账"
            ), [_input(raw)]
    if key == CONFIRMED_SUSPEND:
        approved = metadata(
            proofs["silver_stock_suspend_confirmed_approved_content_check"].evaluation
        )
        reference_fields = (
            "confirmed_fact_source_sha256",
            "confirmed_fact_calendar_sha256",
        )
        if all(details.get(field) for field in reference_fields) and all(
            details.get(field) and details[field] == approved.get(field)
            for field in ("confirmed_fact_version", "confirmed_fact_logical_sha256")
        ):
            return _reason(
                "check_passed", "该版全日停牌事实与批准内容和所用日历一致"
            ), [
                _versioned_input("批准的全日停牌事实", details[reference_fields[0]]),
                _versioned_input(CALENDAR_SILVER, details[reference_fields[1]]),
            ]
    if (
        key.startswith("raw_major_index_mins_")
        and details.get("write_mode") == "staged_atomic_replace"
    ):
        check = proofs[f"{key}_core_check"]
        fields = metadata(check.evaluation)
        scope_hash = details.get("scope_hash")
        if (
            check.run_id == bundle.materialization.run_id
            and fields.get("file_path") == details.get("dagster/uri")
            and scope_hash
            and scope_hash == fields.get("scope_hash")
            and details.get("source_row_count")
            == details.get("output_row_count")
            == fields.get("checked_row_count")
        ):
            return _reason(
                "check_passed", "按本次正式源交付核对主要指数名单和必备时点"
            ), [
                _versioned_input("主要指数分钟行情应有范围", scope_hash),
            ]
    if key == RAW_DAILY_BASIC:
        if details.get("delivery_method") == "tushare_daily" and details.get(
            "input_code_hash"
        ):
            return _reason(
                "check_passed", "同次文件通过股票日线应有代码及必需状态检查"
            ), [
                _versioned_input("raw_tushare_stock_daily", details["input_code_hash"]),
            ]
        if details.get("delivery_method") == "prod_history" and details.get(
            "history_export_fingerprint"
        ):
            return _reason("check_passed", "已对照冻结的每日指标历史导出"), [
                _versioned_input(
                    "股票每日指标历史导出", details["history_export_fingerprint"]
                ),
            ]
    if key in {RAW_STOCK_FACTOR, SILVER_STOCK_FACTOR}:
        proof = metadata(proofs[f"{key}_file_contract_check"].evaluation)
        fields = (
            "file_sha256",
            "scope_digest",
            "day_source_digest",
            "processing_version",
        )
        comparison = proof.get("comparison") or {}
        if all(details.get(f) and details[f] == proof.get(f) for f in fields) and all(
            comparison.get(f) == 0
            for f in ("missing_key_count", "unexpected_key_count", "changed_row_count")
        ):
            inputs = [
                _versioned_input(
                    "股票技术因子当次源批次", details["day_source_digest"]
                ),
                _versioned_input("股票技术因子当次覆盖范围", details["scope_digest"]),
            ]
            if key == SILVER_STOCK_FACTOR:
                raw = rows.get(RAW_STOCK_FACTOR)
                if (
                    not raw
                    or raw["completeness"]["status"] != "complete"
                    or not details.get("raw_sha256")
                    or details["raw_sha256"] != proof.get("raw_sha256")
                    or details["raw_sha256"] != raw["version"]["target_version"]
                    or inputs != raw["version"]["inputs"]
                ):
                    return None
                inputs.append(_input(raw))
            return _reason(
                "check_passed", "已复用该日技术因子源覆盖和同版键值对账"
            ), inputs
    if key == "raw_tushare_dc_member":
        return _reason("check_passed", "现有生产 Check 通过"), []
    if (
        key == ANNOUNCEMENT_ASSET
        and (details.get("announcement_identity") or {}).get("day") == day.isoformat()
    ):
        return _reason("check_passed", "已和本次冻结的公告分页交付对账"), []
    if key in RAW_INDEX_PERIOD:
        return _reason("published_coverage", "同次期末交付已按固定指数名单校验"), []
    if key in {
        "raw_tushare_stk_period_bar_adj_week",
        "raw_tushare_stk_period_bar_adj_month",
    } and details.get("period_delivery"):
        return _reason("published_coverage", "当期文件的交付版本及生产对账通过"), []
    if key in {"silver_stock_weekly", "silver_stock_monthly"}:
        raw_key = (
            "raw_tushare_stk_period_bar_adj_week"
            if key.endswith("weekly")
            else "raw_tushare_stk_period_bar_adj_month"
        )
        raw = rows.get(raw_key)
        raw_version = details.get("silver_source_version")
        references = details.get("silver_reference_versions")
        if (
            raw
            and raw_version
            and raw["completeness"]["status"] == "complete"
            and json.dumps(raw_version, separators=(",", ":"))
            == raw["version"]["target_version"]
            and references
        ):
            return _reason(
                "published_coverage", "已核对同版 Raw、生命周期和身份映射的当期投影"
            ), [
                _input(raw),
                *(
                    {
                        "asset_key": name,
                        "target_version": json.dumps(version),
                        "scope": {},
                    }
                    for name, version in references.items()
                ),
            ]
    if key == "raw_tushare_moneyflow_mkt_dc" and details.get("dagster/row_count") == 1:
        return _reason(
            "check_passed", "现有生产 Check 确认所选日的市场资金流向记录"
        ), []
    if key in MONEYFLOW_SILVER_INPUTS:
        raw = _moneyflow_source(key, details, bundle, rows)
        if raw and raw["completeness"]["status"] == "complete":
            return _reason("check_passed", "与核验通过的同版 Raw 资金流向一致"), [
                _input(raw)
            ]
    return None


def _input(row):
    return {
        "asset_key": row["scope"]["asset_key"],
        "scope": row["scope"],
        "target_version": row["version"]["target_version"],
    }


def _versioned_input(name, version):
    return {"asset_key": name, "target_version": version, "scope": {}}


def _coverage(
    row, *, expected, actual, missing, extra, samples, exceptions, inputs, reason
):
    row["completeness"].update(
        status="gap" if missing or extra else "complete",
        reason=reason,
        expected_count=expected,
        actual_count=actual,
        missing_count=missing,
        extra_count=extra,
        samples=samples,
        exceptions=exceptions,
    )
    row["version"]["inputs"] = inputs


def _etf_minutes(row, bundle, rows):
    key = row["scope"]["asset_key"]
    details = materialization_fields(bundle)
    identity = row["version"]["target_version"]
    if key.startswith("raw_"):
        scope = bundle.checks.get(f"{key}_request_scope_check")
        bars = bundle.checks.get(f"{key}_bar_domain_check")
        if not scope or not bars or not identity:
            return
        coverage = metadata(scope.evaluation)
        domain = metadata(bars.evaluation)
        basic_version = details.get("basic_silver_content_hash")
        basis = details.get("basic_reference_fingerprint")
        if not (
            basic_version
            and basis == coverage.get("basic_reference_fingerprint")
            and identity == coverage.get("raw_sha256") == domain.get("raw_sha256")
            and domain.get("gap_policy_hash")
        ):
            return
        missing = coverage["missing_count"]
        if not missing and (not scope.evaluation.passed or not bars.evaluation.passed):
            return
        _coverage(
            row,
            expected=coverage["expected_count"],
            actual=coverage["present_count"],
            missing=missing,
            extra=coverage.get("unexplained_new_count"),
            samples=domain.get("samples", []),
            exceptions=domain.get("bar_domain_reason_codes", [])
            if bars.evaluation.passed
            else [],
            inputs=[
                {
                    "asset_key": "silver_etf_basic",
                    "target_version": basic_version,
                    "scope": {"reference_fingerprint": basis},
                }
            ],
            reason=_reason(
                "coverage_gap" if missing else "check_passed",
                "冻结 ETF 名单存在缺码"
                if missing
                else "已核对冻结 ETF 名单和当日分钟时点",
            ),
        )
        row["version"]["rule_version"] += f":{domain['gap_policy_hash']}"
        return
    raw = rows.get(key.replace("silver_", "raw_", 1))
    if not raw or raw["completeness"]["status"] != "complete" or not identity:
        return
    raw_version = raw["version"]["target_version"]
    for check in bundle.checks.values():
        fields = metadata(check.evaluation)
        if (
            check.evaluation.passed
            and fields.get("check_scope") == "reconciliation"
            and fields.get("silver_sha256") == identity
            and fields.get("raw_sha256") == raw_version == details.get("raw_sha256")
        ):
            row["completeness"].update(
                status="complete",
                reason=_reason("check_passed", "与已核验的同版 Raw 分钟线双向一致"),
            )
            row["version"]["inputs"] = [_input(raw)]
            return


def _etf_daily(key, evidence, rows, recalculated):
    raw_key = ETF_DAILY_INPUTS[key]
    silver = evidence.get(key)
    raw = evidence.get(raw_key)
    if not silver or not raw or not raw.materialization or not silver.materialization:
        return
    name = ETF_COVERAGE_CHECK[key]
    check = silver.checks.get(name)
    parity = silver.checks.get(f"{key}_source_parity_check")
    if not check or not parity or not parity.evaluation.passed:
        return
    details = materialization_fields(silver)
    raw_row, silver_row = rows[raw_key], rows[key]
    raw_version = raw_row["version"]["target_version"]
    fields = metadata(check.evaluation)
    frozen_reference = details.get("basic_reference_fingerprint")
    basic_version = details.get("basic_silver_content_hash")
    pointer = (silver.materialization.asset_materialization.tags or {}).get(
        f"dagster/input_event_pointer/{raw_key}"
    )
    # These checks reread the Raw partition. The check in the publication run
    # can be associated with the input pointer and the Raw file contract hash
    # only while that pointer still identifies the selected Raw publication.
    if not (
        raw_version
        and silver_row["version"]["target_version"]
        and pointer == str(raw.materialization.storage_id)
        and check.run_id == parity.run_id == silver.materialization.run_id
        and any(
            item.evaluation.passed
            and metadata(item.evaluation).get("content_hash") == raw_version
            for item in raw.checks.values()
        )
        and frozen_reference
        and frozen_reference == fields.get("basic_reference_fingerprint")
        and basic_version
        and basic_version == fields.get("basic_silver_content_hash")
        and fields.get("reason_code")
        in {"ready", "coverage_warning", "etf_daily_silver_coverage_failed"}
        and set(fields.get("failed_rule_names", ()))
        <= {"missing_expected_codes", "unexpected_silver_codes"}
        and fields.get("expected_code_count", 0) > 0
    ):
        return
    facts = fields.get("confirmed_business_fact_versions")
    if key == "silver_etf_adj_factor" and facts is None:
        return
    inputs = [
        {
            "asset_key": "silver_etf_basic",
            "target_version": basic_version,
            "scope": {"reference_fingerprint": frozen_reference},
        }
    ]
    inputs.extend(
        {
            "asset_key": "基金清算事实",
            "target_version": f"{fact['fact_id']}:{fact['revision']}",
            "scope": {"ts_code": fact["ts_code"]},
        }
        for fact in facts or ()
    )
    expected = fields["expected_code_count"]
    matching = fields["raw_matching_code_count"]
    for row, count, extra, bound_inputs in (
        (raw_row, expected - matching, 0, inputs),
        (
            silver_row,
            fields["missing_expected_code_count"],
            fields["silver_extra_code_count"],
            [*inputs, _input(raw_row)],
        ),
    ):
        if (
            row["scope"]["asset_key"] not in recalculated
            or row["completeness"]["status"] == "not_applicable"
        ):
            continue
        _coverage(
            row,
            expected=expected,
            actual=expected - count,
            missing=count,
            extra=extra,
            samples=fields.get("failure_samples", []),
            exceptions=facts or [],
            inputs=bound_inputs,
            reason=_reason(
                "coverage_gap" if count or extra else "check_passed",
                "当天上市的沪深 ETF 名单存在覆盖差异"
                if count or extra
                else "已核对当天上市的沪深 ETF 名单",
            ),
        )
    if raw_key in recalculated:
        raw_row["completeness"]["checked_at"] = _timestamp(check.event.timestamp)
        raw_row["completeness"]["evidence"].append(
            {
                **_check_ref(name, check, silver_row["version"]["target_version"]),
                "asset_key": key,
            }
        )


def _row(target, day, observed_at, evidence, built, previous_stock_basic, stock_basic_runs_succeeded):
    key = target.asset_key
    details = materialization_fields(evidence) if evidence else {}
    record = evidence.materialization if evidence else None
    checks = evidence.checks if evidence else {}
    actual = _actual_date(target, details) if record else None
    if record and actual is None and key in DAILY_SNAPSHOTS:
        actual = datetime.fromtimestamp(record.timestamp, SHANGHAI).date().isoformat()
    scope = {
        "asset_key": key,
        "business_date": day.isoformat(),
        "partition_key": target.partition,
        "as_of_date": actual,
        "frequency": target.frequency,
        "coverage_scope": (
            "regular_session"
            if key.startswith("raw_stk_mins_")
            else "listed_sh_sz_etf"
            if key in ETF_DAILY_INPUTS or key in ETF_DAILY_INPUTS.values()
            else "dataset"
        ),
    }
    target_version = _published_version(key, details)
    local_coverage = (
        _local_technical_proof(evidence, details)
        if record and key == LOCAL_TECHNICAL
        else None
    )
    production_coverage = _production_coverage(evidence, details) if record else None
    if local_coverage:
        target_version = f"dg-materialization:{record.storage_id}"
    if key in RAW_INDEX_PERIOD:
        target_version = details.get("upstream_batch_id")
    if key in INDEX_BASIC:
        coverage = details.get("index_basic_coverage") or {}
        target_version = target_version or _target_version(coverage)
    if key == ANNOUNCEMENT_ASSET:
        target_version = _target_version(details.get("fingerprint") or {})
    if (
        key == "raw_tushare_dc_member"
        and details.get("source_closure_status") == "validated_before_promote"
    ):
        target_version = target_version or details.get("tushare_source_fingerprint")
    version = {
        "target_version": target_version,
        "inputs": [],
        "rule_version": target.entry.data_contract,
    }
    update = _update(target, day, observed_at, record, actual)
    if (
        evidence is None
        or (
            not record
            and target.exact_as_of
            and key not in DAILY_SNAPSHOTS
            and key not in SILVER_INDEX_PERIOD
        )
    ) and target.requires_update:
        update["status"] = "unknown"
        update["reason"] = _reason("delivery_unverified", "暂无法读取这项的发布记录")
    proof = [_publication_ref(record, target_version)] if record else []
    proof.extend(
        _check_ref(name, check, target_version) for name, check in checks.items()
    )
    status, reason = (
        "pending",
        _reason("not_verified", "暂无符合该数据集口径的核验结果"),
    )
    components = []
    index_period_coverage = None
    if target.excluded_reason:
        status, reason = (
            "not_applicable",
            _reason("not_in_scope", target.excluded_reason),
        )
    elif local_coverage:
        if local_coverage["missing_count"] or local_coverage["extra_count"]:
            status = "gap"
            reason = _reason(
                "missing_or_extra_keys",
                "本机板块日线技术指标与同版 Gold 的业务键有差异",
            )
        elif checks[f"{LOCAL_TECHNICAL}_core_check"].evaluation.passed:
            status = "complete"
            reason = _reason(
                "check_passed", "本机板块日线技术指标与同版 Gold 的业务键一致"
            )
        version["inputs"] = [
            _versioned_input(
                "gold_dc_daily_technical",
                json.dumps(
                    local_coverage["source_file_version"], separators=(",", ":")
                ),
            )
        ]
    elif production_coverage and (
        not target.exact_as_of or actual == update["expected_date"]
    ):
        status = production_coverage["status"]
        if status == "complete" and not _checks_passed(target.check_names, checks):
            status = "pending"
        reason = {
            "complete": _reason("check_passed", "现有生产 Check 已核对当次产出的覆盖"),
            "gap": _reason("missing_or_extra_keys", "当次产出与应有范围有差异"),
            "pending": (
                _reason("manual_review", "名单有增减，需要人工确认")
                if production_coverage["status"] == "pending"
                else _reason("not_verified", "其余生产 Check 尚未通过")
            ),
        }[status]
        version["rule_version"] = production_coverage["rule_version"]
        version["inputs"] = [
            _versioned_input(asset, value)
            for asset, value in production_coverage["inputs"].items()
        ]
        if (
            status == "complete"
            and version["rule_version"] == "stock_snapshot_projection_v1"
            and any(
                not _stock_snapshot_input_matches(asset, input_version, built)
                for asset, input_version in production_coverage["inputs"].items()
            )
        ):
            status = "pending"
            reason = _reason(
                "upstream_parity_only", "与本次输入转换一致，来源范围齐备待确认"
            )
    elif key == STOCK_BASIC_RAW and update["status"] == "updated":
        reason = _reason("not_verified", "缺少两日同口径的股票基础信息成功发布及 Check")
        if (
            previous_stock_basic
            and stock_basic_runs_succeeded
            and _checks_passed(target.check_names, checks)
            and _checks_passed(target.check_names, previous_stock_basic.checks)
        ):
            previous_details = materialization_fields(previous_stock_basic)
            count = details.get("dagster/row_count")
            previous_count = previous_details.get("dagster/row_count")
            if (
                all(
                    (item.get("params") or {}).get("list_status") == "L,D,P,G"
                    for item in (details, previous_details)
                )
                and count is not None
                and previous_count is not None
            ):
                previous_version = _target_version(previous_details)
                proof.append(_publication_ref(previous_stock_basic.materialization, previous_version))
                if previous_version:
                    version["inputs"] = [
                        _versioned_input("上一交易日股票基础信息 Raw", previous_version)
                    ]
                if abs(count - previous_count) <= 20:
                    status = "complete"
                    reason = _reason(
                        "check_passed", "股票基础信息全状态数量净增减不超过 20 条"
                    )
                else:
                    reason = _reason(
                        "not_verified", "股票基础信息全状态数量净增减超过 20 条"
                    )
    elif record and key in PUBLICATION_CHECK_REASONS:
        if key == "raw_index_daily" and not details.get("expected_code_set_hash"):
            reason = _reason("not_verified", "缺少当次登记指数名单的范围记录")
        elif _checks_passed(target.check_names, checks):
            status = "complete"
            reason = _reason("check_passed", PUBLICATION_CHECK_REASONS[key])
        else:
            reason = _reason("not_verified", "当次发布缺少通过的必需 Check")
    elif (
        target_version
        and record
        and (not target.exact_as_of or actual == update["expected_date"])
    ):
        if key in SILVER_INDEX_PERIOD:
            index_period_coverage = _index_period_proof(
                scope, details, checks.get(f"{key}_file_contract_check"), target_version
            )
            if index_period_coverage:
                status = "complete"
                reason = _reason("check_passed", "已核对每个应有指数的目标交易日")
                version = index_period_coverage["version"]
        else:
            result = _reuse(target, day, actual, details, evidence, built)
            if result:
                status, (reason, version["inputs"]) = "complete", result
    elif record:
        reason = _reason("version_mismatch", "已有产出，暂不能把齐备结论绑定到这版产出")
    if status == "pending" and record and key in SILVER_INDEX_PERIOD:
        reason = _reason("not_verified", "缺少该版本的齐备证据")
    if status == "pending" and key in DC_CLASSIFICATION:
        reason = _reason("reference_missing", "暂无所选日适用的板块分类标准集")
        components = [
            _component("东方财富行业板块", status, reason),
            _component("东方财富地域板块", status, reason),
            _component("东方财富概念板块", status, reason),
        ]
    if key.startswith("raw_stk_mins_"):
        post_close = (
            production_coverage.get("post_close_count") if production_coverage else None
        )
        components.append(
            _component(
                "盘后时段", "pending", _reason("not_verified", "暂无盘后交付覆盖结论")
            )
            if post_close is None
            else _component(
                "盘后时段",
                "complete",
                _reason(
                    "published_coverage",
                    f"已保留当次 Prod 交付的 {post_close} 根盘后记录",
                ),
            )
        )
    if status == "pending" and target_version and key in MONEYFLOW_SILVER_INPUTS:
        raw = _moneyflow_source(key, details, evidence, built)
        if raw:
            version["inputs"] = [_input(raw)]
            reason = _reason(
                "upstream_parity_only", "已核对同版 Raw 的标准化结果，Raw 齐备待确认"
            )
    check_time = max((check.event.timestamp for check in checks.values()), default=None)
    counts = _counts(status, key, details)
    coverage = index_period_coverage or local_coverage or production_coverage
    if coverage:
        counts = {field: coverage[field] for field in counts}
    return {
        "dataset_name": target.entry.dataset_name,
        "layer": target.entry.layer.value,
        "scope": scope,
        "version": version,
        "update": update,
        "observed_at": observed_at.isoformat(),
        "completeness": {
            "status": status,
            "reason": reason,
            "checked_at": _timestamp(check_time) if check_time is not None else None,
            **counts,
            "samples": coverage["samples"] if coverage else [],
            "exceptions": [],
            "evidence": proof,
            "components": components,
        },
    }


def _counts(status, key, details):
    rows = details.get("dagster/row_count")
    verified_calendar = status == "complete" and key in {CALENDAR_RAW, CALENDAR_SILVER}
    expected = None
    if verified_calendar:
        expected = (
            date.fromisoformat(details["calendar_end_date"])
            - date.fromisoformat(details["calendar_start_date"])
        ).days + 1
    return {
        "expected_count": expected,
        "actual_count": rows,
        "missing_count": 0 if verified_calendar else None,
        "extra_count": 0 if verified_calendar else None,
    }


def stock_daily_checks_passed(evidence):
    daily = evidence.get(STOCK_DAILY_SILVER)
    return daily is not None and _checks_passed(SILVER_STOCK_DAILY_CHECKS, daily.checks)


def _stock_daily_qfq(row, evidence, file_exists, run_succeeded):
    completeness = row["completeness"]
    if completeness["status"] == "not_applicable":
        return
    if not stock_daily_checks_passed(evidence):
        completeness["reason"] = _reason(
            "upstream_pending", "当日股票日线 Silver Check 尚未全部通过"
        )
        return
    if not file_exists:
        completeness["reason"] = _reason("not_verified", "未确认当日前复权文件存在")
        return
    if not run_succeeded:
        completeness["reason"] = _reason("not_verified", "未确认当次前复权任务成功")
        return
    completeness["status"] = "complete"
    completeness["reason"] = _reason(
        "check_passed", "当日股票日线 Silver Check 通过，前复权 Gold 文件存在且任务成功"
    )
    completeness["evidence"].extend(
        {**_check_ref(name, check, None), "asset_key": STOCK_DAILY_SILVER}
        for name, check in evidence[STOCK_DAILY_SILVER].checks.items()
    )


def _stock_minute_qfq(row, source, evidence, run_succeeded):
    completeness = row["completeness"]
    if completeness["status"] == "not_applicable":
        return
    if not source or source["completeness"]["status"] != "complete":
        completeness["reason"] = _reason(
            "upstream_pending", "当日输入频度的股票分钟线 Silver 齐备待确认"
        )
        return
    details = materialization_fields(evidence) if evidence else {}
    if not (
        details.get("output_file_count", 0) > 0
        and details.get("replacement_row_count", 0) > 0
        and run_succeeded
    ):
        completeness["reason"] = _reason(
            "not_verified", "未确认当日股票分钟前复权 Gold 已写入且任务成功"
        )
        return
    source_version = details.get("audit_source_file_version")
    if (
        not source_version
        or json.dumps(source_version, separators=(",", ":"))
        != source["version"]["target_version"]
    ):
        completeness["reason"] = _reason(
            "version_mismatch", "暂无法确认当次前复权使用了已核验的股票分钟线 Silver"
        )
        return
    row["version"].update(
        target_version=details.get("audit_delivery_version"),
        inputs=[_input(source)],
    )
    completeness["status"] = "complete"
    completeness["actual_count"] = details["replacement_row_count"]
    completeness["reason"] = _reason(
        "check_passed",
        "当日输入频度的股票分钟线 Silver 齐备，前复权 Gold 已写入且任务成功",
    )


def _stock_minute_silver(row, evidence, bundles, rows, raw_keys):
    details = materialization_fields(evidence) if evidence else {}
    inputs = details.get("audit_input_versions")
    completeness = row["completeness"]
    if not inputs or completeness["status"] not in {"complete", "gap"}:
        return
    if details.get("frozen_preserved_row_count"):
        completeness.update(
            status="pending",
            reason=_reason("not_verified", "历史冻结记录的适用范围还未核验"),
        )
        return
    daily = bundles.get(STOCK_DAILY_SILVER)
    if not (
        stock_daily_checks_passed(bundles)
        and _target_version(materialization_fields(daily))
        == inputs.get(STOCK_DAILY_SILVER)
        and any(
            item["asset_key"] == STOCK_DAILY_SILVER
            and item["target_version"] == inputs[STOCK_DAILY_SILVER]
            for item in row["version"]["inputs"]
        )
        and all(
            raw in rows
            and rows[raw]["completeness"]["status"] == "complete"
            and rows[raw]["version"]["target_version"] == inputs.get(raw)
            for raw in raw_keys
        )
    ):
        completeness.update(
            status="pending",
            reason=_reason(
                "upstream_pending", "股票分钟线 Raw 或当日日线的同版齐备证据待确认"
            ),
        )
        return
    row["version"]["inputs"] = [
        *(_input(rows[raw]) for raw in raw_keys),
        *(
            _versioned_input(asset, value)
            for asset, value in inputs.items()
            if asset not in raw_keys
        ),
    ]


def _macd_kdj_coverage(row, target, evidence, indicator, source):
    state = target.asset_key in MACD_KDJ_STATE_INPUTS
    completeness = row["completeness"]
    if completeness["status"] == "not_applicable":
        return
    fields = materialization_fields(evidence) if evidence else {}
    comparison = (
        _production_coverage(evidence, fields)
        if evidence and state
        else fields.get("audit_comparison")
    )
    same_indicator_run = bool(
        indicator and evidence and evidence.materialization
    ) and any(
        item["type"] == "materialization"
        and item["run_id"] == evidence.materialization.run_id
        for item in indicator["completeness"]["evidence"]
    )
    if not (
        source
        and source["completeness"]["status"] == "complete"
        and (
            not state
            or same_indicator_run
            and indicator["completeness"]["status"] == "complete"
        )
        and comparison
        and comparison["inputs"].get(source["scope"]["asset_key"])
        and comparison["inputs"][source["scope"]["asset_key"]]
        == source["version"]["target_version"]
    ):
        completeness.update(
            status="pending",
            reason=_reason(
                "upstream_pending", "当次采用的股票分钟前复权或指标齐备证据待确认"
            ),
        )
        return
    if comparison["status"] == "complete" and not _checks_passed(
        target.check_names, evidence.checks
    ):
        completeness.update(
            status="pending", reason=_reason("not_verified", "其余生产 Check 尚未通过")
        )
        return
    status = comparison["status"]
    row["version"]["inputs"] = [_input(source)]
    if state:
        row["version"]["inputs"].append(_input(indicator))
        row["version"]["inputs"].extend(
            _versioned_input(key, value)
            for key, value in comparison["inputs"].items()
            if key != source["scope"]["asset_key"]
        )
    else:
        row["version"]["target_version"] = (
            f"dg-materialization:{evidence.materialization.storage_id}"
        )
    row["version"]["rule_version"] = comparison["rule_version"]
    completeness.update(
        status=status,
        reason=(
            _reason("check_passed", "本次计算的股票代码和行数符合预期")
            if status == "complete"
            else _reason(
                "missing_or_extra_keys", "本次计算的股票代码或行数与预期不一致"
            )
        ),
        **{
            field: comparison[field]
            for field in (
                "expected_count",
                "actual_count",
                "missing_count",
                "extra_count",
                "samples",
            )
        },
    )


def make_summary(
    day,
    observed_at,
    targets,
    evidence,
    previous=None,
    changed=(),
    *,
    stock_daily_qfq_file_exists=None,
    qfq_successful_deliveries=(),
    previous_stock_basic=None,
    stock_basic_runs_succeeded=False,
    index_minute_results=None,
):
    prior_rows = (
        {row["scope"]["asset_key"]: row for row in previous["rows"]}
        if previous and changed
        else {}
    )
    built = {}
    for target in targets:
        key = target.asset_key
        if key in prior_rows and key not in changed:
            built[key] = prior_rows[key]
        else:
            built[key] = _row(
                target, day, observed_at, evidence.get(key), built, previous_stock_basic,
                stock_basic_runs_succeeded,
            )
    recalculated = set(changed) if prior_rows else set(built)
    for key, raw_keys in STOCK_MINUTE_SILVER_INPUTS.items():
        if key in built and key in recalculated:
            _stock_minute_silver(
                built[key], evidence.get(key), evidence, built, raw_keys
            )
    if STOCK_DAILY_QFQ_GOLD in built and STOCK_DAILY_QFQ_GOLD in recalculated:
        _stock_daily_qfq(
            built[STOCK_DAILY_QFQ_GOLD],
            evidence,
            stock_daily_qfq_file_exists,
            STOCK_DAILY_QFQ_GOLD in qfq_successful_deliveries,
        )
    for key, source in STOCK_MINUTE_QFQ_INPUTS.items():
        if key in recalculated and key in built:
            _stock_minute_qfq(
                built[key],
                built.get(source),
                evidence.get(key),
                key in qfq_successful_deliveries,
            )
    for target in targets:
        key = target.asset_key
        if key in recalculated and key in MACD_KDJ_INDICATOR_INPUTS:
            _macd_kdj_coverage(
                built[key],
                target,
                evidence.get(key),
                None,
                built.get(MACD_KDJ_INDICATOR_INPUTS[key]),
            )
    for target in targets:
        key = target.asset_key
        if key in recalculated and key in MACD_KDJ_STATE_INPUTS:
            indicator = MACD_KDJ_STATE_INPUTS[key]
            _macd_kdj_coverage(
                built[key],
                target,
                evidence.get(key),
                built.get(indicator),
                built.get(MACD_KDJ_INDICATOR_INPUTS[indicator]),
            )
    for prefix in ("raw_etf_mins_", "silver_etf_mins_"):
        for key, bundle in evidence.items():
            if (
                key in recalculated
                and key.startswith(prefix)
                and built[key]["completeness"]["status"] == "pending"
            ):
                _etf_minutes(built[key], bundle, built)
    for key, raw_key in ETF_DAILY_INPUTS.items():
        if key in built and raw_key in built:
            _etf_daily(key, evidence, built, recalculated)
    for key, stored in (index_minute_results or {}).items():
        row = built[key]
        if stored is None:
            if row["update"]["status"] == "updated":
                row["completeness"].update(
                    status="pending",
                    reason=_reason("not_verified", "缺少与当前产出及输入匹配的分钟线独立审计结果"),
                )
            continue
        output, result = stored
        row["version"] = result["version"]
        proof = row["completeness"]["evidence"]
        row["completeness"].update(
            **result["completeness"],
            evidence=[*proof, {
                "type": "independent_audit",
                "run_id": output.event_log_entry.run_id,
                "record_id": output.storage_id,
                "target_version": result["version"]["target_version"],
                "message": result["completeness"]["reason"]["message"],
            }],
        )
    rows = list(built.values())
    counts = dict.fromkeys(STATUSES, 0)
    for row in rows:
        counts[row["completeness"]["status"]] += 1
    return {
        "schema_version": 1,
        "business_date": day.isoformat(),
        "observed_at": observed_at.isoformat(),
        "generated_at": datetime.now(SHANGHAI).isoformat(),
        "summary": counts,
        "rows": rows,
    }
