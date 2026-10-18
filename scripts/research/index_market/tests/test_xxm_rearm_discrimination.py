"""Literal arithmetic examples; no software event expected from a model."""
import pytest

from scripts.research.index_market.xxm.rearm_discrimination import margins, origin_dif_comparison, run


def sample(**overrides):
    values=dict(close=95., segment_dif=-6., reference_price=100., nearest_price=98.,
                reference_dif=-10., origin_price=96., origin_dif=-5., bars_after=1)
    return margins(**(values|overrides))


def test_independent_literal_gaps_and_stricter_origin_dif():
    result=sample()
    assert result['priceGap']==3 and result['difGap']==4
    assert result['belowOriginClose'] is True
    assert result['aboveOriginDif'] is False
    assert result['originCloseGap']==1 and result['originDifGap']==-1
    assert result['atLeastTwoFollowingBars'] is False


def test_nearest_price_is_an_independent_gate():
    assert sample(nearest_price=94.)['priceGap']==-1


def test_reference_price_is_an_independent_gate():
    assert sample(reference_price=94.)['priceGap']==-1


def test_price_and_dif_equalities_are_not_strict():
    result=sample(close=96.,segment_dif=-5.)
    assert result['belowOriginClose'] is False and result['aboveOriginDif'] is False


def test_second_following_bar_count():
    assert sample(bars_after=2)['atLeastTwoFollowingBars'] is True


def test_display_rounding_is_not_an_unbounded_source_error_claim():
    result=sample(close=97.999,segment_dif=-9.9995)['displayRoundingOnly']
    assert result['priceComparisonStable'] is False and result['difComparisonStable'] is False
    assert sample()['displayRoundingOnly']['priceComparisonStable'] is True


def test_no_same_bar_or_negative_wait():
    with pytest.raises(ValueError): sample(bars_after=0)


def test_output_must_be_reports(tmp_path):
    with pytest.raises(ValueError): run(tmp_path/'run_01')


def test_existing_output_is_rejected_before_any_source_read(tmp_path, monkeypatch):
    import scripts.research.index_market.xxm.rearm_discrimination as module
    monkeypatch.setattr(module,'ROOT',tmp_path)
    output=tmp_path/'reports/run_existing'
    output.mkdir(parents=True)
    (output/'kept.txt').write_text('original')
    with pytest.raises(FileExistsError): run(output)
    assert (output/'kept.txt').read_text()=='original'


def test_current_dif_is_distinct_from_a_cumulative_trough():
    result=origin_dif_comparison(current_dif=-4.,segment_dif=-8.,origin_dif=-8.)
    assert result['currentDifGap']==4 and result['currentDifAboveOrigin'] is True
    assert result['cumulativeDifGap']==0 and result['cumulativeDifAboveOrigin'] is False


def test_current_dif_equality_is_not_strictly_above_origin():
    assert origin_dif_comparison(current_dif=-8.,segment_dif=-9.,origin_dif=-8.)['currentDifAboveOrigin'] is False
