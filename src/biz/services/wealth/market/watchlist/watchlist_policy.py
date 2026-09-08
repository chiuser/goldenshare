from __future__ import annotations

from dataclasses import dataclass
import unicodedata

import regex

DEFAULT_GROUP_NAME = "我的自选"
MAX_GROUPS = 10
MAX_CUSTOM_GROUPS = 9
MAX_GROUP_NAME_CHARS = 6
MAX_GROUP_NAME_UTF8_BYTES = 1024
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200
MAX_BATCH_MEMBERSHIPS = 200
MAX_API_ID = 9007199254740991
PALETTE = (
    "#F7C76B",
    "#5AA7FF",
    "#A78BFA",
    "#2DD4BF",
    "#FB923C",
    "#F472B6",
    "#A3E635",
    "#22D3EE",
)
SORT_FIELDS = (
    "price",
    "changePct",
    "vol",
    "peTtm",
    "pb",
    "volumeRatio",
    "turnoverRate",
    "netAmount",
)
TRIM_CODEPOINTS = (
    0x9,
    0xA,
    0xB,
    0xC,
    0xD,
    0x20,
    0xA0,
    0x1680,
    *range(0x2000, 0x200B),
    0x2028,
    0x2029,
    0x202F,
    0x205F,
    0x3000,
    0xFEFF,
)
TRIM_CHARS = "".join(map(chr, TRIM_CODEPOINTS))


class WatchlistError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WatchlistRequestError(WatchlistError):
    def __init__(self, message: str) -> None:
        super().__init__("WL_REQUEST_INVALID", message)


def count_visible_graphemes(value: str) -> int:
    return len(regex.findall(r"\X", value))


def normalize_group_name(raw: str) -> str:
    try:
        if len(raw.encode("utf-8")) > MAX_GROUP_NAME_UTF8_BYTES:
            raise WatchlistRequestError("分组名称输入最多 1024 UTF-8 字节")
    except UnicodeEncodeError as exc:
        raise WatchlistRequestError("分组名称包含非法字符") from exc
    value = unicodedata.normalize("NFC", raw).strip(TRIM_CHARS)
    if not value:
        raise WatchlistRequestError("请输入分组名称")
    if len(value.encode("utf-8")) > MAX_GROUP_NAME_UTF8_BYTES:
        raise WatchlistRequestError("分组名称输入最多 1024 UTF-8 字节")
    for char in value:
        if regex.fullmatch(r"[\p{Cc}\p{Zl}\p{Zp}\p{Cs}]", char) or (
            regex.fullmatch(r"\p{Cf}", char) and char not in "\u200c\u200d"
        ):
            raise WatchlistRequestError("分组名称不能包含控制字符")
    segments = regex.findall(r"\X", value)
    if any(
        not regex.fullmatch(r"\p{Zs}+", segment)
        and not regex.search(r"[\p{L}\p{N}\p{P}\p{S}]", segment)
        for segment in segments
    ):
        raise WatchlistRequestError("分组名称必须包含正常可见内容")
    if len(segments) > MAX_GROUP_NAME_CHARS:
        raise WatchlistRequestError("分组名称最多 6 个可见字符")
    if value == DEFAULT_GROUP_NAME:
        raise WatchlistRequestError("自定义分组不能命名为我的自选")
    return value


@dataclass(frozen=True, slots=True)
class WatchlistPageRequest:
    limit: int
    sort_by: str | None
    direction: str | None


class WatchlistPolicy:
    def normalize_ts_code(self, ts_code: str) -> str:
        code = ts_code.strip().upper()
        if not 1 <= len(code) <= 16:
            raise WatchlistRequestError("股票代码长度必须为 1 到 16 个字符")
        return code

    def api_id(self, value: int) -> int:
        if type(value) is not int or not 1 <= value <= MAX_API_ID:
            raise WatchlistRequestError("ID 必须为有效安全正整数")
        return value

    def ids(self, values: list[int], *, maximum: int, code: str) -> list[int]:
        if not 1 <= len(values) <= maximum or len(set(values)) != len(values):
            raise WatchlistError(code, f"请选择 1 到 {maximum} 个不重复的有效对象")
        for value in values:
            self.api_id(value)
        return values

    def color(self, color: str) -> str:
        if color not in PALETTE:
            raise WatchlistRequestError("请选择色板中的颜色")
        return color

    def normalize_page(
        self, *, limit: int, sort_by: str | None, direction: str | None
    ) -> WatchlistPageRequest:
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise WatchlistRequestError("每批数量必须在 1 到 200 之间")
        if (sort_by is not None or direction is not None) and (
            sort_by not in SORT_FIELDS or direction not in ("asc", "desc")
        ):
            raise WatchlistRequestError("排序字段和方向必须同时有效")
        return WatchlistPageRequest(limit, sort_by, direction)
