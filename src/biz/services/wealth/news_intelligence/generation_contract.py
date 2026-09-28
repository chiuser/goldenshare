from __future__ import annotations

from typing import Mapping


QWEN_ANALYSIS_FIELDS = frozenset(
    {
        "importance",
        "one_sentence",
        "facts",
        "impact",
        "uncertainties",
        "entities",
        "evidence",
    }
)

QWEN_ANALYSIS_GBNF = r"""
root ::= "{" ws "\"importance\"" ws ":" ws [1-5] ws "," ws "\"one_sentence\"" ws ":" ws string ws "," ws "\"facts\"" ws ":" ws string-array ws "," ws "\"impact\"" ws ":" ws string ws "," ws "\"uncertainties\"" ws ":" ws string-array ws "," ws "\"entities\"" ws ":" ws string-array ws "," ws "\"evidence\"" ws ":" ws string-array ws "}" ws
string-array ::= "[" ws (string (ws "," ws string)*)? ws "]"
string ::= "\"" char* "\""
char ::= [^"\\\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})
ws ::= [ \t\n\r]*
""".strip()


def build_analysis_prompt(*, title: str, content: str) -> str:
    return (
        "你是中文新闻研究助理。只能依据给定原文，不得补充常识事实。"
        "importance只能是1到5；one_sentence是一句结论；facts、uncertainties、entities和evidence必须是字符串数组；"
        "evidence必须摘取能回查的短语。只输出满足语法的JSON。\n"
        f"标题：{title}\n正文：{content}"
    )


def validate_analysis_payload(payload: Mapping[str, object]) -> dict[str, object]:
    if set(payload) != QWEN_ANALYSIS_FIELDS:
        raise ValueError("Qwen analysis keys do not match the frozen contract")
    importance = payload["importance"]
    if (
        not isinstance(importance, int)
        or isinstance(importance, bool)
        or not 1 <= importance <= 5
    ):
        raise ValueError("importance must be an integer from 1 to 5")
    for field in ("one_sentence", "impact"):
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
    for field in ("facts", "uncertainties", "entities", "evidence"):
        value = payload[field]
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ValueError(f"{field} must be a string array")
    return dict(payload)
