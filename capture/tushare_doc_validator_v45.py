#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tushare 文档校验器 v45

目标：
1. 校验本地生成的 Markdown front matter 与基础结构。
2. 回源页对照标题、关键 section、链接保留情况。
3. 对数据样例做“可见行数”校验，避免明显丢行。
4. 输出 JSON 报告，便于批量复查与后续回归。

示例：
    python3 tushare_doc_validator_v45.py --out ./capture/tushare-staging
    python3 tushare_doc_validator_v45.py --out ./capture/tushare-staging --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from bs4 import Tag

from tushare_leaf_doc_scraper_v45 import (
    GentleSession,
    detect_section_heading,
    extract_doc_title,
    extract_pre_like_text,
    find_content_root,
    html_table_to_rows,
    iter_content_children,
    looks_like_sample_data_row_line,
    normalize_space,
    parse_sample_table,
    read_front_matter,
    scan_generated_docs,
    soup_from_html,
    strip_markdown_wrappers,
)

REQUIRED_FRONT_MATTER_KEYS = {
    "title",
    "doc_id",
    "source_url",
    "category_path",
    "scraped_at",
}
INTRO_SECTION_TITLES = {"接口介绍"}
SAMPLE_SECTION_TITLES = {"数据样例"}
OUTPUT_SECTION_TITLES = {"输出参数", "东财数据输出参数", "新浪数据输出参数"}
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
MARKDOWN_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
MARKDOWN_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
MARKDOWN_TABLE_SEP_RE = re.compile(r"^\|\s*(?::?-{3,}:?\s*\|\s*)+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验 Tushare Markdown 文档与源页面的一致性")
    parser.add_argument("--out", required=True, help="待校验的输出目录")
    parser.add_argument("--report", default=None, help="JSON 报告输出路径，默认写到输出目录下 validation_report.json")
    parser.add_argument("--max-docs", type=int, default=None, help="最多校验多少篇文档")
    parser.add_argument("--min-delay", type=float, default=0.1, help="请求最小等待秒数")
    parser.add_argument("--max-delay", type=float, default=0.2, help="请求最大等待秒数")
    parser.add_argument("--strict", action="store_true", help="存在 error 时返回非 0")
    return parser.parse_args()


def canonical_url(url: str, base_url: str = "") -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    absolute = urljoin(base_url, raw) if base_url else raw
    parsed = urlsplit(absolute)
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = "&".join(
        f"{key}={value}" if value else key
        for key, value in sorted(parse_qsl(parsed.query, keep_blank_values=True))
    )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def read_markdown_doc(path: Path) -> tuple[Optional[dict[str, object]], str]:
    text = path.read_text(encoding="utf-8")
    meta = read_front_matter(path)
    if not meta or not text.startswith("---\n"):
        return meta, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return meta, text
    body = text[end + 5 :].lstrip("\n")
    return meta, body


def extract_markdown_links(text: str) -> set[str]:
    links: set[str] = set()
    for raw in MARKDOWN_LINK_RE.findall(text):
        url = canonical_url(raw)
        if url:
            links.add(url)
    return links


def extract_markdown_h1(body: str) -> str:
    match = MARKDOWN_H1_RE.search(body)
    return normalize_space(match.group(1)) if match else ""


def extract_markdown_h2s(body: str) -> set[str]:
    return {normalize_space(match.group(1)) for match in MARKDOWN_H2_RE.finditer(body)}


def extract_markdown_section(body: str, heading: str) -> str:
    lines = body.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if normalize_space(line) == f"## {heading}":
            start = idx + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    return "\n".join(lines[start:end]).strip()


def count_markdown_tables(text: str) -> int:
    lines = text.splitlines()
    total = 0
    i = 0
    while i + 1 < len(lines):
        if lines[i].startswith("|") and MARKDOWN_TABLE_SEP_RE.match(lines[i + 1]):
            total += 1
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                i += 1
            continue
        i += 1
    return total


def count_markdown_table_rows(text: str) -> int:
    lines = text.splitlines()
    total = 0
    i = 0
    while i + 1 < len(lines):
        if lines[i].startswith("|") and MARKDOWN_TABLE_SEP_RE.match(lines[i + 1]):
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                total += 1
                i += 1
            continue
        i += 1
    return total


def count_visible_sample_rows_text(text: str) -> int:
    total = 0
    for raw_line in text.splitlines():
        line = normalize_space(raw_line)
        if not line:
            continue
        if re.match(r"^\d+\s+\S+", line):
            total += 1
            continue
        if looks_like_sample_data_row_line(line):
            total += 1
    return total


def count_markdown_code_sample_rows(text: str) -> int:
    total = 0
    in_fence = False
    fence_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("```"):
            if in_fence:
                total += count_visible_sample_rows_text("\n".join(fence_lines))
                fence_lines = []
                in_fence = False
            else:
                in_fence = True
            continue
        if in_fence:
            fence_lines.append(line)
    return total


