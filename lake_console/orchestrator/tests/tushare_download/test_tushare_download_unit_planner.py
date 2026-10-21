from dataclasses import replace

import pytest

from orchestrator.tushare_download import (
    DownloadError,
    DownloadTask,
    ObjectTimeRange,
    TimeRange,
)
from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download.task_input import validate_task
from orchestrator.tushare_download.unit_planner import UnitPlanner

from .fixtures import contract


def planned(task, definition=None):
    c = definition or contract()
    planner = UnitPlanner(validate_task(task, c, 1048576), c)
    result = []
    while (unit := planner.next_unit()) is not None:
        result.append(unit)
    assert planner.total_units == len(result)
    return result


@pytest.mark.parametrize(
    "task,expected",
    [
        (DownloadTask("fixture.daily@1", M.SNAPSHOT), [(None, None, None)]),
        (
            DownloadTask(
                "fixture.daily@1", M.BY_POINT, points=("2018-07-18", "2018-07-17")
            ),
            [(None, "2018-07-17", None), (None, "2018-07-18", None)],
        ),
        (
            DownloadTask("fixture.daily@1", M.BY_OBJECT, objects=("B", "A")),
            [("B", None, None), ("A", None, None)],
        ),
        (
            DownloadTask(
                "fixture.daily@1",
                M.BY_OBJECT_POINT,
                objects=("B", "A"),
                points=("2018-07-18", "2018-07-17"),
            ),
            [
                ("B", "2018-07-17", None),
                ("A", "2018-07-17", None),
                ("B", "2018-07-18", None),
                ("A", "2018-07-18", None),
            ],
        ),
        (
            DownloadTask(
                "fixture.daily@1",
                M.BY_OBJECT_RANGE,
                objects=("B", "A"),
                time_range=TimeRange("2018-07-17", "2018-07-18"),
            ),
            [
                ("B", None, TimeRange("2018-07-17", "2018-07-18")),
                ("A", None, TimeRange("2018-07-17", "2018-07-18")),
            ],
        ),
        (
            DownloadTask(
                "fixture.daily@1",
                M.BY_RANGE,
                time_range=TimeRange("2018-07-17", "2018-07-18"),
            ),
            [(None, None, TimeRange("2018-07-17", "2018-07-18"))],
        ),
    ],
)
def test_six_modes_with_literal_unit_order(task, expected):
    assert [(u.object_code, u.point, u.time_range) for u in planned(task)] == expected


def test_none_empty_and_range_do_not_generate_a_calendar():
    assert planned(DownloadTask("fixture.daily@1", M.BY_POINT, points=())) == []
    assert planned(DownloadTask("fixture.daily@1", M.BY_OBJECT, objects=())) == []
    for task in (
        DownloadTask("fixture.daily@1", M.BY_POINT),
        DownloadTask(
            "fixture.daily@1",
            M.BY_POINT,
            time_range=TimeRange("2018-07-17", "2018-07-18"),
        ),
        DownloadTask(
            "fixture.daily@1",
            M.BY_POINT,
            points=("2018-07-16",),
            time_range=TimeRange("2018-07-17", "2018-07-18"),
        ),
    ):
        with pytest.raises(DownloadError):
            planned(task)


@pytest.mark.parametrize(
    "change",
    [
        {"objects": ("A", "A")},
        {"objects": ("__ALL__",)},
        {"objects": ("A,B",)},
        {"objects": (" A",)},
        {"points": ("2018-07-18",)},
    ],
)
def test_object_mode_rejects_duplicates_sentinels_and_incompatible_roles(change):
    with pytest.raises(DownloadError):
        planned(
            replace(
                DownloadTask("fixture.daily@1", M.BY_OBJECT, objects=("A",)), **change
            )
        )


def test_object_ranges_and_stable_intent_identity():
    task = DownloadTask(
        "fixture.daily@1",
        M.BY_OBJECT_RANGE,
        object_ranges=(
            ObjectTimeRange("A", TimeRange("2018-07-17", "2018-07-18")),
            ObjectTimeRange("B", TimeRange("2018-07-16", "2018-07-18")),
        ),
    )
    assert [u.object_code for u in planned(task)] == ["A", "B"]
    with pytest.raises(DownloadError):
        planned(
            replace(
                task,
                object_ranges=(
                    task.object_ranges[0],
                    ObjectTimeRange("A", TimeRange("2018-07-16", "2018-07-18")),
                ),
            )
        )
    a = DownloadTask(
        "fixture.daily@1",
        M.BY_POINT,
        points=("2018-07-18",),
        filters={"exchange": "SSE", "extra": "x"},
    )
    b = replace(a, filters={"extra": "x", "exchange": "SSE"})
    assert planned(a)[0].unit_id == planned(b)[0].unit_id
    assert (
        planned(a)[0].unit_id != planned(replace(a, points=("2018-07-17",)))[0].unit_id
    )
