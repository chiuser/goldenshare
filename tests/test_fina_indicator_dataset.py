from __future__ import annotations

from datetime import date
from decimal import Decimal
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy import Numeric

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.generic import GenericDAO
from src.foundation.datasets.fina_indicator_contracts import (
    FINA_INDICATOR_DECIMAL_FIELDS,
    FINA_INDICATOR_IDENTITY_FIELDS,
    FINA_INDICATOR_SOURCE_FIELDS,
)
from src.foundation.datasets.freshness_policies import EVENT_RUN_TRACE, get_freshness_policy
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionNormalizeError, IngestionValidationError, IngestionWriteError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import DatasetNormalizer, NormalizedBatch
from src.foundation.ingestion.observed_snapshot import compute_source_content_hash
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
import src.foundation.ingestion.source_client as source_client_module
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.all_models import RawFinaIndicator as ExportedRawFinaIndicator
from src.foundation.models.raw.raw_fina_indicator import RawFinaIndicator
from src.foundation.models.table_model_registry import get_model_by_table_name, table_model_registry
from src.ops.action_catalog import list_workflow_definitions
from src.ops.catalog.dataset_catalog_views import OPS_DATASET_DEFAULT_VIEW


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic/versions/20260829_000160_add_fina_indicator_dataset.py"


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.SZ",
        "ann_date": "20260829",
        "end_date": "20260630",
        **{field_name: "1.25" for field_name in FINA_INDICATOR_DECIMAL_FIELDS},
        "update_flag": "1",
    }
    row.update(overrides)
    return row


def _fetch_result(rows: list[dict[str, object]], *, unit_id: str = "fina_indicator") -> SourceFetchResult:
    return SourceFetchResult(
        unit_id=unit_id,
        request_count=1,
        retry_count=0,
        latency_ms=0,
        rows_raw=rows,
    )


def _unit(unit_date: date, *, unit_id: str = "fina_indicator") -> PlanUnitSnapshot:
    return PlanUnitSnapshot(
        unit_id=unit_id,
        dataset_key="fina_indicator",
        source_key="tushare",
        trade_date=unit_date,
        request_params={"ann_date": unit_date.strftime("%Y%m%d")},
        progress_context={"ann_date": unit_date.isoformat(), "date_field": "ann_date"},
        pagination_policy="offset_limit",
        page_limit=5_000,
    )


def _normalize(
    rows: list[dict[str, object]],
    *,
    unit_date: date = date(2026, 8, 29),
    unit_id: str = "fina_indicator",
) -> NormalizedBatch:
    return DatasetNormalizer().normalize(
        definition=get_dataset_definition("fina_indicator"),
        fetch_result=_fetch_result(rows, unit_id=unit_id),
        expected_unit_date=unit_date,
    )


def _resolver() -> DatasetActionResolver:
    class NoPoolSession:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"fina_indicator planner must not read an object pool: {name}")

    return DatasetActionResolver(NoPoolSession())


def test_fina_indicator_definition_freezes_full_source_storage_and_schedule_contract() -> None:
    definition = get_dataset_definition("fina_indicator")
    capability = definition.capabilities.actions[0]
    schedule_policy = capability.schedule_time_policy

    assert len(FINA_INDICATOR_SOURCE_FIELDS) == 167
    assert len(FINA_INDICATOR_DECIMAL_FIELDS) == 163
    assert FINA_INDICATOR_IDENTITY_FIELDS == ("ts_code", "ann_date", "end_date", "update_flag")
    assert definition.source.api_name == "fina_indicator_vip"
    assert definition.source.source_fields == FINA_INDICATOR_SOURCE_FIELDS
    assert definition.source.request_builder_key == "_fina_indicator_vip_params"
    assert definition.input_model.filters == ()
    assert definition.date_model.date_axis == "natural_day"
    assert definition.date_model.input_shape == "ann_date_or_start_end"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.date_model.audit_applicable is False
    assert definition.planning.universe_policy == "no_pool"
    assert definition.planning.page_limit == 5_000
    assert definition.planning.max_units_per_execution is None
    assert definition.planning.fetch_concurrency == 1
    assert definition.storage.raw_dao_name == "raw_fina_indicator"
    assert definition.storage.core_dao_name == "raw_fina_indicator"
    assert definition.storage.target_table == "raw_tushare.fina_indicator"
    assert definition.storage.serving_table == "core_serving.equity_fina_indicator"
    assert definition.storage.delivery_mode == "raw_with_serving_view"
    assert definition.storage.write_path == "raw_only_upsert"
    assert definition.storage.conflict_columns == FINA_INDICATOR_IDENTITY_FIELDS
    assert definition.quality.reject_policy == "fail_unit_on_any_rejection"
    assert definition.quality.batch_unique_key_fields == FINA_INDICATOR_IDENTITY_FIELDS
    assert capability.supported_time_modes == ("point", "range")
    assert schedule_policy is not None
    assert schedule_policy.policy == "since_last_success_day_range"
    assert schedule_policy.schedule_types == ("cron",)
    assert schedule_policy.cron_repeat_modes == ("daily", "weekly", "monthly")
    assert schedule_policy.explicit_time_input == "forbidden"
    assert get_freshness_policy("fina_indicator") == EVENT_RUN_TRACE


