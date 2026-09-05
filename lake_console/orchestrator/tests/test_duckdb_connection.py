import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch, sentinel

from orchestrator.defs.duckdb_connection import (
    DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
    DEFAULT_DUCKDB_MEMORY_LIMIT,
    DEFAULT_DUCKDB_PRESERVE_INSERTION_ORDER,
    DEFAULT_DUCKDB_TEMP_DIRECTORY,
    DEFAULT_DUCKDB_THREADS,
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.resources import DuckDBResource


class DuckDBConnectionTests(unittest.TestCase):
    def test_default_settings_are_fixed_contract(self) -> None:
        self.assertEqual(
            DEFAULT_DUCKDB_CONNECTION_SETTINGS.temp_directory,
            DEFAULT_DUCKDB_TEMP_DIRECTORY,
        )
        self.assertEqual(
            DEFAULT_DUCKDB_CONNECTION_SETTINGS.max_temp_directory_size,
            DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
        )
        self.assertEqual(
            DEFAULT_DUCKDB_CONNECTION_SETTINGS.memory_limit,
            DEFAULT_DUCKDB_MEMORY_LIMIT,
        )
        self.assertEqual(
            DEFAULT_DUCKDB_CONNECTION_SETTINGS.threads,
            DEFAULT_DUCKDB_THREADS,
        )
        self.assertEqual(
            DEFAULT_DUCKDB_CONNECTION_SETTINGS.preserve_insertion_order,
            DEFAULT_DUCKDB_PRESERVE_INSERTION_ORDER,
        )

    def test_connect_configured_duckdb_applies_runtime_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = DuckDBConnectionSettings(
                temp_directory=Path(temp_dir) / "duckdb_tmp",
                max_temp_directory_size="1GB",
                memory_limit="1GB",
                threads=2,
                preserve_insertion_order=False,
            )
            with connect_configured_duckdb(settings) as connection:
                rows = dict(
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
                self.assertEqual(rows["temp_directory"], str(settings.temp_directory))
                self.assertEqual(rows["threads"], "2")
                self.assertEqual(rows["preserve_insertion_order"], "false")
                self.assertIn("max_temp_directory_size", rows)
                self.assertIn("memory_limit", rows)
            self.assertTrue(settings.temp_directory.exists())

    def test_connect_configured_duckdb_rejects_invalid_temp_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file = Path(temp_dir) / "not_a_directory"
            temp_file.write_text("x")
            settings = DuckDBConnectionSettings(temp_directory=temp_file)
            with (
                self.assertRaises(FileExistsError),
                connect_configured_duckdb(settings),
            ):
                pass

    def test_duckdb_resource_uses_configured_connection(self) -> None:
        # Runtime settings are covered above with an explicit temporary directory.
        # This test checks delegation without opening the production spill path.
        manager = MagicMock()
        manager.__enter__.return_value = sentinel.connection
        with (
            patch(
                "orchestrator.defs.resources.connect_configured_duckdb",
                return_value=manager,
            ) as factory,
            DuckDBResource().connect() as connection,
        ):
            self.assertIs(connection, sentinel.connection)
            manager.__exit__.assert_not_called()

        factory.assert_called_once_with()
        manager.__enter__.assert_called_once_with()
        manager.__exit__.assert_called_once_with(None, None, None)

    def test_duckdb_resource_exits_connection_on_consumer_error(self) -> None:
        manager = MagicMock()
        manager.__enter__.return_value = sentinel.connection
        manager.__exit__.return_value = False
        error = ValueError("consumer failed")
        with (
            patch(
                "orchestrator.defs.resources.connect_configured_duckdb",
                return_value=manager,
            ) as factory,
            self.assertRaises(ValueError) as caught,
            DuckDBResource().connect() as connection,
        ):
            self.assertIs(connection, sentinel.connection)
            raise error

        self.assertIs(caught.exception, error)
        factory.assert_called_once_with()
        manager.__enter__.assert_called_once_with()
        manager.__exit__.assert_called_once_with(ValueError, error, ANY)

    def test_duckdb_resource_propagates_connection_factory_error(self) -> None:
        error = RuntimeError("connection failed")
        with (
            patch(
                "orchestrator.defs.resources.connect_configured_duckdb",
                side_effect=error,
            ) as factory,
            self.assertRaises(RuntimeError) as caught,
            DuckDBResource().connect(),
        ):
            self.fail("a failed factory must not yield a connection")

        self.assertIs(caught.exception, error)
        factory.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
