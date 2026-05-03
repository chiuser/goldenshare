from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands import register_commands


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args) or 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lake-console", description="Goldenshare 本地 Tushare Lake 管理台")
    subparsers = parser.add_subparsers(dest="command")
    register_commands(subparsers)
    return parser
