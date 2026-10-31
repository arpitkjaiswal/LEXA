"""Local faster-whisper adapter; PyAV resamples the in-memory WAV as needed."""

from __future__ import annotations

import asyncio
from typing import Any

from buddy.core.audio import RecordedAudio
from buddy.core.config import STTConfig
from buddy.core.errors import TranscriptionError


class WhisperSTT:
    def __init__(self, config: STTConfig, *, model: Any = None) -> None:
        self.config = config
        self._model = model
        self._lock = asyncio.Lock()

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.config.model,
                device=self.config.device,
                compute_type=self.config.compute_type,
                local_files_only=self.config.local_files_only,
            )
        except (ImportError, OSError):
            raise TranscriptionError(
                "Install the voice extra to use local faster-whisper."
            ) from None
        except Exception:
            raise TranscriptionError(
                "Cannot load the Whisper model. Check stt.model, disk/RAM and the first-run "
                "model download. Use stt.local_files_only after caching the model."
            ) from None

    async def prepare(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._load)

    async def transcribe(self, audio: RecordedAudio) -> str:
        if not audio.pcm:
            return ""
        async with self._lock:
            return await asyncio.to_thread(self._transcribe, audio)

    def _transcribe(self, audio: RecordedAudio) -> str:
        self._load()
        try:
            with audio.wav_buffer() as buffer:
                segments, _ = self._model.transcribe(
                    buffer,
                    language=self.config.language,
                    beam_size=3,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 400},
                    condition_on_previous_text=False,
                )
                return " ".join(segment.text.strip() for segment in segments).strip()
        except Exception:
            raise TranscriptionError(
                "Local transcription failed. Try again or set stt.model: tiny."
            ) from None
