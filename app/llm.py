"""LLM client for OpenRouter (OpenAI-compatible) and NVIDIA NIM (legacy).

Free API key: sign up at https://openrouter.ai and create a key.
Set OPENROUTER_API_KEY and OPENROUTER_MODEL.

The agent degrades gracefully when no key is configured: intent routing falls
back to keywords and FAQ answers return the top knowledge-base snippet verbatim.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import Settings

log = logging.getLogger("nexglo.llm")


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._model = ""

        if settings.llm_configured:
            try:
                from openai import OpenAI

                if settings.llm_provider == "openrouter":
                    self._client = OpenAI(
                        base_url=settings.openrouter_base_url,
                        api_key=settings.openrouter_api_key,
                        timeout=settings.openrouter_timeout_seconds,
                    )
                    self._model = settings.openrouter_model
                    # OpenRouter recommended headers
                    self._extra_headers = {
                        "HTTP-Referer": "https://nexglotv.com",
                        "X-Title": "NexgloTV WhatsApp Agent",
                    }
                else:
                    # Legacy NVIDIA NIM
                    self._client = OpenAI(
                        base_url=settings.nim_base_url,
                        api_key=settings.nvidia_api_key,
                        timeout=30.0,
                    )
                    self._model = settings.nim_model
                    self._extra_headers = {}

            except Exception as exc:  # pragma: no cover - import/config failure
                log.warning("Could not initialise LLM client: %s", exc)
                self._client = None
        else:
            log.warning(
                "LLM API key not set. Running in offline mode "
                "(keyword routing + raw KB answers)."
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 600,
    ) -> Optional[str]:
        """Return the assistant text, or None on any failure / when offline."""
        if self._client is None:
            return None
        try:
            # Build kwargs
            kwargs = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": min(max_tokens, self.settings.openrouter_max_output_tokens),
            }
            if self._extra_headers:
                kwargs["extra_headers"] = self._extra_headers

            resp = self._client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            return content.strip() if content else None
        except Exception as exc:
            log.warning("LLM request failed: %s", exc)
            return None