from __future__ import annotations

from uuid import UUID


class LeaseNotFoundError(Exception):
    """
    Raised when something expects an existing lease by id and
    there isn't one -- almost always because reconciliation
    already reclaimed it out from under the caller. Distinct
    from a worker simply never having held a lease at all.
    """

    def __init__(self, lease_id: UUID) -> None:
        super().__init__(f"No lease found with id {lease_id}.")
        self.lease_id = lease_id
