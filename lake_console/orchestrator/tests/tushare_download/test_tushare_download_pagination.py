from dataclasses import replace

import pytest

from orchestrator.tushare_download import DownloadError, DownloadTask, TimeRange
from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download import DownloadProgressEvent as E
from orchestrator.tushare_download.download_models import SourcePage, SourceRecord
from orchestrator.tushare_download.source_contract import ModeRule

from .fixtures import build, contract, rows


@pytest.mark.parametrize("limit,tail,expected_count", [(2, 0, 2), (2, 1, 3), (3, 1, 4)])
def test_each_contract_owns_its_page_size_and_full_page_continues(
    limit, tail, expected_count
):
    definition = contract(limit=limit)
    downloader, calls, _, _ = build(
        lambda request, attempt: rows(
            count=limit if dict(request.params)["offset"] == 0 else tail
        ),
        definition=definition,
    )
    events = []
    with downloader.download(
        DownloadTask(definition.contract_name, M.SNAPSHOT), on_progress=events.append
    ) as session:
        results = list(session)
    assert len(results) == 1 and len(results[0].records) == expected_count
    assert [dict(r.params)["offset"] for r in calls] == [0, limit]
    assert all(
        dict(r.params)["limit"] == limit and r.fields == definition.field_names
        for r in calls
    )
    assert sum(e.event == E.UNIT_COMPLETED for e in events) == 1
    assert results[0].statistics.empty_page_count == int(tail == 0)


def split_definition():
    return contract(
        strategy=3,
        modes=(
            ModeRule(
                M.BY_RANGE, range_start_param="start_date", range_end_param="end_date"
            ),
        ),
    )


def test_range_split_discards_parent_and_indivisible_first_page_is_reused():
    def source(request, attempt):
        p = dict(request.params)
        if p["start_date"] != p["end_date"]:
            return rows(count=2)  # Artificial saturated parent probe, not retained.
        if p["start_date"] == "20180717":
            return rows("20180717", count=1)
        return rows("20180718", count=2 if p["offset"] == 0 else 1)

    downloader, calls, _, _ = build(source, definition=split_definition())
    events = []
    with downloader.download(
        DownloadTask(
            "fixture.daily@1",
            M.BY_RANGE,
            time_range=TimeRange("2018-07-17", "2018-07-18"),
        ),
        on_progress=events.append,
    ) as session:
        results = list(session)
        assert len(results) == 1
        result = results[0]
    assert [
        (
            dict(r.params)["start_date"],
            dict(r.params)["end_date"],
            dict(r.params)["offset"],
        )
        for r in calls
    ] == [
        ("20180717", "20180718", 0),
        ("20180717", "20180717", 0),
        ("20180718", "20180718", 0),
        ("20180718", "20180718", 2),
    ]
    assert len(result.records) == 4 and result.statistics.split_count == 1
    assert (
        result.statistics.successful_response_count == 4
        and result.statistics.accepted_page_count == 3
    )
    assert [e.page_accepted for e in events if e.event == E.PAGE_COMPLETED] == [
        False,
        True,
        True,
        True,
    ]
    assert result.unit.time_range == TimeRange("2018-07-17", "2018-07-18")


def test_repeated_page_content_is_not_an_error_and_is_not_deduplicated():
    downloader, calls, _, _ = build(
        lambda request, attempt: (
            rows(count=2) if dict(request.params)["offset"] < 4 else ()
        )
    )
    with downloader.download(DownloadTask("fixture.daily@1", M.SNAPSHOT)) as session:
        results = list(session)
        assert len(results) == 1
        result = results[0]
    assert len(calls) == 3 and len(result.records) == 4


