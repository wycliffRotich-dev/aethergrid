from pydantic import BaseModel, Field


class CreateApiKeyRequest(BaseModel):
    """
    Request payload for issuing a new API key.
    """

    label: str = Field(min_length=1)