def test_fina_indicator_point_range_weekends_and_long_ranges_use_natural_day_units_only() -> None:
    point = _resolver().build_plan(
        DatasetActionRequest(
            dataset_key="fina_indicator",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", ann_date=date(2026, 8, 29)),
        )
    )
    weekend_range = _resolver().build_plan(
        DatasetActionRequest(
            dataset_key="fina_indicator",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range",
                start_date=date(2026, 8, 29),
                end_date=date(2026, 8, 31),
            ),
        )
    )
    long_range = _resolver().build_plan(
        DatasetActionRequest(
            dataset_key="fina_indicator",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range",
                start_date=date(2025, 1, 1),
                end_date=date(2026, 1, 2),
            ),
        )
    )

    assert point.units[0].request_params == {"ann_date": "20260829"}
    assert [unit.request_params for unit in weekend_range.units] == [
        {"ann_date": "20260829"},
        {"ann_date": "20260830"},
        {"ann_date": "20260831"},
    ]
    assert len(long_range.units) == 367
    assert all(set(unit.request_params) == {"ann_date"} for unit in long_range.units)


@pytest.mark.parametrize(
    "filters",
    (
        {"ts_code": "000001.SZ"},
        {"period": "20260630"},
        {"update_flag": "1"},
        {"limit": 100},
        {"offset": 0},
    ),
)
def test_fina_indicator_rejects_source_and_pagination_filters_from_ops(filters: dict[str, object]) -> None:
    with pytest.raises(IngestionValidationError) as exc_info:
        _resolver().build_plan(
            DatasetActionRequest(
                dataset_key="fina_indicator",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", ann_date=date(2026, 8, 29)),
                filters=filters,
            )
        )
    assert exc_info.value.structured_error.error_code == "unknown_params"


def test_fina_indicator_source_client_repeats_all_fields_until_short_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fina_indicator")
    calls: list[tuple[str, dict, tuple[str, ...]]] = []
    total_rows = 5_001

    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            calls.append((api_name, dict(params), fields))
            offset = int(params["offset"])
            limit = int(params["limit"])
            return [
                _row(ts_code=f"{offset + index:06d}.SZ")
                for index in range(max(min(limit, total_rows - offset), 0))
            ]

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _source_key: Connector())
    result = DatasetSourceClient().fetch(definition=definition, unit=_unit(date(2026, 8, 29)))

    assert [params["offset"] for _api_name, params, _fields in calls] == [0, 5_000]
    assert all(api_name == "fina_indicator_vip" for api_name, _params, _fields in calls)
    assert [params for _api_name, params, _fields in calls] == [
        {"ann_date": "20260829", "limit": 5_000, "offset": 0},
        {"ann_date": "20260829", "limit": 5_000, "offset": 5_000},
    ]
    assert all(fields == FINA_INDICATOR_SOURCE_FIELDS for _api_name, _params, fields in calls)
    assert len(result.rows_raw) == total_rows
    assert result.pagination_diagnostics["observed_short_page"] is True


def test_fina_indicator_source_client_never_returns_partial_pages(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[int] = []

    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            assert api_name == "fina_indicator_vip"
            assert fields == FINA_INDICATOR_SOURCE_FIELDS
            offset = int(params["offset"])
            calls.append(offset)
            if offset == 5_000:
                raise RuntimeError("source page failed")
            return [_row(ts_code=f"{index:06d}.SZ") for index in range(5_000)]

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _source_key: Connector())
    with pytest.raises(RuntimeError, match="source page failed"):
        DatasetSourceClient().fetch(
            definition=get_dataset_definition("fina_indicator"),
            unit=_unit(date(2026, 8, 29)),
        )
    assert calls == [0, 5_000]


def test_fina_indicator_empty_announcement_day_is_a_valid_empty_batch(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            assert api_name == "fina_indicator_vip"
            assert params == {"ann_date": "20000101", "limit": 5_000, "offset": 0}
            assert fields == FINA_INDICATOR_SOURCE_FIELDS
            return []

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _source_key: Connector())
    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition("fina_indicator"),
        unit=_unit(date(2000, 1, 1)),
    )
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("fina_indicator"),
        fetch_result=result,
        expected_unit_date=date(2000, 1, 1),
    )

    assert result.rows_raw == []
    assert batch.rows_normalized == []
    assert batch.rows_rejected == 0


