import asyncio
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from buddy.core.wake import WakeDetector, effective_framework


def test_apple_silicon_uses_litert_instead_of_onnx(config, monkeypatch):
    from buddy.core import wake

    monkeypatch.setattr(wake.sys, "platform", "darwin")
    monkeypatch.setattr(wake.platform, "machine", lambda: "arm64")
    assert effective_framework(config) == "tflite"
    monkeypatch.setattr(wake.platform, "machine", lambda: "x86_64")
    assert effective_framework(config) == "onnx"


def test_detector_resamples_native_rate_and_requires_consecutive_frames(config):
    pytest.importorskip("scipy")
    calls, streams = [], []

    class Model:
        def reset(self):
            pass

        def predict(self, samples):
            assert samples.dtype == np.int16 and len(samples) == 1280
            calls.append(True)
            return {"hey_jarvis": [0.6, 0.2, 0.7, 0.8][len(calls) - 1]}

    class Stream:
        def __init__(self, **kwargs):
            assert kwargs["samplerate"] == 48000 and kwargs["blocksize"] == 3840
            self.closed = False
            streams.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def read(self, frames):
            return np.full(frames, 200, dtype=np.int16).tobytes(), False

    def check(**kwargs):
        raise ValueError

    sd = SimpleNamespace(
        check_input_settings=check,
        PortAudioError=ValueError,
        query_devices=lambda *a: {"default_samplerate": 48000},
        RawInputStream=Stream,
    )
    detector = WakeDetector(config, model=Model(), sounddevice_module=sd)
    assert detector._wait(threading.Event()) is True
    assert len(calls) == 4 and streams[0].closed


async def test_cancellation_waits_for_wake_microphone_to_close(config):
    closed, opened = threading.Event(), threading.Event()
    detector = WakeDetector(config, model=object())

    def wait(stop):
        opened.set()
        stop.wait(2)
        closed.set()
        return False

    detector._wait = wait
    task = asyncio.create_task(detector.wait(threading.Event()))
    await asyncio.to_thread(opened.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
