"""Request model of ``POST``/``PATCH /api/v1/credentials`` (write-only values)."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr

__all__ = ["CredentialsRequest"]


class CredentialsRequest(BaseModel):
    """Alpaca key and secret; ``SecretStr`` keeps them out of reprs and logs."""

    model_config = ConfigDict(extra="forbid")

    api_key: Annotated[SecretStr, Field(min_length=1, json_schema_extra={"writeOnly": True})]
    api_secret: Annotated[SecretStr, Field(min_length=1, json_schema_extra={"writeOnly": True})]
