from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands.common import add_lake_root_arg, print_json, settings_from_args
from lake_console.backend.app.services.filesystem_scanner import FilesystemScanner


def register_catalog_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    dataset_parser = subparsers.add_parser("list-datasets", help="扫描本地 Lake 数据集")
    add_lake_root_arg(dataset_parser)
    dataset_parser.set_defaults(handler=_handle_list_datasets)


def _handle_list_datasets(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    items = FilesystemScanner(settings.lake_root).list_datasets()
    print_json([item.model_dump(mode="json") for item in items])
    return 0
