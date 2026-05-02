#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tushare 文档抓取器 v45（DOM-first）

设计目标：
1. 按正文 DOM 顺序渲染，避免把整页先压扁成纯文本后再猜结构。
2. 保留关键链接、段落边界、表格、代码块和样例块。
3. 页面样例在“能无损识别”为表格时转 Markdown 表格，否则保留原样。
4. 支持菜单发现、按父节点抓取、按 doc_id 抓取、单页抓取，以及索引重建。

依赖：
    pip install requests beautifulsoup4 lxml

示例：
    python3 tushare_leaf_doc_scraper_v45.py --out ./capture/tushare-staging
    python3 tushare_leaf_doc_scraper_v45.py --out ./capture/tushare-staging --publish-to ./docs/sources/tushare --publish-prune
    python3 tushare_leaf_doc_scraper_v45.py --publish-only --out ./capture/tushare-staging --publish-to ./docs/sources/tushare --publish-prune
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT_URL = "https://tushare.pro/document/2?doc_id=14"
DOC_ID_RE = re.compile(r"doc_id=(\d+)")
DEFAULT_PUBLISH_MANIFEST_PATH = Path(__file__).with_name("tushare_publish_manifest_v45.json")
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

SECTION_ALIASES = {
    "接口介绍": "接口介绍",
    "接口说明": "接口介绍",
    "输入参数": "输入参数",
    "接口参数": "输入参数",
    "输出参数": "输出参数",
    "输出指标": "输出参数",
    "输出字段": "输出参数",
    "接口用法": "接口用法",
    "接口示例": "接口用法",
    "代码示例": "接口用法",
    "接口用例": "接口用法",
    "接口使用": "接口用法",
    "数据样例": "数据样例",
    "数据结果": "数据样例",
    "数据示例": "数据样例",
    "复权说明": "复权说明",
    "freq参数说明": "freq参数说明",
    "东财数据输出参数": "东财数据输出参数",
    "新浪数据输出参数": "新浪数据输出参数",
}

INTRO_SECTION_TITLES = {"接口介绍"}
USAGE_SECTION_TITLES = {"接口用法"}
SAMPLE_SECTION_TITLES = {"数据样例"}
OUTPUT_SECTION_TITLES = {"输出参数", "东财数据输出参数", "新浪数据输出参数"}
INPUT_SECTION_TITLES = {"输入参数"}
MARKDOWN_TABLE_SEP_RE = re.compile(r"^\|\s*(?::?-{3,}:?\s*\|\s*)+$")
LIMIT_INPUT_ROW_KEY = "limit"
OFFSET_INPUT_ROW_KEY = "offset"
MANIFEST_TABLE_ROW_SPECS: dict[int, dict[str, list[str]]] = {
    94: {
        "输入参数": ["ts_code", "symbol"],
    },
    143: {
        "输出参数": ["score"],
    },
    195: {
        "输出参数": ["url"],
    },
}

MANIFEST_BLOCK_SPECS: dict[int, list[dict[str, str]]] = {
    94: [
        {
            "marker": "**指数列表**",
            "before_heading": "## 接口用法",
        }
    ]
}
MANIFEST_LINE_INSERTION_SPECS: dict[int, list[dict[str, str]]] = {
    365: [
        {
            "line": "## 输出参数",
            "before_line": "| 名称 | 类型 | 默认显示 | 描述 |",
        }
    ]
}

MANIFEST_FIXED_LINE_PREFIX_SPECS: dict[int, list[str]] = {
    95: ["- 描述：", "- 权限："],
}

MANIFEST_EXACT_LINE_REMOVALS_DEFAULT: dict[int, list[str]] = {
    95: [
        "> 注意：深证成指（399001.SZ）被普遍看作反映深证A股整体表现的大盘，而实际上该指数只包含500只成分股。而各类行情软件上展示的成交量、成交金额是深市所有A股的股票成交情况，如果需要获得与行情软件上一样的成交数据，可以调取深证A指（399107.SZ）。",
    ]
}
MANIFEST_USAGE_NOTE = (
    "发布时以 doc_id 为键应用本清单，不再从 docs/sources/tushare 运行时反向抽取补丁。"
    "staging 文档会先按抓取结果落盘，再依据本清单补齐输入参数表、特殊表格行、正文块和固定说明后发布到正式目录。"
)
MANIFEST_FIELD_NOTES = {
    "limit_offset_input_rows": "按 doc_id 补齐“输入参数”表中的 limit/offset 行。",
    "table_row_patches": "按 doc_id 和 section heading 覆盖或插入指定表格行。",
    "block_patches": "按 doc_id 插入或替换正文块，用于保留人工确认过的说明块。",
    "line_insertions": "按 doc_id 在指定正文行前插入单行文本，适合补回缺失的 section 标题。",
    "fixed_line_prefix_replacements": "按 doc_id 用固定前缀匹配整行替换，适合描述/权限等单行口径修订。",
    "exact_line_removals": "按 doc_id 删除指定整行，适合移除不再保留的旧提示语。",
}

META_LABELS = {
    "接口名称": "接口",
    "接口": "接口",
    "接口说明": "描述",
    "描述": "描述",
    "限量": "限量",
    "权限": "权限",
    "积分": "积分",
    "更新时间": "更新时间",
    "其它": "其它",
    "Python SDK版本要求": "Python SDK版本要求",
}

TABLE_HEADER_CANDIDATES = {
    "输入参数": ("名称", "类型", "必选", "描述"),
    "输出参数": ("名称", "类型", "默认显示", "描述"),
    "东财数据输出参数": ("名称", "类型", "描述"),
    "新浪数据输出参数": ("名称", "类型", "描述"),
    "复权说明": ("类型", "算法", "参数标识"),
    "freq参数说明": ("freq", "说明"),
}

CATEGORY_ONLY_HINTS = {
    "股票数据",
    "基础数据",
    "行情数据",
    "财务数据",
    "参考数据",
    "特色数据",
    "两融及转融通",
    "资金流向数据",
    "打板专题数据",
    "ETF专题",
    "指数专题",
    "公募基金",
    "期货数据",
    "现货数据",
    "期权数据",
    "债券专题",
    "外汇数据",
    "港股数据",
    "美股数据",
    "行业经济",
    "宏观经济",
    "国内宏观",
    "国际宏观",
    "利率数据",
    "国民经济",
    "价格指数",
    "金融",
    "景气度",
    "财富管理",
    "数据索引",
    "大模型语料专题数据",
}

SPECIAL_USAGE_LABELS = {"或者", "或者：", "说明", "说明：", "例如", "例如："}
NOTE_PREFIX_RE = re.compile(r"^(注|说明|备注|注意|提示)[:：]")


@dataclass
class DocEntry:
    doc_id: int
    title: str
    url: str
    category_path: list[str]
    is_leaf: bool = True
    api_name: str = ""


class GentleSession:
    def __init__(self, min_delay: float, max_delay: float, timeout: float = 30.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def _sleep(self, base: Optional[float] = None) -> None:
        duration = random.uniform(self.min_delay, self.max_delay) if base is None else base
        time.sleep(duration)

    def get(self, url: str, retries: int = 4) -> requests.Response:
        last_error: Optional[Exception] = None
        backoff = 5.0
        for attempt in range(1, retries + 1):
            if attempt > 1:
                self._sleep(backoff + random.uniform(0.0, 2.5))
                backoff = min(backoff * 2, 60.0)
            else:
                self._sleep()

            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                print(f"[warn] GET failed ({attempt}/{retries}) {url} -> {exc}", file=sys.stderr)

        raise RuntimeError(f"request failed: {url}; last_error={last_error}")

    def get_bytes(self, url: str, retries: int = 4) -> tuple[bytes, str]:
        resp = self.get(url, retries=retries)
        return resp.content, (resp.headers.get("Content-Type") or "")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_block_text(text: str) -> str:
    text = (text or "").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] if name else "untitled"


def extract_doc_id(url: str) -> Optional[int]:
    if not url:
        return None
    m = DOC_ID_RE.search(url)
    if m:
        return int(m.group(1))
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    values = query.get("doc_id")
    if values and values[0].isdigit():
        return int(values[0])
    return None


def soup_from_html(html_text: str) -> BeautifulSoup:
    return BeautifulSoup(html_text, "lxml")


def canonical_section_title(text: str) -> Optional[str]:
    clean = normalize_space(re.sub(r"[*_`#]+", "", text or "")).strip("：: ")
    return SECTION_ALIASES.get(clean)


def strip_markdown_wrappers(text: str) -> str:
    text = text or ""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return normalize_space(text)


def yaml_json_line(key: str, value: object) -> str:
    return f"{key}: {json.dumps(value, ensure_ascii=False)}"


def escape_md_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>").strip()


