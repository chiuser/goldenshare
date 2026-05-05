from __future__ import annotations

from datetime import date

import pytest

from src.foundation.services.migration.stock_st_missing_date_repair.evidence_resolver import (
    resolve_candidate,
)
from src.foundation.services.migration.stock_st_missing_date_repair.membership_resolver import (
    is_st_like_name,
    normalize_st_display_name,
)
from src.foundation.services.migration.stock_st_missing_date_repair.models import (
    StockStMissingDateContext,
    StockStNamechangeRecord,
)
from src.foundation.services.migration.stock_st_missing_date_repair.service import (
    StockStMissingDateRepairService,
)


class _FakeLoader:
    def __init__(
        self,
        *,
        context: StockStMissingDateContext,
        active_namechanges: dict[str, tuple[StockStNamechangeRecord, ...]],
    ) -> None:
        self._context = context
        self._active_namechanges = active_namechanges

    def load_date_context(self, session, trade_date: date) -> StockStMissingDateContext:  # type: ignore[no-untyped-def]
        assert trade_date == self._context.trade_date
        return self._context

    def load_active_namechanges(self, session, *, trade_date: date, candidate_codes: tuple[str, ...]):  # type: ignore[no-untyped-def]
        assert trade_date == self._context.trade_date
        assert candidate_codes == self._context.candidate_codes
        return self._active_namechanges


def test_normalize_st_display_name_strips_display_prefixes() -> None:
    assert normalize_st_display_name("XR*ST测试") == "*ST测试"
    assert normalize_st_display_name("XDST华微") == "ST华微"
    assert normalize_st_display_name("DRS*ST示例") == "S*ST示例"
    assert normalize_st_display_name("NST长油") == "ST长油"
    assert is_st_like_name("XR*ST测试") is True
    assert is_st_like_name("通葡股份") is False


def test_resolve_candidate_prefers_latest_non_st_boundary() -> None:
    selected_old = StockStNamechangeRecord(
        id=1,
        ts_code="600255.SH",
        name="*ST鑫科",
        start_date=date(2020, 12, 17),
        end_date=date(2021, 3, 15),
        ann_date=date(2020, 12, 12),
        change_reason="改名",
    )
    selected_new = StockStNamechangeRecord(
        id=2,
        ts_code="600255.SH",
        name="鑫科材料",
        start_date=date(2021, 3, 16),
        end_date=None,
        ann_date=date(2021, 3, 15),
        change_reason="撤销*ST",
    )

    candidate, review = resolve_candidate(
        trade_date=date(2021, 3, 16),
        ts_code="600255.SH",
        prev_name="*ST鑫科",
        next_name=None,
        same_day_st_events=(),
        active_namechanges=(selected_new, selected_old),
    )

    assert candidate.include is False
    assert candidate.validation_status == "excluded_non_st_namechange"
    assert candidate.selected_namechange == selected_new
    assert review is None


def test_stock_st_missing_date_repair_service_preview_writes_artifacts(tmp_path) -> None:
    trade_date = date(2020, 4, 23)
    context = StockStMissingDateContext(
        trade_date=trade_date,
        prev_date=date(2020, 4, 22),
        next_date=date(2020, 4, 24),
        prev_names={"000001.SZ": "*ST样本"},
        next_names={"000001.SZ": "*ST样本", "600225.SH": "天津松江"},
        same_day_st_events={},
        candidate_codes=("000001.SZ", "600225.SH"),
    )
    active_namechanges = {
        "000001.SZ": (
            StockStNamechangeRecord(
                id=1,
                ts_code="000001.SZ",
                name="*ST样本",
                start_date=date(2020, 1, 1),
                end_date=None,
                ann_date=date(2020, 1, 1),
                change_reason="*ST",
            ),
        ),
        "600225.SH": (
            StockStNamechangeRecord(
                id=2,
                ts_code="600225.SH",
                name="天津松江",
                start_date=date(2018, 5, 7),
                end_date=date(2020, 4, 23),
                ann_date=date(2018, 5, 4),
                change_reason="撤销*ST",
            ),
        ),
    }
    service = StockStMissingDateRepairService(
        candidate_loader=_FakeLoader(context=context, active_namechanges=active_namechanges)
    )

    result = service.run(
        session=object(),  # type: ignore[arg-type]
        trade_dates=[trade_date],
        output_dir=tmp_path,
        apply=False,
        fail_on_review_items=False,
    )

    preview = result.date_previews[0]
    assert preview.reconstructed_count == 1
    assert preview.selected_non_st_count == 1
    assert preview.manual_review_count == 0
    assert result.artifacts.summary_path.exists()
    assert result.artifacts.preview_rows_path.exists()
    assert result.artifacts.manual_review_path.exists()
    summary_content = result.artifacts.summary_path.read_text(encoding="utf-8")
    preview_content = result.artifacts.preview_rows_path.read_text(encoding="utf-8")
    assert "2020-04-23" in summary_content
    assert "000001.SZ" in preview_content
    assert "600225.SH" not in preview_content


