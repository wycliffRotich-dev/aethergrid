import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.create_api_key_service import (
    CreateApiKeyService,
)
from app.application.services.revoke_api_key_service import (
    RevokeApiKeyService,
)
from app.domain.entities.api_key import ApiKey
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.exceptions.scope_denied_error import ScopeDeniedError
from app.domain.services.key_authorization import (
    authorize_key_management,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.presentation.auth import (
    require_api_key,
    require_rate_limit,
)
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

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api-keys",
    tags=["ApiKeys"],
    dependencies=[
        Depends(require_api_key),
        Depends(require_rate_limit),
    ],
)


@router.post(
    "",
    response_model=CreateApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": (
                "caller lacks the keys:manage scope (ADR 0055)."
            ),
        },
    },
)
def create_api_key(
    request: CreateApiKeyRequest,
    caller: Annotated[
        ApiKey,
        Depends(require_api_key),
    ],
    service: Annotated[
        CreateApiKeyService,
        Depends(get_create_api_key_service),
    ],
) -> CreateApiKeyResponse:
    """
    Issue a new API key. The plaintext key is returned exactly
    once, in this response.

    Requires the calling key to hold keys:manage (ADR 0055).
    The issued key records the caller as its issuer (ADR
    0056), letting the caller later revoke it without needing
    keys:manage itself.
    """
    try:
        authorize_key_management(caller.scopes)
    except ScopeDeniedError as exc:
        logger.warning(
            "key issuance denied: caller_id=%s "
            "missing_scope=%s route=POST /api-keys",
            caller.id,
            exc.scope,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    issued = service.execute(
        label=request.label,
        issued_by=caller.id,
    )

    return CreateApiKeyResponse(
        id=str(issued.id),
        label=issued.label,
        key=issued.plaintext_key,
    )


@router.post(
    "/{api_key_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": (
                "caller lacks keys:manage and did not issue "
                "this key (ADR 0056)."
            ),
        },
    },
)
def revoke_api_key(
    api_key_id: str,
    caller: Annotated[
        ApiKey,
        Depends(require_api_key),
    ],
    service: Annotated[
        RevokeApiKeyService,
        Depends(get_revoke_api_key_service),
    ],
) -> None:
    """
    Revoke an existing API key.

    Allowed for a caller holding keys:manage, or for the key
    that issued this one (ADR 0056). The decision needs the
    target's issued_by, so it is made inside the service,
    after the target is loaded, rather than at the route
    the way every other scope gate in this codebase works.

    Revoking an already-revoked key still succeeds silently,
    the same 204 as revoking an active one.
    """
    try:
        service.execute(
            ApiKeyId(
                value=UUID(api_key_id),
            ),
            caller=caller,
        )
    except ApiKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ScopeDeniedError as exc:
        logger.warning(
            "key revocation denied: caller_id=%s "
            "missing_scope=%s route=POST /api-keys/%s/revoke",
            caller.id,
            exc.scope,
            api_key_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
