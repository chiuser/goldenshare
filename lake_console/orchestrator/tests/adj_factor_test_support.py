"""Isolate only connection settings; retain the real DuckDB engine and SQL."""

import shutil
import sys
from dataclasses import replace

import pytest

from orchestrator.defs.duckdb_connection import (
    DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    connect_configured_duckdb,
)


@pytest.fixture(autouse=True)
def isolated_factor_duckdb(tmp_path, monkeypatch):
    temp = tmp_path / "duckdb-temp"
    temp.mkdir()

    def isolated(settings=None, *, temp_policy="managed"):
        settings = replace(settings or DEFAULT_DUCKDB_CONNECTION_SETTINGS, temp_directory=temp)
        return connect_configured_duckdb(settings, temp_policy=temp_policy)

    for name in (
        "orchestrator.defs.assets.adj_factor",
        "orchestrator.defs.checks.adj_factor_checks",
        "orchestrator.defs.bootstrap.adj_factor_silver_history",
        "orchestrator.defs.resources",
    ):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "connect_configured_duckdb"):
            monkeypatch.setattr(module, "connect_configured_duckdb", isolated)
    try:
        yield
    finally:
        # Only this test's pytest-owned resource directory; reports live elsewhere.
        shutil.rmtree(tmp_path)
