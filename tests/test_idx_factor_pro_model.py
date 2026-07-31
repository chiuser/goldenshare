from __future__ import annotations

import runpy
from pathlib import Path

from sqlalchemy import Float

from src.foundation.datasets.definitions.index_series import IDX_FACTOR_PRO_SOURCE_FIELDS, IDX_FACTOR_PRO_VALUE_FIELDS
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.raw.raw_idx_factor_pro import RawIdxFactorPro


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPO_ROOT / "alembic/versions/20260801_000120_add_idx_factor_pro_dataset.py"


def test_idx_factor_pro_source_fields_are_full_and_ordered() -> None:
    definition = get_dataset_definition("idx_factor_pro")

    assert definition.source.source_fields == IDX_FACTOR_PRO_SOURCE_FIELDS
    assert len(IDX_FACTOR_PRO_SOURCE_FIELDS) == 89
    assert IDX_FACTOR_PRO_SOURCE_FIELDS[:11] == (
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_change",
        "vol",
        "amount",
    )
    assert IDX_FACTOR_PRO_SOURCE_FIELDS[-4:] == ("xsii_td1_bfq", "xsii_td2_bfq", "xsii_td3_bfq", "xsii_td4_bfq")
    assert IDX_FACTOR_PRO_VALUE_FIELDS == IDX_FACTOR_PRO_SOURCE_FIELDS[2:]
    assert len(IDX_FACTOR_PRO_VALUE_FIELDS) == 87


def test_idx_factor_pro_raw_and_view_models_match_definition_contract() -> None:
    expected_fields = list(IDX_FACTOR_PRO_SOURCE_FIELDS)
    raw_columns = RawIdxFactorPro.__table__.columns
    view_columns = IndexFactorPro.__table__.columns

    assert [column.name for column in RawIdxFactorPro.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert {index.name for index in RawIdxFactorPro.__table__.indexes} == {"idx_raw_tushare_idx_factor_pro_trade_date"}
    assert [column.name for column in raw_columns if column.name in IDX_FACTOR_PRO_SOURCE_FIELDS] == expected_fields
    assert [column.name for column in view_columns if column.name in IDX_FACTOR_PRO_SOURCE_FIELDS] == expected_fields
    assert {"api_name", "fetched_at", "raw_payload"}.issubset(set(raw_columns.keys()))
    assert {"source", "created_at", "updated_at"}.issubset(set(view_columns.keys()))
    assert not IndexFactorPro.__table__.indexes
    assert all(isinstance(raw_columns[field].type, Float) for field in IDX_FACTOR_PRO_VALUE_FIELDS)
    assert all(isinstance(view_columns[field].type, Float) for field in IDX_FACTOR_PRO_VALUE_FIELDS)


def test_idx_factor_pro_migration_creates_only_raw_table_and_raw_backed_view() -> None:
    migration = runpy.run_path(str(MIGRATION_PATH))
    migration_text = MIGRATION_PATH.read_text(encoding="utf-8")

    assert migration["revision"] == "20260801_000120"
    assert migration["down_revision"] == "20260625_000119"
    assert ("ts_code", "trade_date", *migration["IDX_FACTOR_PRO_VALUE_COLUMNS"]) == IDX_FACTOR_PRO_SOURCE_FIELDS
    assert 'op.create_table(\n        "idx_factor_pro"' in migration_text
    assert "CREATE VIEW core_serving.index_factor_pro" in migration_text
    assert "FROM raw_tushare.idx_factor_pro" in migration_text
    assert "core_serving.index_factor_pro" not in migration_text.split("def downgrade", maxsplit=1)[0].replace("CREATE VIEW core_serving.index_factor_pro", "")
