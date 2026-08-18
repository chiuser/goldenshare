from __future__ import annotations

import re


SW2021_CLASSIFICATION_VERSION = "SW2021"
SW2021_NORMALIZATION_RULE_VERSION = "sw2021-index-code-v1"
SW2021_INDEX_CODE_ALIASES_V1: dict[str, str] = {
    "850401.SI": "850412.SI",
}

_SW_INDEX_CODE_PATTERN = re.compile(r"^\d{6}\.SI$")
_FORBIDDEN_SW_INDEX_CODES = {"840401", "840401.SI"}


class SwIndustryContractError(ValueError):
    pass


def normalize_sw2021_index_code(
    value: object,
    *,
    classification_industry_code: object | None = None,
) -> str:
    source_code = str(value or "").strip().upper()
    if source_code in _FORBIDDEN_SW_INDEX_CODES:
        raise SwIndustryContractError("840401 是禁用的笔误代码")
    if not _SW_INDEX_CODE_PATTERN.fullmatch(source_code):
        raise SwIndustryContractError(
            f"申万指数代码格式非法：{source_code or '<empty>'}"
        )

    business_code = SW2021_INDEX_CODE_ALIASES_V1.get(source_code, source_code)
    if source_code == "850401.SI" and classification_industry_code is not None:
        industry_code = str(classification_industry_code or "").strip()
        if industry_code != "230501":
            raise SwIndustryContractError(
                "分类源代码 850401.SI 仅允许用于 industry_code=230501"
            )
    return business_code


__all__ = [
    "SW2021_CLASSIFICATION_VERSION",
    "SW2021_INDEX_CODE_ALIASES_V1",
    "SW2021_NORMALIZATION_RULE_VERSION",
    "SwIndustryContractError",
    "normalize_sw2021_index_code",
]
