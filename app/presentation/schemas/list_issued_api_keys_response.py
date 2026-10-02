from datetime import datetime

from pydantic import BaseModel


class IssuedApiKeySummaryResponse(BaseModel):
    """
    A single API key as shown in an issued-keys listing.

    Never includes key_hash. issued_by is deliberately absent
    here too: every entry in this list shares the same issuer
    by construction, the one named in the request path.
    """

    id: str
    label: str
    scopes: list[str]
    created_at: datetime
    revoked_at: datetime | None


class ListIssuedApiKeysResponse(BaseModel):
    """
    HTTP response returned when listing the keys issued by a
    given API key (ADR 0056 follow-up).
    """

    issued: list[IssuedApiKeySummaryResponse]
