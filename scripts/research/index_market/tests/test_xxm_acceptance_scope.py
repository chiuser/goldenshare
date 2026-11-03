"""P5-05/06/08: real saved field contracts and independent author facts.

Producer headers: retained source_audit CSVs. Author-summary expectations below
were copied from original source records reviewed in LLD 10.3.3.1, not from
the migration operation or a detector. No old runner, API oracle or network.
"""
import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.research.index_market.xxm.acceptance import sha, load_source, collect_readouts

ROOT = Path(__file__).resolve().parents[4]
READOUTS = ROOT / "reports/xxm/observations/xxm_implementation_20261013"
SOURCES = ROOT / "reports/xxm/sources/xxm_macd_structure_20261011/sources"
PARAMS = "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3"
DAY_FIELDS = ("ts_code", "trade_date", "close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq")
MINUTE_FIELDS = ("ts_code", "freq", "trade_date", "trade_time", "close", "macd_dif",
                 "macd_dea", "macd", "params_key", "indicator_version", "observation_count")


def saved_source(root, period, *, close="100.25", missing_dea=False):
    root.mkdir()
    if period == "day":
        name = "daily_source.csv"
        fields = list(DAY_FIELDS)
        row = dict(ts_code="000001.SH", trade_date="2023-01-03", close=close,
                   macd_dif_bfq="5", macd_dea_bfq="3.5", macd_bfq="3")
        dea = "macd_dea_bfq"
    else:
        name = "minute_90_source.csv"
        fields = list(MINUTE_FIELDS)
        row = dict(ts_code="000001.SH", freq="90", trade_date="2023-01-03",
                   trade_time="2023-01-03 11:00:00", close=close, macd_dif="5",
                   macd_dea="3.5", macd="3", params_key=PARAMS,
                   indicator_version="1", observation_count="1")
        dea = "macd_dea"
    if missing_dea:
        fields.remove(dea)
        del row[dea]  # Deliberately invalid producer input; SHA still matches it.
    path = root/name
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    # The other manifest entry proves no recursive source-code protection occurs.
    (root/"manifest.json").write_text(json.dumps({
        "files": [dict(name=name, sha256=digest), dict(name="absent_old_source.py", sha256="not-a-code-check")]}))
    return path, digest


@pytest.mark.parametrize("period", ["day", "m90"])
def test_saved_source_uses_real_fields_and_original_dea(tmp_path, period):
    path, digest = saved_source(tmp_path/"source", period)
    bars = load_source(path.parent, period)
    assert sha(path) == digest
    bar, = bars
    assert (bar.close, bar.dif, bar.dea, bar.hist) == (100.25, 5.0, 3.5, 3.0)
    assert bar.time == ("2023-01-03" if period == "day" else "2023-01-03T11:00:00+08:00")
    bar.validate(period)


def test_two_legal_source_directories_do_not_share_results(tmp_path):
    a, _ = saved_source(tmp_path/"a", "day", close="100")
    b, _ = saved_source(tmp_path/"b", "day", close="101")
    assert load_source(a.parent, "day")[0].close == 100
    assert load_source(b.parent, "day")[0].close == 101


@pytest.mark.parametrize("period", ["day", "m90"])
def test_missing_dea_is_not_reconstructed(tmp_path, period):
    path, _ = saved_source(tmp_path/"bad", period, missing_dea=True)
    with pytest.raises(KeyError): load_source(path.parent, period)


def test_changed_data_is_rejected_before_parsing(tmp_path):
    path, _ = saved_source(tmp_path/"bad", "day")
    path.write_text(path.read_text()+"changed")
    with pytest.raises(ValueError, match="changed"): load_source(path.parent, "day")


@pytest.mark.parametrize("fault", ["date", "number"])
def test_consumer_bar_validation_still_rejects_bad_values(tmp_path, fault):
    path, _ = saved_source(tmp_path/"bad", "day")
    text = path.read_text().replace("2023-01-03", "not-a-date") if fault == "date" else path.read_text().replace("100.25", "NaN")
    path.write_text(text)
    (path.parent/"manifest.json").write_text(json.dumps({"files": [
        dict(name=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())]}))
    bar, = load_source(path.parent, "day")
    with pytest.raises(ValueError): bar.validate("day")