def count_markdown_sample_rows(text: str) -> int:
    return count_markdown_table_rows(text) + count_markdown_code_sample_rows(text)


def extract_source_links(content_root: Tag, base_url: str) -> set[str]:
    links: set[str] = set()
    for anchor in content_root.select("a[href]"):
        href = canonical_url(anchor.get("href", ""), base_url=base_url)
        label = normalize_space(anchor.get_text(" ", strip=True))
        if not href or not label:
            continue
        links.add(href)
    return links


def extract_source_sections(content_root: Tag) -> tuple[str, list[str]]:
    title, title_node = extract_doc_title(content_root, "")
    sections: list[str] = []
    seen: set[str] = set()
    for node in iter_content_children(content_root):
        heading = detect_section_heading(node, title_node)
        if not heading or heading in seen:
            continue
        sections.append(heading)
        seen.add(heading)
    return title, sections


def count_source_tables(content_root: Tag, base_url: str) -> int:
    total = 0
    for table in content_root.find_all("table"):
        rows = html_table_to_rows(table, base_url)
        if len(rows) >= 2 and max((len(row) for row in rows), default=0) >= 2:
            total += 1
    return total


def count_source_sample_rows(content_root: Tag, base_url: str) -> int:
    title, title_node = extract_doc_title(content_root, "")
    current_section: Optional[str] = None
    output_columns: list[str] = []
    total = 0
    for node in iter_content_children(content_root):
        heading = detect_section_heading(node, title_node)
        if heading:
            current_section = heading
            continue
        if current_section in OUTPUT_SECTION_TITLES and node.name == "table":
            rows = html_table_to_rows(node, base_url)
            if len(rows) >= 2:
                output_columns = [strip_markdown_wrappers(row[0]) for row in rows[1:] if row and row[0]]
        if current_section not in SAMPLE_SECTION_TITLES:
            continue
        if node.name == "table":
            rows = html_table_to_rows(node, base_url)
            if len(rows) >= 2:
                total += len(rows) - 1
            continue
        if node.name == "pre" or "codehilite" in (node.get("class") or []):
            text = extract_pre_like_text(node)
            rows = parse_sample_table(text, output_columns=output_columns or None)
            if rows and len(rows) >= 2:
                total += len(rows) - 1
            else:
                total += count_visible_sample_rows_text(text)
    return total


