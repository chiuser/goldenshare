from dataclasses import replace

import pytest

from orchestrator.tushare_download import DownloadError, DownloadTask
from orchestrator.tushare_download import DownloadErrorCode as C
from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download.unit_memory import UnitMemory

from .fixtures import build, contract, rows, small_config


def test_shared_reference_fits_but_a_second_distinct_buffer_exceeds_capacity():
    # Small deterministic capacity test, not an RSS measurement or a 2GiB allocation.
    config = replace(
        small_config(), unit_memory_limit_bytes=150000, working_reserve_bytes=64
    )
    memory = UnitMemory(config)
    shared = bytes(100000)
    memory.attach("first", shared)
    memory.attach("same", shared)
    with pytest.raises(DownloadError) as caught:
        memory.attach("distinct", bytes(100000))
    assert caught.value.code == C.CAPACITY
    assert "实际工作空间超限" in str(caught.value)
    memory.clear()
    memory.attach("new", bytes(100000))


def test_estimated_shortage_and_actual_shortage_are_local_and_never_retry():
    memory = UnitMemory(small_config())
    with pytest.raises(DownloadError) as caught:
        memory.reserve("future", 5 * 1024 * 1024)
    assert caught.value.code == C.CAPACITY
    assert "预计工作空间不足" in str(caught.value)
    downloader, calls, _, _ = build(
        lambda request, attempt: rows(count=200),
        definition=contract(strategy=1),
        config=replace(small_config(), unit_memory_limit_bytes=20000),
    )
    with (
        pytest.raises(DownloadError) as caught,
        downloader.download(DownloadTask("fixture.daily@1", M.SNAPSHOT)) as session,
    ):
        next(session)
    assert caught.value.code == C.CAPACITY and len(calls) == 1
    assert session.summary.delivered_units == session.summary.retry_count == 0


def test_deep_owned_object_and_shared_reference_release_without_recursion():
    memory = UnitMemory(small_config())
    value = 7
    for _ in range(700):
        value = [value]
    memory.attach("first", value)
    memory.attach("second", value)
    assert len(memory._nodes) == 701
    memory.release("first")
    assert len(memory._nodes) == 701
    memory.release("second")
    assert memory._nodes == {}


def test_deep_release_is_independent_of_registration_order():
    memory = UnitMemory(small_config())
    label, value = "leaf", 7
    memory.attach(label, value)
    # Each parent references an already registered child. This isolates release
    # from traversal during registration; the old release alone fails here.
    for i in range(1500):
        value = [value]
        memory.attach(i, value)
        memory.release(label)
        label = i
    assert len(memory._nodes) == 1501
    memory.release(label)
    assert memory._nodes == {} and memory._size == 0
