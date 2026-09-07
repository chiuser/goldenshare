import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch, sentinel

from stock_suspend_confirmed_test_support import require_isolated_context

require_isolated_context()

import duckdb
import pytest

from orchestrator.defs import duckdb_connection as connection_module
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


@pytest.fixture
def local_settings(tmp_path):
    directory = tmp_path / "existing-temp"
    directory.mkdir()
    return DuckDBConnectionSettings(
        temp_directory=directory,
        max_temp_directory_size="0B",
        memory_limit="512MB",
        threads=2,
    )


def assert_closed(connection):
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        connection.execute("SELECT 1")


def test_existing_no_spill_uses_real_connection_without_directory_writes(local_settings):
    # Deliberately request spill in settings: the explicit policy must override
    # only spill/extensions, without mutating the caller's frozen settings.
    settings = replace(local_settings, max_temp_directory_size="1GB")
    config_before = settings.config()
    with (
        patch.object(Path, "mkdir", side_effect=AssertionError("unexpected mkdir")) as mkdir,
        patch.object(connection_module.duckdb, "connect", wraps=duckdb.connect) as connect,
    ):
        with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as connection:
            rows = dict(connection.execute(
                "SELECT name, value FROM duckdb_settings() WHERE name IN "
                "('temp_directory','memory_limit','threads','preserve_insertion_order',"
                "'max_temp_directory_size','autoinstall_known_extensions','autoload_known_extensions')"
            ).fetchall())
            assert rows == {
                "temp_directory": str(settings.temp_directory),
                "memory_limit": "488.2 MiB", "threads": "2",
                "preserve_insertion_order": "false",
                "max_temp_directory_size": "0 bytes",
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
            }
            assert connection.execute("SELECT 42").fetchone() == (42,)
        mkdir.assert_not_called()
        connect.assert_called_once_with(database=":memory:", config={
            **config_before, "max_temp_directory_size": "0B",
            "autoinstall_known_extensions": "false", "autoload_known_extensions": "false",
        })
    assert settings.config() == config_before
    assert list(settings.temp_directory.iterdir()) == []
    assert_closed(connection)


@pytest.mark.parametrize("case", (
    "missing", "leaf_file", "parent_file", "leaf_symlink", "ancestor_symlink", "relative", "dotdot",
))
def test_existing_no_spill_rejects_paths_before_connect(tmp_path, case):
    directory = tmp_path / "temp"
    expected_error = ValueError
    if case == "missing":
        expected_error = FileNotFoundError
    elif case in ("leaf_file", "parent_file"):
        directory.write_text("sentinel")
        if case == "parent_file":
            directory = directory / "child"
        expected_error = NotADirectoryError
    elif case in ("leaf_symlink", "ancestor_symlink"):
        target = tmp_path / "target"
        target.mkdir()
        directory.symlink_to(target, target_is_directory=True)
        if case == "ancestor_symlink":
            (target / "child").mkdir()
            directory = directory / "child"
    elif case == "relative":
        directory = Path("relative-temp")
    elif case == "dotdot":
        directory = tmp_path / ".." / "temp"
    settings = DuckDBConnectionSettings(temp_directory=directory)
    with (
        patch.object(Path, "mkdir", side_effect=AssertionError("unexpected mkdir")) as mkdir,
        patch.object(connection_module.duckdb, "connect") as connect,
        pytest.raises(expected_error),
        connect_configured_duckdb(settings, temp_policy="existing_no_spill"),
    ):
        pytest.fail("invalid path must not yield")
    mkdir.assert_not_called()
    connect.assert_not_called()
    if case == "missing":
        assert not directory.exists()
    elif case in ("leaf_file", "parent_file"):
        assert (tmp_path / "temp").read_text() == "sentinel"


def test_unknown_policy_rejected_before_any_path_io(local_settings):
    with (
        patch.object(Path, "lstat", side_effect=AssertionError("unexpected stat")) as stat,
        patch.object(Path, "mkdir", side_effect=AssertionError("unexpected mkdir")) as mkdir,
        patch.object(connection_module.duckdb, "connect") as connect,
        pytest.raises(ValueError, match="Unknown DuckDB temp policy"),
        connect_configured_duckdb(local_settings, temp_policy="unknown"),
    ):
        pytest.fail("unknown policy must not yield")
    stat.assert_not_called()
    mkdir.assert_not_called()
    connect.assert_not_called()


