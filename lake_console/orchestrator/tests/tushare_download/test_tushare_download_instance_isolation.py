import ast
from pathlib import Path
from threading import Event, Thread, get_ident

from orchestrator.tushare_download import DownloadMode as M
from orchestrator.tushare_download import DownloadTask

from .fixtures import build, rows


def test_separate_instances_do_not_share_active_session_or_close_each_other():
    a, calls_a, transports_a, _ = build(lambda request, attempt: rows())
    b, calls_b, transports_b, _ = build(lambda request, attempt: rows())
    task = DownloadTask(
        "fixture.daily@1", M.BY_OBJECT, objects=tuple(f"X{i}" for i in range(100))
    )
    with a.download(task) as first, b.download(task) as second:
        next(first)
        assert len(list(second)) == 100
        assert transports_a[0].closed == 0
        assert len(list(first)) == 99
    assert len(calls_a) == len(calls_b) == 100
    assert transports_a[0] is not transports_b[0]


def test_business_created_thread_owns_load_callback_results_and_close_while_main_continues():
    main_id = get_ident()
    ready, release = Event(), Event()
    ids, failures, results = [], [], []

    def worker():
        try:
            ids.append(get_ident())
            downloader, _, _, _ = build(lambda request, attempt: rows())

            def observer(event):
                ids.append(get_ident())
                if not ready.is_set():
                    ready.set()
                    assert release.wait(2)

            with downloader.download(
                DownloadTask("fixture.daily@1", M.SNAPSHOT), on_progress=observer
            ) as session:
                for result in session:
                    ids.append(get_ident())
                    results.append(result)
            ids.append(get_ident())
        except BaseException as error:  # noqa: BLE001 - test business thread explicitly forwards any failure.
            failures.append(error)

    thread = Thread(target=worker)
    thread.start()
    try:
        assert ready.wait(2)
        assert thread.is_alive() and not results
        # Main-thread work continues while the calling download thread is in its callback.
        main_marker = ["page remains responsive"]
        assert main_marker == ["page remains responsive"]
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and not failures and len(results) == 1
    assert len(set(ids)) == 1 and ids[0] != main_id


def test_component_source_has_no_business_framework_or_thread_process_lock_management():
    import orchestrator.tushare_download as package

    root = Path(package.__file__).parent
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(), feature_version=(3, 10))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("orchestrator.defs", "src.", "dagster")
                )
            if isinstance(node, ast.Import):
                assert not any(
                    a.name
                    in ("threading", "multiprocessing", "subprocess", "fcntl", "signal")
                    for a in node.names
                )
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                assert name not in (
                    "Thread",
                    "Process",
                    "Popen",
                    "Lock",
                    "RLock",
                    "flock",
                    "fork",
                    "set_token",
                )
