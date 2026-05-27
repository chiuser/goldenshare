"""Registered metadata keys and values for Dagster asset governance."""

from enum import Enum


SOURCE_SYSTEM_METADATA_KEY = "goldenshare/source_system"
SOURCE_API_METADATA_KEY = "goldenshare/source_api"
SOURCE_CATEGORY_PATH_METADATA_KEY = "goldenshare/source_category_path"
SOURCE_DOC_METADATA_KEY = "goldenshare/source_doc"
DATA_CONTRACT_METADATA_KEY = "goldenshare/data_contract"
PATH_TEMPLATE_METADATA_KEY = "goldenshare/path_template"

SOURCE_ROW_COUNT_METADATA_KEY = "goldenshare/source_row_count"
DUPLICATE_REMOVED_COUNT_METADATA_KEY = "goldenshare/duplicate_removed_count"
REJECTED_ROW_COUNT_METADATA_KEY = "goldenshare/rejected_row_count"
REJECT_REASON_COUNTS_METADATA_KEY = "goldenshare/reject_reason_counts"
SAMPLE_ROWS_METADATA_KEY = "goldenshare/sample_rows"

CHECK_SCOPE_METADATA_KEY = "goldenshare/check_scope"
CHECKED_ROW_COUNT_METADATA_KEY = "goldenshare/checked_row_count"
FAILED_ROW_COUNT_METADATA_KEY = "goldenshare/failed_row_count"
FAILURE_SAMPLES_METADATA_KEY = "goldenshare/failure_samples"


class SourceSystem(str, Enum):
    TUSHARE = "tushare"
    DERIVED = "derived"
    SEED = "seed"
    OLD_LAKE_BOOTSTRAP = "old_lake_bootstrap"


class CheckScope(str, Enum):
    SCHEMA = "schema"
    ROW_COUNT = "row_count"
    KEY_UNIQUENESS = "key_uniqueness"
    PARTITION_ALIGNMENT = "partition_alignment"
    VALUE_SANITY = "value_sanity"
    FRESHNESS = "freshness"


def _coerce_source_system(source_system: SourceSystem | str) -> SourceSystem:
    if isinstance(source_system, SourceSystem):
        return source_system
    return SourceSystem(source_system)


def _coerce_check_scope(check_scope: CheckScope | str) -> CheckScope:
    if isinstance(check_scope, CheckScope):
        return check_scope
    return CheckScope(check_scope)


def build_definition_metadata(
    *,
    source_system: SourceSystem | str,
    data_contract: str,
    path_template: str | None = None,
    source_api: str | None = None,
    source_category_path: str | None = None,
    source_doc: str | None = None,
) -> dict[str, str]:
    """Build approved asset definition metadata keys."""

    metadata = {
        SOURCE_SYSTEM_METADATA_KEY: _coerce_source_system(source_system).value,
        DATA_CONTRACT_METADATA_KEY: data_contract,
    }
    if path_template:
        metadata[PATH_TEMPLATE_METADATA_KEY] = path_template
    if source_api:
        metadata[SOURCE_API_METADATA_KEY] = source_api
    if source_category_path:
        metadata[SOURCE_CATEGORY_PATH_METADATA_KEY] = source_category_path
    if source_doc:
        metadata[SOURCE_DOC_METADATA_KEY] = source_doc
    return metadata


def build_check_metadata(
    *,
    check_scope: CheckScope | str,
    checked_row_count: int | None = None,
    failed_row_count: int | None = None,
) -> dict[str, str | int]:
    """Build common asset check metadata without embedding sample payloads."""

    metadata: dict[str, str | int] = {
        CHECK_SCOPE_METADATA_KEY: _coerce_check_scope(check_scope).value,
    }
    if checked_row_count is not None:
        if checked_row_count < 0:
            raise ValueError("checked_row_count must be non-negative.")
        metadata[CHECKED_ROW_COUNT_METADATA_KEY] = checked_row_count
    if failed_row_count is not None:
        if failed_row_count < 0:
            raise ValueError("failed_row_count must be non-negative.")
        metadata[FAILED_ROW_COUNT_METADATA_KEY] = failed_row_count
    return metadata
