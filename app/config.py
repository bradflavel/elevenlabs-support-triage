from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: str = Field(..., alias="DATABASE_URL")
    elevenlabs_webhook_secret: str = Field(..., alias="ELEVENLABS_WEBHOOK_SECRET")
    elevenlabs_agent_id: str | None = Field(default=None, alias="ELEVENLABS_AGENT_ID")
    app_env: str = Field(default="dev", alias="APP_ENV")


def get_settings() -> Settings:
    return Settings()
