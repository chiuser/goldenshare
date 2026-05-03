from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, print_json, settings_from_args
from lake_console.backend.app.services.lake_root_service import LakeRootService


def register_status_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    init_parser = subparsers.add_parser("init", help="初始化 Lake Root 目录结构")
    add_lake_root_arg(init_parser)
    init_parser.set_defaults(handler=_handle_init)

    status_parser = subparsers.add_parser("status", help="查看 Lake Root 状态")
    add_lake_root_arg(status_parser)
    status_parser.set_defaults(handler=_handle_status)


def _handle_init(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    LakeRootService(settings.lake_root).initialize()
    print(f"[lake] initialized root={settings.lake_root}")
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    status = LakeRootService(settings.lake_root).get_status()
    print_json(status.model_dump(mode="json"))
    return 0
