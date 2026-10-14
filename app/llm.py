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


RECOMMENDED_OPENROUTER_MODELS = [
    {
        "id": "meta-llama/llama-3.3-70b-instruct",
        "name": "Llama 3.3 70B Instruct (Default & Recommended)",
        "provider": "Meta",
        "description": "State-of-the-art open weights, excellent for customer service and high-speed WhatsApp chatting.",
        "cost_per_m_tokens": "$0.12 input / $0.30 output",
        "latency": "Fast (~600ms)",
    },
    {
        "id": "meta-llama/llama-3.3-70b-instruct:free",
        "name": "Llama 3.3 70B Instruct (Free Tier)",
        "provider": "Meta via OpenRouter Free",
        "description": "Completely 100% free tier hosted on OpenRouter. Perfect for zero-budget testing.",
        "cost_per_m_tokens": "Free ($0.00)",
        "latency": "Fast (~700ms)",
    },
    {
        "id": "nvidia/llama-3.1-nemotron-70b-instruct",
        "name": "NVIDIA Llama 3.1 Nemotron 70B",
        "provider": "NVIDIA",
        "description": "NVIDIA-tuned alignment model, outstanding for dialog, customer service, and structured tasks.",
        "cost_per_m_tokens": "$0.35 input / $0.40 output",
        "latency": "Fast (~600ms)",
    },
    {
        "id": "google/gemini-2.0-flash-001",
        "name": "Gemini 2.0 Flash",
        "provider": "Google",
        "description": "Blazing fast inference, native multilingual capabilities, and ultra-cheap token pricing.",
        "cost_per_m_tokens": "$0.10 input / $0.40 output",
        "latency": "Ultra-fast (~300ms)",
    },
    {
        "id": "deepseek/deepseek-chat",
        "name": "DeepSeek V3",
        "provider": "DeepSeek",
        "description": "Superb reasoning and instruction adherence with ultra-competitive pricing.",
        "cost_per_m_tokens": "$0.14 input / $0.28 output",
        "latency": "Fast (~700ms)",
    },
    {
        "id": "anthropic/claude-3.5-haiku",
        "name": "Claude 3.5 Haiku",
        "provider": "Anthropic",
        "description": "High brand safety, concise formatting, and great tone for formal customer care.",
        "cost_per_m_tokens": "$0.80 input / $4.00 output",
        "latency": "Fast (~650ms)",
    },
    {
        "id": "openai/gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider": "OpenAI",
        "description": "Highly consistent OpenAI compact model, fast and reliable worldwide.",
        "cost_per_m_tokens": "$0.15 input / $0.60 output",
        "latency": "Fast (~500ms)",
    },
]

RECOMMENDED_NVIDIA_MODELS = [
    {
        "id": "meta/llama-3.3-70b-instruct",
        "name": "Llama 3.3 70B Instruct (NVIDIA NIM Default)",
        "provider": "Meta via NVIDIA NIM",
        "description": "State-of-the-art open weights on NVIDIA GPU infrastructure with 1,000 free requests.",
        "cost_per_m_tokens": "Free API Credits (build.nvidia.com)",
        "latency": "Fast (~500ms)",
    },
    {
        "id": "nvidia/llama-3.1-nemotron-70b-instruct",
        "name": "NVIDIA Llama 3.1 Nemotron 70B",
        "provider": "NVIDIA",
        "description": "NVIDIA's customized model optimized for helpfulness, reasoning, and conversational customer care.",
        "cost_per_m_tokens": "Free API Credits (build.nvidia.com)",
        "latency": "Fast (~600ms)",
    },
    {
        "id": "meta/llama-3.1-8b-instruct",
        "name": "Llama 3.1 8B Instruct",
        "provider": "Meta via NVIDIA NIM",
        "description": "Ultra-lightweight model with lightning fast response times for simple customer inquiries.",
        "cost_per_m_tokens": "Free API Credits (build.nvidia.com)",
        "latency": "Ultra-fast (~200ms)",
    },
    {
        "id": "mistralai/mistral-large-2-instruct",
        "name": "Mistral Large 2",
        "provider": "Mistral via NVIDIA NIM",
        "description": "Top-tier 123B parameter European multilingual model hosted on NVIDIA NIM.",
        "cost_per_m_tokens": "Free API Credits (build.nvidia.com)",
        "latency": "Fast (~650ms)",
    },
    {
        "id": "deepseek-ai/deepseek-r1",
        "name": "DeepSeek R1",
        "provider": "DeepSeek via NVIDIA NIM",
        "description": "Deep reasoning model running on NVIDIA accelerated compute.",
        "cost_per_m_tokens": "Free API Credits (build.nvidia.com)",
        "latency": "Variable",
    },
]



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
                    self._model = settings.openrouter_model or "meta-llama/llama-3.3-70b-instruct"
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
                self._model = settings.openrouter_model or "meta-llama/llama-3.3-70b-instruct"
        else:
            self._model = settings.openrouter_model or "meta-llama/llama-3.3-70b-instruct"
            log.warning(
                "LLM API key not set. Running in offline mode "
                "(keyword routing + raw KB answers)."
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def model(self) -> str:
        return self._model

    def set_model(self, model_name: str) -> str:
        """Switch the active model dynamically without restarting."""
        clean = model_name.strip()
        if clean:
            self._model = clean
            log.info("Switched active LLM model to: %s", self._model)
        return self._model

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