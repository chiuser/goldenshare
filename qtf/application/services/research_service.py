from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from qtf.application.ports.repositories import ResearchRepository
from qtf.contracts.errors import QtfRequestConflict, QtfRequestInvalid
from qtf.contracts.research import CreateResearchCommand, ResearchBundle, RevisionContent


class ResearchService:
    def __init__(
        self,
        repository: ResearchRepository,
        *,
        key_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._repository = repository
        self._key_factory = key_factory or _opaque_key

    def create_research(self, command: CreateResearchCommand) -> ResearchBundle:
        normalized = _normalize_create_command(command)
        existing = self._repository.find_bundle_by_create_request_key(normalized.request_key)
        if existing is not None:
            _ensure_create_replay_matches(existing, normalized)
            return existing

        bundle, created = self._repository.create_research_with_initial_revision(
            research_key=self._key_factory("research"),
            revision_key=self._key_factory("revision"),
            request_key=normalized.request_key,
            title=normalized.title,
            template_key=normalized.template_key,
            capability_key=normalized.capability_key,
            created_by_user_id=normalized.created_by_user_id,
            content=normalized.initial_revision,
        )
        if not created:
            _ensure_create_replay_matches(bundle, normalized)
        return bundle

    def save_draft(
        self,
        *,
        revision_key: str,
        expected_draft_version: int,
        content: RevisionContent,
    ) -> ResearchBundle:
        normalized_revision_key = _required_text(revision_key, "revision_key", 96)
        if expected_draft_version < 1:
            raise QtfRequestInvalid("draft version must be greater than zero")
        return self._repository.update_draft(
            revision_key=normalized_revision_key,
            expected_draft_version=expected_draft_version,
            content=content,
        )


def _opaque_key(kind: str) -> str:
    return f"qtf_{kind}_{uuid4().hex}"


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise QtfRequestInvalid(f"{field} is required")
    if len(normalized) > max_length:
        raise QtfRequestInvalid(f"{field} exceeds {max_length} characters")
    return normalized


def _normalize_create_command(command: CreateResearchCommand) -> CreateResearchCommand:
    if command.created_by_user_id <= 0:
        raise QtfRequestInvalid("created_by_user_id must be greater than zero")
    return CreateResearchCommand(
        request_key=_required_text(command.request_key, "request_key", 96),
        title=_required_text(command.title, "title", 160),
        template_key=_required_text(command.template_key, "template_key", 96),
        capability_key=_required_text(command.capability_key, "capability_key", 96),
        created_by_user_id=command.created_by_user_id,
        initial_revision=command.initial_revision,
    )


def _ensure_create_replay_matches(bundle: ResearchBundle, command: CreateResearchCommand) -> None:
    research = bundle.research
    revision = bundle.revision
    if (
        research.title != command.title
        or research.template_key != command.template_key
        or research.capability_key != command.capability_key
        or research.created_by_user_id != command.created_by_user_id
        or revision.content != command.initial_revision
    ):
        raise QtfRequestConflict("request_key was already used for different research content")
