"""I03 resource and I04 input-path tests; no actual checks/jobs."""

from stock_suspend_confirmed_test_support import (
    checked_test_input_file,
    make_confirmed_test_resources,
    require_isolated_context,
    verify_lake_resource,
)

# This must precede business imports and fail under an ordinary pytest invocation.
ALLOWED = require_isolated_context()

import hashlib
import json
import os
import stat
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator.defs.resources import LakeRootResource


def test_i03_actual_resource_root():
    root = ALLOWED / "lake"
    resources = make_confirmed_test_resources(lake_root=root, work_root=ALLOWED)
    resource = resources["lake_root"]
    assert type(resource) is LakeRootResource
    assert resource.root() == root
    assert resource.root_path == str(root)
    assert not root.exists()  # Resource construction did not mkdir or probe.


@pytest.mark.parametrize("variant", ["wrong_keyword", "missing_root", "formal_root", "wrong_work_root"])
def test_i03_factory_rejects_before_path_io(variant):
    kwargs = {"lake_root": ALLOWED / "lake", "work_root": ALLOWED}
    expected = ValueError
    if variant == "wrong_keyword":
        kwargs["root_path"] = kwargs.pop("lake_root")
        expected = TypeError
    elif variant == "missing_root":
        del kwargs["lake_root"]
        expected = TypeError
    elif variant == "formal_root":
        kwargs["lake_root"] = Path("/Volumes/datasource/data_lake")
    else:
        kwargs["work_root"] = ALLOWED.parent
    with patch.object(Path, "stat") as stat, patch.object(Path, "lstat") as lstat, \
            patch.object(Path, "mkdir") as mkdir, patch.object(Path, "open") as opened, \
            patch.object(LakeRootResource, "ensure_available_for_run") as probe:
        with pytest.raises(expected):
            make_confirmed_test_resources(**kwargs)
        for spy in (stat, lstat, mkdir, opened, probe):
            spy.assert_not_called()


def _input_fixture_inventory(directory):
    """Record synthetic identities/content without following links."""
    result = []
    for path in (directory, *sorted(directory.rglob("*"))):
        observed = path.lstat()
        result.append((
            str(path.relative_to(directory)), observed.st_dev, observed.st_ino,
            observed.st_mode, observed.st_size, observed.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(observed.st_mode)
            else os.readlink(path) if stat.S_ISLNK(observed.st_mode) else None,
        ))
    return result


@pytest.mark.parametrize(("variant", "reason"), [
    ("regular_file", None),
    ("missing_root", "test_lake_root_missing"),
    ("missing_file", "test_input_file_missing"),
    ("root_is_file", "test_lake_root_not_directory"),
    ("target_is_directory", "test_input_not_regular_file"),
    ("dotdot", "outside_test_root"),
    ("file_symlink", "symlink_not_allowed"),
    ("parent_symlink", "symlink_not_allowed"),
])
def test_i04_input_path_preflight(variant, reason):
    case_root = ALLOWED / f"input-{variant}"
    case_root.mkdir()
    root = case_root / "lake"
    target = root / "facts.txt"
    link = None
    if variant == "root_is_file":
        root.write_text("synthetic wrong-type root\n")
    elif variant != "missing_root":
        root.mkdir()
        (root / "unchanged.txt").write_text("synthetic unchanged input\n")
        if variant == "regular_file":
            target.write_text("synthetic regular input\n")
        elif variant == "target_is_directory":
            target.mkdir()
        elif variant == "dotdot":
            target = ALLOWED / ".." / "denied-fixture" / "sentinel.txt"
        elif variant == "file_symlink":
            link = target
            link.symlink_to(ALLOWED.parent / "denied-fixture" / "sentinel.txt")
        elif variant == "parent_symlink":
            link = root / "linked-directory"
            link.symlink_to(ALLOWED.parent / "denied-fixture", target_is_directory=True)
            target = link / "sentinel.txt"

    before = _input_fixture_inventory(case_root)
    original_stat = os.stat
    path_calls = []

    def guarded_stat(path, *args, **kwargs):
        # CPython 3.13 Path.lstat() delegates to os.stat(follow_symlinks=False).
        assert kwargs.get("follow_symlinks") is False
        observed = Path(path)
        assert observed.is_relative_to(ALLOWED) and ".." not in observed.parts
        if link is not None:
            assert observed == link or not observed.is_relative_to(link)
        path_calls.append(str(observed))
        return original_stat(path, *args, **kwargs)

    forbidden = (
        (Path, "open"), (Path, "mkdir"), (Path, "resolve"),
        (os, "open"), (os, "mkdir"), (os, "rename"), (os, "replace"), (os, "unlink"),
        (LakeRootResource, "ensure_available_for_run"),
    )
    with ExitStack() as stack:
        spies = [stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name)))
                 for owner, name in forbidden]
        stack.enter_context(patch.object(os, "stat", side_effect=guarded_stat))
        if reason is None:
            assert checked_test_input_file(target, lake_root=root) == target
        else:
            with pytest.raises(ValueError, match=f"^{reason}$"):
                checked_test_input_file(target, lake_root=root)
        for spy in spies:
            spy.assert_not_called()
    assert _input_fixture_inventory(case_root) == before
    if variant == "dotdot":
        assert path_calls == []
    else:
        assert path_calls
    if link is not None:
        assert str(link) in path_calls
    print(json.dumps({"variant": variant, "reason": reason or "accepted",
                      "path_calls": path_calls, "forbidden_calls": 0,
                      "fixture_unchanged": True}), flush=True)


@pytest.mark.parametrize("variant", ["wrong_keyword", "implicit_default", "explicit_formal"])
def test_i03_detects_real_resource_default_without_io(variant):
    kwargs = {"lake_root": str(ALLOWED / "lake")} if variant == "wrong_keyword" else {}
    if variant == "explicit_formal":
        kwargs = {"root_path": "/Volumes/datasource/data_lake"}
    with patch.object(Path, "stat") as stat, patch.object(Path, "lstat") as lstat, \
            patch.object(Path, "mkdir") as mkdir, patch.object(Path, "open") as opened, \
            patch.object(LakeRootResource, "ensure_available_for_run") as probe:
        resource = LakeRootResource(**kwargs)
        assert resource.root() == Path("/Volumes/datasource/data_lake")
        with pytest.raises(ValueError, match="resource_root_mismatch"):
            verify_lake_resource(resource, expected_root=ALLOWED / "lake")
        for spy in (stat, lstat, mkdir, opened, probe):
            spy.assert_not_called()