def validate_doc(path: Path, client: GentleSession) -> dict[str, object]:
    meta, body = read_markdown_doc(path)
    rel_path = path.as_posix()
    result: dict[str, object] = {
        "local_path": rel_path,
        "doc_id": None,
        "title": "",
        "errors": [],
        "warnings": [],
        "metrics": {},
    }
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not meta:
        errors.append({"code": "missing_front_matter", "message": "缺少或无法解析 front matter"})
        result["errors"] = errors
        result["warnings"] = warnings
        return result

    result["doc_id"] = meta.get("doc_id")
    result["title"] = str(meta.get("title", ""))

    missing_keys = sorted(REQUIRED_FRONT_MATTER_KEYS - set(meta.keys()))
    if missing_keys:
        errors.append(
            {
                "code": "front_matter_keys_missing",
                "message": f"front matter 缺少字段: {', '.join(missing_keys)}",
            }
        )

    doc_id = meta.get("doc_id")
    source_url = str(meta.get("source_url", ""))
    title = normalize_space(str(meta.get("title", "")))
    markdown_h1 = extract_markdown_h1(body)
    md_links = extract_markdown_links(body)
    md_h2s = extract_markdown_h2s(body)
    md_table_count = count_markdown_tables(body)
    md_sample_rows = count_markdown_sample_rows(extract_markdown_section(body, "数据样例"))

    if not isinstance(doc_id, int):
        errors.append({"code": "doc_id_invalid", "message": "front matter 中的 doc_id 不是整数"})
    else:
        expected_prefix = f"{doc_id:04d}_"
        if not path.name.startswith(expected_prefix):
            warnings.append(
                {
                    "code": "filename_prefix_mismatch",
                    "message": f"文件名未以 {expected_prefix} 开头",
                }
            )

    if not source_url:
        errors.append({"code": "source_url_missing", "message": "front matter 中缺少 source_url"})

    if title and markdown_h1 and title != markdown_h1:
        errors.append(
            {
                "code": "title_h1_mismatch",
                "message": f"front matter title 与 H1 不一致: {title} != {markdown_h1}",
            }
        )

    if source_url and canonical_url(source_url) not in md_links:
        errors.append({"code": "source_url_not_linked", "message": "正文中未保留原始链接"})

    if body and "- 分类：" not in body:
        warnings.append({"code": "category_line_missing", "message": "正文中缺少分类行"})

    if "- 接口：" in body and not meta.get("api_name"):
        warnings.append({"code": "api_name_missing", "message": "正文存在接口信息，但 front matter 缺少 api_name"})

    if not source_url or not isinstance(doc_id, int):
        result["errors"] = errors
        result["warnings"] = warnings
        result["metrics"] = {
            "markdown_links": len(md_links),
            "markdown_tables": md_table_count,
            "markdown_sample_rows": md_sample_rows,
        }
        return result

    try:
        html_text = client.get(source_url).text
        soup = soup_from_html(html_text)
        content_root = find_content_root(soup)
    except Exception as exc:  # noqa: BLE001
        errors.append({"code": "source_fetch_failed", "message": f"源页抓取失败: {exc}"})
        result["errors"] = errors
        result["warnings"] = warnings
        result["metrics"] = {
            "markdown_links": len(md_links),
            "markdown_tables": md_table_count,
            "markdown_sample_rows": md_sample_rows,
        }
        return result

    source_title, source_sections = extract_source_sections(content_root)
    source_links = extract_source_links(content_root, source_url)
    missing_links = sorted(link for link in source_links if link not in md_links)
    source_table_count = count_source_tables(content_root, source_url)
    source_sample_rows = count_source_sample_rows(content_root, source_url)
    normalized_source_title = normalize_space(source_title)
    has_source_structure = bool(source_sections or source_links or source_table_count or source_sample_rows)

    if title and normalized_source_title and normalized_source_title != "untitled" and title != normalized_source_title:
        errors.append(
            {
                "code": "source_title_mismatch",
                "message": f"源页标题与 Markdown 标题不一致: {source_title} != {title}",
            }
        )
    elif title and normalized_source_title == "untitled" and not has_source_structure:
        warnings.append(
            {
                "code": "source_dom_empty",
                "message": "源页返回空正文，跳过标题与结构校验",
            }
        )

    for section in source_sections:
        if section in INTRO_SECTION_TITLES:
            continue
        if section not in md_h2s:
            errors.append(
                {
                    "code": "section_missing",
                    "message": f"Markdown 缺少 section: {section}",
                }
            )

    if missing_links:
        errors.append(
            {
                "code": "source_links_missing",
                "message": f"缺少 {len(missing_links)} 个源页链接: {', '.join(missing_links[:5])}",
            }
        )

    if md_table_count < source_table_count:
        warnings.append(
            {
                "code": "table_count_lower_than_source",
                "message": f"Markdown 表格数少于源页: {md_table_count} < {source_table_count}",
            }
        )

    if source_sample_rows > 0 and md_sample_rows == 0:
        errors.append({"code": "sample_section_missing", "message": "源页存在数据样例，但 Markdown 未提取出样例"})
    elif md_sample_rows < source_sample_rows:
        errors.append(
            {
                "code": "sample_rows_dropped",
                "message": f"数据样例可见行数变少: {md_sample_rows} < {source_sample_rows}",
            }
        )

    result["errors"] = errors
    result["warnings"] = warnings
    result["metrics"] = {
        "source_sections": source_sections,
        "markdown_sections": sorted(md_h2s),
        "source_links": len(source_links),
        "markdown_links": len(md_links),
        "missing_links": len(missing_links),
        "source_tables": source_table_count,
        "markdown_tables": md_table_count,
        "source_sample_rows": source_sample_rows,
        "markdown_sample_rows": md_sample_rows,
    }
    return result


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out)
    if not out_dir.exists():
        print(f"[error] 输出目录不存在: {out_dir}", file=sys.stderr)
        return 2

    docs = scan_generated_docs(out_dir)
    if args.max_docs is not None:
        docs = docs[: args.max_docs]
    if not docs:
        print(f"[error] 未在 {out_dir} 下发现可校验的 Markdown 文档", file=sys.stderr)
        return 2

    client = GentleSession(min_delay=args.min_delay, max_delay=args.max_delay)
    results: list[dict[str, object]] = []
    error_docs = 0
    warning_docs = 0

    for row in docs:
        path = out_dir / str(row["local_path"])
        print(f"[check] {row['doc_id']} {row['title']} -> {row['local_path']}")
        result = validate_doc(path, client)
        results.append(result)
        if result["errors"]:
            error_docs += 1
            print(f"[error] {row['doc_id']} {row['title']} errors={len(result['errors'])}")
        elif result["warnings"]:
            warning_docs += 1
            print(f"[warn] {row['doc_id']} {row['title']} warnings={len(result['warnings'])}")
        else:
            print(f"[ok] {row['doc_id']} {row['title']}")

    summary = {
        "out_dir": str(out_dir.resolve()),
        "checked_docs": len(results),
        "docs_with_errors": error_docs,
        "docs_with_warnings": warning_docs,
        "error_count": sum(len(item["errors"]) for item in results),
        "warning_count": sum(len(item["warnings"]) for item in results),
    }
    report = {
        "summary": summary,
        "results": results,
    }

    report_path = Path(args.report) if args.report else out_dir / "validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[done] checked={summary['checked_docs']} "
        f"docs_with_errors={summary['docs_with_errors']} "
        f"docs_with_warnings={summary['docs_with_warnings']} "
        f"report={report_path}"
    )

    if args.strict and summary["docs_with_errors"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
