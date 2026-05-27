"""Registered metadata keys and values for Dagster asset governance."""

from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.catalog import get_dataset_chinese_name


DAGSTER_URI_METADATA_KEY = "dagster/uri"
DAGSTER_ROW_COUNT_METADATA_KEY = "dagster/row_count"
DAGSTER_COLUMN_SCHEMA_METADATA_KEY = "dagster/column_schema"

GOLDENSHARE_METADATA_PREFIX = "goldenshare/"

DATASET_ID_METADATA_KEY = "goldenshare/dataset_id"
DATASET_NAME_METADATA_KEY = "goldenshare/dataset_name"
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
READY_FOR_TRADE_DATE_METADATA_KEY = "goldenshare/ready_for_trade_date"

CHECK_SCOPE_METADATA_KEY = "goldenshare/check_scope"
CHECKED_ROW_COUNT_METADATA_KEY = "goldenshare/checked_row_count"
FAILED_ROW_COUNT_METADATA_KEY = "goldenshare/failed_row_count"
FILE_PATH_METADATA_KEY = "goldenshare/file_path"
INPUT_FILE_PATHS_METADATA_KEY = "goldenshare/input_file_paths"
MISSING_FILE_PATHS_METADATA_KEY = "goldenshare/missing_file_paths"
FAILURE_SAMPLES_METADATA_KEY = "goldenshare/failure_samples"

_LEGACY_METADATA_ALIASES = {
    "path",
    "raw_path",
    "silver_path",
    "gold_path",
    "index_basic_path",
    "stock_basic_path",
    "paths",
    "missing_paths",
    "row_count",
    "columns",
    "schema",
}


class SourceSystem(str, Enum):
    TUSHARE = "tushare"
    DERIVED = "derived"
    SEED = "seed"
    OLD_LAKE_BOOTSTRAP = "old_lake_bootstrap"


class CheckScope(str, Enum):
    FILE_EXISTS = "file_exists"
    SCHEMA = "schema"
    ROW_COUNT = "row_count"
    KEY_UNIQUENESS = "key_uniqueness"
    PARTITION_ALIGNMENT = "partition_alignment"
    VALUE_SANITY = "value_sanity"
    FRESHNESS = "freshness"
    REFERENTIAL_INTEGRITY = "referential_integrity"
    RECONCILIATION = "reconciliation"


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
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build approved asset definition metadata keys."""

    metadata: dict[str, Any] = {
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
    metadata.update(_namespace_goldenshare_metadata(extra_metadata or {}))
    return metadata


def build_asset_definition_metadata(
    *,
    dataset_id: str,
    source_system: SourceSystem | str,
    data_contract: str,
    path_template: str | None = None,
    source_api: str | None = None,
    source_category_path: str | None = None,
    source_doc: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build complete asset definition metadata, including dataset identity."""

    return {
        **build_dataset_metadata(dataset_id=dataset_id),
        **build_definition_metadata(
            source_system=source_system,
            data_contract=data_contract,
            path_template=path_template,
            source_api=source_api,
            source_category_path=source_category_path,
            source_doc=source_doc,
            extra_metadata=extra_metadata,
        ),
    }


def build_dataset_metadata(*, dataset_id: str) -> dict[str, str]:
    """Build stable dataset identity metadata for an asset definition."""

    return {
        DATASET_ID_METADATA_KEY: dataset_id,
        DATASET_NAME_METADATA_KEY: get_dataset_chinese_name(dataset_id),
    }


