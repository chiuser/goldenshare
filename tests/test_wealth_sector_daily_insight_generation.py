from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    FORMULA_BUNDLE_VERSION, TEMPLATE_VERSION,
    SectorAnalysisDailyFactsPlanDriftError,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.fact_builder import SectorAnalysisDailyFactBuilder
from src.biz.services.wealth.market.sector_analysis.daily_facts.insight_builder import SectorDailyInsightBuilder
from src.biz.services.wealth.market.sector_analysis.daily_facts.materialization_service import SectorAnalysisDailyFactsMaterializationService
from src.biz.services.wealth.market.sector_analysis.daily_facts.repository import SectorAnalysisDailyFactsRepository
from src.biz.services.wealth.market.sector_analysis.daily_facts.template_renderer import SectorDailyInsightTemplateRenderer
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import WealthSectorAnalysisPublishBatch
from src.foundation.models.core_serving.wealth_sector_daily_insight_item import WealthSectorDailyInsightItem
from tests.test_wealth_sector_analysis_daily_materialization import MODELS, SourceStub, _bundle, _engine


@pytest.fixture(scope="module")
def sample():
    bundle = _bundle()
    return bundle, SectorAnalysisDailyFactBuilder().build(bundle)


@pytest.mark.parametrize("qualification,value,expected", [
    ("ELIGIBLE", "50.0001", 1), ("ELIGIBLE", "100", 1),
    ("ELIGIBLE", "50", 0), ("ELIGIBLE", "49", 0),
    ("INELIGIBLE", "100", 0), ("ELIGIBLE", None, 0),
    ("ELIGIBLE", "NaN", 0), ("ELIGIBLE", "Infinity", 0),
])
def test_summary_requires_existing_qualification_and_strict_threshold(sample, qualification, value, expected):
    bundle, facts = sample
    revised = replace(facts, member_breadth=tuple(
        replace(row, values={**row.values, "member_qualification": qualification,
                             "member_up_pct": Decimal(value) if value is not None else None})
        for row in facts.member_breadth
    ))
    before = repr(revised)
    summaries, items = SectorDailyInsightBuilder().build(bundle=bundle, facts=revised, previous=None)
    assert len(summaries) == 3
    assert all(row.values["breadth_up_share_above_50_count"] == expected for row in summaries)
    assert repr(revised) == before  # Insight must not modify any of the five method facts.
    if not expected and qualification == "INELIGIBLE":
        assert all("MEMBER_BREADTH" not in (row.values["primary_evidence_type"], row.values["secondary_evidence_type_1"]) for row in items)


def test_real_two_member_counterexample_is_not_counted():
    bundle = _bundle()
    bundle = replace(bundle, member_market_facts=tuple(
        row for row in bundle.member_market_facts if row.stock_code in {"000001.SZ", "000002.SZ"}
    ))
    facts = SectorAnalysisDailyFactBuilder().build(bundle)
    assert all(row.values["member_qualification"] == "INELIGIBLE" for row in facts.member_breadth)
    assert all(row.values["member_up_pct"] == 100 for row in facts.member_breadth)
    summaries, _ = SectorDailyInsightBuilder().build(bundle=bundle, facts=facts, previous=None)
    assert all(row.values["breadth_up_share_above_50_count"] == 0 for row in summaries)


def _values(**overrides):
    return {
        "return_pct_1d": Decimal("1.255"), "return_pct_5d": Decimal("-2.126"),
        "current_rank_20d": 4, "current_rankable_count_20d": 20,
        "previous_rank_20d": 3, "previous_rankable_count_20d": 10,
        "percentile_change_pp": Decimal("10.245"),
        "price_volume_state_current": "JOINT", "price_volume_state_previous": "PRICE_ONLY",
        "member_up_pct_current": Decimal("75"), "member_up_pct_previous": Decimal("50"),
        "turnover_up_pct_current": Decimal("81"), "turnover_up_pct_previous": Decimal("90"),
        "dual_qualification_20d_80_current": "QUALIFIED", "dual_qualification_20d_80_previous": "NOT_QUALIFIED",
        "rotation_status_20d_current": "LEADING_IMPROVING", "rotation_status_20d_previous": "WEAK_IMPROVING",
        "ma20_above_pct_current": Decimal("66.7"), "ma20_above_pct_previous": Decimal("66.7"),
        **overrides,
    }


