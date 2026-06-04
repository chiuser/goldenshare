from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb


DEFAULT_DUCKDB_TEMP_DIRECTORY = Path("/Volumes/datasource/.goldenshare_duckdb_tmp")
DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE = "512GB"
DEFAULT_DUCKDB_MEMORY_LIMIT = "16GB"
DEFAULT_DUCKDB_THREADS = 4
DEFAULT_DUCKDB_PRESERVE_INSERTION_ORDER = False


@dataclass(frozen=True)
class DuckDBConnectionSettings:
    temp_directory: Path = DEFAULT_DUCKDB_TEMP_DIRECTORY
    max_temp_directory_size: str = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE
    memory_limit: str = DEFAULT_DUCKDB_MEMORY_LIMIT
    threads: int = DEFAULT_DUCKDB_THREADS
    preserve_insertion_order: bool = DEFAULT_DUCKDB_PRESERVE_INSERTION_ORDER

    def config(self) -> dict[str, str]:
        if self.threads <= 0:
            raise ValueError("DuckDB threads must be positive.")
        if not self.max_temp_directory_size:
            raise ValueError("DuckDB max_temp_directory_size is required.")
        if not self.memory_limit:
            raise ValueError("DuckDB memory_limit is required.")
        return {
            "temp_directory": str(self.temp_directory),
            "max_temp_directory_size": self.max_temp_directory_size,
            "memory_limit": self.memory_limit,
            "threads": str(self.threads),
            "preserve_insertion_order": (
                "true" if self.preserve_insertion_order else "false"
            ),
        }


DEFAULT_DUCKDB_CONNECTION_SETTINGS = DuckDBConnectionSettings()


@contextmanager
def connect_configured_duckdb(
    settings: DuckDBConnectionSettings = DEFAULT_DUCKDB_CONNECTION_SETTINGS,
) -> Iterator[duckdb.DuckDBPyConnection]:
    settings.temp_directory.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(database=":memory:", config=settings.config())
    try:
        _validate_connection_settings(connection, settings)
        yield connection
    finally:
        connection.close()


def _validate_connection_settings(
    connection: duckdb.DuckDBPyConnection,
    settings: DuckDBConnectionSettings,
) -> None:
    current_settings = dict(
        connection.execute(
            """
            SELECT name, value
            FROM duckdb_settings()
            WHERE name IN (
              'temp_directory',
              'max_temp_directory_size',
              'memory_limit',
              'threads',
              'preserve_insertion_order'
            )
            """
        ).fetchall()
    )
    expected = {
        "temp_directory": str(settings.temp_directory),
        "threads": str(settings.threads),
        "preserve_insertion_order": (
            "true" if settings.preserve_insertion_order else "false"
        ),
    }
    for name, value in expected.items():
        if str(current_settings.get(name)) != value:
            raise RuntimeError(
                f"DuckDB setting {name!r} was not applied: "
                f"expected {value!r}, got {current_settings.get(name)!r}."
            )
    if "max_temp_directory_size" not in current_settings:
        raise RuntimeError("DuckDB max_temp_directory_size setting is missing.")
    if "memory_limit" not in current_settings:
        raise RuntimeError("DuckDB memory_limit setting is missing.")
