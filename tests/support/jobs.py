from __future__ import annotations

from typing import Any

from app.domain.entities.job import Job
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


def make_job(**overrides: Any) -> Job:
    """
    Build a Job for a test.

    Every test job goes through here, so what a test job looks like
    by default is decided in one place. Only the fields Job requires
    are defaulted: a new id and the smallest resource request the
    domain tests already use (1 core, 512 MiB, no VRAM). Everything
    else, such as max_retries and priority, keeps Job's own default,
    so a test that does not name a field gets exactly what production
    code would. Any Job field can be overridden by keyword.
    """
    defaults: dict[str, Any] = {
        "id": JobId.new(),
        "resources": ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        # The default tenant, so a test only names a tenant when
        # tenancy is what it is testing (ADR 0064).
        "tenant_id": DEFAULT_TENANT_ID,
    }
    defaults.update(overrides)

    return Job(**defaults)