def _render(category="HEAD_GAINER", *, values=None, evidence=(), previous=()):
    return SectorDailyInsightTemplateRenderer().render(
        category=category, sector_name="电子", industry_level=1,
        values=values if values is not None else _values(),
        evidence_types=evidence, previous_evidence_types=previous,
    )


def test_head_sentence_contains_real_periods_rank_and_values():
    result = _render(evidence=("PRICE_VOLUME", "MEMBER_BREADTH"), previous=("PRICE_VOLUME", "MEMBER_BREADTH"))
    assert result[1] == "sector-daily-insight-template@2"
    assert result[2] == (
        "电子当日上涨1.26%；20日强度位列一级行业第4/20；近5日下跌2.13%；"
        "20日量价状态由“价格增强”变为“量价共同增强”；上涨成分股占比由50.00%升至75.00%。"
    )
    assert result == _render(evidence=("PRICE_VOLUME", "MEMBER_BREADTH"), previous=("PRICE_VOLUME", "MEMBER_BREADTH"))
    assert "佐证：" not in result[2]


@pytest.mark.parametrize("category,event,daily,delta,expected", [
    ("HEAD_LOSER", "HEAD_LOSER", "-3", "10", "电子当日下跌3.00%"),
    ("STRENGTHENING", "STRENGTHENING", "1", "10", "20日强度由第3/10变为第4/20；强度百分位提高10.00个百分点"),
    ("WEAKENING", "WEAKENING", "-1", "-10", "强度百分位下降10.00个百分点"),
    ("STRENGTHENING", "COUNTER_TREND_STRENGTHENING", "-1", "10", "当日下跌1.00%；但20日同组强度百分位提高10.00个百分点，属于相对抗跌"),
    ("WEAKENING", "RISING_BUT_WEAKENING", "1", "-10", "当日上涨1.00%；但20日同组强度百分位下降10.00个百分点，属于相对滞后"),
])
def test_four_categories_and_countertrend(category, event, daily, delta, expected):
    text = _render(category, values=_values(event_type=event, return_pct_1d=Decimal(daily), percentile_change_pp=Decimal(delta)))[2]
    assert expected in text
    assert "升至第4/20" not in text
    if category in ("STRENGTHENING", "WEAKENING"):
        assert "第3/10变为第4/20" in text


def test_missing_optional_facts_are_omitted_not_fabricated():
    text = _render(values=_values(current_rank_20d=None, return_pct_5d=None))[2]
    assert text == "电子当日上涨1.26%。"
    assert "--" not in text
    with pytest.raises(ValueError, match="both ranks"):
        _render("STRENGTHENING", values=_values(previous_rank_20d=None))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_required_number_never_becomes_a_sentence(value):
    with pytest.raises(ValueError, match="finite"):
        _render(values=_values(return_pct_1d=Decimal(value)))


def test_flat_optional_return_and_rounding_do_not_produce_negative_zero():
    text = _render(values=_values(return_pct_5d=Decimal("-0")))[2]
    assert "近5日持平" in text
    assert SectorDailyInsightTemplateRenderer._pct(Decimal("-0.001")) == "0.00%"


@pytest.mark.parametrize("kind,expected", [
    ("PRICE_VOLUME", "由“价格增强”变为“量价共同增强”"),
    ("MEMBER_BREADTH", "由50.00%升至75.00%"),
    ("TURNOVER_BREADTH", "由90.00%降至81.00%"),
    ("DUAL_MOMENTUM", "由“不符合条件”变为“符合条件”"),
    ("RELATIVE_ROTATION", "由“偏弱但改善”变为“领先且改善”"),
    ("MA20_BREADTH", "站上MA20成分股占比为66.70%"),
])
def test_each_evidence_is_a_value_or_state_not_just_a_label(kind, expected):
    assert expected in _render(evidence=(kind,), previous=(kind,))[2]


