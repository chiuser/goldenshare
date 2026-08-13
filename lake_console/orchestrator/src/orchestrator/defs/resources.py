import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dagster as dg
import duckdb
from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.health.lake_root import assert_lake_root_available_for_run
from orchestrator.defs.notifications.feishu import FeishuWebhookResource
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, GOLD, RAW, SILVER, lake_path


class LakeRootResource(dg.ConfigurableResource):
    root_path: str = DEFAULT_LAKE_ROOT

    def root(self) -> Path:
        return Path(self.root_path)

    def ensure_available_for_run(self) -> None:
        assert_lake_root_available_for_run(self.root())

    def raw_path(self, *parts: str) -> Path:
        return lake_path(self.root(), RAW, *parts)

    def silver_path(self, *parts: str) -> Path:
        return lake_path(self.root(), SILVER, *parts)

    def gold_path(self, *parts: str) -> Path:
        return lake_path(self.root(), GOLD, *parts)


class DuckDBResource(dg.ConfigurableResource):
    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with connect_configured_duckdb() as connection:
            yield connection


@dataclass(frozen=True)
class TushareResult:
    rows: list[dict[str, Any]]
    columns: tuple[str, ...]
    metadata: dict[str, Any]


class TushareResource(dg.ConfigurableResource):
    token: str

    def call(
        self,
        api_name: str,
        params: Mapping[str, Any] | None,
        fields: Sequence[str],
    ) -> TushareResult:
        token = self._require_token()
        field_names = tuple(fields)
        if not api_name:
            raise ValueError("Tushare api_name is required.")
        if not field_names:
            raise ValueError("Tushare fields must be explicit; empty fields are not allowed.")

        try:
            import tushare as ts
        except ModuleNotFoundError as exc:
            raise RuntimeError("Missing tushare dependency in the Dagster orchestrator environment.") from exc

        client = ts.pro_api(token)
        api = getattr(client, api_name, None)
        if not callable(api):
            raise ValueError(f"Unsupported Tushare API: {api_name}")

        request_params = dict(params or {})
        frame = api(**request_params, fields=",".join(field_names))
        rows = frame.to_dict("records")
        columns = tuple(str(column) for column in frame.columns)
        metadata = {
            "api_name": api_name,
            "params": request_params,
            "fields": list(field_names),
            "row_count": len(rows),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        return TushareResult(rows=rows, columns=columns, metadata=metadata)

    def _require_token(self) -> str:
        token = self.token.strip()
        if not token:
            raise RuntimeError("Missing TUSHARE_TOKEN; cannot call Tushare API.")
        return token


class ProdPostgresResource(dg.ConfigurableResource):
    host_env_var: str = "PROD_POSTGRES_HOST"
    port_env_var: str = "PROD_POSTGRES_PORT"
    user_env_var: str = "PROD_POSTGRES_USER"
    password_env_var: str = "PROD_POSTGRES_PASSWORD"
    database_env_var: str = "PROD_POSTGRES_DATABASE"
    sslmode_env_var: str = "PROD_POSTGRES_SSLMODE"
    default_sslmode: str = "prefer"
    connect_timeout_seconds: int = 10

    @contextmanager
    def connect(self) -> Iterator[Any]:
        try:
            import psycopg2
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing psycopg2 dependency in the Dagster orchestrator environment."
            ) from exc

        connection = psycopg2.connect(
            host=self._required_env(self.host_env_var),
            port=int(self._required_env(self.port_env_var)),
            user=self._required_env(self.user_env_var),
            password=self._required_env(self.password_env_var),
            dbname=self._required_env(self.database_env_var),
            sslmode=self._optional_env(self.sslmode_env_var, self.default_sslmode),
            connect_timeout=self.connect_timeout_seconds,
        )
        try:
            connection.set_session(readonly=True, autocommit=True)
            yield connection
        finally:
            connection.close()

    @contextmanager
    def connect_readonly_transaction(self) -> Iterator[Any]:
        """Open a rollback-only read transaction for bounded streaming exports."""

        try:
            import psycopg2
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing psycopg2 dependency in the Dagster orchestrator environment."
            ) from exc

        connection = psycopg2.connect(
            host=self._required_env(self.host_env_var),
            port=int(self._required_env(self.port_env_var)),
            user=self._required_env(self.user_env_var),
            password=self._required_env(self.password_env_var),
            dbname=self._required_env(self.database_env_var),
            sslmode=self._optional_env(self.sslmode_env_var, self.default_sslmode),
            connect_timeout=self.connect_timeout_seconds,
        )
        try:
            connection.set_session(readonly=True, autocommit=False)
            try:
                yield connection
            finally:
                connection.rollback()
        finally:
            connection.close()

    def duckdb_connection_string(self) -> str:
        parts = {
            "host": self._required_env(self.host_env_var),
            "port": self._required_env(self.port_env_var),
            "user": self._required_env(self.user_env_var),
            "password": self._required_env(self.password_env_var),
            "dbname": self._required_env(self.database_env_var),
            "sslmode": self._optional_env(self.sslmode_env_var, self.default_sslmode),
            "connect_timeout": str(self.connect_timeout_seconds),
        }
        return " ".join(
            f"{key}={self._postgres_conninfo_value(value)}"
            for key, value in parts.items()
        )

    @staticmethod
    def _required_env(name: str) -> str:
        value = os.environ.get(name, "").strip()
        if not value:
            raise RuntimeError(f"Missing required prod Postgres env var: {name}.")
        return value

    @staticmethod
    def _optional_env(name: str, default: str) -> str:
        return os.environ.get(name, "").strip() or default

    @staticmethod
    def _postgres_conninfo_value(value: str) -> str:
        if not value:
            return "''"
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        if any(character.isspace() for character in escaped) or "'" in value or "\\" in value:
            return f"'{escaped}'"
        return escaped


