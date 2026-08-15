from __future__ import annotations

from app.domain.value_objects.api_key_id import ApiKeyId


class RateLimitExceededError(Exception):
    """
    Raised when a caller has exhausted its token bucket and
    must wait before its next request will be admitted.

    Carries retry_after_seconds, the time until the bucket
    next has a token available, so the presentation layer can
    surface it as a Retry-After header, the same way callers
    are told when they may safely retry.
    """

    def __init__(
        self,
        api_key_id: ApiKeyId,
        retry_after_seconds: float,
    ) -> None:
        super().__init__(
            f"API key '{api_key_id}' has exceeded its rate limit; "
            f"retry after {retry_after_seconds:.1f}s."
        )
        self.api_key_id = api_key_id
        self.retry_after_seconds = retry_after_seconds
