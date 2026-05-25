from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import dagster as dg
import duckdb

from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, GOLD, RAW, SILVER, lake_path


class LakeRootResource(dg.ConfigurableResource):
    root_path: str = DEFAULT_LAKE_ROOT

    def root(self) -> Path:
        return Path(self.root_path)

    def ensure_available_for_run(self) -> None:
        root = self.root()
        required_paths = [root, root / RAW, root / SILVER, root / GOLD]
        missing_paths = [path for path in required_paths if not path.exists()]
        if missing_paths:
            missing = ", ".join(str(path) for path in missing_paths)
            raise FileNotFoundError(f"Lake root is not ready for this run. Missing: {missing}")

    def raw_path(self, *parts: str) -> Path:
        return lake_path(self.root(), RAW, *parts)

    def silver_path(self, *parts: str) -> Path:
        return lake_path(self.root(), SILVER, *parts)

    def gold_path(self, *parts: str) -> Path:
        return lake_path(self.root(), GOLD, *parts)


class DuckDBResource(dg.ConfigurableResource):
    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = duckdb.connect(database=":memory:")
        try:
            yield connection
        finally:
            connection.close()


class LakeMetaPostgresResource(dg.ConfigurableResource):
    postgres_url: str = "postgresql://congming@localhost:5432/goldenshare_lake_meta"

    @contextmanager
    def connect(self):
        try:
            import psycopg2
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing psycopg2-binary dependency in the Dagster orchestrator environment."
            ) from exc

        connection = psycopg2.connect(self.postgres_url)
        try:
            yield connection
        finally:
            connection.close()

    def ensure_market_major_indices_tables(self) -> None:
        ddl_statements = (
            """
            CREATE TABLE IF NOT EXISTS market_major_indices (
              rank INT NOT NULL,
              ts_code TEXT NOT NULL,
              display_name TEXT,
              PRIMARY KEY (rank),
              UNIQUE (ts_code)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS market_major_indices_change_history (
              id BIGSERIAL PRIMARY KEY,
              before_payload JSONB,
              after_payload JSONB,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              dagster_run_id TEXT
            )
            """,
        )
        with self.connect() as connection:
            with connection.cursor() as cursor:
                for statement in ddl_statements:
                    cursor.execute(statement)
            connection.commit()


@dataclass(frozen=True)
class ProdStrategyConfigFile:
    payload: dict[str, Any]
    metadata: dict[str, Any]


class ProdStrategyConfigFileResource(dg.ConfigurableResource):
    ssh_target: str = "goldenshare-prod"
    major_indices_config_path: str = (
        "/opt/goldenshare/goldenshare/src/biz/services/wealth/config/definitions/"
        "major_indices.cn_a.v1.json"
    )
    timeout_seconds: int = 20

    def read_major_indices_definition(self) -> ProdStrategyConfigFile:
        completed = subprocess.run(
            ["ssh", self.ssh_target, "cat", self.major_indices_config_path],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Failed to read prod major indices strategy config over read-only SSH."
            )

        raw_content = completed.stdout
        try:
            payload = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Prod major indices strategy config is not valid JSON.") from exc

        return ProdStrategyConfigFile(
            payload=payload,
            metadata={
                "remote_source": "prod_strategy_config.major_indices.cn_a.v1.json",
                "content_sha256": hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
            },
        )


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


defs = dg.Definitions(
    resources={
        "lake_root": LakeRootResource(),
        "duckdb": DuckDBResource(),
        "lake_meta_postgres": LakeMetaPostgresResource(),
        "prod_strategy_config_file": ProdStrategyConfigFileResource(),
        "tushare": TushareResource(token=dg.EnvVar("TUSHARE_TOKEN")),
    }
)
