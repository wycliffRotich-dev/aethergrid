from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.application.services.authenticate_api_key_service import (
    AuthenticateApiKeyService,
    InvalidApiKeyError,
)
from app.domain.entities.api_key import ApiKey
from app.presentation.dependencies import (
    get_authenticate_api_key_service,
)


def require_api_key(
    *,
    authorization: Annotated[
        str | None,
        Header(),
    ] = None,
    service: Annotated[
        AuthenticateApiKeyService,
        Depends(get_authenticate_api_key_service),
    ],
) -> ApiKey:
    """
    FastAPI dependency enforcing API key auth on a route.

    Usage:

        @router.post("", dependencies=[Depends(require_api_key)])
        def create_job(...): ...

    or, if the caller identity itself is needed inside the
    handler:

        def create_job(
            request: CreateJobRequest,
            caller: Annotated[ApiKey, Depends(require_api_key)],
        ): ...
    """
    if authorization is None or not authorization.startswith(
        "Bearer "
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_key = authorization.removeprefix("Bearer ").strip()

    try:
        return service.execute(raw_key)
    except InvalidApiKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or revoked credential",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