def test_27_saved_readouts_and_independent_return_trees():
    first = collect_readouts(READOUTS)
    second = collect_readouts(READOUTS)
    assert len(first) == len({(r["period"], r["time"]) for r in first}) == 27
    assert (first[0]["period"], first[0]["time"], first[0]["software"]) == (
        "m120", "2025-06-25T15:00:00+08:00", dict(close=3455.97, dif=12.048, dea=4.513, hist=15.069))
    assert (first[-1]["period"], first[-1]["time"], first[-1]["software"]) == (
        "day", "2025-11-14", dict(close=3990.49, dif=34.363, dea=36.454, hist=-4.181))
    assert first[0]["sourceRecord"] == "software_numeric_history_audit.json:observations"
    assert first[-1]["source"]["dea"] == 36.453
    first[0]["software"]["close"] = -1
    assert second[0]["software"]["close"] == 3455.97


@pytest.mark.parametrize("fault", ["root", "count", "duplicate", "missing"])
def test_saved_readout_contract_rejects_malformed_records(tmp_path, fault):
    records = json.loads((READOUTS/"software_readouts.json").read_text())
    if fault == "root": records = {"observations": records}
    elif fault == "count": records.pop()
    elif fault == "duplicate": records[-1] = records[0]
    else: del records[0]["imageSha256"]
    (tmp_path/"software_readouts.json").write_text(json.dumps(records))
    with pytest.raises(ValueError): collect_readouts(tmp_path)