def test_fina_indicator_normalizer_preserves_all_fields_hashes_and_update_flag_variants() -> None:
    batch = _normalize(
        [
            _row(ts_code="\x00 000001.sz ", update_flag="\x00 0 "),
            _row(update_flag="1"),
        ]
    )

    assert len(batch.rows_normalized) == 2
    first = batch.rows_normalized[0]
    assert first["ts_code"] == "000001.SZ"
    assert first["update_flag"] == "0"
    assert all(isinstance(first[field_name], Decimal) for field_name in FINA_INDICATOR_DECIMAL_FIELDS)
    assert first["source_content_hash"] == compute_source_content_hash(
        row=first,
        source_fields=FINA_INDICATOR_SOURCE_FIELDS,
    )
    assert {row["update_flag"] for row in batch.rows_normalized} == {"0", "1"}


def test_fina_indicator_normalizer_deduplicates_exact_rows_and_fails_on_identity_conflict() -> None:
    exact = _normalize([_row(), _row()])
    assert len(exact.rows_normalized) == 1
    assert exact.rows_deduplicated == 1

    with pytest.raises(IngestionNormalizeError) as conflict:
        _normalize([_row(), _row(eps="9.99")])
    assert conflict.value.structured_error.error_code == "normalize.batch_unique_key_conflicting"

    missing = _row()
    missing.pop("rd_exp")
    with pytest.raises(IngestionNormalizeError) as missing_field:
        _normalize([missing])
    assert missing_field.value.structured_error.error_code == "normalize.source_content_hash_invalid"

    with pytest.raises(IngestionNormalizeError) as mismatch:
        _normalize([_row(ann_date="20260830")])
    assert mismatch.value.structured_error.error_code == "normalize.unit_date_mismatch"


class _StubRawDao:
    model = RawFinaIndicator

    def __init__(self) -> None:
        self.bulk_upsert_calls: list[tuple[list[dict], list[str] | None]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls.append((rows, list(conflict_columns or []) or None))
        return len(rows)


def test_fina_indicator_writer_only_upserts_raw_and_rejects_partial_units(mocker) -> None:
    raw_dao = _StubRawDao()
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(raw_fina_indicator=raw_dao),
    )
    writer = DatasetWriter(session=mocker.Mock())
    definition = get_dataset_definition("fina_indicator")
    normalized = _normalize([_row(update_flag="0"), _row(update_flag="1")])

    result = writer.write(definition=definition, batch=normalized, plan_unit=_unit(date(2026, 8, 29)))

    assert raw_dao.bulk_upsert_calls == [
        (normalized.rows_normalized, list(FINA_INDICATOR_IDENTITY_FIELDS))
    ]
    assert result.target_table == "raw_tushare.fina_indicator"
    assert result.rows_written == 2

    rejected = NormalizedBatch(
        unit_id="rejected",
        rows_normalized=normalized.rows_normalized,
        rows_rejected=1,
        rejected_reasons={"normalize.invalid_decimal:eps": 1},
    )
    with pytest.raises(IngestionWriteError) as exc_info:
        writer.write(definition=definition, batch=rejected, plan_unit=_unit(date(2026, 8, 29)))
    assert exc_info.value.structured_error.error_code == "write.unit_rows_rejected"
    assert len(raw_dao.bulk_upsert_calls) == 1


