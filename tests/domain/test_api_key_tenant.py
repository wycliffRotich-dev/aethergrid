from __future__ import annotations

import pytest

from app.domain.entities.api_key import ApiKey
from app.domain.value_objects.api_key_scope import KEYS_MANAGE
from app.domain.value_objects.tenant_id import TenantId


def test_issue_requires_a_tenant():
    with pytest.raises(TypeError):
        ApiKey.issue(label="no-tenant")  # type: ignore[call-arg]


def test_issue_records_the_tenant():
    tenant_id = TenantId.new()

    api_key, _ = ApiKey.issue(label="runner", tenant_id=tenant_id)

    assert api_key.tenant_id == tenant_id


def test_a_child_key_inherits_its_issuers_tenant_and_records_the_issuer():
    tenant_id = TenantId.new()
    issuer, _ = ApiKey.issue(label="issuer", tenant_id=tenant_id)

    child, _ = issuer.issue_child(label="child")

    assert child.tenant_id == tenant_id
    assert child.issued_by == issuer.id


def test_issue_child_takes_no_tenant_so_a_caller_cannot_choose_one():
    issuer, _ = ApiKey.issue(label="issuer", tenant_id=TenantId.new())

    with pytest.raises(TypeError):
        issuer.issue_child(  # type: ignore[call-arg]
            label="child",
            tenant_id=TenantId.new(),
        )


def test_children_of_different_issuers_stay_in_their_own_tenants():
    first, _ = ApiKey.issue(label="first", tenant_id=TenantId.new())
    second, _ = ApiKey.issue(label="second", tenant_id=TenantId.new())

    assert first.issue_child(label="a")[0].tenant_id == first.tenant_id
    assert second.issue_child(label="b")[0].tenant_id == second.tenant_id
    assert first.tenant_id != second.tenant_id


def test_a_child_does_not_inherit_scopes():
    issuer, _ = ApiKey.issue(
        label="issuer",
        tenant_id=TenantId.new(),
        scopes=frozenset({KEYS_MANAGE}),
    )

    child, _ = issuer.issue_child(label="child")

    assert child.scopes == frozenset()
