from __future__ import annotations

from typing import Any

from src.foundation.dao.factory import DAOFactory


RAW_MULTI_DAO_NAME: dict[tuple[str, str], str] = {
    ("tushare", "stock_basic"): "raw_stock_basic",
    ("biying", "stock_basic"): "raw_biying_stock_basic",
}


class RawMultiWriter:
    def __init__(self, dao_factory: DAOFactory) -> None:
        self.dao_factory = dao_factory

    def bulk_upsert(self, source_key: str, dataset_key: str, rows: list[dict[str, Any]]) -> int:
        dao_name = RAW_MULTI_DAO_NAME.get((source_key, dataset_key))
        if dao_name is None:
            raise ValueError(f"Unsupported raw multi route: source={source_key}, dataset={dataset_key}")
        dao = getattr(self.dao_factory, dao_name)
        return dao.bulk_upsert(rows)
