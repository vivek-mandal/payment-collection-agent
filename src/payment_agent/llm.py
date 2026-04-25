"""LLM layer — client factory, field extraction, response generation.

We use the openai SDK directly (no LangChain wrapper needed).
The SDK already handles Azure, standard OpenAI, and any OpenAI-compatible
endpoint (OpenRouter, Together, Ollama, etc.) — you just point it at the
right base_url with the right key.

build_llm_client(settings) picks the right flavour automatically based on
which env vars are present (see config.py for the three supported modes).

FieldExtractor   — LLM call #1: user utterance → typed ExtractedFields  (temp=0)
ResponseGenerator — LLM call #2: FSM outcome   → natural-language reply  (temp=0.3)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openai import AzureOpenAI, OpenAI
from pydantic import ValidationError

from payment_agent.config import Settings, get_settings
from payment_agent.models import ConversationState, ExtractedFields

log = logging.getLogger(__name__)

_PROMPTS = Path(__file__).parent / "prompts"


# ---------------------------------------------------------------------------
# Client factory — returns a plain openai client (Azure or standard)
# ---------------------------------------------------------------------------

def build_llm_client(settings: Settings | None = None) -> AzureOpenAI | OpenAI:
    """Return the right openai client based on available env vars.

    Azure   → AzureOpenAI(endpoint, key, api_version)
    OpenAI  → OpenAI(api_key)           standard api.openai.com
    OpenAI  → OpenAI(api_key, base_url) OpenRouter / any compatible endpoint
    """
    cfg = settings or get_settings()

    if cfg.provider == "azure":
        return AzureOpenAI(
            azure_endpoint=cfg.azure_openai_endpoint,  # type: ignore[arg-type]
            api_key=cfg.azure_openai_api_key,
            api_version=cfg.azure_openai_api_version,
        )

    # Standard OpenAI or compatible (OpenRouter, etc.)
    kwargs: dict[str, Any] = {"api_key": cfg.openai_api_key}
    if cfg.openai_base_url:
        kwargs["base_url"] = cfg.openai_base_url
    return OpenAI(**kwargs)


def _model_name(cfg: Settings) -> str:
    """Deployment name for Azure, model name for OpenAI/OpenRouter."""
    if cfg.provider == "azure":
        return cfg.azure_deployment_name or "gpt-4o"
    return cfg.openai_model


def _chat(
    client: AzureOpenAI | OpenAI,
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    json_object: bool = False,
) -> str:
    """Single wrapper around client.chat.completions.create."""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_object:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return (response.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# Field extractor — LLM call #1
# ---------------------------------------------------------------------------

class FieldExtractor:
    """Convert a raw user utterance into typed ExtractedFields (temp=0)."""

    def __init__(self, client: AzureOpenAI | OpenAI, settings: Settings | None = None) -> None:
        self._client = client
        self._cfg = settings or get_settings()
        self._model = _model_name(self._cfg)
        self._template = (_PROMPTS / "extraction_system.txt").read_text("utf-8")

    def extract(
        self,
        user_input: str,
        *,
        state: str = "greeting",
        last_agent_message: str | None = None,
    ) -> ExtractedFields:
        if not user_input.strip():
            return ExtractedFields()
        system = self._template.replace("STATE_PLACEHOLDER", state)
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if last_agent_message:
            messages.append({"role": "assistant", "content": last_agent_message})
        messages.append({"role": "user", "content": user_input})
        try:
            raw = _chat(
                self._client,
                self._model,
                messages=messages,
                temperature=self._cfg.extraction_temperature,
                max_tokens=self._cfg.extraction_max_tokens,
                json_object=True,
            )
            return ExtractedFields.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            log.warning("extractor: bad model output — %s", exc)
            return ExtractedFields()
        except Exception as exc:
            log.exception("extractor: unexpected failure — %s", exc)
            return ExtractedFields()


# ---------------------------------------------------------------------------
# Response generator — LLM call #2
# ---------------------------------------------------------------------------

class ResponseGenerator:
    """Turn an FSM BusinessOutcome into a natural-language reply (temp=0.3)."""

    def __init__(self, client: AzureOpenAI | OpenAI, settings: Settings | None = None) -> None:
        self._client = client
        self._cfg = settings or get_settings()
        self._model = _model_name(self._cfg)
        self._template = (_PROMPTS / "response_system.txt").read_text("utf-8")

    def render(
        self,
        *,
        state: str,
        account_id: str | None,
        verified: bool,
        attempts_used: int,
        collected: ConversationState,
        outcome: str,
        history: list[dict[str, str]],
    ) -> str:
        system = self._template.format(
            state=state,
            account_id=account_id or "not yet provided",
            verified=verified,
            attempts_used=attempts_used,
            max_attempts=self._cfg.max_verification_attempts,
            collected=json.dumps(collected.safe_summary(), indent=2),
            outcome=outcome,
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(history[-self._cfg.history_window_turns:])
        try:
            return _chat(
                self._client,
                self._model,
                messages=messages,
                temperature=self._cfg.response_temperature,
                max_tokens=self._cfg.response_max_tokens,
            )
        except Exception as exc:
            log.exception("responder: failed — %s", exc)
            return (
                "I'm having trouble processing your request right now. "
                "Please try again in a moment."
            )