# Exact original author/source leaves, independently copied before extraction.
AUTHOR_SUMMARIES = {
    "correction_context_20261012.json": {
        "research_date": "2026-10-12",
        "existing_sources": [
            {"date": "20250711", "file": "/Users/congming/github/goldenshare/reports/xxm_macd_structure_20261011/sources/20250711_vidiq_transcript.json",
             "sha256": "60ffceeb69494f34218c4652ea89c68ce4e8f0571f1b70fc81ea58dcc5f28909",
             "video_url": "https://www.youtube.com/watch?v=BlSH7x0QElk", "text_field": "response.transcription",
             "locator": "zero-based character offsets, not timestamps",
             "excerpts": [{"offset": 1176, "match": "减仓纠错的标准"}, {"offset": 2452, "match": "不理60分钟"}]},
            {"date": "20251016", "file": "/Users/congming/github/goldenshare/reports/xxm_macd_structure_20261011/sources/20251016_vidiq_transcript.json",
             "sha256": "9a9d7e8ae11bda26fd46a48f29945b2e1fc9858503ba9f8b61b9a38488a1f041",
             "video_url": "https://www.youtube.com/watch?v=o4w4G6q-fSQ", "text_field": "response.transcription",
             "locator": "zero-based character offsets, not timestamps",
             "excerpts": [{"offset": 466, "match": "要求90分钟和120分钟"}, {"offset": 2267, "match": "全部钝化消失"}]},
            {"date": "20251024", "file": "/Users/congming/github/goldenshare/reports/xxm_macd_structure_20261011/sources/20251024_vidiq_transcript.json",
             "sha256": "8c7775baa81a0dec719f585c05d199dec660434eb644df1780195cfa17431b93",
             "video_url": "https://www.youtube.com/watch?v=iflE76iVGO8", "text_field": "response.transcription",
             "locator": "zero-based character offsets, not timestamps",
             "excerpts": [{"offset": 418, "match": "这个消失是结构消失"}, {"offset": 471, "match": "反复的红角线绿角线"},
                          {"offset": 968, "match": "结构形成的纠错标准"}, {"offset": 1015, "match": "90分钟只形成过"}]},
        ],
        "new_public_sources": [
            {"url": "https://blog.sina.com.cn/s/article_archive_1300871220_202606_1.html",
             "retrieval": "ARCHIVE_FETCHED", "purpose": "Identifies June18 and June26 live pages; not substantive lecture evidence"},
            {"url": "https://blog.sina.com.cn/s/blog_4d89b834010302cm.html", "title": "徐小明：周一操作策略",
             "publication": "2026-06-28 14:08:38", "event_date": "2026-06-26", "retrieval": "FULL_PAGE_TEXT_FETCHED",
             "paraphrase": "作者回顾上周五即26日上证跌穿趋势，并强调突破与破位分别决定进攻与防守；没有指定通道、具体边界或调整数量。"},
        ],
        "fetch_limits": [
            {"target": "June18 live", "url": "https://blog.sina.com.cn/s/blog_4d89b834010302c2.html", "result": "Cache miss; no body used"},
            {"target": "June26 live", "url": "https://blog.sina.com.cn/s/blog_4d89b834010302ci.html", "result": "Cache miss; exact-URL search empty; no body used"},
            {"target": "Initial batched click", "result": "Tool connection failure; independent local work continued"},
        ],
    },
    "post_june9_author_check_20261012.json": {
        "research_date": "2026-10-12",
        "sources": [
            {"id": "author_20260612_live", "url": "https://blog.sina.com.cn/s/blog_4d89b834010302bq.html",
             "title": "徐小明：6月12日盘中即时直播", "page_publication": "2026-06-11 15:08:47",
             "event_date": "2026-06-12", "retrieval": "FULL_PAGE_TEXT_FETCHED",
             "paraphrases": [
                 {"time": "09:46", "claim": "作者记录90分钟已有红柱，60分钟红柱增多。"},
                 {"time": "10:01", "claim": "作者把先出红柱作为本次底部钝化构筑的条件。"},
                 {"time": "10:19", "claim": "作者记录120分钟盘中也已有红柱。"},
                 {"time": "11:02-11:10", "claim": "作者把随后钝化能否形成结构与下跌速度及是否加速联系起来。"},
                 {"time": "14:23", "claim": "作者仍等待收盘。"},
             ]},
            {"id": "author_20260615_strategy", "url": "https://blog.sina.com.cn/s/blog_4d89b834010302bx.html",
             "title": "徐小明：周二操作策略", "page_publication": "2026-06-15 16:43:34",
             "event_date": "2026-06-15", "retrieval": "FULL_PAGE_TEXT_FETCHED_EARLIER_IN_TURN; later refresh unavailable, no further retry",
             "paraphrases": [{"claim": "作者讨论此前个股风险释放，并转向进攻背景。"},
                            {"claim": "长期看涨的解释涉及货币、居民存款、GDP及市值等宏观背景。"}]},
            {"id": "author_20260615_live_index", "url": "https://blog.sina.com.cn/s/blog_4d89b834010302bt.html",
             "title": "徐小明：6月15日盘中即时直播", "page_publication": "2026-06-12 16:23:01",
             "event_date": "2026-06-15", "retrieval": "SEARCH_INDEX_EXCERPT_NOT_FULL_PAGE_FETCH; full open cache miss",
             "paraphrases": [{"time": "14:47", "claim": "索引摘录中作者预计长期趋势可能通过，对短期趋势仍不确定。"}]},
        ],
        "source_limits": ["Author blog is lecture context, not software numerical truth.",
                          "No video transcript obtained this turn; exhausted MCP not retried.",
                          "Do not turn author probability statements into measured statistical facts.",
                          "No new trading instruction or formal algorithm change."],
    },
}


@pytest.mark.parametrize("name", ["correction_context_20261012.json", "post_june9_author_check_20261012.json"])
def test_retained_source_summaries_match_independent_literals(name):
    assert json.loads((SOURCES/name).read_text()) == AUTHOR_SUMMARIES[name]


def test_retained_source_summaries_exclude_model_comparisons_and_tasks():
    first = json.loads((SOURCES/"correction_context_20261012.json").read_text())
    second = json.loads((SOURCES/"post_june9_author_check_20261012.json").read_text())
    assert set(first) == {"research_date", "existing_sources", "new_public_sources", "fetch_limits"}
    assert set(second) == {"research_date", "sources", "source_limits"}
    assert "purpose" in first["new_public_sources"][0] and "title" not in first["new_public_sources"][0]
    assert "purpose" not in first["new_public_sources"][1] and "paraphrase" in first["new_public_sources"][1]
    assert all("comparison" not in x for x in first["new_public_sources"] + second["sources"])
    assert not {"analysis", "next_request", "prediction_file", "prediction_sha256", "next_material"} & (first.keys() | second.keys())
