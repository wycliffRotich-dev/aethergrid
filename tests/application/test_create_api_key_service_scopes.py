from __future__ import annotations

import pytest

from app.application.services.create_api_key_service import (
    CreateApiKeyService,
)
from app.domain.exceptions.unknown_api_key_scope_error import (
    UnknownApiKeyScopeError,
)
from app.domain.value_objects.api_key_scope import JOBS_EXECUTE
from app.infrastructure.repositories.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
)


def _service() -> tuple[CreateApiKeyService, InMemoryApiKeyRepository]:
    repository = InMemoryApiKeyRepository()
    return CreateApiKeyService(repository), repository


def test_issues_with_no_scopes_by_default() -> None:
    service, repository = _service()

    issued = service.execute(label="plain")

    assert issued.scopes == frozenset()
    stored = repository.get_by_id(issued.id)
    assert stored.scopes == frozenset()


def test_grants_and_persists_the_requested_scopes() -> None:
    service, repository = _service()

    issued = service.execute(
        label="runner",
        scopes=frozenset({JOBS_EXECUTE}),
    )

    assert issued.scopes == frozenset({JOBS_EXECUTE})
    stored = repository.get_by_id(issued.id)
    assert stored.has_scope(JOBS_EXECUTE)


def test_unknown_scope_is_rejected_and_nothing_is_persisted() -> None:
    service, repository = _service()

    with pytest.raises(UnknownApiKeyScopeError):
        service.execute(
            label="runner",
            scopes=frozenset({"job:execute"}),
        )

    assert repository.list_active() == []
