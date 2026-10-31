"""Bounded, on-demand microphone capture. PCM stays in memory."""

from __future__ import annotations

import asyncio
import io
import threading
import wave
from dataclasses import dataclass
from typing import Any

from buddy.core.config import AudioConfig
from buddy.core.errors import AudioError


@dataclass(frozen=True)
class RecordedAudio:
    pcm: bytes
    sample_rate: int

    @property
    def duration(self) -> float:
        return len(self.pcm) / (2 * self.sample_rate)

    def wav_buffer(self) -> io.BytesIO:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self.sample_rate)
            output.writeframes(self.pcm)
        buffer.seek(0)
        return buffer


class Microphone:
    def __init__(self, config: AudioConfig, *, sounddevice_module: Any = None) -> None:
        self.config = config
        self._sounddevice = sounddevice_module

    async def record(self, stop: threading.Event) -> RecordedAudio:
        """Cancellation signals the recorder and waits for the stream to close."""
        task = asyncio.create_task(asyncio.to_thread(self._record, stop))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            stop.set()
            try:
                await task
            except AudioError:
                pass
            raise

    def _record(self, stop: threading.Event) -> RecordedAudio:
        try:
            import numpy as np

            if self._sounddevice is None:
                import sounddevice

                self._sounddevice = sounddevice
            sd = self._sounddevice
        except (ImportError, OSError):
            raise AudioError(
                "Voice capture needs the voice extra and PortAudio. See README setup."
            ) from None
        if stop.is_set():
            return RecordedAudio(b"", self.config.sample_rate)
        try:
            # Some Mac audio devices only accept their native 44.1/48 kHz rate.
            device = sd.query_devices(self.config.device, "input")
            if device["max_input_channels"] < 1:
                raise AudioError("This device has no microphone input. Try --list-devices.")
            rate = self.config.sample_rate
            try:
                sd.check_input_settings(
                    device=self.config.device,
                    channels=1,
                    dtype="int16",
                    samplerate=rate,
                )
            except sd.PortAudioError:
                rate = int(device["default_samplerate"])
            block_frames = max(128, int(rate * 0.05))
            max_frames = int(rate * self.config.max_record_seconds)
            chunks: list[bytes] = []
            count = 0
            with sd.RawInputStream(
                samplerate=rate,
                device=self.config.device,
                channels=1,
                dtype="int16",
                blocksize=block_frames,
            ) as stream:
                while not stop.is_set() and count < max_frames:
                    frames = min(block_frames, max_frames - count)
                    data, overflowed = stream.read(frames)
                    if overflowed:
                        raise AudioError(
                            "Microphone input overflowed. Try again or use a smaller STT model."
                        )
                    chunks.append(bytes(data))
                    count += frames
            audio = RecordedAudio(b"".join(chunks), rate)
            if audio.duration < self.config.min_record_seconds:
                return RecordedAudio(b"", rate)
            samples = np.frombuffer(audio.pcm, dtype=np.int16).astype(np.float32) / 32768
            if (
                samples.size == 0
                or float(np.sqrt(np.mean(samples * samples))) < self.config.silence_rms
            ):
                return RecordedAudio(b"", rate)
            return audio
        except AudioError:
            raise
        except Exception:
            raise AudioError(
                "Cannot open the microphone. In macOS System Settings > Privacy & Security > "
                "Microphone, allow your terminal. Check --list-devices and audio.device."
            ) from None


def list_devices() -> str:
    try:
        import sounddevice as sd

        return str(sd.query_devices())
    except (ImportError, OSError):
        raise AudioError(
            "Install the voice extra and PortAudio before listing microphones."
        ) from None
    except Exception:
        raise AudioError(
            "PortAudio could not list audio devices. Check your audio setup."
        ) from None