def test_explicit_managed_preserves_config_and_creates_directory(local_settings):
    settings = replace(local_settings, temp_directory=local_settings.temp_directory / "new" / "temp")
    with patch.object(connection_module.duckdb, "connect", wraps=duckdb.connect) as connect:
        with connect_configured_duckdb(settings, temp_policy="managed") as connection:
            assert connection.execute("SELECT 1").fetchone() == (1,)
        connect.assert_called_once_with(database=":memory:", config=settings.config())
    assert settings.temp_directory.is_dir()
    assert_closed(connection)


@pytest.mark.parametrize("policy", ("managed", "existing_no_spill"))
def test_real_connection_closed_on_consumer_error(local_settings, policy):
    error = ValueError("consumer failed")
    with (
        pytest.raises(ValueError) as caught,
        connect_configured_duckdb(local_settings, temp_policy=policy) as connection,
    ):
        raise error
    assert caught.value is error
    assert_closed(connection)


@pytest.mark.parametrize("setting", (
    "temp_directory", "max_temp_directory_size", "autoinstall_known_extensions", "autoload_known_extensions",
))
def test_setting_mismatch_closes_real_connection_without_fallback(local_settings, setting):
    native_connect = duckdb.connect
    opened = []

    def misreported_connection(**kwargs):
        actual = native_connect(**kwargs)
        opened.append(actual)
        wrapper = MagicMock(wraps=actual)

        def execute(sql):
            cursor = actual.execute(sql)
            rows = cursor.fetchall()
            result = MagicMock(wraps=cursor)
            result.fetchall.return_value = [(name, "wrong" if name == setting else value) for name, value in rows]
            return result

        wrapper.execute.side_effect = execute
        return wrapper

    with (
        patch.object(connection_module.duckdb, "connect", side_effect=misreported_connection) as connect,
        pytest.raises(RuntimeError, match="was not applied"),
        connect_configured_duckdb(local_settings, temp_policy="existing_no_spill"),
    ):
        pytest.fail("mismatched settings must not yield")
    connect.assert_called_once()
    assert len(opened) == 1
    assert_closed(opened[0])
    assert list(local_settings.temp_directory.iterdir()) == []


@pytest.mark.parametrize("field,value", (("threads", 0), ("memory_limit", ""), ("max_temp_directory_size", "")))
def test_invalid_settings_do_not_connect(local_settings, field, value):
    with (
        patch.object(connection_module.duckdb, "connect") as connect,
        pytest.raises(ValueError),
        connect_configured_duckdb(replace(local_settings, **{field: value}), temp_policy="existing_no_spill"),
    ):
        pytest.fail("invalid settings must not yield")
    connect.assert_not_called()


def test_memory_exhaustion_does_not_enable_spill_or_retry(local_settings):
    settings = replace(local_settings, memory_limit="1MB")
    native_connect = duckdb.connect
    opened = []

    def capture_connection(**kwargs):
        actual = native_connect(**kwargs)
        opened.append(actual)
        return actual

    # On the installed SDK, 1MB is already insufficient for initialization's
    # settings query. Test that real failure; do not raise the resource budget.
    with (
        patch.object(connection_module.duckdb, "connect", side_effect=capture_connection) as connect,
        pytest.raises(duckdb.OutOfMemoryException),
        connect_configured_duckdb(settings, temp_policy="existing_no_spill"),
    ):
        pytest.fail("initialization exhausted memory and must not yield")
    connect.assert_called_once_with(database=":memory:", config={
        **settings.config(), "max_temp_directory_size": "0B",
        "autoinstall_known_extensions": "false", "autoload_known_extensions": "false",
    })
    assert len(opened) == 1
    assert_closed(opened[0])
    assert list(settings.temp_directory.iterdir()) == []


def test_connection_failure_propagates_without_retry(local_settings):
    error = RuntimeError("native connection failed")
    with (
        patch.object(connection_module.duckdb, "connect", side_effect=error) as connect,
        pytest.raises(RuntimeError) as caught,
        connect_configured_duckdb(local_settings, temp_policy="existing_no_spill"),
    ):
        pytest.fail("failed connection must not yield")
    assert caught.value is error
    connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
