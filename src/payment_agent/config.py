"""Runtime configuration.

Supports three LLM provider modes — auto-detected from env vars:

  MODE 1 — Azure OpenAI (your setup)
    AZURE_OPENAI_ENDPOINT   = https://...cognitiveservices.azure.com/
    AZURE_OPENAI_API_KEY    = <key>
    AZURE_DEPLOYMENT_NAME   = gpt-4.1
    AZURE_OPENAI_API_VERSION = 2024-02-01    (optional, has default)

  MODE 2 — Standard OpenAI API key
    OPENAI_API_KEY          = sk-...
    OPENAI_MODEL            = gpt-4o         (optional, has default)

  MODE 3 — OpenRouter / any OpenAI-compatible endpoint
    OPENAI_API_KEY          = <openrouter-key>
    OPENAI_BASE_URL         = https://openrouter.ai/api/v1
    OPENAI_MODEL            = openai/gpt-4o  (optional, has default)

The openai SDK handles all three. We just build the right client.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Azure OpenAI ---
    azure_openai_endpoint: str | None = Field(None)
    azure_openai_api_key: str | None = Field(None)
    azure_deployment_name: str | None = Field(None)
    azure_openai_api_version: str = Field("2024-02-01")

    # --- Standard OpenAI / OpenRouter / any compatible endpoint ---
    openai_api_key: str | None = Field(None)
    openai_base_url: str | None = Field(None)          # set for OpenRouter etc.
    openai_model: str = Field("gpt-4o")

    # --- Payment API ---
    payment_api_base_url: str = Field(
        "https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com"
    )
    api_timeout_seconds: int = Field(10, ge=1, le=60)
    api_max_retries: int = Field(3, ge=1, le=10)

    # --- Agent behavior ---
    max_verification_attempts: int = Field(3, ge=1, le=10)
    history_window_turns: int = Field(12, ge=2, le=50)
    extraction_temperature: float = Field(0.0, ge=0.0, le=2.0)
    response_temperature: float = Field(0.3, ge=0.0, le=2.0)
    response_max_tokens: int = Field(350, ge=50, le=4000)
    extraction_max_tokens: int = Field(400, ge=50, le=4000)

    @model_validator(mode="after")
    def _require_at_least_one_provider(self) -> "Settings":
        has_azure = self.azure_openai_endpoint and self.azure_openai_api_key
        has_openai = self.openai_api_key
        if not has_azure and not has_openai:
            raise ValueError(
                "No LLM provider configured.\n"
                "Set either:\n"
                "  AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY + AZURE_DEPLOYMENT_NAME\n"
                "  or OPENAI_API_KEY (optionally with OPENAI_BASE_URL for OpenRouter etc.)"
            )
        return self

    @property
    def provider(self) -> Literal["azure", "openai"]:
        if self.azure_openai_endpoint and self.azure_openai_api_key:
            return "azure"
        return "openai"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
