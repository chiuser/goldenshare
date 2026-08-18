from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.datasets.definitions import BOARD_HOTSPOT_ROWS
from src.foundation.datasets.definitions._builder import build_definition
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import (
    DatasetActionRequest,
    DatasetActionResolver,
    DatasetTimeInput,
)
from src.foundation.ingestion.errors import (
    IngestionNormalizeError,
    IngestionSourceError,
    IngestionValidationError,
    IngestionWriteError,
)
from src.foundation.ingestion.execution_plan import ValidatedDatasetActionRequest
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.pre_write_validators import (
    PreWriteValidationError,
    get_pre_write_validator,
)
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
from src.foundation.models.core_serving.sw_industry_classification import (
    SwIndustryClassification,
)
from src.foundation.models.core_serving.sw_industry_member import SwIndustryMember
from src.ops.dataset_definition_projection import get_dataset_freshness_projection
from src.ops.queries.manual_action_query_service import ManualActionQueryService
from src.ops.services.schedule_automation_capability_resolver import (
    ScheduleAutomationCapabilityResolver,
)


SOURCE_FIELDS = (
    "l1_code",
    "l1_name",
    "l2_code",
    "l2_name",
    "l3_code",
    "l3_name",
    "ts_code",
    "name",
    "in_date",
    "out_date",
    "is_new",
)


def _definition_row() -> dict:
    return deepcopy(
        next(
            row
            for row in BOARD_HOTSPOT_ROWS
            if row["identity"]["dataset_key"] == "index_member_all"
        )
    )


def _plan():  # type: ignore[no-untyped-def]
    return DatasetActionResolver(None).build_plan(
        DatasetActionRequest(
            dataset_key="index_member_all",
            action="maintain",
            time_input=DatasetTimeInput(mode="none"),
        )
    )


def _validated_request(plan) -> ValidatedDatasetActionRequest:  # type: ignore[no-untyped-def]
    return ValidatedDatasetActionRequest(
        request_id=plan.plan_id,
        dataset_key=plan.dataset_key,
        action=plan.action,
        run_profile=plan.run_profile,
        trigger_source="test",
        params=dict(plan.filters),
        source_key=plan.source.source_key,
    )


def _member_row(
    ts_code: str,
    *,
    is_new: str,
    in_date: str,
    out_date: str | None = None,
) -> dict:
    return {
        "l1_code": "801040.SI",
        "l1_name": "钢铁",
        "l2_code": "801045.SI",
        "l2_name": "特钢Ⅱ",
        "l3_code": "850412.SI",
        "l3_name": "特钢Ⅲ",
        "ts_code": ts_code,
        "name": f"股票{ts_code[:6]}",
        "in_date": in_date,
        "out_date": out_date,
        "is_new": is_new,
    }


def _member_source_rows() -> list[dict]:
    return [
        _member_row("000001.SZ", is_new="Y", in_date="20210101"),
        _member_row("000002.SZ", is_new="Y", in_date="20210102"),
        _member_row(
            "000003.SZ",
            is_new="N",
            in_date="20210103",
            out_date="20260815",
        ),
    ]