def rows_to_markdown(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    normalized: list[list[str]] = []
    for row in rows:
        row = row[:width] + [""] * max(0, width - len(row))
        normalized.append([escape_md_cell(cell) for cell in row])

    header = normalized[0]
    sep = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _merge_signed_tokens(tokens: list[str]) -> list[str]:
    cleaned = [t for t in tokens if t and t != "\\"]
    merged: list[str] = []
    i = 0
    while i < len(cleaned):
        tok = cleaned[i]
        if tok in {"-", "+"} and i + 1 < len(cleaned) and re.fullmatch(
            r"(?:\d+(?:\.\d+)?|\.\d+|NaN|None)",
            cleaned[i + 1],
            re.I,
        ):
            merged.append(tok + cleaned[i + 1])
            i += 2
            continue
        merged.append(tok)
        i += 1
    return merged


def _line_tokens(line: str) -> list[str]:
    return re.split(r"\s+", normalize_space(line)) if normalize_space(line) else []


def looks_like_sample_header_line(line: str, output_columns: Optional[list[str]] = None) -> bool:
    tokens = [t for t in _line_tokens(line) if t != "\\"]
    if len(tokens) < 2:
        return False
    if tokens[0].isdigit():
        return False
    if output_columns:
        out_set = {c.lower() for c in output_columns}
        match_count = sum(1 for t in tokens if t.lower() in out_set)
        return match_count >= max(2, min(4, len(tokens) // 2))
    return all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t) for t in tokens)


def looks_like_sample_data_row_line(line: str) -> bool:
    tokens = _line_tokens(line)
    if len(tokens) < 2:
        return False
    first = tokens[0]
    if re.fullmatch(r"\d+", first):
        return True
    if re.fullmatch(r"\d{8}", first):
        return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", first):
        return True
    if re.fullmatch(r"\d{6}\.[A-Z]{2}", first):
        return True
    return False


def parse_whitespace_table(text: str, output_columns: Optional[list[str]] = None) -> Optional[list[list[str]]]:
    raw_lines = [normalize_space(line) for line in text.splitlines() if normalize_space(line)]
    if len(raw_lines) < 2:
        return None

    header_tokens = _merge_signed_tokens(re.split(r"\s+", raw_lines[0].strip()))
    if len(header_tokens) < 2:
        return None

    final_headers = header_tokens[:]
    if output_columns:
        lowered = [x.lower() for x in output_columns]
        header_lower = [x.lower() for x in header_tokens]
        if not all(token in lowered for token in header_lower):
            coarse = _merge_signed_tokens(re.split(r"\s{2,}", raw_lines[0].strip()))
            if len(coarse) >= 2 and all(token.lower() in lowered for token in coarse):
                header_tokens = coarse
                header_lower = [x.lower() for x in header_tokens]
        if len(output_columns) == len(header_tokens):
            match_count = sum(1 for token in header_lower if token in lowered)
            if match_count >= max(2, len(header_tokens) - 2):
                final_headers = output_columns[:]

    data_rows: list[list[str]] = []
    col_count = len(final_headers)

    for line in raw_lines[1:]:
        stripped = line.strip()
        if not stripped or set(stripped) <= {".", " "}:
            continue

        tokens = _merge_signed_tokens(re.split(r"\s+", stripped))
        if tokens and re.fullmatch(r"\d+|\.\.|\.\.\.", tokens[0]):
            tokens = tokens[1:]
        if output_columns and len(tokens) == col_count + 1 and "time" in output_columns:
            time_idx = output_columns.index("time")
            if (
                0 <= time_idx < len(tokens) - 1
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", tokens[time_idx])
                and re.fullmatch(r"\d{2}:\d{2}:\d{2}", tokens[time_idx + 1])
            ):
                tokens = tokens[:time_idx] + [tokens[time_idx] + " " + tokens[time_idx + 1]] + tokens[time_idx + 2 :]
        if len(tokens) < col_count:
            continue

        row = tokens[: col_count - 1] + [" ".join(tokens[col_count - 1 :])]
        if not row or row[0] in {"...", ".."}:
            continue
        data_rows.append(row)

    if not data_rows:
        return None
    return [final_headers] + data_rows


def parse_pandas_wrapped_sample(text: str, output_columns: Optional[list[str]] = None) -> Optional[list[list[str]]]:
    lines = [normalize_space(x) for x in text.splitlines() if normalize_space(x)]
    if len(lines) < 6:
        return None
    if re.match(r"^\d", lines[0]):
        return None

    blocks: list[tuple[list[str], dict[str, list[str]]]] = []
    i = 0
    while i < len(lines):
        if re.match(r"^\d+\s", lines[i]):
            return None
        header = _merge_signed_tokens(_line_tokens(lines[i]))
        if len(header) < 2:
            break
        i += 1
        data: dict[str, list[str]] = {}
        while i < len(lines) and re.match(r"^\d+\s", lines[i]):
            toks = _merge_signed_tokens(_line_tokens(lines[i]))
            if len(toks) >= 2:
                data[toks[0]] = toks[1:]
            i += 1
        if not data:
            break
        blocks.append((header, data))

    if len(blocks) < 2:
        return None

    common = set(blocks[0][1].keys())
    for _, data in blocks[1:]:
        common &= set(data.keys())
    common_indices = sorted(common, key=lambda x: int(x) if x.isdigit() else x)
    if len(common_indices) < 1:
        return None

    final_headers: list[str] = []
    if output_columns and sum(len(h) for h, _ in blocks) == len(output_columns):
        offset = 0
        for h, _ in blocks:
            final_headers.extend(output_columns[offset:offset + len(h)])
            offset += len(h)
    else:
        for h, _ in blocks:
            final_headers.extend(h)

    rows: list[list[str]] = [final_headers]
    for idx in common_indices:
        merged_row: list[str] = []
        for h, data in blocks:
            vals = data.get(idx, [])
            vals = vals[:len(h)] + [""] * max(0, len(h) - len(vals))
            merged_row.extend(vals)
        rows.append(merged_row)
    return rows


def parse_vertical_repeated_columns_sample(text: str, output_columns: Optional[list[str]] = None) -> Optional[list[list[str]]]:
    if not output_columns or len(output_columns) < 4:
        return None

    raw_lines = [normalize_space(line) for line in text.splitlines() if normalize_space(line)]
    if len(raw_lines) < len(output_columns) * 2:
        return None

    header = [normalize_space(x) for x in output_columns]
    header_len = len(header)

    if [normalize_space(x) for x in raw_lines[:header_len]] != header:
        return None

    data_lines = raw_lines[header_len:]
    rows: list[list[str]] = [header]
    parsed = 0
    i = 0
    while i + header_len - 1 < len(data_lines):
        row = [normalize_space(x) for x in data_lines[i:i + header_len]]
        if len(row) != header_len or not row[0]:
            i += 1
            continue
        rows.append(row)
        parsed += 1
        i += header_len

    if parsed < 1:
        return None
    return rows


def parse_visible_ellipsis_pandas_sample(text: str) -> Optional[list[list[str]]]:
    lines = [line.rstrip() for line in clean_sample_text(text).splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    header_matches = list(re.finditer(r"\S+", lines[0]))
    header_tokens = [m.group(0) for m in header_matches]
    if "..." not in header_tokens or len(header_tokens) < 5:
        return None

    ellipsis_idx = header_tokens.index("...")
    prefix_headers = header_tokens[:ellipsis_idx]
    suffix_headers = header_tokens[ellipsis_idx + 1 :]
    suffix_header_starts = [m.start() for m in header_matches[ellipsis_idx + 1 :]]
    if not prefix_headers or not suffix_headers:
        return None

    rows: list[list[str]] = [header_tokens]
    for line in lines[1:]:
        matches = list(re.finditer(r"\S+", line))
        if not matches:
            continue
        if re.fullmatch(r"\d+", matches[0].group(0)):
            matches = matches[1:]
        if not matches:
            continue

        tokens = [m.group(0) for m in matches]
        starts = [m.start() for m in matches]
        if "..." not in tokens:
            continue

        row_ellipsis_idx = tokens.index("...")
        prefix_tokens = tokens[:row_ellipsis_idx]
        if len(prefix_tokens) != len(prefix_headers):
            continue

        suffix_tokens = tokens[row_ellipsis_idx + 1 :]
        suffix_starts = starts[row_ellipsis_idx + 1 :]
        mapped_suffix = [""] * len(suffix_headers)

        cursor = 0
        for i, (tok, start) in enumerate(zip(suffix_tokens, suffix_starts)):
            remaining_tokens = len(suffix_tokens) - i
            max_header_idx = len(suffix_headers) - remaining_tokens
            if cursor > max_header_idx:
                break
            candidate_indices = range(cursor, max_header_idx + 1)
            best_idx = min(candidate_indices, key=lambda idx: abs(suffix_header_starts[idx] - start))
            mapped_suffix[best_idx] = tok
            cursor = best_idx + 1

        rows.append(prefix_tokens + ["..."] + mapped_suffix)

    return rows if len(rows) > 1 else None


def parse_tokenized_wrapped_sample(text: str, output_columns: Optional[list[str]] = None) -> Optional[list[list[str]]]:
    if not output_columns or len(output_columns) < 6:
        return None
    lines = [normalize_space(x) for x in text.splitlines() if normalize_space(x)]
    if len(lines) < len(output_columns) + 6:
        return None
    if sum(1 for ln in lines[: min(20, len(lines))] if len(_line_tokens(ln)) > 1) > 2:
        return None

    def match_expected(cur: str, expected: str) -> bool:
        cur_l = cur.lower()
        exp_l = expected.lower()
        if cur_l == exp_l:
            return True
        if exp_l == "sz_net_amount" and cur_l == "sh_net_amount":
            return True
        return False

    def next_header_starts(pos: int, remaining: list[str]) -> bool:
        if len(remaining) < 2 or pos + 1 >= len(lines):
            return False
        return match_expected(lines[pos], remaining[0]) and match_expected(lines[pos + 1], remaining[1])

    def merge_signed_token(pos: int) -> tuple[str, int]:
        tok = lines[pos]
        if tok in {"-", "+"} and pos + 1 < len(lines) and re.fullmatch(
            r"(?:\d+(?:\.\d+)?|\.\d+|NaN|None)",
            lines[pos + 1],
            re.I,
        ):
            return tok + lines[pos + 1], pos + 2
        return tok, pos + 1

    blocks: list[tuple[list[str], dict[str, list[str]]]] = []
    offset = 0
    i = 0
    while offset < len(output_columns) and i < len(lines):
        header: list[str] = []
        while i < len(lines):
            cur = lines[i]
            if cur == "\\":
                i += 1
                break
            if re.fullmatch(r"\d+", cur):
                break
            expected = output_columns[offset + len(header)] if offset + len(header) < len(output_columns) else None
            if expected and match_expected(cur, expected):
                header.append(expected)
                i += 1
                continue
            break
        if len(header) < 2:
            break
        offset += len(header)

        data: dict[str, list[str]] = {}
        while i < len(lines):
            remaining = output_columns[offset:]
            if remaining and next_header_starts(i, remaining):
                break
            if lines[i] == "\\":
                i += 1
                continue
            if not re.fullmatch(r"\d+", lines[i]):
                break
            idx = lines[i]
            i += 1
            vals: list[str] = []
            while i < len(lines) and len(vals) < len(header):
                remaining = output_columns[offset:]
                if not vals and remaining and next_header_starts(i, remaining):
                    break
                if lines[i] == "\\":
                    i += 1
                    continue
                tok, i = merge_signed_token(i)
                vals.append(tok)
            if len(vals) != len(header):
                break
            data[idx] = vals
        if not data:
            break
        blocks.append((header, data))

    if len(blocks) < 2:
        return None

    common = set(blocks[0][1].keys())
    for _, data in blocks[1:]:
        common &= set(data.keys())
    if len(common) < 1:
        return None

    common_indices = sorted(common, key=lambda x: int(x) if x.isdigit() else x)
    final_headers: list[str] = []
    for h, _ in blocks:
        final_headers.extend(h)
    if len(final_headers) != len(output_columns):
        final_headers = output_columns[:]

    rows: list[list[str]] = [final_headers]
    for idx in common_indices:
        row: list[str] = []
        for h, data in blocks:
            vals = data.get(idx, [])
            vals = vals[:len(h)] + [""] * max(0, len(h) - len(vals))
            row.extend(vals)
        if len(row) == len(final_headers):
            rows.append(row)
    return rows if len(rows) > 1 else None


def parse_long_text_three_col_sample(text: str) -> Optional[list[list[str]]]:
    raw_lines = [normalize_space(line) for line in text.splitlines() if normalize_space(line)]
    if len(raw_lines) < 3:
        return None

    rows: list[list[str]] = [["名称", "说明", "关联机构"]]
    if len(raw_lines) >= 3 and raw_lines[0] == "名称" and raw_lines[1] == "说明" and raw_lines[2] == "关联机构":
        data_lines = raw_lines[3:]
        parsed = 0
        i = 0
        while i + 2 < len(data_lines):
            name = data_lines[i].strip()
            desc = data_lines[i + 1].strip()
            orgs = data_lines[i + 2].strip()
            if not name or not desc or not orgs:
                i += 1
                continue
            rows.append([name, desc, orgs])
            parsed += 1
            i += 3
        if parsed >= 2:
            return rows
    return None


def clean_sample_text(text: str) -> str:
    lines = [line.rstrip() for line in normalize_block_text(text).splitlines()]
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("In [") or stripped.startswith("Out["):
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stripped) and cleaned and cleaned[-1].rstrip().endswith("\\"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip("\n")


def parse_sample_table(text: str, output_columns: Optional[list[str]] = None) -> Optional[list[list[str]]]:
    cleaned = clean_sample_text(text)
    if not cleaned:
        return None
    return (
        parse_tokenized_wrapped_sample(cleaned, output_columns=output_columns)
        or parse_visible_ellipsis_pandas_sample(cleaned)
        or parse_pandas_wrapped_sample(cleaned, output_columns=output_columns)
        or parse_vertical_repeated_columns_sample(cleaned, output_columns=output_columns)
        or parse_whitespace_table(cleaned, output_columns=output_columns)
        or parse_long_text_three_col_sample(cleaned)
    )


def looks_like_python(text: str) -> bool:
    patterns = (
        "import ",
        "from ",
        "def ",
        "class ",
        "pro.",
        "ts.",
        "df =",
        "print(",
        "set_token(",
    )
    return any(p in text for p in patterns)


def split_mixed_code_and_sample(text: str, output_columns: Optional[list[str]] = None) -> tuple[str, str]:
    lines = normalize_block_text(text).splitlines()
    sample_start: Optional[int] = None
    for idx, raw in enumerate(lines):
        line = normalize_space(raw)
        if line.startswith("In [") or line.startswith("Out["):
            sample_start = idx
            break
        if looks_like_sample_header_line(line, output_columns=output_columns):
            nxt = normalize_space(lines[idx + 1]) if idx + 1 < len(lines) else ""
            if looks_like_sample_data_row_line(nxt):
                sample_start = idx
                break
            nxt2 = normalize_space(lines[idx + 2]) if idx + 2 < len(lines) else ""
            if line.endswith("\\") and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nxt) and looks_like_sample_data_row_line(nxt2):
                sample_start = idx
                break
    if sample_start is None:
        return normalize_block_text(text), ""
    code_text = "\n".join(lines[:sample_start]).strip()
    sample_text = "\n".join(lines[sample_start:]).strip()
    return code_text, sample_text


def guess_image_url(node: Tag, base_url: str) -> Optional[str]:
    src = (node.get("src") or node.get("data-src") or node.get("data-original") or "").strip()
    if not src:
        return None
    return urljoin(base_url, src)


def normalize_inline_markdown(text: str) -> str:
    text = (text or "").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def render_inline(node: object, base_url: str) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name == "br":
        return "\n"
    if node.name == "img":
        return ""

    inner = "".join(render_inline(child, base_url) for child in node.children)

    if node.name == "a":
        href = (node.get("href") or "").strip()
        href = urljoin(base_url, href) if href else ""
        label = normalize_inline_markdown(inner) or href
        return f"[{label}]({href})" if href else label
    if node.name in {"strong", "b"}:
        inner = normalize_inline_markdown(inner)
        return f"**{inner}**" if inner else ""
    if node.name in {"em", "i"}:
        inner = normalize_inline_markdown(inner)
        return f"*{inner}*" if inner else ""
    if node.name == "code":
        inner = normalize_inline_markdown(inner).replace("`", "\\`")
        return f"`{inner}`" if inner else ""
    return inner


def split_node_fragments(node: Tag) -> list[list[object]]:
    fragments: list[list[object]] = [[]]
    for child in node.children:
        if isinstance(child, Tag) and child.name == "br":
            fragments.append([])
            continue
        fragments[-1].append(child)
    return fragments


def plain_text_from_fragment(fragment: Sequence[object]) -> str:
    parts: list[str] = []
    for item in fragment:
        if isinstance(item, NavigableString):
            parts.append(str(item))
        elif isinstance(item, Tag):
            parts.append(item.get_text(" ", strip=False))
    return normalize_space("".join(parts))


def markdown_text_from_fragment(fragment: Sequence[object], base_url: str) -> str:
    return normalize_inline_markdown("".join(render_inline(item, base_url) for item in fragment))


def split_node_lines(node: Tag, base_url: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for fragment in split_node_fragments(node):
        plain = plain_text_from_fragment(fragment)
        markdown = markdown_text_from_fragment(fragment, base_url)
        if plain or markdown:
            lines.append((plain, markdown))
    return lines


def split_list_item_lines(node: Tag, base_url: str) -> list[tuple[str, str]]:
    fragments: list[list[object]] = [[]]
    for child in node.children:
        if isinstance(child, Tag) and child.name in {"ul", "ol"}:
            continue
        if isinstance(child, Tag) and child.name == "br":
            fragments.append([])
            continue
        fragments[-1].append(child)

    lines: list[tuple[str, str]] = []
    for fragment in fragments:
        plain = plain_text_from_fragment(fragment)
        markdown = markdown_text_from_fragment(fragment, base_url)
        if plain or markdown:
            lines.append((plain, markdown))
    return lines


def html_table_to_rows(table: Tag, base_url: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        row: list[str] = []
        for cell in cells:
            lines = split_node_lines(cell, base_url)
            rendered = "<br>".join(md for _, md in lines if md)
            rendered = normalize_inline_markdown(rendered)
            row.append(rendered)
        if any(cell for cell in row):
            rows.append(row)
    return rows


def extract_api_name_from_lines(lines: Sequence[str]) -> str:
    for line in lines:
        plain = strip_markdown_wrappers(line)
        plain = re.sub(r"^[-*]\s*", "", plain)
        m = re.match(r"^(接口名称|接口)\s*[：:]\s*([A-Za-z_][A-Za-z0-9_]*)", plain)
        if m:
            return m.group(2)
    return ""


def patch_index_topic_input_params(lines: list[str], entry: DocEntry) -> list[str]:
    if entry.category_path != ["指数专题"]:
        return lines

    limit_row = "| limit | int | N | 单次返回数据长度 |"
    offset_row = "| offset | int | N | 请求数据的开始位移量 |"
    if limit_row in lines and offset_row in lines:
        return lines

    input_heading_idx: Optional[int] = None
    for idx, line in enumerate(lines):
        if normalize_space(line) == "## 输入参数":
            input_heading_idx = idx
            break
    if input_heading_idx is None:
        return lines

    table_header_idx: Optional[int] = None
    for idx in range(input_heading_idx + 1, len(lines)):
        if lines[idx].startswith("## "):
            break
        if normalize_space(lines[idx]) == "| 名称 | 类型 | 必选 | 描述 |":
            table_header_idx = idx
            break
    if table_header_idx is None:
        return lines

    table_end_idx = table_header_idx + 2
    while table_end_idx < len(lines) and lines[table_end_idx].startswith("|"):
        table_end_idx += 1

    insert_rows: list[str] = []
    section_rows = lines[table_header_idx:table_end_idx]
    if limit_row not in section_rows:
        insert_rows.append(limit_row)
    if offset_row not in section_rows:
        insert_rows.append(offset_row)
    if not insert_rows:
        return lines

    return lines[:table_end_idx] + insert_rows + lines[table_end_idx:]


def is_short_usage_label(text: str, next_node: Optional[Tag]) -> bool:
    plain = normalize_space(text).strip("：:")
    if not plain or plain in SPECIAL_USAGE_LABELS:
        return False
    if len(plain) > 16:
        return False
    if next_node is None:
        return False
    return next_node.name == "pre" or "codehilite" in (next_node.get("class") or [])


def render_intro_lines(lines: Sequence[tuple[str, str]]) -> list[str]:
    out: list[str] = []
    for plain, markdown in lines:
        probe = strip_markdown_wrappers(markdown)
        m = re.match(r"^(接口名称|接口|接口说明|描述|限量|权限|积分|更新时间|其它|Python SDK版本要求)\s*[：:]\s*(.*)$", probe)
        if m:
            label = META_LABELS[m.group(1)]
            value_match = re.match(
                r"^(?:\*\*)?(接口名称|接口|接口说明|描述|限量|权限|积分|更新时间|其它|Python SDK版本要求)(?:\*\*)?\s*[：:]\s*(.*)$",
                markdown,
            )
            value = value_match.group(2).strip() if value_match else m.group(2).strip()
            out.append(f"- {label}：{value}" if value else f"- {label}")
        elif NOTE_PREFIX_RE.match(plain):
            out.append(f"> {markdown}")
        elif markdown:
            out.append(markdown)
    return out


def render_regular_lines(
    lines: Sequence[tuple[str, str]],
    *,
    section_title: Optional[str],
    next_node: Optional[Tag],
) -> list[str]:
    out: list[str] = []
    for plain, markdown in lines:
        if not markdown:
            continue
        if section_title in OUTPUT_SECTION_TITLES and "：" in plain:
            out.append(f"- {markdown}")
            continue
        if section_title in USAGE_SECTION_TITLES and plain in {"或者", "或者："}:
            out.append("或者：")
            continue
        if section_title in USAGE_SECTION_TITLES and plain in SPECIAL_USAGE_LABELS:
            out.append(markdown)
            continue
        if section_title in USAGE_SECTION_TITLES and is_short_usage_label(plain, next_node):
            out.append(f"### {plain.strip('：: ')}")
            continue
        if NOTE_PREFIX_RE.match(plain):
            out.append(f"> {markdown}")
            continue
        out.append(markdown)
    return out


def extract_images(node: Tag, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for img in node.find_all("img"):
        url = guess_image_url(img, base_url)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def find_content_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    root = soup.select_one("div.content")
    if root:
        return root
    main = soup.find(["main", "article", "section"])
    return main or soup


def iter_content_children(content_root: Tag | BeautifulSoup) -> list[Tag]:
    children: list[Tag] = []
    for child in content_root.children:
        if isinstance(child, Tag):
            children.append(child)
    return children


def is_empty_node(node: Tag) -> bool:
    if node.name == "hr":
        return True
    if node.name == "br":
        return True
    if "search-panel" in (node.get("class") or []):
        return True
    if node.name == "p":
        lines = split_node_lines(node, "")
        return not lines and not node.find("img")
    return False


def extract_doc_title(content_root: Tag | BeautifulSoup, fallback_title: str) -> tuple[str, Optional[Tag]]:
    for node in iter_content_children(content_root):
        if node.name in {"h1", "h2"}:
            text = normalize_space(node.get_text(" ", strip=True))
            if text:
                return text, node
    if fallback_title:
        return fallback_title, None
    return "untitled", None


def detect_section_heading(node: Tag, title_node: Optional[Tag]) -> Optional[str]:
    if node is title_node:
        return None
    if node.name not in {"h1", "h2", "h3", "h4", "p"}:
        return None
    lines = split_node_lines(node, "")
    if len(lines) != 1:
        return None
    plain, markdown = lines[0]
    text = plain or strip_markdown_wrappers(markdown)
    if not text:
        return None
    return canonical_section_title(text)


def next_significant_node(nodes: Sequence[Tag], start_idx: int, title_node: Optional[Tag]) -> Optional[Tag]:
    for node in nodes[start_idx:]:
        if node is title_node or is_empty_node(node):
            continue
        return node
    return None


def extract_pre_like_text(node: Tag) -> str:
    if node.name == "pre":
        return normalize_block_text(node.get_text("", strip=False))
    if "codehilite" in (node.get("class") or []):
        pre = node.find("pre")
        if pre:
            return normalize_block_text(pre.get_text("", strip=False))
        return normalize_block_text(node.get_text("", strip=False))
    return normalize_block_text(node.get_text("", strip=False))


def render_images_as_blocks(image_urls: Sequence[str], alt: str = "页面附图") -> list[list[str]]:
    blocks: list[list[str]] = []
    for url in image_urls:
        blocks.append([f"![{alt}]({url})"])
    return blocks


def render_paragraph_blocks(
    node: Tag,
    *,
    section_title: Optional[str],
    next_node: Optional[Tag],
    base_url: str,
) -> list[list[str]]:
    blocks: list[list[str]] = []
    image_urls = extract_images(node, base_url)
    lines = split_node_lines(node, base_url)
    if lines:
        if section_title in INTRO_SECTION_TITLES or section_title is None:
            rendered = render_intro_lines(lines)
        else:
            rendered = render_regular_lines(lines, section_title=section_title, next_node=next_node)
        if rendered:
            blocks.append(rendered)
    if image_urls:
        blocks.extend(render_images_as_blocks(image_urls))
    return blocks


def render_list_blocks(
    node: Tag,
    *,
    section_title: Optional[str],
    next_node: Optional[Tag],
    base_url: str,
) -> list[list[str]]:
    rendered_items: list[str] = []
    for li in node.find_all("li", recursive=False):
        lines = split_list_item_lines(li, base_url)
        if lines:
            if section_title in INTRO_SECTION_TITLES or section_title is None:
                parts = render_intro_lines(lines)
            else:
                parts = render_regular_lines(lines, section_title=section_title, next_node=next_node)
            parts = [part for part in parts if part]
            if parts:
                rendered_items.append(f"- {'<br>'.join(parts)}")

        child_list = child_list_of_li(li)
        if child_list:
            child_blocks = render_list_blocks(
                child_list,
                section_title=section_title,
                next_node=next_node,
                base_url=base_url,
            )
            for block in child_blocks:
                rendered_items.extend(block)

    return [rendered_items] if rendered_items else []


def render_table_blocks(node: Tag, *, base_url: str) -> tuple[list[list[str]], list[str]]:
    rows = html_table_to_rows(node, base_url)
    if not rows:
        return [], []
    output_columns: list[str] = []
    if len(rows) >= 2:
        output_columns = [strip_markdown_wrappers(row[0]) for row in rows[1:] if row and row[0]]
    return [rows_to_markdown(rows)], output_columns


def render_code_or_sample_blocks(
    node: Tag,
    *,
    section_title: Optional[str],
    output_columns: Optional[list[str]],
) -> list[list[str]]:
    text = extract_pre_like_text(node)
    if not text:
        return []

    if section_title in SAMPLE_SECTION_TITLES:
        rows = parse_sample_table(text, output_columns=output_columns)
        if rows:
            return [rows_to_markdown(rows)]
        return [["```text", text, "```"]]

    if section_title in USAGE_SECTION_TITLES:
        code_text, sample_text = split_mixed_code_and_sample(text, output_columns=output_columns)
        blocks: list[list[str]] = []
        if code_text:
            blocks.append(["```python", code_text, "```"])
        if sample_text:
            rows = parse_sample_table(sample_text, output_columns=output_columns)
            if rows:
                blocks.append(rows_to_markdown(rows))
            else:
                blocks.append(["```text", sample_text, "```"])
        return blocks

    language = "python" if looks_like_python(text) else "text"
    return [[f"```{language}", text, "```"]]


def render_markdown(entry: DocEntry, soup: BeautifulSoup) -> tuple[str, str, str]:
    content_root = find_content_root(soup)
    title, title_node = extract_doc_title(content_root, entry.title)
    nodes = iter_content_children(content_root)

    out: list[str] = [
        "---",
        yaml_json_line("title", title),
        yaml_json_line("doc_id", entry.doc_id),
        yaml_json_line("source_url", entry.url),
    ]
    if entry.title and entry.title != title:
        out.append(yaml_json_line("menu_title", entry.title))
    out.append(yaml_json_line("category_path", entry.category_path))
    out.append(yaml_json_line("scraped_at", time.strftime("%Y-%m-%d %H:%M:%S")))
    out.append("---")
    out.append("")
    out.append(f"# {title}")
    out.append("")
    if entry.category_path:
        out.append(f"- 分类：{' / '.join(entry.category_path)}")
    out.append(f"- 原始链接：[${entry.url}]({entry.url})".replace("[$", "["))  # keep a clickable URL
    out.append("")

    current_section: Optional[str] = None
    output_columns: list[str] = []
    intro_meta_lines: list[str] = []

    for idx, node in enumerate(nodes):
        if node is title_node or is_empty_node(node):
            continue

        section_heading = detect_section_heading(node, title_node)
        if section_heading:
            current_section = section_heading
            if current_section not in INTRO_SECTION_TITLES:
                if out and out[-1] != "":
                    out.append("")
                out.append(f"## {current_section}")
                out.append("")
            continue

        next_node = next_significant_node(nodes, idx + 1, title_node)

        blocks: list[list[str]] = []
        new_output_columns: list[str] = []

        if node.name == "table":
            blocks, new_output_columns = render_table_blocks(node, base_url=entry.url)
        elif node.name == "pre" or "codehilite" in (node.get("class") or []):
            blocks = render_code_or_sample_blocks(
                node,
                section_title=current_section,
                output_columns=output_columns or None,
            )
        elif node.name in {"ul", "ol"}:
            blocks = render_list_blocks(
                node,
                section_title=current_section,
                next_node=next_node,
                base_url=entry.url,
            )
        elif node.name in {"p", "div", "h1", "h2", "h3", "h4"}:
            blocks = render_paragraph_blocks(
                node,
                section_title=current_section,
                next_node=next_node,
                base_url=entry.url,
            )
        elif node.name == "img":
            url = guess_image_url(node, entry.url)
            if url:
                blocks = [[f"![页面附图]({url})"]]

        if current_section in INTRO_SECTION_TITLES or current_section is None:
            for block in blocks:
                intro_meta_lines.extend(block)
                if intro_meta_lines and intro_meta_lines[-1] != "":
                    intro_meta_lines.append("")
        else:
            for block in blocks:
                if not block:
                    continue
                if out and out[-1] != "":
                    out.append("")
                out.extend(block)
        if new_output_columns and current_section in OUTPUT_SECTION_TITLES:
            output_columns = new_output_columns

    while intro_meta_lines and not intro_meta_lines[-1]:
        intro_meta_lines.pop()
    if intro_meta_lines:
        insert_at = len(out)
        for idx, line in enumerate(out):
            if line.startswith("## "):
                insert_at = idx
                break
        prefix = out[:insert_at]
        suffix = out[insert_at:]
        if prefix and prefix[-1] != "":
            prefix.append("")
        prefix.extend(intro_meta_lines)
        if suffix and prefix and prefix[-1] != "":
            prefix.append("")
        out = prefix + suffix

    api_name = extract_api_name_from_lines(intro_meta_lines) or entry.api_name
    body_lines = "\n".join(out).strip().splitlines()
    if api_name and not any(line.startswith("api_name:") for line in body_lines):
        closing_idx = next((idx for idx, line in enumerate(body_lines[1:], start=1) if line == "---"), None)
        if closing_idx is not None:
            body_lines.insert(closing_idx, yaml_json_line("api_name", api_name))
    body_lines = patch_index_topic_input_params(body_lines, entry)
    body_text = "\n".join(body_lines).strip() + "\n"
    return body_text, title, api_name


def top_link_for_li(li: Tag) -> Optional[Tag]:
    for child in li.children:
        if isinstance(child, Tag) and child.name == "a":
            return child
    return None


def child_list_of_li(li: Tag) -> Optional[Tag]:
    for child in li.children:
        if isinstance(child, Tag) and child.name in {"ul", "ol"}:
            return child
    return None


def walk_menu_li(li: Tag, path: list[str], out: list[DocEntry], seen: set[int]) -> None:
    link = top_link_for_li(li)
    if link is None:
        return
    doc_id = extract_doc_id(link.get("href", ""))
    if doc_id is None or doc_id in seen:
        return

    title = normalize_space(link.get_text(" ", strip=True))
    child_list = child_list_of_li(li)
    is_leaf = child_list is None
    out.append(
        DocEntry(
            doc_id=doc_id,
            title=title,
            url=urljoin(ROOT_URL, link.get("href", "")),
            category_path=path[:],
            is_leaf=is_leaf,
        )
    )
    seen.add(doc_id)

    if child_list is not None:
        next_path = path + [title]
        for child_li in child_list.find_all("li", recursive=False):
            walk_menu_li(child_li, next_path, out, seen)


def discover_docs_from_root(client: GentleSession) -> list[DocEntry]:
    print(f"[info] fetching root page: {ROOT_URL}")
    html_text = client.get(ROOT_URL).text
    soup = soup_from_html(html_text)

    menu_root = soup.select_one("#jstree > ul")
    if menu_root is None:
        raise RuntimeError("menu root #jstree > ul not found")

    entries: list[DocEntry] = []
    seen: set[int] = set()
    for li in menu_root.find_all("li", recursive=False):
        walk_menu_li(li, [], entries, seen)
    entries.sort(key=lambda x: (x.doc_id, len(x.category_path), x.title))
    return entries


def _norm_menu_key(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip()


def _entry_full_path(entry: DocEntry) -> str:
    parts = [*entry.category_path, entry.title]
    return " / ".join([p for p in parts if p])


def select_entries_under_parent(entries: Sequence[DocEntry], parent_selector: str) -> tuple[DocEntry, list[DocEntry]]:
    selector = (parent_selector or "").strip()
    if not selector:
        raise ValueError("parent selector is empty")

    parent: Optional[DocEntry] = None

    if selector.isdigit():
        doc_id = int(selector)
        parent = next((e for e in entries if e.doc_id == doc_id), None)
    else:
        norm_selector = _norm_menu_key(selector.replace(">", "/"))
        exact_full = [e for e in entries if _norm_menu_key(_entry_full_path(e)) == norm_selector]
        if len(exact_full) == 1:
            parent = exact_full[0]
        elif len(exact_full) > 1:
            parent = sorted(exact_full, key=lambda e: (len(e.category_path), e.doc_id))[0]
        else:
            exact_title = [e for e in entries if _norm_menu_key(e.title) == norm_selector]
            if len(exact_title) == 1:
                parent = exact_title[0]
            elif len(exact_title) > 1:
                parent = sorted(exact_title, key=lambda e: (len(e.category_path), e.doc_id))[0]
            else:
                fuzzy = [
                    e for e in entries
                    if norm_selector in _norm_menu_key(_entry_full_path(e)) or norm_selector in _norm_menu_key(e.title)
                ]
                if len(fuzzy) == 1:
                    parent = fuzzy[0]
                elif len(fuzzy) > 1:
                    parent = sorted(fuzzy, key=lambda e: (len(e.category_path), e.doc_id))[0]

    if parent is None:
        raise ValueError(f"parent not found: {parent_selector}")

    subtree_prefix = parent.category_path + [parent.title]
    descendants: list[DocEntry] = []
    for entry in entries:
        if entry.doc_id == parent.doc_id:
            descendants.append(entry)
            continue
        if len(entry.category_path) >= len(subtree_prefix) and entry.category_path[:len(subtree_prefix)] == subtree_prefix:
            descendants.append(entry)
    descendants = sorted(descendants, key=lambda e: (len(e.category_path), e.doc_id, e.title))
    return parent, descendants


def resolve_entry_path_from_menu(entries: Sequence[DocEntry], entry: DocEntry) -> DocEntry:
    for item in entries:
        if item.doc_id == entry.doc_id:
            title = entry.title
            if not title or re.fullmatch(r"doc_\d+", title):
                title = item.title
            return DocEntry(
                doc_id=item.doc_id,
                title=title,
                url=entry.url,
                category_path=item.category_path,
                is_leaf=item.is_leaf,
                api_name=entry.api_name,
            )
    return entry


def build_single_entry(url: str, title: str) -> DocEntry:
    doc_id = extract_doc_id(url)
    if doc_id is None:
        raise ValueError(f"invalid single-url, doc_id not found: {url}")
    return DocEntry(doc_id=doc_id, title=title or f"doc_{doc_id}", url=url, category_path=[], is_leaf=True)


def choose_output_title(rendered_title: str, menu_title: str) -> str:
    rendered_title = normalize_space(rendered_title)
    menu_title = normalize_space(menu_title)
    if rendered_title and rendered_title not in CATEGORY_ONLY_HINTS:
        return rendered_title
    return menu_title or rendered_title or "untitled"


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_front_matter(path: Path) -> Optional[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    block = text[4:end]
    meta: dict[str, object] = {}
    for raw_line in block.splitlines():
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            continue
        try:
            meta[key] = json.loads(raw_value)
        except json.JSONDecodeError:
            meta[key] = raw_value
    return meta


def split_front_matter_and_body(text: str) -> tuple[str, list[str]]:
    if not text.startswith("---\n"):
        return "", text.rstrip("\n").splitlines()
    end = text.find("\n---\n", 4)
    if end < 0:
        return "", text.rstrip("\n").splitlines()
    front_matter = text[: end + 5].rstrip("\n")
    body = text[end + 5 :].lstrip("\n")
    return front_matter, body.rstrip("\n").splitlines()


def rebuild_markdown_text(front_matter: str, body_lines: Sequence[str]) -> str:
    parts: list[str] = []
    if front_matter:
        parts.append(front_matter)
    if body_lines:
        if parts:
            parts.append("")
        parts.append("\n".join(body_lines).rstrip())
    return "\n".join(parts).rstrip() + "\n"


def normalize_markdown_blank_lines(lines: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    in_fence = False
    previous_blank = False
    for line in lines:
        if line.startswith("```"):
            normalized.append(line)
            in_fence = not in_fence
            previous_blank = False
            continue
        if in_fence:
            normalized.append(line)
            continue
        is_blank = not line.strip()
        if is_blank:
            if previous_blank:
                continue
            normalized.append("")
            previous_blank = True
            continue
        normalized.append(line)
        previous_blank = False
    return trim_blank_edges(normalized)


def find_section_range(lines: Sequence[str], heading: str) -> Optional[tuple[int, int]]:
    normalized_heading = f"## {heading}"
    start_idx: Optional[int] = None
    for idx, line in enumerate(lines):
        if normalize_space(line) == normalized_heading:
            start_idx = idx + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        if lines[idx].startswith("## "):
            end_idx = idx
            break
    return start_idx, end_idx


def find_first_table_range(lines: Sequence[str], heading: str) -> Optional[tuple[int, int]]:
    section_range = find_section_range(lines, heading)
    if section_range is None:
        return None
    start_idx, end_idx = section_range
    table_start: Optional[int] = None
    for idx in range(start_idx, end_idx - 1):
        if lines[idx].startswith("|") and MARKDOWN_TABLE_SEP_RE.match(lines[idx + 1]):
            table_start = idx
            break
    if table_start is None:
        return None
    table_end = table_start + 2
    while table_end < end_idx and lines[table_end].startswith("|"):
        table_end += 1
    return table_start, table_end


def markdown_table_row_key(line: str) -> str:
    stripped = line.strip().strip("|")
    if not stripped:
        return ""
    cells = [cell.strip() for cell in stripped.split("|")]
    return cells[0] if cells else ""


def extract_table_rows_by_keys(
    lines: Sequence[str],
    heading: str,
    wanted_keys: Sequence[str],
) -> dict[str, str]:
    table_range = find_first_table_range(lines, heading)
    if table_range is None:
        return {}
    start_idx, end_idx = table_range
    wanted = {key.strip() for key in wanted_keys}
    found: dict[str, str] = {}
    for idx in range(start_idx + 2, end_idx):
        key = markdown_table_row_key(lines[idx])
        if key in wanted:
            found[key] = lines[idx]
    return found


def upsert_table_rows(lines: list[str], heading: str, rows_by_key: dict[str, str]) -> list[str]:
    if not rows_by_key:
        return lines
    table_range = find_first_table_range(lines, heading)
    if table_range is None:
        return lines
    start_idx, end_idx = table_range
    updated = list(lines)
    existing_row_positions: dict[str, int] = {}
    for idx in range(start_idx + 2, end_idx):
        key = markdown_table_row_key(updated[idx])
        if key:
            existing_row_positions[key] = idx
    for key, row_line in rows_by_key.items():
        if key in existing_row_positions:
            updated[existing_row_positions[key]] = row_line
    insert_rows = [row_line for key, row_line in rows_by_key.items() if key not in existing_row_positions]
    if insert_rows:
        updated = updated[:end_idx] + insert_rows + updated[end_idx:]
    return updated


def trim_blank_edges(lines: Sequence[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def extract_marker_block(lines: Sequence[str], marker: str) -> list[str]:
    start_idx: Optional[int] = None
    normalized_marker = normalize_space(marker)
    for idx, line in enumerate(lines):
        if normalize_space(line) == normalized_marker:
            start_idx = idx
            break
    if start_idx is None:
        return []
    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].startswith("## "):
            end_idx = idx
            break
    return trim_blank_edges(lines[start_idx:end_idx])


def find_first_line_by_prefix(lines: Sequence[str], prefix: str) -> str:
    for line in lines:
        if line.startswith(prefix):
            return line
    return ""


def contains_normalized_line(lines: Sequence[str], target: str) -> bool:
    normalized_target = normalize_space(target)
    return any(normalize_space(line) == normalized_target for line in lines)


def insert_line_before(lines: list[str], *, line: str, before_line: str) -> list[str]:
    if contains_normalized_line(lines, line):
        return lines

    insert_idx: Optional[int] = None
    normalized_before = normalize_space(before_line)
    for idx, current in enumerate(lines):
        if normalize_space(current) == normalized_before:
            insert_idx = idx
            break
    if insert_idx is None:
        return lines

    prefix = list(lines[:insert_idx])
    suffix = list(lines[insert_idx:])
    if prefix and prefix[-1] != "":
        prefix.append("")
    prefix.append(line)
    if suffix and prefix[-1] != "":
        prefix.append("")
    return prefix + suffix


def upsert_marker_block(lines: list[str], block_lines: Sequence[str], marker: str, before_heading: str) -> list[str]:
    block = trim_blank_edges(block_lines)
    if not block:
        return lines

    updated = list(lines)
    normalized_marker = normalize_space(marker)
    existing_start: Optional[int] = None
    for idx, line in enumerate(updated):
        if normalize_space(line) == normalized_marker:
            existing_start = idx
            break
    if existing_start is not None:
        existing_end = len(updated)
        for idx in range(existing_start + 1, len(updated)):
            if updated[idx].startswith("## "):
                existing_end = idx
                break
        updated = updated[:existing_start] + updated[existing_end:]

    insert_idx = len(updated)
    normalized_heading = normalize_space(before_heading)
    for idx, line in enumerate(updated):
        if normalize_space(line) == normalized_heading:
            insert_idx = idx
            break

    prefix = updated[:insert_idx]
    suffix = updated[insert_idx:]
    if prefix and prefix[-1] != "":
        prefix.append("")
    prefix.extend(block)
    if suffix and prefix and prefix[-1] != "":
        prefix.append("")
    return prefix + suffix


def scan_generated_docs(out_dir: Path) -> list[dict[str, object]]:
    docs: list[dict[str, object]] = []
    for path in sorted(out_dir.rglob("*.md")):
        if path.name == "README.md":
            continue
        meta = read_front_matter(path)
        if not meta or "doc_id" not in meta or "title" not in meta:
            continue
        rel = os.path.relpath(path, out_dir).replace("\\", "/")
        docs.append(
            {
                "doc_id": meta["doc_id"],
                "title": meta["title"],
                "api_name": meta.get("api_name", ""),
                "category_path": meta.get("category_path", []),
                "source_url": meta.get("source_url", ""),
                "local_path": rel,
            }
        )
    docs.sort(key=lambda x: (int(x["doc_id"]), x["local_path"]))
    return docs


def build_publish_manifest_from_docs(publish_dir: Path) -> dict[str, object]:
    docs = scan_generated_docs(publish_dir)
    if not docs:
        raise RuntimeError(f"未在目录发现可抽取清单的文档: {publish_dir}")

    docs_by_id = {int(item["doc_id"]): publish_dir / str(item["local_path"]) for item in docs}

    limit_offset_input_rows: dict[str, dict[str, str]] = {}
    table_row_patches: dict[str, dict[str, dict[str, str]]] = {}
    block_patches: dict[str, list[dict[str, object]]] = {}
    line_insertions: dict[str, list[dict[str, str]]] = {}
    fixed_line_prefix_replacements: dict[str, dict[str, str]] = {}

    for doc_id, path in docs_by_id.items():
        _, body_lines = split_front_matter_and_body(path.read_text(encoding="utf-8"))

        limit_offset_rows = extract_table_rows_by_keys(
            body_lines,
            "输入参数",
            [LIMIT_INPUT_ROW_KEY, OFFSET_INPUT_ROW_KEY],
        )
        # 兼容历史手工修订：少数旧文档曾把 limit/offset 误加到“输出参数”表里。
        # 清单重建时仍按“输入参数补丁”提取，避免这类分页参数在首次 manifest 化时丢失。
        if len(limit_offset_rows) != 2:
            legacy_output_rows = extract_table_rows_by_keys(
                body_lines,
                "输出参数",
                [LIMIT_INPUT_ROW_KEY, OFFSET_INPUT_ROW_KEY],
            )
            if len(legacy_output_rows) == 2:
                limit_offset_rows = legacy_output_rows
        if len(limit_offset_rows) == 2:
            limit_offset_input_rows[str(doc_id)] = limit_offset_rows

        for section_heading, row_keys in MANIFEST_TABLE_ROW_SPECS.get(doc_id, {}).items():
            rows = extract_table_rows_by_keys(body_lines, section_heading, row_keys)
            if rows:
                table_row_patches.setdefault(str(doc_id), {})[section_heading] = rows

        for block_rule in MANIFEST_BLOCK_SPECS.get(doc_id, []):
            block_lines = extract_marker_block(body_lines, block_rule["marker"])
            if block_lines:
                block_patches.setdefault(str(doc_id), []).append(
                    {
                        "marker": block_rule["marker"],
                        "before_heading": block_rule["before_heading"],
                        "lines": block_lines,
                    }
                )

        for line_rule in MANIFEST_LINE_INSERTION_SPECS.get(doc_id, []):
            line_value = str(line_rule["line"])
            before_value = str(line_rule["before_line"])
            if contains_normalized_line(body_lines, line_value) and contains_normalized_line(body_lines, before_value):
                line_insertions.setdefault(str(doc_id), []).append(
                    {
                        "line": line_value,
                        "before_line": before_value,
                    }
                )

        prefixes = MANIFEST_FIXED_LINE_PREFIX_SPECS.get(doc_id, [])
        if prefixes:
            found_lines = {
                prefix: line
                for prefix in prefixes
                if (line := find_first_line_by_prefix(body_lines, prefix))
            }
            if found_lines:
                fixed_line_prefix_replacements[str(doc_id)] = found_lines

    return {
        "schema_version": 1,
        "generated_from": str(publish_dir),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "usage_note": MANIFEST_USAGE_NOTE,
        "field_notes": MANIFEST_FIELD_NOTES,
        "limit_offset_input_rows": limit_offset_input_rows,
        "table_row_patches": table_row_patches,
        "block_patches": block_patches,
        "line_insertions": line_insertions,
        "fixed_line_prefix_replacements": fixed_line_prefix_replacements,
        "exact_line_removals": MANIFEST_EXACT_LINE_REMOVALS_DEFAULT,
    }


def load_publish_manifest(manifest_path: Path) -> dict[str, object]:
    if not manifest_path.exists():
        raise RuntimeError(f"发布清单不存在: {manifest_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"发布清单 JSON 非法: {manifest_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"发布清单格式不合法: {manifest_path}")
    return raw


def write_docs_index_csv(out_dir: Path, docs: Sequence[dict[str, object]]) -> None:
    with (out_dir / "docs_index.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["doc_id", "title", "api_name", "category_path", "source_url", "local_path"],
        )
        writer.writeheader()
        for row in docs:
            writer.writerow(
                {
                    **row,
                    "category_path": " / ".join(row["category_path"]),
                }
            )


def write_docs_readme(out_dir: Path, docs: Sequence[dict[str, object]]) -> None:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in docs:
        key = " / ".join(row["category_path"]) if row["category_path"] else "未分类"
        grouped.setdefault(key, []).append(row)

    lines: list[str] = ["# Tushare 接口文档索引", ""]
    for key in sorted(grouped.keys()):
        lines.append(f"## {key}")
        lines.append("")
        for row in sorted(grouped[key], key=lambda x: int(x["doc_id"])):
            lines.append(f"- [{row['title']}]({row['local_path']})")
        lines.append("")
    save_text(out_dir / "README.md", "\n".join(lines).rstrip() + "\n")


def apply_publish_patches(staged_text: str, doc_id: int, manifest: dict[str, object]) -> str:
    front_matter, staged_body_lines = split_front_matter_and_body(staged_text)
    doc_key = str(doc_id)

    limit_offset_rows = (
        manifest.get("limit_offset_input_rows", {}).get(doc_key, {})
        if isinstance(manifest.get("limit_offset_input_rows", {}), dict)
        else {}
    )
    if isinstance(limit_offset_rows, dict) and len(limit_offset_rows) == 2:
        staged_body_lines = upsert_table_rows(staged_body_lines, "输入参数", limit_offset_rows)

    table_row_patches = manifest.get("table_row_patches", {})
    if isinstance(table_row_patches, dict):
        for section_heading, rows_by_key in table_row_patches.get(doc_key, {}).items():
            if isinstance(rows_by_key, dict) and rows_by_key:
                staged_body_lines = upsert_table_rows(staged_body_lines, section_heading, rows_by_key)

    block_patches = manifest.get("block_patches", {})
    if isinstance(block_patches, dict):
        for block_rule in block_patches.get(doc_key, []):
            if not isinstance(block_rule, dict):
                continue
            block_lines = block_rule.get("lines", [])
            if not isinstance(block_lines, list) or not block_lines:
                continue
            staged_body_lines = upsert_marker_block(
                staged_body_lines,
                block_lines,
                marker=str(block_rule["marker"]),
                before_heading=str(block_rule["before_heading"]),
            )

    line_insertions = manifest.get("line_insertions", {})
    if isinstance(line_insertions, dict):
        for line_rule in line_insertions.get(doc_key, []):
            if not isinstance(line_rule, dict):
                continue
            line_value = line_rule.get("line")
            before_value = line_rule.get("before_line")
            if not isinstance(line_value, str) or not isinstance(before_value, str):
                continue
            staged_body_lines = insert_line_before(
                staged_body_lines,
                line=line_value,
                before_line=before_value,
            )

    fixed_line_replacements = manifest.get("fixed_line_prefix_replacements", {})
    fixed_lines = fixed_line_replacements.get(doc_key, {}) if isinstance(fixed_line_replacements, dict) else {}
    if isinstance(fixed_lines, dict) and fixed_lines:
        replaced_lines: list[str] = []
        for line in staged_body_lines:
            replacement = next((value for prefix, value in fixed_lines.items() if line.startswith(prefix)), None)
            replaced_lines.append(replacement if replacement is not None else line)
        staged_body_lines = replaced_lines

    exact_line_removals = manifest.get("exact_line_removals", {})
    raw_removals = exact_line_removals.get(doc_key, []) if isinstance(exact_line_removals, dict) else []
    removals = {line for line in raw_removals if isinstance(line, str)}
    if removals:
        staged_body_lines = [line for line in staged_body_lines if line not in removals]

    staged_body_lines = normalize_markdown_blank_lines(staged_body_lines)
    return rebuild_markdown_text(front_matter, staged_body_lines)


def remove_empty_directories(root: Path) -> None:
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        if any(path.iterdir()):
            continue
        path.rmdir()


def remove_noise_files(root: Path) -> None:
    for pattern in (".DS_Store", "._*"):
        for path in root.rglob(pattern):
            if path.is_file():
                path.unlink()


def rebuild_publish_indexes(out_dir: Path) -> None:
    docs = scan_generated_docs(out_dir)
    write_docs_index_csv(out_dir, docs)
    write_docs_readme(out_dir, docs)


def publish_docs(staging_dir: Path, publish_dir: Path, *, prune: bool, manifest_path: Path) -> None:
    staged_docs = scan_generated_docs(staging_dir)
    if not staged_docs:
        raise RuntimeError(f"未在 staging 目录发现可发布的 Markdown 文档: {staging_dir}")

    publish_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_publish_manifest(manifest_path)

    target_relative_paths: set[str] = set()
    for row in staged_docs:
        doc_id = int(row["doc_id"])
        relative_path = str(row["local_path"])
        staging_path = staging_dir / relative_path
        publish_path = publish_dir / relative_path

        staged_text = staging_path.read_text(encoding="utf-8")
        final_text = apply_publish_patches(staged_text, doc_id, manifest)
        save_text(publish_path, final_text)
        target_relative_paths.add(relative_path)
        print(f"[publish] {doc_id} -> {publish_path}")

    if prune:
        for path in sorted(publish_dir.rglob("*.md")):
            if path.name == "README.md":
                continue
            relative_path = os.path.relpath(path, publish_dir).replace("\\", "/")
            if relative_path in target_relative_paths:
                continue
            path.unlink()
            print(f"[delete] {path}")
        remove_empty_directories(publish_dir)

    remove_noise_files(publish_dir)
    rebuild_publish_indexes(publish_dir)
    print(
        f"[publish-done] docs={len(staged_docs)} "
        f"prune={'yes' if prune else 'no'} "
        f"manifest={manifest_path} "
        f"target={publish_dir.resolve()}"
    )


def rebuild_indexes(out_dir: Path, discovered_entries: Optional[Sequence[DocEntry]] = None) -> None:
    remove_noise_files(out_dir)
    if discovered_entries is not None:
        save_text(
            out_dir / "index.discovered.json",
            json.dumps([asdict(x) for x in discovered_entries], ensure_ascii=False, indent=2),
        )
        save_text(
            out_dir / "index.category.json",
            json.dumps([asdict(x) for x in discovered_entries if not x.is_leaf], ensure_ascii=False, indent=2),
        )

    docs = scan_generated_docs(out_dir)
    leaf_entries = [
        DocEntry(
            doc_id=int(item["doc_id"]),
            title=str(item["title"]),
            url=str(item["source_url"]),
            category_path=list(item["category_path"]),
            is_leaf=True,
            api_name=str(item["api_name"]),
        )
        for item in docs
    ]
    save_text(out_dir / "index.leaf.json", json.dumps([asdict(x) for x in leaf_entries], ensure_ascii=False, indent=2))
    save_text(out_dir / "docs_index.json", json.dumps(docs, ensure_ascii=False, indent=2))
    write_docs_index_csv(out_dir, docs)
    write_docs_readme(out_dir, docs)


def should_keep(entry: DocEntry, include: Optional[str]) -> bool:
    if not include:
        return True
    joined = " / ".join(entry.category_path + [entry.title])
    return include in joined


def fetch_and_save_leaf_docs(
    client: GentleSession,
    entries: Iterable[DocEntry],
    out_dir: Path,
    *,
    include: Optional[str],
    max_pages: Optional[int],
    discovered_entries: Optional[Sequence[DocEntry]] = None,
) -> None:
    total_checked = 0
    total_saved = 0
    for entry in entries:
        if not entry.is_leaf:
            continue
        if not should_keep(entry, include):
            continue
        if max_pages is not None and total_checked >= max_pages:
            break

        total_checked += 1
        print(f"[check] {entry.doc_id} {entry.title} -> {entry.url}")
        try:
            html_text = client.get(entry.url).text
            soup = soup_from_html(html_text)
        except Exception as exc:  # noqa: BLE001
            print(f"[error] skip {entry.url}: {exc}", file=sys.stderr)
            continue

        md, rendered_title, api_name = render_markdown(entry, soup)
        filename_title = choose_output_title(rendered_title, entry.title)
        saved_entry = DocEntry(
            doc_id=entry.doc_id,
            title=filename_title,
            url=entry.url,
            category_path=entry.category_path,
            is_leaf=True,
            api_name=api_name,
        )
        folder = out_dir
        if saved_entry.category_path:
            folder = out_dir.joinpath(*[sanitize_filename(x) for x in saved_entry.category_path])
        filename = f"{saved_entry.doc_id:04d}_{sanitize_filename(filename_title)}.md"
        save_path = folder / filename
        save_text(save_path, md)
        total_saved += 1
        print(f"[saved] {save_path}")

    rebuild_indexes(out_dir, discovered_entries=discovered_entries)
    print(f"[done] checked={total_checked}, saved_leaf={total_saved}, output={out_dir.resolve()}")


def parse_doc_ids_arg(raw: str) -> list[int]:
    values: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"invalid doc id: {part}")
        values.append(int(part))
    if not values:
        raise ValueError("doc id list is empty")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取 Tushare 叶子接口文档并导出 Markdown（DOM-first 版本）")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--min-delay", type=float, default=4.0, help="最小等待秒数，默认 4")
    parser.add_argument("--max-delay", type=float, default=8.0, help="最大等待秒数，默认 8")
    parser.add_argument("--max-pages", type=int, default=None, help="最多抓取多少个叶子页面")
    parser.add_argument("--include", type=str, default=None, help="仅处理标题或分类路径中包含该关键词的页面")
    parser.add_argument("--single-url", type=str, default=None, help="仅抓取一个指定页面")
    parser.add_argument("--single-title", type=str, default="", help="配合 --single-url 使用")
    parser.add_argument(
        "--parent",
        type=str,
        default=None,
        help="指定父节点，只抓该菜单节点下的所有叶子页。可传 doc_id、标题，或完整路径，例如 15 或 '股票数据 / 行情数据'",
    )
    parser.add_argument("--doc-ids", type=str, default=None, help="仅抓取逗号分隔的 doc_id 列表，例如 25,49,109,146")
    parser.add_argument("--publish-to", type=str, default=None, help="将加工后的 Markdown 发布到正式目录")
    parser.add_argument("--publish-prune", action="store_true", help="发布时删除正式目录中 staging 不再存在的旧文档")
    parser.add_argument("--publish-only", action="store_true", help="仅把现有 --out 目录发布到 --publish-to，不进行抓取")
    parser.add_argument("--publish-manifest", type=str, default=str(DEFAULT_PUBLISH_MANIFEST_PATH), help="发布补丁清单路径")
    parser.add_argument("--rebuild-publish-manifest-from", type=str, default=None, help="从正式文档目录反向生成发布补丁清单并写入 --publish-manifest")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.min_delay <= 0 or args.max_delay <= 0 or args.max_delay < args.min_delay:
        print("[error] delay 参数不合法", file=sys.stderr)
        return 2

    mode_count = sum(bool(x) for x in (args.single_url, args.parent, args.doc_ids))
    if mode_count > 1:
        print("[error] --single-url、--parent、--doc-ids 不能同时使用", file=sys.stderr)
        return 2

    if args.publish_only and not args.publish_to:
        print("[error] --publish-only 需要配合 --publish-to 使用", file=sys.stderr)
        return 2

    if args.publish_only and any((args.single_url, args.parent, args.doc_ids, args.include, args.max_pages is not None)):
        print("[error] --publish-only 不能与抓取筛选参数同时使用", file=sys.stderr)
        return 2

    if args.rebuild_publish_manifest_from and any((args.single_url, args.parent, args.doc_ids, args.publish_only)):
        print("[error] --rebuild-publish-manifest-from 不能与抓取/发布执行参数同时使用", file=sys.stderr)
        return 2

    manifest_path = Path(args.publish_manifest)

    if args.rebuild_publish_manifest_from:
        source_dir = Path(args.rebuild_publish_manifest_from)
        if not source_dir.exists():
            print(f"[error] manifest source 目录不存在: {source_dir}", file=sys.stderr)
            return 2
        manifest = build_publish_manifest_from_docs(source_dir)
        save_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(f"[manifest] rebuilt -> {manifest_path}")
        return 0

    out_dir = Path(args.out)

    if args.publish_only:
        if not out_dir.exists():
            print(f"[error] staging 目录不存在: {out_dir}", file=sys.stderr)
            return 2
        try:
            publish_docs(out_dir, Path(args.publish_to), prune=args.publish_prune, manifest_path=manifest_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[error] publish failed: {exc}", file=sys.stderr)
            return 1
        return 0

    is_partial_scrape = any((args.single_url, args.parent, args.doc_ids, args.include, args.max_pages is not None))
    if args.publish_prune and is_partial_scrape:
        print("[error] 使用抓取筛选参数时不能开启 --publish-prune，避免误删正式目录文档", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    client = GentleSession(min_delay=args.min_delay, max_delay=args.max_delay)

    discovered = discover_docs_from_root(client)
    print(f"[info] discovered {len(discovered)} menu nodes from root")

    if args.single_url:
        entry = build_single_entry(args.single_url, args.single_title)
        entry = resolve_entry_path_from_menu(discovered, entry)
        fetch_and_save_leaf_docs(
            client=client,
            entries=[entry],
            out_dir=out_dir,
            include=args.include,
            max_pages=1,
            discovered_entries=discovered,
        )
        if args.publish_to:
            publish_docs(out_dir, Path(args.publish_to), prune=args.publish_prune, manifest_path=manifest_path)
        return 0

    if args.doc_ids:
        try:
            wanted = set(parse_doc_ids_arg(args.doc_ids))
        except ValueError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 2
        selected = [entry for entry in discovered if entry.doc_id in wanted]
        if not selected:
            print("[error] requested doc ids not found in menu", file=sys.stderr)
            return 2
        fetch_and_save_leaf_docs(
            client=client,
            entries=selected,
            out_dir=out_dir,
            include=args.include,
            max_pages=args.max_pages,
            discovered_entries=discovered,
        )
        if args.publish_to:
            publish_docs(out_dir, Path(args.publish_to), prune=args.publish_prune, manifest_path=manifest_path)
        return 0

    if args.parent:
        try:
            parent, entries = select_entries_under_parent(discovered, args.parent)
        except ValueError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 2
        print(f"[info] selected parent: {parent.doc_id} {_entry_full_path(parent)}")
        print(f"[info] subtree size: {len(entries)} nodes")
        fetch_and_save_leaf_docs(
            client=client,
            entries=entries,
            out_dir=out_dir,
            include=args.include,
            max_pages=args.max_pages,
            discovered_entries=discovered,
        )
        if args.publish_to:
            publish_docs(out_dir, Path(args.publish_to), prune=args.publish_prune, manifest_path=manifest_path)
        return 0

    fetch_and_save_leaf_docs(
        client=client,
        entries=[entry for entry in discovered if entry.is_leaf],
        out_dir=out_dir,
        include=args.include,
        max_pages=args.max_pages,
        discovered_entries=discovered,
    )
    if args.publish_to:
        publish_docs(out_dir, Path(args.publish_to), prune=args.publish_prune, manifest_path=manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