@pytest.mark.parametrize("total,passes", [(None, False), (1, False), (2, True)])
def test_single_response_at_known_boundary_requires_reliable_completeness(
    total, passes
):
    definition = contract(strategy=1)
    definition = replace(
        definition,
        pagination=replace(
            definition.pagination, truncation_limit=2, reliable_total_path=("total",)
        ),
    )

    def source(request, attempt):
        return SourcePage(
            request.fields,
            tuple(SourceRecord(request.fields, x, 0) for x in rows(count=2)),
            total=total,
        )

    downloader, calls, _, _ = build(source, definition=definition)
    if passes:
        with downloader.download(
            DownloadTask(definition.contract_name, M.SNAPSHOT)
        ) as session:
            results = list(session)
        assert len(results[0].records) == 2
    else:
        with (
            pytest.raises(DownloadError),
            downloader.download(
                DownloadTask(definition.contract_name, M.SNAPSHOT)
            ) as session,
        ):
            next(session)
    assert len(calls) == 1


def test_reliable_total_accepts_normal_full_then_short_page_and_rejects_impossible_count():
    definition = contract()
    definition = replace(
        definition,
        pagination=replace(definition.pagination, reliable_total_path=("total",)),
    )

    def source(request, attempt):
        return SourcePage(
            request.fields,
            tuple(
                SourceRecord(request.fields, x, 0)
                for x in rows(count=2 if dict(request.params)["offset"] == 0 else 1)
            ),
            total=3,
        )

    downloader, calls, _, _ = build(source, definition=definition)
    with downloader.download(
        DownloadTask(definition.contract_name, M.SNAPSHOT)
    ) as session:
        results = list(session)
    assert len(results[0].records) == 3 and len(calls) == 2
    broken, broken_calls, _, _ = build(
        lambda request, attempt: replace(source(request, attempt), total=1),
        definition=definition,
    )
    with (
        pytest.raises(DownloadError),
        broken.download(DownloadTask(definition.contract_name, M.SNAPSHOT)) as session,
    ):
        next(session)
    assert len(broken_calls) == 1 and session.summary.delivered_units == 0


@pytest.mark.parametrize(
    "ending,expected_rows", [("short", 3), ("empty", 2), ("total", 3)]
)
def test_supported_endings_finish_with_next_offset_metadata(ending, expected_rows):
    definition = contract()
    definition = replace(
        definition,
        pagination=replace(
            definition.pagination,
            short_page_ends=ending == "short",
            empty_page_ends=ending == "empty",
            reliable_total_path=("total",) if ending == "total" else None,
            reliable_next_offset_path=("next_offset",),
        ),
    )

    def source(request, attempt):
        first = dict(request.params)["offset"] == 0
        count = 2 if first else 0 if ending == "empty" else 1
        return SourcePage(
            request.fields,
            tuple(SourceRecord(request.fields, row, 0) for row in rows(count=count)),
            total=3 if ending == "total" else None,
            next_offset=2 if first else None,
        )

    downloader, calls, _, _ = build(source, definition=definition)
    with downloader.download(
        DownloadTask(definition.contract_name, M.SNAPSHOT)
    ) as session:
        results = list(session)
    assert [dict(r.params)["offset"] for r in calls] == [0, 2]
    assert len(results) == 1 and len(results[0].records) == expected_rows


@pytest.mark.parametrize("ending", ["short", "empty"])
def test_missing_optional_total_does_not_block_other_declared_endings(ending):
    definition = contract()
    definition = replace(
        definition,
        pagination=replace(
            definition.pagination,
            short_page_ends=ending == "short",
            empty_page_ends=ending == "empty",
            reliable_total_path=("total",),
        ),
    )

    def source(request, attempt):
        first = dict(request.params)["offset"] == 0
        count = 2 if first else 1 if ending == "short" else 0
        return SourcePage(
            request.fields,
            tuple(SourceRecord(request.fields, row, 0) for row in rows(count=count)),
            total=None,
        )

    downloader, calls, _, _ = build(source, definition=definition)
    with downloader.download(
        DownloadTask(definition.contract_name, M.SNAPSHOT)
    ) as session:
        results = list(session)
    assert len(calls) == 2 and len(results) == 1
    assert len(results[0].records) == (3 if ending == "short" else 2)