def _classification_rows(version: str = "SW2021") -> list[SwIndustryClassification]:
    suffix = "" if version == "SW2021" else "-legacy"
    return [
        SwIndustryClassification(
            src=version,
            industry_code="230000",
            source_index_code="801040.SI",
            index_code="801040.SI",
            industry_name=f"钢铁{suffix}",
            source_parent_code=None,
            parent_code=None,
            level="L1",
            is_pub=True,
            source="tushare",
            normalization_rule_version="sw2021-index-code-v1",
        ),
        SwIndustryClassification(
            src=version,
            industry_code="230500",
            source_index_code="801045.SI",
            index_code="801045.SI",
            industry_name=f"特钢Ⅱ{suffix}",
            source_parent_code="230000",
            parent_code="230000",
            level="L2",
            is_pub=True,
            source="tushare",
            normalization_rule_version="sw2021-index-code-v1",
        ),
        SwIndustryClassification(
            src=version,
            industry_code="230501",
            source_index_code="850401.SI",
            index_code="850412.SI",
            industry_name=f"特钢Ⅲ{suffix}",
            source_parent_code="230500",
            parent_code="230500",
            level="L3",
            is_pub=True,
            source="tushare",
            normalization_rule_version="sw2021-index-code-v1",
        ),
        SwIndustryClassification(
            src=version,
            industry_code="270000",
            source_index_code="801120.SI",
            index_code="801120.SI",
            industry_name=f"食品饮料{suffix}",
            source_parent_code=None,
            parent_code=None,
            level="L1",
            is_pub=True,
            source="tushare",
            normalization_rule_version="sw2021-index-code-v1",
        ),
        SwIndustryClassification(
            src=version,
            industry_code="270100",
            source_index_code="801121.SI",
            index_code="801121.SI",
            industry_name=f"食品加工{suffix}",
            source_parent_code="270000",
            parent_code="270000",
            level="L2",
            is_pub=True,
            source="tushare",
            normalization_rule_version="sw2021-index-code-v1",
        ),
    ]


@pytest.fixture()
def member_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        SwIndustryClassification.__table__.create(connection)
        SwIndustryMember.__table__.create(connection)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _BaselineMemberConnector:
    totals = {"Y": 5895, "N": 2004}

    def __init__(self, *, empty_variant: str | None = None, mismatch_n: bool = False) -> None:
        self.empty_variant = empty_variant
        self.mismatch_n = mismatch_n
        self.calls: list[dict] = []

    def call(
        self, *, api_name: str, params: dict, fields: tuple[str, ...]
    ) -> list[dict]:
        assert api_name == "index_member_all"
        assert fields == SOURCE_FIELDS
        assert set(params) == {"is_new", "offset", "limit"}
        assert params["limit"] == 2000
        self.calls.append(dict(params))
        variant = str(params["is_new"])
        if variant == self.empty_variant:
            return []
        total = self.totals[variant]
        offset = int(params["offset"])
        page_size = max(min(int(params["limit"]), total - offset), 0)
        returned_variant = "Y" if variant == "N" and self.mismatch_n else variant
        return [
            {"is_new": returned_variant, "ordinal": offset + index}
            for index in range(page_size)
        ]


class _MemberConnector:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = deepcopy(rows)
        self.calls: list[dict] = []

    def call(
        self, *, api_name: str, params: dict, fields: tuple[str, ...]
    ) -> list[dict]:
        assert api_name == "index_member_all"
        assert fields == SOURCE_FIELDS
        assert set(params) == {"is_new", "offset", "limit"}
        self.calls.append(dict(params))
        rows = [row for row in self.rows if row["is_new"] == params["is_new"]]
        offset = int(params["offset"])
        return deepcopy(rows[offset : offset + int(params["limit"])])


class _CountedMemberConnector:
    def __init__(self, totals: dict[str, int]) -> None:
        self.totals = dict(totals)
        self.calls: list[dict] = []

    def call(
        self, *, api_name: str, params: dict, fields: tuple[str, ...]
    ) -> list[dict]:
        assert api_name == "index_member_all"
        assert fields == SOURCE_FIELDS
        assert set(params) == {"is_new", "offset", "limit"}
        self.calls.append(dict(params))
        variant = str(params["is_new"])
        offset = int(params["offset"])
        page_limit = int(params["limit"])
        page_end = min(offset + page_limit, self.totals[variant])
        return [
            {"is_new": variant, "ordinal": index}
            for index in range(offset, page_end)
        ]


