from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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


defs = dg.Definitions(
    resources={
        "lake_root": LakeRootResource(),
        "duckdb": DuckDBResource(),
    }
)
