import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.defs.bootstrap.source_method import BootstrapSourceMethod
from orchestrator.defs.duckdb_sql import (
    SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
    STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, silver_stock_identity_map_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata


OLD_TUSHARE_LAKE_ROOT = Path("/Volumes/datasource/goldenshare-tushare-lake")


@dataclass(frozen=True)
class StockIdentityMapBootstrapSpec:
    dataset_key: str
    source_path: Path
    target_path: Path
    source_fields: tuple[str, ...]
    target_fields: tuple[str, ...]
    select_sql_template: str
    empty_policy: str
    business_key: tuple[str, ...]
    source_method_metadata: str = BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP.value

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", Path(self.source_path))
        object.__setattr__(self, "target_path", Path(self.target_path))
        object.__setattr__(self, "source_fields", tuple(self.source_fields))
        object.__setattr__(self, "target_fields", tuple(self.target_fields))
        object.__setattr__(self, "business_key", tuple(self.business_key))

        if self.dataset_key != "silver_stock_identity_map":
            raise ValueError("Stock identity map bootstrap dataset_key is invalid.")
        if self.empty_policy != "require_positive":
            raise ValueError("Stock identity map bootstrap requires positive output.")
        if self.source_method_metadata != BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP.value:
            raise ValueError(
                "Stock identity map source_method_metadata must be old_lake_bootstrap."
            )
        if not self.source_fields:
            raise ValueError("Stock identity map source_fields must not be empty.")
        if not self.target_fields:
            raise ValueError("Stock identity map target_fields must not be empty.")
        if not self.select_sql_template:
            raise ValueError("Stock identity map select_sql_template is required.")


def stock_identity_map_bootstrap_spec(
    lake_root: Path | None = None,
    old_lake_root: Path = OLD_TUSHARE_LAKE_ROOT,
) -> StockIdentityMapBootstrapSpec:
    target_root = Path(lake_root or DEFAULT_LAKE_ROOT)
    return StockIdentityMapBootstrapSpec(
        dataset_key="silver_stock_identity_map",
        source_path=(
            Path(old_lake_root)
            / "manifest"
            / "security_identity"
            / "security_identity_map.parquet"
        ),
        target_path=silver_stock_identity_map_path(target_root),
        source_fields=SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
        target_fields=SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
        select_sql_template=STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE,
        empty_policy="require_positive",
        business_key=("source_ts_code",),
    )


def bootstrap_stock_identity_map_to_silver(
    spec: StockIdentityMapBootstrapSpec,
    duckdb_resource: DuckDBResource,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    if not spec.source_path.exists():
        raise FileNotFoundError(f"Stock identity map source file is missing: {spec.source_path}")
    if spec.target_path.exists() and not overwrite:
        raise FileExistsError(
            f"Stock identity map target file already exists: {spec.target_path}"
        )

    tmp_path = _tmp_path(spec.target_path)
    select_sql = _render_select_sql(spec)
    spec.target_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        with duckdb_resource.connect() as connection:
            connection.execute(copy_query_to_parquet(select_sql, tmp_path))
            row_count = _row_count(connection, tmp_path)
            columns = tuple(_column_names(connection, tmp_path))
            _validate_written_identity_map(spec, row_count, columns)
        os.replace(tmp_path, spec.target_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return build_materialization_metadata(
        uri=spec.target_path,
        row_count=row_count,
        observed_columns=columns,
        extra_metadata={
            "source_method": spec.source_method_metadata,
            "bootstrap_spec": spec.dataset_key,
            "empty_policy": spec.empty_policy,
        },
    )


def _render_select_sql(spec: StockIdentityMapBootstrapSpec) -> str:
    return spec.select_sql_template.format(old_path=duckdb_string(spec.source_path))


def _validate_written_identity_map(
    spec: StockIdentityMapBootstrapSpec,
    row_count: int,
    columns: tuple[str, ...],
) -> None:
    if spec.empty_policy == "require_positive" and row_count <= 0:
        raise ValueError(f"Bootstrap produced no rows for required dataset: {spec.dataset_key}")
    if columns != spec.target_fields:
        raise ValueError(
            "Bootstrap output columns do not match target_fields for "
            f"{spec.dataset_key}: expected {spec.target_fields}, got {columns}"
        )


def _column_names(connection, path: Path) -> list[str]:
    rows = connection.execute(describe_parquet_query(path, hive_partitioning=False)).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path) -> int:
    return int(connection.execute(count_parquet_query(path, hive_partitioning=False)).fetchone()[0])


def _tmp_path(target_path: Path) -> Path:
    return target_path.with_name(f"{target_path.name}.tmp")