def test_index_member_all_plan_freezes_one_y_n_snapshot_unit() -> None:
    definition = get_dataset_definition("index_member_all")
    plan = _plan()

    assert definition.source.source_fields == SOURCE_FIELDS
    assert definition.input_model.time_fields == ()
    assert definition.input_model.filters == ()
    assert definition.planning.request_variant_fields == ("is_new",)
    assert definition.planning.request_variant_defaults == {"is_new": ("Y", "N")}
    assert definition.planning.page_limit == 2000
    assert definition.planning.max_source_rows_per_unit == 20000
    assert definition.planning.max_units_per_execution == 1
    assert definition.storage.raw_table is None
    assert definition.storage.raw_dao_name is None
    assert definition.storage.write_path == "serving_direct_scope_replace"
    assert definition.storage.replacement_scope_fields == (
        "classification_version",
    )
    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.filters == {}
    assert len(plan.units) == 1
    assert plan.units[0].request_params == {}
    assert plan.planning.max_source_rows_per_unit == 20000
    assert plan.units[0].max_source_rows_per_unit == 20000
    assert plan.units[0].request_variants == ({"is_new": "Y"}, {"is_new": "N"})

    duplicate_variant_row = _definition_row()
    duplicate_variant_row["planning"]["request_variant_defaults"] = {
        "is_new": ("Y", "Y")
    }
    with pytest.raises(ValueError, match="不得重复"):
        build_definition(duplicate_variant_row)

    for time_input, filters in (
        (DatasetTimeInput(mode="none"), {"is_new": "Y"}),
        (DatasetTimeInput(mode="none"), {"l3_code": "850412.SI"}),
        (DatasetTimeInput(mode="none"), {"ts_code": "000001.SZ"}),
        (DatasetTimeInput(mode="point", trade_date=date(2026, 8, 18)), {}),
        (
            DatasetTimeInput(
                mode="range",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 18),
            ),
            {},
        ),
    ):
        with pytest.raises(IngestionValidationError):
            DatasetActionResolver(None).build_plan(
                DatasetActionRequest(
                    dataset_key="index_member_all",
                    action="maintain",
                    time_input=time_input,
                    filters=filters,
                )
            )


def test_index_member_all_source_fans_in_five_pages_and_fails_closed(mocker) -> None:
    definition = get_dataset_definition("index_member_all")
    unit = _plan().units[0]
    connector = _BaselineMemberConnector()
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=connector,
    )

    result = DatasetSourceClient().fetch(definition=definition, unit=unit)

    assert [(call["is_new"], call["offset"]) for call in connector.calls] == [
        ("Y", 0),
        ("Y", 2000),
        ("Y", 4000),
        ("N", 0),
        ("N", 2000),
    ]
    assert len(result.rows_raw) == 7899
    assert result.request_count == 5
    assert result.pagination_diagnostics == {
        "policy": "offset_limit",
        "page_limit": 2000,
        "page_count": 5,
        "total_rows_merged": 7899,
        "terminal_offset": 2000,
        "terminal_page_rows": 4,
        "observed_short_page": True,
        "request_variants": [
            {
                "variant": {"is_new": "Y"},
                "page_count": 3,
                "total_rows": 5895,
                "terminal_offset": 4000,
                "terminal_page_rows": 1895,
            },
            {
                "variant": {"is_new": "N"},
                "page_count": 2,
                "total_rows": 2004,
                "terminal_offset": 2000,
                "terminal_page_rows": 4,
            },
        ],
    }

    for connector, expected_code in (
        (_BaselineMemberConnector(empty_variant="N"), "source_variant_empty"),
        (_BaselineMemberConnector(mismatch_n=True), "source_variant_mismatch"),
    ):
        mocker.patch(
            "src.foundation.ingestion.source_client.create_source_connector",
            return_value=connector,
        )
        with pytest.raises(IngestionSourceError) as exc_info:
            DatasetSourceClient().fetch(definition=definition, unit=unit)
        assert exc_info.value.structured_error.error_code == expected_code


