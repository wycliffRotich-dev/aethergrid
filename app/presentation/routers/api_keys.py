from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.create_api_key_service import (
    CreateApiKeyService,
)
from app.application.services.revoke_api_key_service import (
    RevokeApiKeyService,
)
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    get_create_api_key_service,
    get_revoke_api_key_service,
)
from app.presentation.schemas.create_api_key_request import (
    CreateApiKeyRequest,
)
from app.presentation.schemas.create_api_key_response import (
    CreateApiKeyResponse,
)

router = APIRouter(
    prefix="/api-keys",
    tags=["ApiKeys"],
    # Every route in this router requires an already-valid key.
    # There is no unauthenticated way to mint a key over HTTP --
    # deliberately, since an open POST /api-keys would let
    # anyone issue themselves a credential before any auth
    # exists at all. The very first key has to come from
    # scripts/issue_api_key.py, run locally with direct
    # repository access, never over the network.
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "",
    response_model=CreateApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_api_key(
    request: CreateApiKeyRequest,
    service: Annotated[
        CreateApiKeyService,
        Depends(get_create_api_key_service),
    ],
) -> CreateApiKeyResponse:
    """
    Issue a new API key. The plaintext key is returned exactly
    once, in this response.

    Requires an existing valid key -- this is how a trusted
    caller provisions credentials for another caller (a new
    worker, a new integration), not how the system bootstraps
    its first credential.
    """
    issued = service.execute(
        label=request.label,
    )

    return CreateApiKeyResponse(
        id=str(issued.id),
        label=issued.label,
        key=issued.plaintext_key,
    )


@router.post(
    "/{api_key_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_api_key(
    api_key_id: str,
    service: Annotated[
        RevokeApiKeyService,
        Depends(get_revoke_api_key_service),
    ],
) -> None:
    """
    Revoke an existing API key.

    Revoking an already-revoked key succeeds silently, the
    same 204 as revoking an active one -- the caller's desired
    end state (key is dead) already holds either way.
    """
    try:
        service.execute(
            ApiKeyId(
                value=UUID(api_key_id),
            ),
        )
    except ApiKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
