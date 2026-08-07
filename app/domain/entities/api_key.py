from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.lease import utc_now
from app.domain.exceptions.api_key_already_revoked_error import (
    ApiKeyAlreadyRevokedError,
)
from app.domain.value_objects.api_key_id import ApiKeyId


@dataclass(slots=True)
class ApiKey:
    """
    Represents a caller's credential for authenticating
    against the API.

    The plaintext secret is never held by this entity after
    issuance. Only its hash is persisted, so a database
    compromise alone does not yield usable credentials.
    """

    id: ApiKeyId

    key_hash: str

    label: str

    created_at: datetime

    revoked_at: datetime | None = None

    last_used_at: datetime | None = None

    @staticmethod
    def hash_secret(raw_key: str) -> str:
        """
        SHA-256 over a high-entropy, randomly generated secret.

        Deliberately not a slow password hash (bcrypt/scrypt/
        argon2). Those exist to make brute-forcing low-entropy
        human passwords expensive. This secret is 256 bits from
        secrets.token_urlsafe, already infeasible to brute
        force. Running a deliberately slow hash on every
        incoming request would trade a brute-force risk that
        doesn't exist here for a real one: every authenticated
        call would pay that cost, every time.
        """
        return hashlib.sha256(
            raw_key.encode("utf-8")
        ).hexdigest()

    @classmethod
    def issue(cls, label: str) -> tuple[ApiKey, str]:
        """
        Create a new API key.

        Returns the entity and the plaintext secret. The
        plaintext is returned exactly once, at issuance, the
        same convention GitHub and Stripe use for their
        tokens. It cannot be recovered later, only revoked and
        reissued.
        """
        if not label or not label.strip():
            raise ValueError(
                "label must be a non-empty, human-readable "
                "identifier for the caller"
            )

        raw_key = secrets.token_urlsafe(32)

        api_key = cls(
            id=ApiKeyId.new(),
            key_hash=cls.hash_secret(raw_key),
            label=label.strip(),
            created_at=utc_now(),
        )

        return api_key, raw_key

    def is_active(self) -> bool:
        return self.revoked_at is None

    def revoke(self) -> None:
        if self.revoked_at is not None:
            raise ApiKeyAlreadyRevokedError(self.id)

        self.revoked_at = utc_now()

    def mark_used(self) -> None:
        self.last_used_at = utc_now()