def test_index_member_all_source_row_limit_accepts_boundary_and_fails_closed(
    member_session: Session,
    mocker,
) -> None:
    definition = get_dataset_definition("index_member_all")
    unit = _plan().units[0]

    boundary_connector = _CountedMemberConnector({"Y": 10000, "N": 10000})
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=boundary_connector,
    )
    boundary = DatasetSourceClient().fetch(definition=definition, unit=unit)

    assert len(boundary.rows_raw) == 20000
    assert boundary.request_count == 12
    assert boundary.pagination_diagnostics["observed_short_page"] is True

    oversized_connector = _CountedMemberConnector({"Y": 10001, "N": 10000})
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=oversized_connector,
    )
    with pytest.raises(IngestionSourceError) as exc_info:
        DatasetSourceClient().fetch(definition=definition, unit=unit)

    assert exc_info.value.structured_error.error_code == "source_rows_exceeded"
    assert exc_info.value.structured_error.details == {
        "max_source_rows_per_unit": 20000,
        "rows_before_page": 18001,
        "page_rows": 2000,
        "observed_rows": 20001,
        "page_number": 5,
        "offset": 8000,
        "request_variant": {"is_new": "N"},
    }

    executor = IngestionExecutor(member_session)
    normalize_spy = mocker.spy(executor.normalizer, "normalize")
    with pytest.raises(IngestionSourceError):
        executor.run(
            request=_validated_request(_plan()),
            definition=definition,
            units=(unit,),
        )
    normalize_spy.assert_not_called()
    assert member_session.scalar(select(func.count()).select_from(SwIndustryMember)) == 0


def test_index_member_all_normalization_preserves_dates_codes_and_identity() -> None:
    definition = get_dataset_definition("index_member_all")
    rows = _member_source_rows()
    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="member-normalize",
            request_count=2,
            retry_count=0,
            latency_ms=1,
            rows_raw=rows,
        ),
    )

    assert len(batch.rows_normalized) == 3
    assert batch.rows_rejected == 0
    assert batch.rows_deduplicated == 0
    assert Counter(row["is_new"] for row in batch.rows_normalized) == {
        True: 2,
        False: 1,
    }
    assert all(isinstance(row["in_date"], date) for row in batch.rows_normalized)
    assert next(row for row in batch.rows_normalized if not row["is_new"])[
        "out_date"
    ] == date(2026, 8, 15)
    assert all(row["source_l3_code"] == "850412.SI" for row in batch.rows_normalized)
    assert all(row["l3_code"] == "850412.SI" for row in batch.rows_normalized)

    alias_row = _member_row("000004.SZ", is_new="Y", in_date="20210104")
    alias_row["l3_code"] = "850401.SI"
    alias_batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="member-alias",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[alias_row],
        ),
    )
    assert alias_batch.rows_normalized[0]["source_l3_code"] == "850401.SI"
    assert alias_batch.rows_normalized[0]["l3_code"] == "850412.SI"

    typo_row = deepcopy(alias_row)
    typo_row["l3_code"] = "840401.SI"
    typo_batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="member-typo",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[typo_row],
        ),
    )
    assert typo_batch.rows_rejected == 1
    assert typo_batch.rejected_reasons == {"normalize.sw_industry_code_invalid": 1}

    missing_date_row = deepcopy(rows[0])
    missing_date_row["in_date"] = None
    missing_date_batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="member-missing-date",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[missing_date_row],
        ),
    )
    assert missing_date_batch.rows_rejected == 1

    conflict_rows = [deepcopy(rows[0]), deepcopy(rows[0])]
    conflict_rows[1]["name"] = "冲突名称"
    with pytest.raises(IngestionNormalizeError) as conflict_error:
        DatasetNormalizer().normalize(
            definition=definition,
            fetch_result=SourceFetchResult(
                unit_id="member-conflict",
                request_count=1,
                retry_count=0,
                latency_ms=1,
                rows_raw=conflict_rows,
            ),
        )
    assert (
        conflict_error.value.structured_error.error_code
        == "normalize.batch_unique_key_conflicting"
    )

    identical_batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="member-identical",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[deepcopy(rows[0]), deepcopy(rows[0])],
        ),
    )
    assert len(identical_batch.rows_normalized) == 1
    assert identical_batch.rows_deduplicated == 1