def test_stock_st_missing_date_repair_service_apply_rejects_existing_data(tmp_path, mocker) -> None:
    trade_date = date(2020, 4, 23)
    context = StockStMissingDateContext(
        trade_date=trade_date,
        prev_date=date(2020, 4, 22),
        next_date=date(2020, 4, 24),
        prev_names={"000001.SZ": "*ST样本"},
        next_names={"000001.SZ": "*ST样本"},
        same_day_st_events={},
        candidate_codes=("000001.SZ",),
    )
    active_namechanges = {
        "000001.SZ": (
            StockStNamechangeRecord(
                id=1,
                ts_code="000001.SZ",
                name="*ST样本",
                start_date=date(2020, 1, 1),
                end_date=None,
                ann_date=date(2020, 1, 1),
                change_reason="*ST",
            ),
        ),
    }
    session = mocker.Mock()
    session.scalar.side_effect = [1, 0]
    service = StockStMissingDateRepairService(
        candidate_loader=_FakeLoader(context=context, active_namechanges=active_namechanges)
    )

    with pytest.raises(ValueError, match="已存在数据"):
        service.run(
            session=session,
            trade_dates=[trade_date],
            output_dir=tmp_path,
            apply=True,
            fail_on_review_items=False,
        )


def test_stock_st_missing_date_repair_service_apply_inserts_and_commits(tmp_path, mocker) -> None:
    trade_date = date(2020, 4, 23)
    context = StockStMissingDateContext(
        trade_date=trade_date,
        prev_date=date(2020, 4, 22),
        next_date=date(2020, 4, 24),
        prev_names={"000001.SZ": "*ST样本"},
        next_names={"000001.SZ": "*ST样本"},
        same_day_st_events={},
        candidate_codes=("000001.SZ",),
    )
    active_namechanges = {
        "000001.SZ": (
            StockStNamechangeRecord(
                id=1,
                ts_code="000001.SZ",
                name="*ST样本",
                start_date=date(2020, 1, 1),
                end_date=None,
                ann_date=date(2020, 1, 1),
                change_reason="*ST",
            ),
        ),
    }
    session = mocker.Mock()
    session.scalar.side_effect = [0, 0]
    service = StockStMissingDateRepairService(
        candidate_loader=_FakeLoader(context=context, active_namechanges=active_namechanges)
    )

    result = service.run(
        session=session,
        trade_dates=[trade_date],
        output_dir=tmp_path,
        apply=True,
        fail_on_review_items=False,
    )

    assert result.applied_date_count == 1
    assert result.applied_row_count == 1
    assert session.add_all.call_count == 2
    raw_rows = session.add_all.call_args_list[0].args[0]
    core_rows = session.add_all.call_args_list[1].args[0]
    assert raw_rows[0].api_name == "stock_st_repair"
    assert raw_rows[0].type == "ST"
    assert raw_rows[0].type_name == "风险警示板"
    assert core_rows[0].type == "ST"
    assert core_rows[0].type_name == "风险警示板"
    session.commit.assert_called_once()
