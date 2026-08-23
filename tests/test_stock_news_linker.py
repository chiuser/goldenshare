from __future__ import annotations

from datetime import date

import pytest

from src.foundation.news_linking import (
    HistoricalNameEntry,
    MatchMethod,
    NewsRecord,
    SourceField,
    StockLexiconEntry,
    StockNewsLinker,
)


def _linker(*entries: StockLexiconEntry) -> StockNewsLinker:
    return StockNewsLinker(entries, rule_version="news-stock-rule-test-v1")


def test_code_full_name_and_short_name_are_independent_union_rules() -> None:
    linker = _linker(
        StockLexiconEntry("600519.SH", "600519", "贵州茅台", "贵州茅台股份有限公司"),
        StockLexiconEntry("000858.SZ", "000858", "五粮液", "宜宾五粮液股份有限公司"),
    )

    links = linker.link(
        NewsRecord(
            news_id="news-1",
            title="贵州茅台发布半年报",
            content="600519.SH 与五粮液今日成交活跃",
        )
    )

    assert {(link.news_id, link.ts_code) for link in links} == {
        ("news-1", "600519.SH"),
        ("news-1", "000858.SZ"),
    }


def test_code_match_has_priority_when_same_stock_matches_multiple_rules() -> None:
    linker = _linker(
        StockLexiconEntry("600519.SH", "600519", "贵州茅台", "贵州茅台股份有限公司"),
    )

    links = linker.link(NewsRecord("news-2", "贵州茅台 600519.SH", None))

    assert len(links) == 1
    assert links[0].match_method == MatchMethod.CODE_EXACT
    assert links[0].source_field == SourceField.TITLE
    assert links[0].rule_version == "news-stock-rule-test-v1"


def test_source_field_records_title_content_or_both() -> None:
    linker = _linker(
        StockLexiconEntry("600519.SH", "600519", "贵州茅台", "贵州茅台股份有限公司"),
    )

    title_only = linker.link(NewsRecord("news-title", "贵州茅台公告", None))[0]
    content_only = linker.link(NewsRecord("news-content", None, "贵州茅台公告"))[0]
    both = linker.link(NewsRecord("news-both", "贵州茅台", "600519.SH"))[0]

    assert title_only.source_field == SourceField.TITLE
    assert content_only.source_field == SourceField.CONTENT
    assert both.source_field == SourceField.TITLE_AND_CONTENT


def test_bare_code_and_exchange_code_are_supported_but_unmapped_numbers_are_not() -> None:
    linker = _linker(
        StockLexiconEntry("600519.SH", "600519", "贵州茅台", "贵州茅台股份有限公司"),
    )

    assert linker.link(NewsRecord("bare", "代码 600519", None))[0].ts_code == "600519.SH"
    assert linker.link(NewsRecord("qualified", "代码 600519.SH", None))[0].ts_code == "600519.SH"
    assert linker.link(NewsRecord("number", "日期 20260822", None)) == ()


def test_ambiguous_short_name_uses_first_lexicon_entry() -> None:
    linker = _linker(
        StockLexiconEntry("600001.SH", "600001", "华能", "华能股份有限公司"),
        StockLexiconEntry("000001.SZ", "000001", "华能", "另一家华能有限公司"),
    )

    assert linker.link(NewsRecord("ambiguous", "华能发布公告", None))[0].ts_code == "600001.SH"
    assert linker.link(NewsRecord("explicit", "华能 000001.SZ", None))[0].ts_code == "000001.SZ"


def test_historical_short_name_is_scoped_by_news_date() -> None:
    linker = StockNewsLinker(
        [StockLexiconEntry("600519.SH", "600519", "贵州茅台", "贵州茅台股份有限公司")],
        historical_names=[
            HistoricalNameEntry(
                "600519.SH",
                "茅台股份",
                date(2010, 1, 1),
                date(2018, 12, 31),
            )
        ],
    )

    assert linker.link(NewsRecord("historical", "茅台股份发布公告", news_date=date(2015, 6, 1)))[0].ts_code == "600519.SH"
    assert linker.link(NewsRecord("outside", "茅台股份发布公告", news_date=date(2019, 1, 1))) == ()
    assert linker.link(NewsRecord("missing-date", "茅台股份发布公告")) == ()


def test_non_equity_entries_are_excluded() -> None:
    linker = _linker(
        StockLexiconEntry("000300.SH", "000300", "沪深300", "沪深300指数", security_type="INDEX"),
    )

    assert linker.link(NewsRecord("index", "沪深300 000300.SH", None)) == ()


def test_nfkc_and_whitespace_normalization_support_fullwidth_text() -> None:
    linker = _linker(
        StockLexiconEntry("600519.SH", "600519", "贵州茅台", "贵州茅台股份有限公司"),
    )

    links = linker.link(NewsRecord("normalized", "贵州  茅台", "６００５１９．ＳＨ"))

    assert len(links) == 1
    assert links[0].ts_code == "600519.SH"


def test_empty_news_id_is_rejected() -> None:
    linker = _linker(
        StockLexiconEntry("600519.SH", "600519", "贵州茅台", "贵州茅台股份有限公司"),
    )

    with pytest.raises(ValueError, match="news_id"):
        linker.link(NewsRecord("   ", "贵州茅台", None))


def test_conflicting_duplicate_lexicon_rows_are_rejected() -> None:
    with pytest.raises(ValueError, match="conflicting"):
        _linker(
            StockLexiconEntry("600519.SH", "600519", "贵州茅台", "贵州茅台股份有限公司"),
            StockLexiconEntry("600519.SH", "600519", "另一名称", "贵州茅台股份有限公司"),
        )
