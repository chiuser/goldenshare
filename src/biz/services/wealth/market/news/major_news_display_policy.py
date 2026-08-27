from __future__ import annotations

MAJOR_NEWS_EXCLUDED_SOURCE = "新浪财经"
THS_MAJOR_NEWS_SOURCE = "同花顺"
THS_PROMOTION_TEXT = "关注同花顺财经（ths518），获取更多机会"


def strip_major_news_promotional_text(
    *,
    source: str,
    content: str | None,
) -> str | None:
    if content is None or source.strip() != THS_MAJOR_NEWS_SOURCE:
        return content

    without_punctuated_text = content.replace(f"{THS_PROMOTION_TEXT}。", "")
    return without_punctuated_text.replace(THS_PROMOTION_TEXT, "")
