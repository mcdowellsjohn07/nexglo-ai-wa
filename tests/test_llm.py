"""Tests for LLMClient resilience, NVIDIA NIM integration, and Nemotron defaults."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.config import Settings
from app.llm import LLMClient, RECOMMENDED_OPENROUTER_MODELS, RECOMMENDED_NVIDIA_MODELS


def test_nemotron_default_model():
    settings = Settings()
    assert settings.openrouter_model == "nvidia/nemotron-3.5-lightning:free"
    assert settings.nim_model == "nvidia/nemotron-3.5-lightning"

    client = LLMClient(settings)
    assert client.model == "nvidia/nemotron-3.5-lightning:free"
    assert client.available is False  # No key configured


def test_provider_auto_detection():
    # Only NVIDIA key provided
    s_nvidia = Settings.from_env({"NVIDIA_API_KEY": "nvapi-test12345"})
    assert s_nvidia.llm_provider == "nvidia"
    assert s_nvidia.llm_configured is True

    # Only OpenRouter key provided
    s_openrouter = Settings.from_env({"OPENROUTER_API_KEY": "sk-or-v1-test"})
    assert s_openrouter.llm_provider == "openrouter"
    assert s_openrouter.llm_configured is True

    # Both provided, default prefers explicit or openrouter
    s_both = Settings.from_env({
        "OPENROUTER_API_KEY": "sk-or-v1-test",
        "NVIDIA_API_KEY": "nvapi-test12345",
        "LLM_PROVIDER": "nvidia"
    })
    assert s_both.llm_provider == "nvidia"


def test_nvidia_nim_strips_free_suffix():
    settings = Settings(
        llm_provider="nvidia",
        nvidia_api_key="nvapi-validkey",
        nim_model="nvidia/nemotron-3.5-lightning",
    )
    with patch("openai.OpenAI") as mock_openai:
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance
        mock_instance.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Hello from Nemotron"))]
        )

        client = LLMClient(settings)
        # Force a model with :free suffix
        client.set_model("nvidia/nemotron-3.5-lightning:free")
        
        reply = client.chat([{"role": "user", "content": "hi"}])
        assert reply == "Hello from Nemotron"

        # Verify :free was stripped in the actual call to NIM
        call_args = mock_instance.chat.completions.create.call_args[1]
        assert call_args["model"] == "nvidia/nemotron-3.5-lightning"


def test_openrouter_free_model_fallback_on_429():
    settings = Settings(
        llm_provider="openrouter",
        openrouter_api_key="sk-or-validkey",
        openrouter_model="nvidia/nemotron-3.5-lightning:free",
    )
    with patch("openai.OpenAI") as mock_openai:
        mock_instance = MagicMock()
        mock_openai.return_value = mock_instance

        # First call hits 429 rate limit, second call succeeds with fallback model
        first_fail = Exception("HTTP 429 Too Many Requests: Rate limit exceeded")
        second_success = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Fallback response"))]
        )
        mock_instance.chat.completions.create.side_effect = [first_fail, second_success]

        client = LLMClient(settings)
        reply = client.chat([{"role": "user", "content": "hi"}])

        assert reply == "Fallback response"
        assert mock_instance.chat.completions.create.call_count == 2
        # First call was to the free model
        assert mock_instance.chat.completions.create.call_args_list[0][1]["model"] == "nvidia/nemotron-3.5-lightning:free"
        # Second call fell back to base model
        assert mock_instance.chat.completions.create.call_args_list[1][1]["model"] == "nvidia/nemotron-3.5-lightning"


def test_recommended_catalog_contains_nemotron():
    assert RECOMMENDED_OPENROUTER_MODELS[0]["id"] == "nvidia/nemotron-3.5-lightning:free"
    assert RECOMMENDED_OPENROUTER_MODELS[0].get("default") is True

    assert RECOMMENDED_NVIDIA_MODELS[0]["id"] == "nvidia/nemotron-3.5-lightning"
    assert RECOMMENDED_NVIDIA_MODELS[0].get("default") is True
