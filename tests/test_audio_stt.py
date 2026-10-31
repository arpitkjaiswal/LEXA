import asyncio
import threading
import time
import wave
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from buddy.core.audio import Microphone, RecordedAudio
from buddy.core.errors import AudioError
from buddy.core.stt import WhisperSTT


class AudioDeviceDouble:
    class PortAudioError(Exception):
        pass

    def __init__(self, *, silent=False, native=False, slow=False, broken=False):
        self.silent, self.native, self.slow, self.broken = silent, native, slow, broken
        self.opened = threading.Event()
        self.closed = False
        self.settings = None

    def query_devices(self, device, mode):
        if self.broken:
            raise self.PortAudioError("private device detail")
        return {"max_input_channels": 1, "default_samplerate": 48000}

    def check_input_settings(self, **kwargs):
        if self.native:
            raise self.PortAudioError("unsupported rate")

    def RawInputStream(self, **kwargs):
        self.settings = kwargs
        return self

    def __enter__(self):
        self.opened.set()
        return self

    def read(self, frames):
        if self.slow:
            time.sleep(0.01)
        samples = (
            np.zeros(frames, dtype=np.int16)
            if self.silent
            else np.full(frames, 1200, dtype=np.int16)
        )
        return samples.tobytes(), False

    def __exit__(self, *args):
        self.closed = True


async def test_microphone_is_lazy_bounded_and_closed(config):
    device = AudioDeviceDouble()
    mic = Microphone(replace(config.audio, max_record_seconds=1), sounddevice_module=device)
    assert not device.opened.is_set()
    result = await mic.record(threading.Event())
    assert device.closed and result.duration == 1
    assert len(result.pcm) == 32000


async def test_cancelled_capture_closes_stream_before_task_finishes(config):
    device = AudioDeviceDouble(slow=True)
    mic = Microphone(config.audio, sounddevice_module=device)
    task = asyncio.create_task(mic.record(threading.Event()))
    assert await asyncio.to_thread(device.opened.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert device.closed


async def test_silence_is_discarded(config):
    device = AudioDeviceDouble(silent=True)
    mic = Microphone(replace(config.audio, max_record_seconds=1), sounddevice_module=device)
    assert not (await mic.record(threading.Event())).pcm
    assert device.closed


async def test_released_trigger_does_not_open_mic(config):
    device = AudioDeviceDouble()
    release = threading.Event()
    release.set()
    assert not (await Microphone(config.audio, sounddevice_module=device).record(release)).pcm
    assert not device.opened.is_set()


async def test_native_rate_fallback_and_wav_header(config):
    device = AudioDeviceDouble(native=True)
    result = await Microphone(
        replace(config.audio, max_record_seconds=1), sounddevice_module=device
    ).record(threading.Event())
    assert result.sample_rate == 48000
    with wave.open(result.wav_buffer()) as source:
        assert source.getframerate() == 48000
        assert source.getnchannels() == 1 and source.getsampwidth() == 2


async def test_missing_mic_error_does_not_leak_driver_details(config):
    with pytest.raises(AudioError, match="Microphone") as error:
        await Microphone(config.audio, sounddevice_module=AudioDeviceDouble(broken=True)).record(
            threading.Event(),
        )
    assert "private device" not in str(error.value)


async def test_stt_consumes_lazy_segments_before_wav_buffer_closes(config):
    calls = []

    class ModelDouble:
        def transcribe(self, buffer, **kwargs):
            calls.append(kwargs)

            def segments():
                with wave.open(buffer) as source:
                    assert source.getframerate() == 48000
                    assert source.readframes(1) == b"\x01\x00"
                yield SimpleNamespace(text=" Hello ")
                yield SimpleNamespace(text=" friend. ")

            return segments(), SimpleNamespace(language="en")

    stt = WhisperSTT(config.stt, model=ModelDouble())
    assert await stt.transcribe(RecordedAudio(b"\x01\x00" * 480, 48000)) == "Hello friend."
    assert calls[0]["vad_filter"] is True
    assert await stt.transcribe(RecordedAudio(b"", 16000)) == ""
    assert len(calls) == 1
