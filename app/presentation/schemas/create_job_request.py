from pydantic import BaseModel, Field, field_validator


class CreateJobRequest(BaseModel):
    """
    Request payload for creating a new job.
    """

    cpu_cores: int = Field(gt=0)
    memory_mib: int = Field(gt=0)
    vram_mib: int = Field(ge=0)
    command: list[str] | None = None
    """
    Optional argv-style command for this job to execute,
    e.g. ["python", "train.py", "--epochs", "5"]. See
    ADR 0028. Never a raw shell string.
    """

    @field_validator("command")
    @classmethod
    def command_must_not_be_empty_or_contain_blanks(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is None:
            return value

        if len(value) == 0:
            raise ValueError(
                "command must not be an empty list",
            )

        if any(not part.strip() for part in value):
            raise ValueError(
                "command must not contain empty or "
                "blank arguments",
            )

        return value
