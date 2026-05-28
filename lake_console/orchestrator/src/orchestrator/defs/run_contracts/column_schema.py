"""Column schema contract helpers for Dagster asset definitions."""

from collections.abc import Sequence
from dataclasses import dataclass

import dagster as dg


@dataclass(frozen=True)
class ColumnContract:
    """Stable field contract shown as Dagster asset definition column schema."""

    name: str
    type: str
    description: str

    def __post_init__(self) -> None:
        for field_name in ("name", "type", "description"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ColumnContract.{field_name} must be a non-empty string.")


def build_column_schema_metadata(
    column_schema: Sequence[ColumnContract],
) -> dg.MetadataValue:
    """Build Dagster table schema metadata from stable column contracts."""

    column_names: set[str] = set()
    table_columns: list[dg.TableColumn] = []
    for column in column_schema:
        if column.name in column_names:
            raise ValueError(f"Duplicate column contract name: {column.name!r}.")
        column_names.add(column.name)
        table_columns.append(
            dg.TableColumn(
                name=column.name,
                type=column.type,
                description=column.description,
            )
        )
    return dg.MetadataValue.table_schema(dg.TableSchema(columns=table_columns))
