from __future__ import annotations

from typing import Protocol

from qtf.contracts.research import ResearchBundle, RevisionContent


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
