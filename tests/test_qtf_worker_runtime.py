from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.app.runtime import ops_worker_factory


def test_qtf_worker_resolves_deploy_commit_once_and_injects_it(mocker) -> None:
    completed = subprocess.CompletedProcess(args=["git"], returncode=0, stdout=f"{'a' * 40}\n", stderr="")
    run = mocker.patch.object(ops_worker_factory.subprocess, "run", return_value=completed)
    executor = mocker.patch.object(ops_worker_factory, "QtfTaskExecutor")
    session_factory = mocker.Mock()

    ops_worker_factory.build_qtf_worker(session_factory=session_factory)

    run.assert_called_once_with(
        ["git", "-C", str(ops_worker_factory._REPOSITORY_ROOT), "rev-parse", "--verify", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    executor.assert_called_once_with(session_factory=session_factory, release_commit="a" * 40)


@pytest.mark.parametrize("release_commit", ["", "abc", "A" * 40, "g" * 40])
def test_qtf_worker_rejects_invalid_commit_before_build(mocker, release_commit: str) -> None:
    worker_builder = mocker.patch.object(ops_worker_factory, "_build_worker")

    with pytest.raises(RuntimeError, match="有效的部署 Git commit"):
        ops_worker_factory.build_qtf_worker(session_factory=mocker.Mock(), release_commit=release_commit)

    worker_builder.assert_not_called()


def test_qtf_worker_fails_closed_when_git_cannot_resolve_head(mocker, tmp_path: Path) -> None:
    mocker.patch.object(
        ops_worker_factory.subprocess,
        "run",
        side_effect=subprocess.CalledProcessError(returncode=128, cmd=["git"]),
    )

    with pytest.raises(RuntimeError, match="无法读取部署 Git commit"):
        ops_worker_factory._resolve_qtf_release_commit(repository_root=tmp_path)


def test_non_qtf_worker_does_not_resolve_git_commit(mocker) -> None:
    resolver = mocker.patch.object(ops_worker_factory, "_resolve_qtf_release_commit")

    ops_worker_factory.build_operations_worker(session_factory=mocker.Mock())

    resolver.assert_not_called()