def test_evidence_priority_unknown_states_and_independent_qualifications():
    renderer = SectorDailyInsightTemplateRenderer()
    qualifications = {kind: "ELIGIBLE" for kind in ("MEMBER_BREADTH", "TURNOVER_BREADTH", "MA20_BREADTH")}
    assert renderer.select_evidence(values=_values(), qualifications=qualifications) == (
        "PRICE_VOLUME", "MEMBER_BREADTH", "TURNOVER_BREADTH", "DUAL_MOMENTUM", "RELATIVE_ROTATION", "MA20_BREADTH",
    )
    unavailable = _values(price_volume_state_current="UNAVAILABLE", dual_qualification_20d_80_current="NOT_EVALUATED", rotation_status_20d_current="SAMPLE_INSUFFICIENT")
    assert renderer.select_evidence(values=unavailable, qualifications={**qualifications, "MEMBER_BREADTH": "INELIGIBLE"}) == ("TURNOVER_BREADTH", "MA20_BREADTH")
    assert renderer.select_evidence(values={key: None for key in _values()}, qualifications=qualifications) == ()
    for invalid in (("PRICE_VOLUME",) * 2, ("MEMBER_BREADTH", "PRICE_VOLUME"), ("UNKNOWN",), ("PRICE_VOLUME", "MEMBER_BREADTH", "TURNOVER_BREADTH")):
        with pytest.raises(ValueError, match="unique, ordered"):
            _render(evidence=invalid)


def test_previous_ineligible_breadth_is_not_described_as_a_change():
    renderer = SectorDailyInsightTemplateRenderer()
    previous = renderer.select_evidence(values=_values(), qualifications={"MEMBER_BREADTH": "INELIGIBLE"}, suffix="previous")
    text = _render(evidence=("MEMBER_BREADTH",), previous=previous)[2]
    assert "上涨成分股占比为75.00%" in text
    assert "由50.00%" not in text


def test_storage_rounding_does_not_render_a_spurious_breadth_change():
    text = _render(values=_values(member_up_pct_current=Decimal(100) / 3, member_up_pct_previous=Decimal("33.3333")), evidence=("MEMBER_BREADTH",), previous=("MEMBER_BREADTH",))[2]
    assert "上涨成分股占比为33.33%" in text
    assert "升至" not in text


def test_builder_stores_at_most_two_evidence_codes_and_is_deterministic(sample):
    bundle, facts = sample
    builder = SectorDailyInsightBuilder()
    first = builder.build(bundle=bundle, facts=facts, previous=None)
    assert first == builder.build(bundle=bundle, facts=facts, previous=None)
    assert all(row.category not in {"STRENGTHENING", "WEAKENING"} for row in first[1])
    for item in first[1]:
        assert item.values["secondary_evidence_type_2"] is None
        assert item.values["template_version"] == TEMPLATE_VERSION
        assert "--" not in item.values["rendered_text"]


def test_new_batch_and_items_share_version_and_previous_qualifications_are_read():
    engine = _engine()
    try:
        sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
        service = SectorAnalysisDailyFactsMaterializationService(session_factory=sessions, source_query=SourceStub(_bundle()))
        with sessions() as session:
            preview = service.preview_trade_date(session, trade_date=_bundle().trade_date)
        result = service.materialize_trade_date(trade_date=preview.trade_date, expected_source_hash=preview.source_hash, expected_plan_hash=preview.plan_hash, expected_content_hash=preview.content_hash)
        with sessions() as session:
            batch = session.get(WealthSectorAnalysisPublishBatch, result.batch_id)
            assert batch.template_version == TEMPLATE_VERSION
            assert batch.formula_bundle_version == FORMULA_BUNDLE_VERSION == "sector-analysis-daily-facts@1"
            assert set(session.scalars(select(WealthSectorDailyInsightItem.template_version))) == {TEMPLATE_VERSION}
            previous = SectorAnalysisDailyFactsRepository().load_previous_evidence(session, trade_date=batch.trade_date, hierarchy_version=batch.hierarchy_version)
            assert previous is not None
            assert all(row.member_qualification == "ELIGIBLE" and row.turnover_qualification == "ELIGIBLE" and row.ma20_qualification == "ELIGIBLE" for row in previous.by_sector.values())
        replay = service.materialize_trade_date(trade_date=preview.trade_date, expected_source_hash=preview.source_hash, expected_plan_hash=preview.plan_hash, expected_content_hash=preview.content_hash)
        assert replay.idempotent and replay.batch_id == result.batch_id
    finally:
        engine.dispose()


