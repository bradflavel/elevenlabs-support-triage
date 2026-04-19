from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Metadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    start_time_unix_secs: int | None = None
    call_duration_secs: int | None = None


class Analysis(BaseModel):
    model_config = ConfigDict(extra="allow")

    data_collection_results: dict[str, Any] = Field(default_factory=dict)


class WebhookData(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_id: str
    conversation_id: str
    analysis: Analysis = Field(default_factory=Analysis)
    metadata: Metadata | None = None


class WebhookPayload(BaseModel):
    """Top-level ElevenLabs post-call webhook payload.

    `extra = "allow"` throughout means unknown fields from future SDK
    versions won't cause a 422; only missing transport-level required
    fields (`data.agent_id`, `data.conversation_id`) do.
    """

    model_config = ConfigDict(extra="allow")

    type: str | None = None
    event_timestamp: int | None = None
    data: WebhookData
