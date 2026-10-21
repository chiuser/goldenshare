from dataclasses import replace
from decimal import Decimal

import pytest

from orchestrator.tushare_download import DownloadError, DownloadErrorCode
from orchestrator.tushare_download.contract_registry import (
    ContractRegistry,
    canonical_content,
)
from orchestrator.tushare_download.source_contract import ParameterRule, SourceKind

from .fixtures import DAILY_NAMES, build, contract


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


def test_next_offset_alone_is_rejected_before_source_creation():
    definition = contract()
    definition = replace(
        definition,
        pagination=replace(
            definition.pagination,
            short_page_ends=False,
            empty_page_ends=False,
            reliable_next_offset_path=("next_offset",),
        ),
    )
    created = []

    def factory(binding, clock):
        created.append(True)
        raise AssertionError("invalid contract must not reach transport construction")

    with pytest.raises(DownloadError) as caught:
        build(definition=definition, factory=factory)
    assert caught.value.code == DownloadErrorCode.CONTRACT and created == []


@pytest.mark.parametrize("ending", ["short", "empty", "total"])
def test_implemented_end_conditions_allow_next_offset_as_auxiliary(ending):
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
    assert (
        ContractRegistry((definition,)).resolve(definition.contract_name) is definition
    )
