"""I03 real-resource positive and pre-IO rejection tests; no actual checks/jobs."""

from stock_suspend_confirmed_test_support import (
    make_confirmed_test_resources,
    require_isolated_context,
    verify_lake_resource,
)

# This must precede business imports and fail under an ordinary pytest invocation.
ALLOWED = require_isolated_context()

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
