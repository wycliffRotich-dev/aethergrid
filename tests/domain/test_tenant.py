from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from app.domain.entities.tenant import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
    Tenant,
)
from app.domain.value_objects.tenant_id import TenantId


def test_tenant_id_round_trips_through_its_string_form():
    tenant_id = TenantId.new()

    assert TenantId.from_string(str(tenant_id)) == tenant_id
    assert TenantId(str(tenant_id)) == tenant_id
    assert TenantId(tenant_id.value) == tenant_id


def test_new_tenant_ids_are_distinct():
    assert TenantId.new() != TenantId.new()


def test_tenant_id_rejects_a_malformed_value():
    with pytest.raises(ValueError):
        TenantId("not-a-uuid")


def test_tenant_id_is_immutable():
    tenant_id = TenantId.new()

    with pytest.raises(FrozenInstanceError):
        tenant_id.value = UUID(int=1)  # type: ignore[misc]


def test_tenant_id_is_hashable_so_it_can_key_a_mapping():
    tenant_id = TenantId.new()

    assert {tenant_id: "a"}[TenantId(str(tenant_id))] == "a"


def test_create_assigns_a_fresh_id_and_a_utc_timestamp():
    first = Tenant.create("acme")
    second = Tenant.create("acme")

    assert first.id != second.id
    assert first.created_at.tzinfo is not None
    assert first.created_at.utcoffset().total_seconds() == 0


def test_create_trims_surrounding_whitespace():
    assert Tenant.create("  acme  ").name == "acme"


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_create_rejects_a_blank_name(name):
    with pytest.raises(ValueError):
        Tenant.create(name)


@pytest.mark.parametrize("name", ["", "   "])
def test_direct_construction_also_rejects_a_blank_name(name):
    with pytest.raises(ValueError):
        Tenant(id=TenantId.new(), name=name)


def test_tenant_is_immutable():
    tenant = Tenant.create("acme")

    with pytest.raises(FrozenInstanceError):
        tenant.name = "other"  # type: ignore[misc]


def test_the_default_tenant_constants_are_stable():
    assert str(DEFAULT_TENANT_ID) == (
        "00000000-0000-0000-0000-000000000001"
    )
    assert DEFAULT_TENANT_NAME == "default"
