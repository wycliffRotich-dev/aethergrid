from __future__ import annotations

from app.presentation.schemas.create_api_key_request import (
    CreateApiKeyRequest,
)


def test_http_key_issuance_cannot_request_scopes() -> None:
    """
    ADR 0054: scopes are granted only by scripts/issue_api_key.py,
    with direct repository access. If this request schema ever
    grew a scopes field, any valid key could mint itself a
    jobs:execute key and the scope would protect nothing.
    """
    assert "scopes" not in CreateApiKeyRequest.model_fields
