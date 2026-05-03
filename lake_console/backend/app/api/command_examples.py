from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Query

from lake_console.backend.app.catalog.command_sets import list_command_sets
from lake_console.backend.app.catalog.datasets import list_dataset_definitions
from lake_console.backend.app.catalog.models import LakeCommandExample
from lake_console.backend.app.catalog.view_groups import get_view_group
from lake_console.backend.app.schemas import (
    LakeCommandExampleGroupResponse,
    LakeCommandExampleItemResponse,
    LakeCommandExampleResponse,
    LakeCommandExamplesResponse,
)


router = APIRouter(prefix="/api/lake/command-examples", tags=["command-examples"])


@router.get("", response_model=LakeCommandExamplesResponse)
def list_command_examples(
    group_key: str | None = Query(default=None),
    dataset_key: str | None = Query(default=None),
) -> LakeCommandExamplesResponse:
    grouped_items: dict[str, list[LakeCommandExampleItemResponse]] = defaultdict(list)

    for definition in list_dataset_definitions():
        if group_key and definition.group_key != group_key:
            continue
        if dataset_key and definition.dataset_key != dataset_key:
            continue
        if not definition.command_examples:
            continue
        grouped_items[definition.group_key].append(
            LakeCommandExampleItemResponse(
                item_key=definition.dataset_key,
                item_type="dataset",
                display_name=definition.display_name,
                description=definition.description,
                examples=[_example_response(example) for example in definition.command_examples],
            )
        )

    for command_set in list_command_sets():
        if group_key and command_set.group_key != group_key:
            continue
        if dataset_key and command_set.command_set_key != dataset_key:
            continue
        grouped_items[command_set.group_key].append(
            LakeCommandExampleItemResponse(
                item_key=command_set.command_set_key,
                item_type="command_set",
                display_name=command_set.display_name,
                description=command_set.description,
                examples=[_example_response(example) for example in command_set.command_examples],
            )
        )

    groups = []
    for current_group_key, items in grouped_items.items():
        group = get_view_group(current_group_key)
        groups.append(
            LakeCommandExampleGroupResponse(
                group_key=group.group_key,
                group_label=group.group_label,
                group_order=group.group_order,
                items=sorted(items, key=lambda item: (item.item_type, item.item_key)),
            )
        )
    return LakeCommandExamplesResponse(groups=sorted(groups, key=lambda item: (item.group_order, item.group_key)))


def _example_response(example: LakeCommandExample) -> LakeCommandExampleResponse:
    return LakeCommandExampleResponse(
        example_key=example.example_key,
        title=example.title,
        scenario=example.scenario,
        description=example.description,
        command=example.command,
        argv=list(example.argv),
        prerequisites=list(example.prerequisites),
        notes=list(example.notes),
    )
