"""Speech to text for uploaded audio.

Skipped when the phone already sends a text note (the glasses SDK can transcribe).
Order: OpenAI Whisper API (if OPENAI_API_KEY, costs money) -> local faster-whisper
(free, only if you `pip install faster-whisper`) -> give up and return "".
"""
import asyncio
import logging
import tempfile

import httpx

from . import config

log = logging.getLogger("inspectlog.transcribe")
_local_model = None


async def transcribe(audio: bytes, filename: str) -> str:
    if config.OPENAI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                    files={"file": (filename, audio)},
                    data={"model": "whisper-1"},
                )
                r.raise_for_status()
                return r.json().get("text", "").strip()
        except Exception as e:
            log.warning("Whisper API failed: %s", e)
    try:
        return await asyncio.to_thread(_local, audio, filename)
    except ImportError:
        log.warning("No transcription available (no OPENAI_API_KEY, faster-whisper not installed)")
    except Exception as e:
        log.warning("Local transcription failed: %s", e)
    return ""


def _load():
    global _local_model
    from faster_whisper import WhisperModel  # free, runs on the laptop

    if _local_model is None:
        _local_model = WhisperModel("base.en", compute_type="int8")
    return _local_model


async def warm_up():
    """Load the speech model at server start so the first voice note is quick."""
    try:
        await asyncio.to_thread(_load)
        log.info("Local speech-to-text ready")
    except Exception as e:
        log.warning("Local speech-to-text not available: %s", e)


def _local(audio: bytes, filename: str) -> str:
    _load()
    import subprocess
    import wave

    import numpy as np

    suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".m4a"
    with tempfile.TemporaryDirectory() as tmp:
        src, wav = f"{tmp}/in{suffix}", f"{tmp}/out.wav"
        with open(src, "wb") as f:
            f.write(audio)
        # macOS's built-in converter -> 16 kHz mono WAV (avoids a PyAV version clash in faster-whisper)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", src, wav],
                       check=True, capture_output=True)
        with wave.open(wav) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    samples = pcm.astype(np.float32) / 32768.0
    segments, _ = _local_model.transcribe(samples, language="en", vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()
