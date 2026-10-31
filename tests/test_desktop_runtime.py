import asyncio
from collections import defaultdict
from dataclasses import replace

from conftest import BrainDouble, SpeakerDouble

from buddy.core.audio import RecordedAudio
from buddy.core.config import Secrets
from buddy.core.local_brain import LocalBrain
from buddy.ui.runtime import DesktopRuntime


async def test_mute_closes_wake_and_live_capture_before_transcription(config, monkeypatch):
    from buddy.ui import runtime as module

    events = defaultdict(asyncio.Event)
    wake_open, captured, capture_closed = False, asyncio.Event(), asyncio.Event()
    transcripts = []

    class Wake:
        def __init__(self, config):
            pass

        async def prepare(self):
            pass

        async def wait(self, stop):
            nonlocal wake_open
            wake_open = True
            events["wake_open"].set()
            try:
                await asyncio.Event().wait()
            finally:
                wake_open = False

    class Mic:
        def __init__(self, config):
            pass

        async def record(self, stop):
            assert not wake_open
            captured.set()
            try:
                await asyncio.Event().wait()
            finally:
                stop.set()
                capture_closed.set()
            return RecordedAudio(b"", 16000)

    class STT:
        def __init__(self, config):
            pass

        async def prepare(self):
            pass

        async def transcribe(self, audio):
            transcripts.append(audio)
            return "never transcribed"

    monkeypatch.setattr(module, "create_brain", lambda *a, **k: BrainDouble())
    monkeypatch.setattr(module, "SpeechOutput", lambda *a: SpeakerDouble())
    monkeypatch.setattr(module, "Microphone", Mic)
    monkeypatch.setattr(module, "WhisperSTT", STT)
    monkeypatch.setattr(module, "WakeDetector", Wake)

    def emit(kind, payload):
        events[kind if kind != "state" else payload].set()

    worker = DesktopRuntime(config, emit, wake=True)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(events["wake_open"].wait(), 3)
        worker.submit("talk")
        await asyncio.wait_for(captured.wait(), 3)
        worker.submit("mute", True)
        await asyncio.wait_for(capture_closed.wait(), 3)
        assert not wake_open and transcripts == []
        assert worker.assistant.muted
    finally:
        worker.submit("quit")
        await asyncio.wait_for(task, 3)


async def test_first_launch_and_settings_apply_new_key_without_restart(config, monkeypatch):
    from buddy.ui import runtime as module

    ready, configured, finished = (asyncio.Event() for _ in range(3))
    received = []
    brains = []
    create = module.create_brain

    def factory(value, *, demo=False):
        if not value.secrets.anthropic_api_key:
            return create(value, demo=demo)
        received.append(value.secrets.anthropic_api_key)
        brain = BrainDouble()
        brains.append(brain)
        return brain

    monkeypatch.setattr(module, "create_brain", factory)
    monkeypatch.setattr(module, "SpeechOutput", lambda *a: SpeakerDouble())

    def emit(kind, payload):
        if kind == "ready":
            ready.set()
        elif kind == "mode" and payload["configured"]:
            configured.set()
        elif kind == "turn_end":
            finished.set()

    initial = replace(config, secrets=Secrets())
    worker = DesktopRuntime(initial, emit)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(ready.wait(), 3)
        assert isinstance(worker.assistant.brain, LocalBrain)
        worker.submit("text", "note First launch: local notes work")
        await asyncio.wait_for(finished.wait(), 3)
        assert worker.store.execute("SELECT title FROM notes")[0]["title"] == "First launch"
        old_registry = worker.registry
        await old_registry.invoke("take_screenshot", {})
        assert old_registry.pending
        worker.submit("configure", replace(config, secrets=Secrets("new-test-key", "")))
        await asyncio.wait_for(configured.wait(), 3)
        assert old_registry.pending is None and worker.registry is not old_registry
        assert received == ["new-test-key"]
        finished.clear()
        worker.submit("text", "Hello from the configured provider")
        await asyncio.wait_for(finished.wait(), 3)
        assert brains[0].calls
        configured.clear()
        worker.submit("demo", True)
        await asyncio.wait_for(configured.wait(), 3)
        assert brains[0].closed and worker.assistant.tools is None
    finally:
        worker.submit("quit")
        await asyncio.wait_for(task, 3)


async def test_mute_interrupts_speech_and_discards_partial_conversation(config, monkeypatch):
    from buddy.ui import runtime as module

    started, stopped, ready, muted = (asyncio.Event() for _ in range(4))

    class Speaker(SpeakerDouble):
        async def speak(self, text):
            started.set()
            await asyncio.Event().wait()

        async def stop(self):
            stopped.set()

    monkeypatch.setattr(module, "create_brain", lambda *a, **k: BrainDouble())
    monkeypatch.setattr(module, "SpeechOutput", lambda *a: Speaker())

    def emit(kind, payload):
        if kind == "ready":
            ready.set()
        if kind == "state" and payload == "muted":
            muted.set()

    worker = DesktopRuntime(config, emit)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(ready.wait(), 3)
        worker.submit("text", "Hello")
        await asyncio.wait_for(started.wait(), 3)
        worker.submit("mute", True)
        await asyncio.wait_for(muted.wait(), 3)
        await asyncio.wait_for(stopped.wait(), 3)
        assert worker.assistant.history == []
    finally:
        worker.submit("quit")
        await asyncio.wait_for(task, 3)