def test_refresh_old_insight_keeps_six_method_tables_and_rejects_old_plan(monkeypatch):
    """SQLite-only publication rehearsal: never mutate a production publication in place."""
    class OldInsightFixture(SectorDailyInsightBuilder):
        def build(self, **kwargs):
            summaries, items = super().build(**kwargs)
            # Freeze the two verified old defects as evidence, not a production compatibility path.
            return (
                tuple(replace(row, values={**row.values, "breadth_up_share_above_50_count": 1}) for row in summaries),
                tuple(replace(row, values={**row.values, "template_version": "sector-daily-insight-template@1",
                                          "rendered_text": f"{row.values['sector_name']}当日上涨。 佐证：量价状态、成分股广度。"}) for row in items),
            )

    bundle = _bundle()
    bundle = replace(bundle, member_market_facts=tuple(row for row in bundle.member_market_facts if row.stock_code in {"000001.SZ", "000002.SZ"}))
    engine = _engine()
    try:
        sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
        old_service = SectorAnalysisDailyFactsMaterializationService(session_factory=sessions, source_query=SourceStub(bundle), insight_builder=OldInsightFixture())
        with monkeypatch.context() as patch:
            patch.setattr("src.biz.services.wealth.market.sector_analysis.daily_facts.repository.TEMPLATE_VERSION", "sector-daily-insight-template@1")
            patch.setattr("src.biz.services.wealth.market.sector_analysis.daily_facts.materialization_service.TEMPLATE_VERSION", "sector-daily-insight-template@1")
            with sessions() as session:
                old_plan = old_service.preview_trade_date(session, trade_date=bundle.trade_date)
            old_result = old_service.materialize_trade_date(trade_date=bundle.trade_date, expected_source_hash=old_plan.source_hash, expected_plan_hash=old_plan.plan_hash, expected_content_hash=old_plan.content_hash)

        new_service = SectorAnalysisDailyFactsMaterializationService(session_factory=sessions, source_query=SourceStub(bundle))
        with pytest.raises(SectorAnalysisDailyFactsPlanDriftError):
            new_service.materialize_trade_date(trade_date=bundle.trade_date, expected_source_hash=old_plan.source_hash, expected_plan_hash=old_plan.plan_hash, expected_content_hash=old_plan.content_hash)
        with sessions() as session:
            new_plan = new_service.preview_trade_date(session, trade_date=bundle.trade_date)
        assert old_plan.source_hash == new_plan.source_hash
        assert old_plan.plan_hash != new_plan.plan_hash and old_plan.content_hash != new_plan.content_hash
        new_result = new_service.materialize_trade_date(trade_date=bundle.trade_date, expected_source_hash=new_plan.source_hash, expected_plan_hash=new_plan.plan_hash, expected_content_hash=new_plan.content_hash)
        with sessions() as session:
            assert session.get(WealthSectorAnalysisPublishBatch, old_result.batch_id).status == "SUPERSEDED"
            assert session.get(WealthSectorAnalysisPublishBatch, new_result.batch_id).status == "PUBLISHED"
            repository = SectorAnalysisDailyFactsRepository()
            for model in MODELS[1:7]:
                def content(batch_id):
                    return repository.content_hash_from_records({model.__tablename__: [
                        repository._model_content_record(row)
                        for row in session.scalars(select(model).where(model.batch_id == batch_id))
                    ]})
                assert content(old_result.batch_id) == content(new_result.batch_id)
            summary_model = MODELS[7]
            assert set(session.scalars(select(summary_model.breadth_up_share_above_50_count).where(summary_model.batch_id == old_result.batch_id))) == {1}
            assert set(session.scalars(select(summary_model.breadth_up_share_above_50_count).where(summary_model.batch_id == new_result.batch_id))) == {0}
            previous = repository.load_previous_evidence(session, trade_date=bundle.trade_date, hierarchy_version=bundle.hierarchy.baseline_version)
            assert all(row.member_up_pct == 100 and row.member_qualification == "INELIGIBLE" for row in previous.by_sector.values())
    finally:
        engine.dispose()
