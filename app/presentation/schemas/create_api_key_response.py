from pydantic import BaseModel


class CreateApiKeyResponse(BaseModel):
    """
    HTTP response returned after issuing a new API key.

    `key` is the plaintext credential. It is returned exactly
    once, in this response, and cannot be retrieved again --
    store it now.
    """

    id: str
    label: str
    key: str