class ProdPostgresWriteResource(dg.ConfigurableResource):
    host_env_var: str = "PROD_POSTGRES_WRITE_HOST"
    port_env_var: str = "PROD_POSTGRES_WRITE_PORT"
    user_env_var: str = "PROD_POSTGRES_WRITE_USER"
    password_env_var: str = "PROD_POSTGRES_WRITE_PASSWORD"
    database_env_var: str = "PROD_POSTGRES_WRITE_DATABASE"
    sslmode_env_var: str = "PROD_POSTGRES_WRITE_SSLMODE"
    default_sslmode: str = "prefer"
    connect_timeout_seconds: int = 10

    @contextmanager
    def connect(self) -> Iterator[Any]:
        with self._connect(readonly=False) as connection:
            yield connection

    @contextmanager
    def connect_readonly(self) -> Iterator[Any]:
        with self._connect(readonly=True) as connection:
            yield connection

    @contextmanager
    def _connect(self, *, readonly: bool) -> Iterator[Any]:
        try:
            import psycopg2
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing psycopg2 dependency in the Dagster orchestrator environment."
            ) from exc

        connection = psycopg2.connect(
            host=ProdPostgresResource._required_env(self.host_env_var),
            port=int(ProdPostgresResource._required_env(self.port_env_var)),
            user=ProdPostgresResource._required_env(self.user_env_var),
            password=ProdPostgresResource._required_env(self.password_env_var),
            dbname=ProdPostgresResource._required_env(self.database_env_var),
            sslmode=ProdPostgresResource._optional_env(
                self.sslmode_env_var,
                self.default_sslmode,
            ),
            connect_timeout=self.connect_timeout_seconds,
        )
        try:
            connection.set_session(readonly=readonly, autocommit=False)
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
        finally:
            connection.close()


defs = dg.Definitions(
    resources={
        "lake_root": LakeRootResource(),
        "duckdb": DuckDBResource(),
        "tushare": TushareResource(token=dg.EnvVar("TUSHARE_TOKEN")),
        "prod_postgres": ProdPostgresResource(),
        "prod_postgres_write": ProdPostgresWriteResource(),
        "clickhouse": ClickhouseResource(
            host=dg.EnvVar("CLICKHOUSE_HOST"),
            port=dg.EnvVar.int("CLICKHOUSE_PORT"),
            user=dg.EnvVar("CLICKHOUSE_USER"),
            password=dg.EnvVar("CLICKHOUSE_PASSWORD"),
            database=dg.EnvVar("CLICKHOUSE_DATABASE"),
        ),
        "prod_clickhouse": ClickhouseResource(
            host=dg.EnvVar("PROD_CLICKHOUSE_HOST"),
            port=dg.EnvVar.int("PROD_CLICKHOUSE_PORT"),
            user=dg.EnvVar("PROD_CLICKHOUSE_USER"),
            password=dg.EnvVar("PROD_CLICKHOUSE_PASSWORD"),
            database=dg.EnvVar("PROD_CLICKHOUSE_DATABASE"),
        ),
        "feishu": FeishuWebhookResource(),
    }
)
