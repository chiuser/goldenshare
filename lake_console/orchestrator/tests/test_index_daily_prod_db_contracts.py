import unittest

from orchestrator.defs.prod_db.index_daily import (
    PROD_INDEX_DAILY_DUCKDB_ATTACHED_DATABASE,
    PROD_INDEX_DAILY_DUCKDB_ATTACH_OPTIONS,
    PROD_INDEX_DAILY_FORBIDDEN_COLUMNS,
    PROD_INDEX_DAILY_SOURCE_COLUMNS,
    build_prod_index_daily_duckdb_source_sql,
    build_prod_index_daily_remote_query,
    index_code_set_hash,
    normalize_index_codes,
    validate_prod_index_daily_duckdb_attach_options_contract,
    validate_prod_index_daily_duckdb_source_contract,
    validate_prod_index_daily_select_contract,
)
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_INDEX_DAILY_SCHEMA


class IndexDailyProdDbContractTests(unittest.TestCase):
    def test_remote_query_uses_explicit_projection_and_filters(self) -> None:
        sql = build_prod_index_daily_remote_query(
            trade_date="2026-06-22",
            index_codes=("000001.SH", "399001.SZ"),
        )
        normalized_sql = " ".join(sql.lower().split())

        self.assertNotIn("select *", normalized_sql)
        for forbidden_column in PROD_INDEX_DAILY_FORBIDDEN_COLUMNS:
            self.assertNotIn(forbidden_column, normalized_sql)
        self.assertIn("from core_serving.index_daily_serving", normalized_sql)
        self.assertIn("where trade_date = date '2026-06-22'", normalized_sql)
        self.assertIn("ts_code = any(array['000001.sh', '399001.sz']::text[])", normalized_sql)
        self.assertIn("change_amount as change", normalized_sql)
        self.assertIn("to_char(trade_date, 'yyyymmdd') as trade_date", normalized_sql)
        self.assertIn("order by ts_code", normalized_sql)

    def test_duckdb_source_uses_attached_alias_without_conninfo(self) -> None:
        sql = build_prod_index_daily_duckdb_source_sql(
            trade_date="2026-06-22",
            index_codes=("000001.SH",),
        )
        normalized_sql = " ".join(sql.lower().split())

        self.assertIn("postgres_query(", normalized_sql)
        self.assertIn(PROD_INDEX_DAILY_DUCKDB_ATTACHED_DATABASE, sql)
        for forbidden_text in (
            "host=",
            "user=",
            "password=",
            "dbname=",
            "connect_timeout=",
        ):
            self.assertNotIn(forbidden_text, normalized_sql)

    def test_contract_validators_accept_current_sql(self) -> None:
        validate_prod_index_daily_select_contract()
        validate_prod_index_daily_duckdb_source_contract()
        validate_prod_index_daily_duckdb_attach_options_contract()
        self.assertIn("READ_ONLY", PROD_INDEX_DAILY_DUCKDB_ATTACH_OPTIONS)

    def test_source_columns_match_raw_schema(self) -> None:
        self.assertEqual(
            PROD_INDEX_DAILY_SOURCE_COLUMNS,
            tuple(column.name for column in RAW_INDEX_DAILY_SCHEMA),
        )

    def test_index_codes_must_be_non_empty_and_non_blank(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            normalize_index_codes(())
        with self.assertRaisesRegex(ValueError, "blank"):
            normalize_index_codes(("000001.SH", " "))

    def test_code_set_hash_is_stable_for_sorted_codes(self) -> None:
        self.assertEqual(
            index_code_set_hash(("399001.SZ", "000001.SH")),
            index_code_set_hash(("000001.SH", "399001.SZ")),
        )
