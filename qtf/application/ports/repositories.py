from __future__ import annotations

from typing import Protocol

from qtf.contracts.research import ResearchBundle, RevisionContent
from qtf.contracts.runtime import ExperimentRunRecord, InputPreflightIssueRecord, InputPreflightRecord


class ResearchRepository(Protocol):
    def find_bundle_by_create_request_key(self, request_key: str) -> ResearchBundle | None: ...

    def create_research_with_initial_revision(
        self,
        *,
        research_key: str,
        revision_key: str,
        request_key: str,
        title: str,
        template_key: str,
        capability_key: str,
        created_by_user_id: int,
        content: RevisionContent,
    ) -> tuple[ResearchBundle, bool]: ...

    def update_draft(
        self,
        *,
        revision_key: str,
        expected_draft_version: int,
        content: RevisionContent,
    ) -> ResearchBundle: ...

    def get_bundle_by_research_key(self, research_key: str) -> ResearchBundle: ...

    def get_bundle_by_revision_key(self, revision_key: str) -> ResearchBundle: ...

    def get_bundle_by_revision_id(self, revision_id: int) -> ResearchBundle: ...

    def freeze_revision(
        self,
        *,
        revision_key: str,
        expected_draft_version: int,
        content: RevisionContent,
        revision_hash: str,
        frozen_by_user_id: int,
    ) -> ResearchBundle: ...


class RuntimeRepository(Protocol):
    def find_preflight_by_request_key(self, request_key: str) -> InputPreflightRecord | None: ...

    def get_preflight_by_key(self, preflight_key: str) -> InputPreflightRecord: ...

    def get_latest_preflight_for_revision(self, revision_id: int, *, phase: str) -> InputPreflightRecord | None: ...

    def create_preflight(
        self,
        *,
        preflight_key: str,
        request_key: str,
        revision_id: int,
        draft_hash: str | None,
        phase: str,
        status: str,
        source_contract_hash: str,
        as_of: object,
        requested_start_date: object,
        requested_end_date: object,
        effective_start_date: object,
        effective_end_date: object,
        dataset_evidence: list[dict[str, object]],
        universe_count: int,
        group_count: int,
        valid_group_day_count: int,
        excluded_group_day_count: int,
        plan_estimate: dict[str, object],
        content_hash: str,
        completed_at: object,
        issues: tuple[InputPreflightIssueRecord, ...],
    ) -> InputPreflightRecord: ...

    def find_run_by_request_key(self, request_key: str) -> ExperimentRunRecord | None: ...

    def get_run_by_key(self, run_key: str) -> ExperimentRunRecord: ...

    def stage_run(
        self,
        *,
        run_key: str,
        request_key: str,
        revision_id: int,
        formula_version: str,
    ) -> ExperimentRunRecord: ...

    def link_queued_task_run(self, run_key: str, *, task_run_id: int) -> ExperimentRunRecord: ...

    def update_run(self, run_key: str, **changes: object) -> ExperimentRunRecord: ...
