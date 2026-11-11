"""Native period delivery identities and metadata; no storage or filesystem IO."""

from datetime import date
from uuid import UUID

from orchestrator.defs.run_contracts.run_keys import build_batch_id
from orchestrator.defs.run_contracts.stock_period import digest, frequency, period_date

WORK_KEY = "goldenshare/period_work"
COMPLETION_KEY = "goldenshare/period_completion"
FILE_DELIVERY_KEY = "goldenshare/period_delivery"
SILVER_SCOPE_KEY = "goldenshare/silver_update_scope"
BUSINESS_DATE_TAG = "goldenshare/stock_period_business_date"
KIND_TAG = "goldenshare/stock_period_kind"
FREQUENCY_TAG = "goldenshare/stock_period_freq"
SOURCE_BATCH_TAG = "goldenshare/stock_period_source_batch"
KINDS = (
    "daily",
    "closed_period",
    "factor_repair",
    "retirement_cleanup",
    "history_maintenance",
)


def iso_business_date(value):
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("period_business_date_invalid")
    return value


def validate_delivery_ref(value, freq=None):
    if not isinstance(value, dict) or set(value) != {
        "producer_run_id",
        "freq",
        "upstream_batch_id",
    }:
        raise ValueError("period_delivery_reference_invalid")
    if str(UUID(value["producer_run_id"])) != value["producer_run_id"]:
        raise ValueError("period_delivery_run_id_invalid")
    frequency(value["freq"])
    if freq is not None and value["freq"] != freq:
        raise ValueError("period_delivery_frequency_mismatch")
    if (
        not isinstance(value["upstream_batch_id"], str)
        or not value["upstream_batch_id"]
    ):
        raise ValueError("period_delivery_batch_id_invalid")
    return dict(value)


def delivery_ref(run_id, freq, kind, business_date, periods):
    frequency(freq)
    iso_business_date(business_date)
    if kind not in KINDS or periods != sorted(set(periods)):
        raise ValueError("period_delivery_scope_invalid")
    for period in periods:
        period_date(period, freq)
    return validate_delivery_ref(
        {
            "producer_run_id": run_id,
            "freq": freq,
            "upstream_batch_id": build_batch_id(
                producer="stock_period_raw",
                scope=freq,
                payload={
                    "producer_run_id": run_id,
                    "kind": kind,
                    "business_date": business_date,
                    "periods": periods,
                },
            ),
        }
    )


def delivery_work(
    reference,
    *,
    kind,
    business_date,
    periods,
    stock_codes=(),
    codes_hash=None,
    upstream_completions=(),
):
    from orchestrator.defs.stock_daily_qfq import (
        gold_stock_daily_qfq_factor_repair_codes_hash,
    )

    expected = delivery_ref(
        reference["producer_run_id"], reference["freq"], kind, business_date, periods
    )
    if expected != reference:
        raise ValueError("period_delivery_reference_mismatch")
    codes = sorted(set(stock_codes))
    actual_hash = gold_stock_daily_qfq_factor_repair_codes_hash(codes)
    if codes_hash is not None and codes_hash != actual_hash:
        raise ValueError("period_delivery_codes_hash_mismatch")
    return {
        "version": "stock-period-work@1",
        **reference,
        "kind": kind,
        "business_date": business_date,
        "periods": periods,
        "periods_hash": digest(periods),
        "stock_codes": codes,
        "codes_hash": actual_hash,
        "upstream_completions": list(upstream_completions),
    }


def delivery_completion(reference, *, kind, business_date, periods):
    expected = delivery_ref(
        reference["producer_run_id"], reference["freq"], kind, business_date, periods
    )
    if expected != reference or not periods:
        raise ValueError("period_delivery_completion_invalid")
    return {
        "version": "stock-period-delivery@1",
        **reference,
        "kind": kind,
        "business_date": business_date,
        "periods": periods,
        "periods_hash": digest(periods),
        "file_count": len(periods),
    }


def validate_delivery_completion(value, freq):
    if not isinstance(value, dict):
        raise TypeError("period_delivery_completion_invalid")
    if type(value.get("file_count")) is not int:
        raise ValueError("period_delivery_completion_invalid")
    try:
        reference = validate_delivery_ref(
            {k: value[k] for k in ("producer_run_id", "freq", "upstream_batch_id")},
            freq,
        )
        expected = delivery_completion(
            reference,
            kind=value["kind"],
            business_date=value["business_date"],
            periods=value["periods"],
        )
    except (KeyError, TypeError) as error:
        raise ValueError("period_delivery_completion_invalid") from error
    if value != expected:
        raise ValueError("period_delivery_completion_invalid")
    return reference


def period_run_tags(*, business_date, kind, freq=None):
    iso_business_date(business_date)
    if kind not in KINDS:
        raise ValueError("period_delivery_kind_invalid")
    tags = {BUSINESS_DATE_TAG: business_date, KIND_TAG: kind}
    if freq is not None:
        tags[FREQUENCY_TAG] = frequency(freq)
    return tags


def silver_update_scope(run_id, freq, business_date, reference, periods, *, phase):
    if str(UUID(run_id)) != run_id or phase not in ("planned", "files_complete"):
        raise ValueError("silver_update_scope_invalid")
    validate_delivery_ref(reference, freq)
    iso_business_date(business_date)
    return {
        "version": "stock-period-silver-update@1",
        "phase": phase,
        "producer_run_id": run_id,
        "freq": freq,
        "business_date": business_date,
        "source_completion": reference,
        "periods": periods,
        "periods_hash": digest(periods),
    }


def silver_update_run_tags(reference, *, business_date, kind):
    validate_delivery_ref(reference)
    return {
        **period_run_tags(
            business_date=business_date, kind=kind, freq=reference["freq"]
        ),
        SOURCE_BATCH_TAG: reference["upstream_batch_id"],
    }
