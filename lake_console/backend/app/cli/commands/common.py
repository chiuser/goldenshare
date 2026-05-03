from __future__ import annotations

import argparse
import json
from typing import Any

from lake_console.backend.app.settings import load_settings


def add_lake_root_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", default=None, help="本地移动盘 Lake 根目录；默认读取 GOLDENSHARE_LAKE_ROOT 或 config.local.toml")


def settings_from_args(args: argparse.Namespace):
    return load_settings(lake_root=args.lake_root)


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def parse_freqs(raw_value: str | None, *, fallback: int | None) -> list[int]:
    if raw_value:
        values = [int(item.strip()) for item in raw_value.split(",") if item.strip()]
    elif fallback is not None:
        values = [fallback]
    else:
        values = [1, 5, 15, 30, 60]
    allowed = {1, 5, 15, 30, 60}
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise SystemExit(f"不支持的 freqs={invalid}，允许值：1,5,15,30,60")
    return values


def parse_int_csv(raw_value: str, *, allowed: set[int], label: str) -> list[int]:
    values = [int(item.strip()) for item in raw_value.split(",") if item.strip()]
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise SystemExit(f"不支持的 {label}={invalid}，允许值：{','.join(str(item) for item in sorted(allowed))}")
    return values


def parse_optional_csv(raw_value: str | None) -> list[str] | None:
    if not raw_value:
        return None
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    return values or None