def test_index_member_all_prewrite_enforces_version_dates_and_three_level_closure(
    member_session: Session,
) -> None:
    member_session.add_all(_classification_rows())
    member_session.commit()
    definition = get_dataset_definition("index_member_all")
    normalized = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="member-prewrite",
            request_count=2,
            retry_count=0,
            latency_ms=1,
            rows_raw=_member_source_rows(),
        ),
    ).rows_normalized
    validator = get_pre_write_validator("sw2021_member_snapshot")

    validator(member_session, normalized, definition, _plan().units[0])

    cases = []
    wrong_version = deepcopy(normalized)
    wrong_version[0]["classification_version"] = "SW2014"
    cases.append((wrong_version, "只能引用 SW2021"))
    unknown_code = deepcopy(normalized)
    unknown_code[0]["l1_code"] = "809999.SI"
    cases.append((unknown_code, "代码、层级或名称不匹配"))
    wrong_name = deepcopy(normalized)
    wrong_name[0]["l3_name"] = "错误名称"
    cases.append((wrong_name, "代码、层级或名称不匹配"))
    wrong_l1_parent = deepcopy(normalized)
    wrong_l1_parent[0]["l1_code"] = "801120.SI"
    wrong_l1_parent[0]["l1_name"] = "食品饮料"
    cases.append((wrong_l1_parent, "L1/L2 父子关系不匹配"))
    wrong_l2_parent = deepcopy(normalized)
    wrong_l2_parent[0]["l1_code"] = "801120.SI"
    wrong_l2_parent[0]["l1_name"] = "食品饮料"
    wrong_l2_parent[0]["l2_code"] = "801121.SI"
    wrong_l2_parent[0]["l2_name"] = "食品加工"
    cases.append((wrong_l2_parent, "L2/L3 父子关系不匹配"))
    invalid_dates = deepcopy(normalized)
    invalid_dates[0]["out_date"] = date(2020, 12, 31)
    cases.append((invalid_dates, "纳入/剔除日期非法"))

    for rows, message in cases:
        with pytest.raises(PreWriteValidationError, match=message):
            validator(member_session, rows, definition, _plan().units[0])

    member_session.execute(
        SwIndustryClassification.__table__.delete().where(
            SwIndustryClassification.src == "SW2021"
        )
    )
    member_session.commit()
    with pytest.raises(PreWriteValidationError, match="分类尚未发布"):
        validator(member_session, normalized, definition, _plan().units[0])