def test_fina_indicator_wide_unit_uses_bind_safe_batches() -> None:
    base_row = {
        "ts_code": "000001.SZ",
        "ann_date": date(2026, 8, 29),
        "end_date": date(2026, 6, 30),
        **{field_name: Decimal("1.25") for field_name in FINA_INDICATOR_DECIMAL_FIELDS},
        "update_flag": "1",
        "source_content_hash": "a" * 64,
        "api_name": "fina_indicator_vip",
        "fetched_at": None,
    }
    rows = [{**base_row, "ts_code": f"{index:06d}.SZ"} for index in range(5_000)]

    assert len(rows[0]) == 170
    assert BaseDAO._compute_batch_size(configured_batch_size=10_000, row_param_count=170) == 385
    class BatchSession:
        def __init__(self) -> None:
            self.statements: list[object] = []

        def execute(self, statement):  # type: ignore[no-untyped-def]
            self.statements.append(statement)
            return SimpleNamespace(rowcount=0)

    session = BatchSession()
    dao = GenericDAO(session, RawFinaIndicator)
    dao.settings = SimpleNamespace(sync_batch_size=10_000)
    assert dao._resolve_batch_size(rows) == 385
    assert dao.bulk_upsert(rows, conflict_columns=list(FINA_INDICATOR_IDENTITY_FIELDS)) == 5_000
    assert len(session.statements) == 13


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fina_indicator_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fina_indicator_model_dao_registry_catalog_workflow_and_migration_contracts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fina_indicator")
    table_model_registry.cache_clear()
    assert ExportedRawFinaIndicator is RawFinaIndicator
    assert get_model_by_table_name("raw_tushare.fina_indicator") is RawFinaIndicator
    assert set(RawFinaIndicator.__table__.columns.keys()) == {
        *FINA_INDICATOR_SOURCE_FIELDS,
        "source_content_hash",
        "api_name",
        "fetched_at",
    }
    assert list(RawFinaIndicator.__table__.primary_key.columns.keys()) == list(FINA_INDICATOR_IDENTITY_FIELDS)
    assert all(
        isinstance(RawFinaIndicator.__table__.columns[field_name].type, Numeric)
        and RawFinaIndicator.__table__.columns[field_name].type.precision is None
        and RawFinaIndicator.__table__.columns[field_name].type.scale is None
        for field_name in FINA_INDICATOR_DECIMAL_FIELDS
    )
    factory = DAOFactory(SimpleNamespace())
    assert isinstance(factory.raw_fina_indicator, GenericDAO)
    assert factory.raw_fina_indicator.model is RawFinaIndicator

    group = next(group for group in OPS_DATASET_DEFAULT_VIEW.groups if group.group_key == "equity_financial")
    item = next(item for item in OPS_DATASET_DEFAULT_VIEW.items if item.dataset_key == "fina_indicator")
    assert (group.group_label, group.group_order) == ("A股财务数据", 3)
    assert (item.group_key, item.item_order) == ("equity_financial", 20)
    assert all(
        all(step.dataset_key != "fina_indicator" for step in workflow.steps)
        for workflow in list_workflow_definitions()
    )
    assert definition.date_model.audit_applicable is False

    migration = _load_migration()
    assert migration.revision == "20260829_000160"
    assert migration.down_revision == "20260829_000159"
    assert migration._DECIMAL_FIELDS == FINA_INDICATOR_DECIMAL_FIELDS
    assert migration._VIEW_COLUMNS == (
        *FINA_INDICATOR_SOURCE_FIELDS,
        "source_content_hash",
        "api_name",
        "fetched_at",
    )
    migration_text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert migration_text.index("_assert_hdd_tablespace()") < migration_text.index(
        'op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")'
    )
    assert 'postgresql_tablespace=_TABLESPACE' in migration_text
    assert "ALTER INDEX raw_tushare.pk_raw_tushare_fina_indicator" in migration_text
    assert migration_text.count("TABLESPACE gs_raw_cold_hdd") >= 3
    assert "SELECT *" not in migration_text
    assert "op.drop_table" not in migration_text

    class MissingTablespaceResult:
        @staticmethod
        def scalar() -> None:
            return None

    class MissingTablespaceBind:
        dialect = SimpleNamespace(name="postgresql")

        @staticmethod
        def execute(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            return MissingTablespaceResult()

    relation_calls: list[str] = []
    monkeypatch.setattr(migration.op, "get_bind", lambda: MissingTablespaceBind())
    monkeypatch.setattr(migration.op, "execute", lambda *_args, **_kwargs: relation_calls.append("execute"))
    monkeypatch.setattr(migration.op, "create_table", lambda *_args, **_kwargs: relation_calls.append("table"))
    with pytest.raises(RuntimeError, match="禁止回退到默认 SSD"):
        migration.upgrade()
    assert relation_calls == []
    with pytest.raises(RuntimeError, match="不支持自动 downgrade"):
        migration.downgrade()


def test_fina_indicator_source_document_records_measured_update_flag_difference() -> None:
    source_doc = (
        ROOT / "docs/sources/tushare/股票数据/财务数据/0079_财务指标数据.md"
    ).read_text(encoding="utf-8")
    output_table = source_doc.split("## 输出参数", 1)[1].split("## 接口用法", 1)[0]
    documented_fields = tuple(
        columns[1].strip()
        for line in output_table.splitlines()
        if line.startswith("|")
        and (columns := line.split("|"))[1].strip() not in {"名称", "---"}
    )
    assert documented_fields == FINA_INDICATOR_SOURCE_FIELDS
    assert "fina_indicator_vip` 接受 `update_flag`" in source_doc
    assert "不代表运营维护入口必须开放此参数" in source_doc
