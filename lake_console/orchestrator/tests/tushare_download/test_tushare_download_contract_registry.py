from dataclasses import replace
from decimal import Decimal

import pytest

from orchestrator.tushare_download import DownloadError
from orchestrator.tushare_download.contract_registry import (
    ContractRegistry,
    canonical_content,
)
from orchestrator.tushare_download.source_contract import ParameterRule, SourceKind

from .fixtures import DAILY_NAMES, contract


def test_complete_source_fields_and_same_version_different_content():
    original = contract()
    assert original.field_names == DAILY_NAMES
    assert len(original.fields) == 11
    changed = replace(original, fields=original.fields[1:] + original.fields[:1])
    assert not ContractRegistry.same_content(original, changed)
    assert ContractRegistry.same_content(
        original, replace(original, local_evidence_paths=("other-project/path",))
    )
    changed_type = replace(
        original,
        fields=(replace(original.fields[0], description="changed"),)
        + original.fields[1:],
    )
    assert not ContractRegistry.same_content(original, changed_type)


def test_scalar_canonical_format_has_independent_literal_expected():
    assert (
        canonical_content((True, 1, Decimal("1.00"), "1", None))
        == b'[[4,true],[2,"1"],[3,0,[1,0,0],-2],[1,"1"],[0]]'
    )


def test_contract_registry_rejects_duplicate_fields_names_and_reserved_parameters():
    c = contract()
    for invalid in (
        replace(c, fields=(c.fields[0], c.fields[0])),
        replace(c, contract_name="fixture.daily@latest"),
        replace(
            c, parameters=c.parameters + (ParameterRule("token", SourceKind.STRING),)
        ),
    ):
        with pytest.raises(DownloadError):
            ContractRegistry((invalid,))
    with pytest.raises(DownloadError):
        ContractRegistry((c, c))
    with pytest.raises(DownloadError):
        ContractRegistry((c,)).resolve("fixture.daily@2")