def test_index_member_all_executor_is_atomic_idempotent_and_removes_ghost_members(
    member_session: Session,
    mocker,
) -> None:
    member_session.add_all(_classification_rows())
    member_session.add_all(_classification_rows("SW2014"))
    member_session.add(
        SwIndustryMember(
            l3_code="850412.SI",
            ts_code="600000.SH",
            in_date=date(2014, 1, 1),
            source_l1_code="801040.SI",
            l1_code="801040.SI",
            l1_name="钢铁-legacy",
            source_l2_code="801045.SI",
            l2_code="801045.SI",
            l2_name="特钢Ⅱ-legacy",
            source_l3_code="850412.SI",
            l3_name="特钢Ⅲ-legacy",
            stock_name="历史版本保留样本",
            out_date=None,
            is_new=True,
            classification_version="SW2014",
            source="test",
            normalization_rule_version="legacy",
        )
    )
    member_session.commit()

    definition = get_dataset_definition("index_member_all")
    plan = _plan()
    connector = _MemberConnector(_member_source_rows())
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=connector,
    )

    first = IngestionExecutor(member_session).run(
        request=_validated_request(plan),
        definition=definition,
        units=plan.units,
    )
    assert first.rows_fetched == 3
    assert first.rows_written == first.rows_committed == 3
    assert first.rows_rejected == 0
    assert first.unit_done == 1
    assert (
        member_session.scalar(
            select(func.count())
            .select_from(SwIndustryMember)
            .where(SwIndustryMember.classification_version == "SW2021")
        )
        == 3
    )

    replay = IngestionExecutor(member_session).run(
        request=_validated_request(plan),
        definition=definition,
        units=plan.units,
    )
    assert replay.rows_written == replay.rows_committed == 3
    assert (
        replay.ingestion_diagnostics["persistence"]["immutable_fact"][
            "scope_existing_count"
        ]
        == 3
    )

    transitioned_rows = _member_source_rows()
    transitioned_rows[0]["is_new"] = "N"
    transitioned_rows[0]["out_date"] = "20260818"
    connector.rows = transitioned_rows
    transitioned = IngestionExecutor(member_session).run(
        request=_validated_request(plan),
        definition=definition,
        units=plan.units,
    )
    assert transitioned.rows_written == transitioned.rows_committed == 3
    transitioned_row = member_session.scalar(
        select(SwIndustryMember).where(
            SwIndustryMember.l3_code == "850412.SI",
            SwIndustryMember.ts_code == "000001.SZ",
            SwIndustryMember.in_date == date(2021, 1, 1),
        )
    )
    assert transitioned_row is not None
    assert transitioned_row.is_new is False
    assert transitioned_row.out_date == date(2026, 8, 18)

    removed_row = transitioned_rows[-1]
    connector.rows = transitioned_rows[:-1]
    shrunk = IngestionExecutor(member_session).run(
        request=_validated_request(plan),
        definition=definition,
        units=plan.units,
    )
    assert shrunk.rows_written == shrunk.rows_committed == 2
    assert (
        member_session.scalar(
            select(SwIndustryMember).where(
                SwIndustryMember.l3_code == removed_row["l3_code"],
                SwIndustryMember.ts_code == removed_row["ts_code"],
                SwIndustryMember.in_date
                == date.fromisoformat(
                    f"{removed_row['in_date'][:4]}-{removed_row['in_date'][4:6]}-{removed_row['in_date'][6:]}"
                ),
            )
        )
        is None
    )
    assert (
        member_session.scalar(
            select(func.count())
            .select_from(SwIndustryMember)
            .where(SwIndustryMember.classification_version == "SW2014")
        )
        == 1
    )

    connector.rows = [row for row in transitioned_rows[:-1] if row["is_new"] == "Y"]
    with pytest.raises(IngestionSourceError) as empty_variant_error:
        IngestionExecutor(member_session).run(
            request=_validated_request(plan),
            definition=definition,
            units=plan.units,
        )
    assert (
        empty_variant_error.value.structured_error.error_code
        == "source_variant_empty"
    )
    assert (
        member_session.scalar(
            select(func.count())
            .select_from(SwIndustryMember)
            .where(SwIndustryMember.classification_version == "SW2021")
        )
        == 2
    )

    closure_failure_rows = deepcopy(transitioned_rows[:-1])
    closure_failure_rows[0]["l2_name"] = "错误二级行业"
    connector.rows = closure_failure_rows
    with pytest.raises(IngestionWriteError) as closure_error:
        IngestionExecutor(member_session).run(
            request=_validated_request(plan),
            definition=definition,
            units=plan.units,
        )
    assert (
        closure_error.value.structured_error.error_code
        == "write.scope_preflight_failed"
    )
    assert (
        member_session.scalar(
            select(func.count())
            .select_from(SwIndustryMember)
            .where(SwIndustryMember.classification_version == "SW2021")
        )
        == 2
    )


def test_index_member_all_ops_projection_is_snapshot_only() -> None:
    route = ManualActionQueryService().get_action_route("index_member_all.maintain")
    assert route is not None
    assert route.group_key == "board_theme"
    assert route.action_order == 90
    assert route.filters == ()
    assert route.time_form.default_mode == "none"
    assert [mode.mode for mode in route.time_form.modes] == ["none"]

    projection = get_dataset_freshness_projection("index_member_all")
    assert projection is not None
    assert projection.target_table == "core_serving.sw_industry_member"
    assert projection.raw_table is None
    assert projection.freshness_policy == "snapshot_run_trace"
    assert projection.observed_date_column is None
    assert projection.primary_action_key == "index_member_all.maintain"

    definition = get_dataset_definition("index_member_all")
    assert definition.completeness.scope == "not_applicable"
    assert definition.date_model.audit_applicable is False
    assert definition.capabilities.get_action("maintain").schedule_enabled is False
    assert (
        ScheduleAutomationCapabilityResolver().resolve(
            target_type="dataset_action",
            target_key="index_member_all.maintain",
        )
        is None
    )
