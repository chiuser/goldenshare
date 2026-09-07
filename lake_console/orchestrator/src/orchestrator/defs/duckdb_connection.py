from __future__ import annotations

import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    *,
    temp_policy: Literal["managed", "existing_no_spill"] = "managed",
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open the shared connection; restricted callers must opt in explicitly.

    The restricted policy prevents implicit temp-directory creation, disk spill
    and automatic extensions. It does not prohibit explicit SQL file writes.
    """
    if temp_policy == "managed":
        settings.temp_directory.mkdir(parents=True, exist_ok=True)
        config = settings.config()
    elif temp_policy == "existing_no_spill":
        _validate_existing_temp_directory(settings.temp_directory)
        config = {
            **settings.config(),
            "max_temp_directory_size": "0B",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
        }
    else:
        raise ValueError(f"Unknown DuckDB temp policy: {temp_policy!r}.")
    connection = duckdb.connect(database=":memory:", config=config)
    try:
        _validate_connection_settings(connection, settings)
        if temp_policy == "existing_no_spill":
            _validate_no_spill_settings(connection)
        yield connection
    finally:
        connection.close()


def _validate_existing_temp_directory(directory: Path) -> None:
    if not directory.is_absolute() or ".." in directory.parts:
        raise ValueError("DuckDB existing temp directory must be an absolute path without '..'.")
    # Check ancestors before the leaf; never resolve through a symbolic link.
    for part in (*reversed(directory.parents), directory):
        mode = part.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"DuckDB temp directory cannot contain a symlink: {part}.")
        if not stat.S_ISDIR(mode):
            raise NotADirectoryError(str(part))


def _validate_no_spill_settings(connection: duckdb.DuckDBPyConnection) -> None:
    current_settings = dict(
        connection.execute(
            """
            SELECT name, value FROM duckdb_settings()
            WHERE name IN (
              'max_temp_directory_size',
              'autoinstall_known_extensions',
              'autoload_known_extensions'
            )
            """
        ).fetchall()
    )
    expected = {
        "max_temp_directory_size": "0 bytes",
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
    }
    for name, value in expected.items():
        if current_settings.get(name) != value:
            raise RuntimeError(
                f"DuckDB restricted setting {name!r} was not applied: "
                f"expected {value!r}, got {current_settings.get(name)!r}."
            )


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
