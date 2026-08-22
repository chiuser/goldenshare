from __future__ import annotations

import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_package_discovery_includes_only_src_and_qtf_families() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    find_config = config["tool"]["setuptools"]["packages"]["find"]
    discovered = {
        path.parent.relative_to(REPO_ROOT).as_posix().replace("/", ".")
        for path in REPO_ROOT.rglob("__init__.py")
    }
    packages = {
        package
        for package in discovered
        if any(fnmatchcase(package, pattern) for pattern in find_config["include"])
        and not any(fnmatchcase(package, pattern) for pattern in find_config["exclude"])
    }

    _assert_package_contract(packages)


def test_package_gate_rejects_missing_qtf_or_unapproved_top_level_package() -> None:
    with pytest.raises(AssertionError, match="qtf package is missing"):
        _assert_package_contract({"src"})
    with pytest.raises(AssertionError, match="unapproved package"):
        _assert_package_contract(
            {"src", "qtf", "qtf.application.services", "qtf.adapters.persistence.models", "scripts"}
        )


def _assert_package_contract(packages: set[str]) -> None:
    assert "src" in packages, "src package is missing"
    assert "qtf" in packages, "qtf package is missing"
    assert "qtf.application.services" in packages
    assert "qtf.adapters.persistence.models" in packages
    assert all(
        package == "src"
        or package.startswith("src.")
        or package == "qtf"
        or package.startswith("qtf.")
        for package in packages
    ), "unapproved package family is present"
    assert not any(package == "scripts" or package.startswith("scripts.") for package in packages)
    assert not any(package == "tests" or package.startswith("tests.") for package in packages)
