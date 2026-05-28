from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dagster as dg
import duckdb
from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.notifications.feishu import FeishuWebhookResource
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
        "tushare": TushareResource(token=dg.EnvVar("TUSHARE_TOKEN")),
        "clickhouse": ClickhouseResource(
            host=dg.EnvVar("CLICKHOUSE_HOST"),
            port=dg.EnvVar.int("CLICKHOUSE_PORT"),
            user=dg.EnvVar("CLICKHOUSE_USER"),
            password=dg.EnvVar("CLICKHOUSE_PASSWORD"),
            database=dg.EnvVar("CLICKHOUSE_DATABASE"),
        ),
        "feishu": FeishuWebhookResource(),
    }
)
