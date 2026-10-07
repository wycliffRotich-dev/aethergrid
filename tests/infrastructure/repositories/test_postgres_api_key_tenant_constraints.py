from __future__ import annotations

import uuid

import pytest
from psycopg import errors
from psycopg_pool import ConnectionPool

from app.domain.entities.tenant import DEFAULT_TENANT_ID, Tenant
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.postgres_api_key_repository import (
    PostgresApiKeyRepository,
)
from app.infrastructure.repositories.postgres_tenant_repository import (
    PostgresTenantRepository,
)
from tests.support.api_keys import make_api_key


@pytest.fixture(scope="session")
def pool(test_database_url):
    test_pool = ConnectionPool(
        test_database_url,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True},
    )
    yield test_pool
    test_pool.close()


def _reset(pool) -> None:
    with pool.connection() as conn:
        conn.execute("TRUNCATE api_keys")
        conn.execute(
            "DELETE FROM tenants WHERE id <> %s",
            (str(DEFAULT_TENANT_ID),),
        )


@pytest.fixture
def repositories(pool):
    _reset(pool)
    yield PostgresApiKeyRepository(pool), PostgresTenantRepository(pool)
    _reset(pool)


def _tenant(tenants) -> Tenant:
    tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    tenants.save(tenant)
    return tenant


def test_a_key_in_an_unknown_tenant_is_rejected(repositories):
    keys, _ = repositories
    key, _ = make_api_key(label="orphan", tenant_id=TenantId.new())

    with pytest.raises(errors.ForeignKeyViolation):
        keys.save(key)


def test_a_key_cannot_have_an_issuer_in_another_tenant(repositories):
    keys, tenants = repositories
    issuer_tenant = _tenant(tenants)
    child_tenant = _tenant(tenants)
    issuer, _ = make_api_key(label="issuer", tenant_id=issuer_tenant.id)
    keys.save(issuer)
    child, _ = make_api_key(
        label="child",
        tenant_id=child_tenant.id,
        issued_by=issuer.id,
    )

    with pytest.raises(errors.ForeignKeyViolation):
        keys.save(child)


def test_a_key_may_have_an_issuer_in_the_same_tenant(repositories):
    keys, tenants = repositories
    tenant = _tenant(tenants)
    issuer, _ = make_api_key(label="issuer", tenant_id=tenant.id)
    keys.save(issuer)
    child, _ = issuer.issue_child(label="child")

    keys.save(child)

    stored = keys.get_by_id(child.id)
    assert stored is not None
    assert stored.tenant_id == tenant.id
    assert stored.issued_by == issuer.id


def test_saving_again_never_moves_a_key_to_another_tenant(repositories):
    keys, tenants = repositories
    first = _tenant(tenants)
    second = _tenant(tenants)
    key, _ = make_api_key(label="runner", tenant_id=first.id)
    keys.save(key)

    key.tenant_id = second.id
    keys.save(key)

    stored = keys.get_by_id(key.id)
    assert stored is not None
    assert stored.tenant_id == first.id
