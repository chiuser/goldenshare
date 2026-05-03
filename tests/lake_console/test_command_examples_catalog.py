from __future__ import annotations

import argparse
from pathlib import Path

from lake_console.backend.app.catalog.command_sets import list_command_sets
from lake_console.backend.app.catalog.datasets import list_dataset_definitions
from lake_console.backend.app.cli.main import build_parser


def test_all_lake_datasets_have_command_examples():
    missing = [definition.dataset_key for definition in list_dataset_definitions() if not definition.command_examples]
    assert missing == []


def test_command_examples_use_registered_cli_commands():
    registered_commands = _registered_cli_commands()
    all_examples = [
        example
        for definition in list_dataset_definitions()
        for example in definition.command_examples
    ] + [
        example
        for command_set in list_command_sets()
        for example in command_set.command_examples
    ]

    assert all_examples
    for example in all_examples:
        assert example.argv[0] == "lake-console"
        assert example.argv[1] in registered_commands
        assert example.command == " ".join(example.argv)


def test_command_examples_do_not_reference_removed_commands():
    removed_commands = {"rebuild-stk-mins-derived"}
    all_command_text = "\n".join(
        example.command
        for definition in list_dataset_definitions()
        for example in definition.command_examples
    )
    all_command_text += "\n".join(
        example.command
        for command_set in list_command_sets()
        for example in command_set.command_examples
    )

    for removed_command in removed_commands:
        assert removed_command not in all_command_text


def test_maintenance_commands_are_not_datasets():
    dataset_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    command_sets = {command_set.command_set_key for command_set in list_command_sets()}

    assert "lake_maintenance" in command_sets
    assert "lake_maintenance" not in dataset_keys


def test_frontend_does_not_hardcode_command_examples():
    frontend_entry = Path("lake_console/frontend/src/main.tsx").read_text(encoding="utf-8")

    assert "function commandExamples" not in frontend_entry
    assert "rebuild-stk-mins-derived" not in frontend_entry


def _registered_cli_commands() -> set[str]:
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("lake-console parser has no subcommands")
