from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SectorAnalysisException:
    code: str
    message: str


class SectorAnalysisExceptionBuilder:
    """Build only the public, centrally registered sector-analysis errors."""

    _MESSAGES = {
        "SA_SOURCE_DELAYED": "当前交易日行业数据尚未完整，正在展示最近完整交易日数据。",
        "SA_SOURCE_EMPTY": "当前条件下暂无可计算的行业数据。",
        "SA_HIERARCHY_UNAVAILABLE": "行业分类暂不可用，请稍后重试。",
        "SA_QUERY_FAILED": "板块分析数据读取失败，请稍后重试。",
        "SA_MEMBER_SOURCE_EMPTY": "当前行业暂无成分股数据。",
        "SA_MEMBER_QUERY_FAILED": "成分股数据读取失败，请稍后重试。",
        "SA_BREADTH_SOURCE_EMPTY": "当前行业暂无成员广度来源数据。",
        "SA_BREADTH_QUERY_FAILED": "成员广度数据读取失败，请稍后重试。",
    }

    @classmethod
    def build(cls, code: str) -> SectorAnalysisException:
        message = cls._MESSAGES.get(code)
        if message is None:
            raise ValueError(f"unsupported sector-analysis exception code: {code}")
        return SectorAnalysisException(code=code, message=message)
