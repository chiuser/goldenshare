from __future__ import annotations

import argparse

from lake_console.backend.app.cli.commands.catalog import register_catalog_commands
from lake_console.backend.app.cli.commands.maintenance import register_maintenance_commands
from lake_console.backend.app.cli.commands.status import register_status_commands
from lake_console.backend.app.cli.commands.stk_mins import register_stk_mins_commands
from lake_console.backend.app.cli.commands.sync_dataset import register_sync_dataset_commands


def register_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    register_status_commands(subparsers)
    register_catalog_commands(subparsers)
    register_sync_dataset_commands(subparsers)
    register_maintenance_commands(subparsers)
    register_stk_mins_commands(subparsers)