def build_materialization_metadata(
    *,
    uri: str | Path | None = None,
    row_count: int | None = None,
    columns: Sequence[str] | Sequence[tuple[str, str]] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build materialization metadata with Dagster standard keys first."""

    metadata: dict[str, Any] = {}
    if uri is not None:
        metadata[DAGSTER_URI_METADATA_KEY] = str(uri)
    if row_count is not None:
        if row_count < 0:
            raise ValueError("row_count must be non-negative.")
        metadata[DAGSTER_ROW_COUNT_METADATA_KEY] = row_count
    if columns is not None:
        metadata[DAGSTER_COLUMN_SCHEMA_METADATA_KEY] = _table_schema_metadata(columns)
    metadata.update(_namespace_goldenshare_metadata(extra_metadata or {}))
    return metadata


def build_check_metadata(
    *,
    check_scope: CheckScope | str,
    checked_row_count: int | None = None,
    failed_row_count: int | None = None,
    file_path: str | Path | None = None,
    input_file_paths: Sequence[str | Path] | None = None,
    missing_file_paths: Sequence[str | Path] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build common asset check metadata without embedding sample payloads."""

    metadata: dict[str, Any] = {
        CHECK_SCOPE_METADATA_KEY: _coerce_check_scope(check_scope).value,
    }
    if file_path is not None:
        metadata[FILE_PATH_METADATA_KEY] = str(file_path)
    if input_file_paths is not None:
        metadata[INPUT_FILE_PATHS_METADATA_KEY] = [
            str(path) for path in input_file_paths
        ]
    if missing_file_paths is not None:
        metadata[MISSING_FILE_PATHS_METADATA_KEY] = [
            str(path) for path in missing_file_paths
        ]
    if checked_row_count is not None:
        if checked_row_count < 0:
            raise ValueError("checked_row_count must be non-negative.")
        metadata[CHECKED_ROW_COUNT_METADATA_KEY] = checked_row_count
    if failed_row_count is not None:
        if failed_row_count < 0:
            raise ValueError("failed_row_count must be non-negative.")
        metadata[FAILED_ROW_COUNT_METADATA_KEY] = failed_row_count
    metadata.update(
        _namespace_goldenshare_metadata(extra_metadata or {}, allow_legacy_aliases=True)
    )
    return metadata


def _table_schema_metadata(
    columns: Sequence[str] | Sequence[tuple[str, str]],
) -> dg.MetadataValue:
    table_columns: list[dg.TableColumn] = []
    for column in columns:
        if isinstance(column, tuple):
            name, type_name = column
        else:
            name, type_name = column, "unknown"
        table_columns.append(dg.TableColumn(str(name), str(type_name)))
    return dg.MetadataValue.table_schema(dg.TableSchema(columns=table_columns))


def _namespace_goldenshare_metadata(
    metadata: Mapping[str, Any],
    *,
    allow_legacy_aliases: bool = False,
) -> dict[str, Any]:
    namespaced: dict[str, Any] = {}
    for key, value in metadata.items():
        if key.startswith("dagster/") or key.startswith(GOLDENSHARE_METADATA_PREFIX):
            namespaced[key] = value
        elif key in _LEGACY_METADATA_ALIASES and not allow_legacy_aliases:
            raise ValueError(
                f"{key!r} is a legacy metadata key. Use the typed builder argument "
                "or an explicit goldenshare/* key."
            )
        elif key == "path":
            namespaced[FILE_PATH_METADATA_KEY] = str(value)
        elif key == "raw_path":
            namespaced[f"{GOLDENSHARE_METADATA_PREFIX}raw_file_path"] = str(value)
        elif key == "silver_path":
            namespaced[f"{GOLDENSHARE_METADATA_PREFIX}silver_file_path"] = str(value)
        elif key == "gold_path":
            namespaced[f"{GOLDENSHARE_METADATA_PREFIX}gold_file_path"] = str(value)
        elif key == "index_basic_path":
            namespaced[f"{GOLDENSHARE_METADATA_PREFIX}index_basic_file_path"] = str(
                value
            )
        elif key == "stock_basic_path":
            namespaced[f"{GOLDENSHARE_METADATA_PREFIX}stock_basic_file_path"] = str(
                value
            )
        elif key == "paths":
            if isinstance(value, Mapping):
                namespaced[INPUT_FILE_PATHS_METADATA_KEY] = {
                    str(partition_key): str(path)
                    for partition_key, path in value.items()
                }
            else:
                namespaced[INPUT_FILE_PATHS_METADATA_KEY] = [
                    str(path) for path in value
                ]
        elif key == "missing_paths":
            namespaced[MISSING_FILE_PATHS_METADATA_KEY] = [str(path) for path in value]
        elif key == "row_count":
            namespaced[CHECKED_ROW_COUNT_METADATA_KEY] = value
        elif key == "columns":
            namespaced[f"{GOLDENSHARE_METADATA_PREFIX}observed_columns"] = value
        elif key == "schema":
            namespaced[f"{GOLDENSHARE_METADATA_PREFIX}observed_schema"] = value
        else:
            namespaced[f"{GOLDENSHARE_METADATA_PREFIX}{key}"] = value
    return namespaced
