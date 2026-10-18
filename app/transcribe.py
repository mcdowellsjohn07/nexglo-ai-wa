"""Voice-note transcription engine supporting cloud Whisper and local engines.

Supported backends:
1. Groq Whisper API (whisper-large-v3-turbo via GROQ_API_KEY - sub-second latency)
2. OpenAI Whisper API (whisper-1 via OPENAI_API_KEY)
3. Local faster-whisper (if installed on CPU/GPU)
4. SpeechRecognition / Google Speech (if speech_recognition installed)
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import httpx

log = logging.getLogger("whatsapp_agent.transcribe")

_local_model = None
_local_model_size: Optional[str] = None


def _get_local_model(model_size: str):
    """Lazily load and cache a faster-whisper WhisperModel."""
    global _local_model, _local_model_size
    if _local_model is not None and _local_model_size == model_size:
        return _local_model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    try:
        _local_model = WhisperModel(model_size, device="auto", compute_type="int8")
        _local_model_size = model_size
        return _local_model
    except Exception as exc:
        log.warning("Could not load faster-whisper model '%s': %s", model_size, exc)
        return None


def transcribe_via_cloud(audio_bytes: bytes, filename: str = "voice.ogg") -> Optional[str]:
    """Transcribe audio bytes using cloud Whisper (Groq or OpenAI)."""
    # 1. Groq Whisper (ultra-fast, free tier available)
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {groq_key}"}
            files = {"file": (filename, io.BytesIO(audio_bytes), "audio/ogg")}
            data = {"model": "whisper-large-v3-turbo"}
            resp = httpx.post(url, headers=headers, files=files, data=data, timeout=30.0)
            if resp.status_code == 200:
                result = resp.json()
                text = (result.get("text") or "").strip()
                if text:
                    return text
            else:
                log.warning("Groq Whisper failed (%s): %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            log.warning("Groq transcription error: %s", exc)

    # 2. OpenAI Whisper
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {openai_key}"}
            files = {"file": (filename, io.BytesIO(audio_bytes), "audio/ogg")}
            data = {"model": "whisper-1"}
            resp = httpx.post(url, headers=headers, files=files, data=data, timeout=30.0)
            if resp.status_code == 200:
                result = resp.json()
                text = (result.get("text") or "").strip()
                if text:
                    return text
            else:
                log.warning("OpenAI Whisper failed (%s): %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            log.warning("OpenAI transcription error: %s", exc)

    return None


def transcribe_audio(
    audio_bytes: bytes,
    model_size: str = "base",
    settings: Optional[Any] = None,
) -> Optional[str]:
    """Transcribe raw audio bytes into text.
    
    Checks in order:
    1. Cloud Whisper (Groq / OpenAI if API key provided)
    2. Local faster-whisper (if installed)
    3. SpeechRecognition (if installed)
    """
    if not audio_bytes:
        return None

    # Check for test / simulated audio marker
    if audio_bytes.startswith(b"TEST_VOICE:"):
        return audio_bytes.decode("utf-8", errors="ignore").replace("TEST_VOICE:", "").strip()

    # 1. Try Cloud APIs
    cloud_result = transcribe_via_cloud(audio_bytes)
    if cloud_result:
        return cloud_result

    # 2. Try Local faster-whisper
    local_model = _get_local_model(model_size)
    if local_model is not None:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = Path(tmp.name)
            segments, _info = local_model.transcribe(str(tmp_path), vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if text:
                return text
        except Exception as exc:
            log.warning("Local transcription failed: %s", exc)
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    # 3. SpeechRecognition fallback
    try:
        import speech_recognition as sr
        # Only works if wav / pcm
        r = sr.Recognizer()
        with io.BytesIO(audio_bytes) as audio_file:
            with sr.AudioFile(audio_file) as source:
                audio_data = r.record(source)
                return r.recognize_google(audio_data)
    except Exception:
        pass

    log.info("No transcription backend succeeded for audio (%d bytes)", len(audio_bytes))
    return None
