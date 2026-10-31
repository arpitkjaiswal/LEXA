import asyncio
from types import SimpleNamespace

from conftest import AuditDouble, BrainDouble, SpeakerDouble

from buddy.core.assistant import Assistant
from buddy.core.audio import RecordedAudio
from buddy.core.hotkey import GlobalPushToTalk
from buddy.core.runner import TerminalRunner


class ConsoleDouble:
    def __init__(self, lines):
        self.lines = iter(lines)
        self.output = []
        self.cancelled = False

    def write(self, text, **kwargs):
        self.output.append(text)

    async def readline(self, prompt):
        try:
            return next(self.lines)
        except StopIteration:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise


class MicrophoneDouble:
    def __init__(self, immediate=False):
        self.calls = 0
        self.immediate = immediate

    async def record(self, stop):
        self.calls += 1
        if not self.immediate:
            await asyncio.to_thread(stop.wait)
        return RecordedAudio(b"\x01\x00" * 16000, 16000)


class STTDouble:
    def __init__(self):
        self.prepared = False
        self.calls = 0

    async def prepare(self):
        self.prepared = True

    async def transcribe(self, audio):
        self.calls += 1
        return "Hello"


def build(config, lines, immediate=False, text_mode=False):
    app = Assistant(config, BrainDouble(), SpeakerDouble(), AuditDouble(), on_text=lambda _: None)
    console, mic, stt = ConsoleDouble(lines), MicrophoneDouble(immediate), STTDouble()
    return TerminalRunner(app, console, mic, stt, text_mode=text_mode)


async def test_muted_enter_never_opens_mic(config):
    runner = build(config, ["/mute", "", "/quit"])
    await runner.run()
    assert runner.microphone.calls == 0
    assert runner.stt.calls == 0


async def test_mute_during_capture_discards_audio_before_stt(config):
    runner = build(config, ["", "/mute", "/quit"])
    await runner.run()
    assert runner.microphone.calls == 1
    assert runner.stt.calls == 0 and runner.assistant.history == []


async def test_text_mode_never_loads_stt_or_opens_mic(config):
    runner = build(config, ["hello", "/quit"], text_mode=True)
    await runner.run()
    assert runner.microphone.calls == 0 and not runner.stt.prepared
    assert runner.assistant.history[0]["content"] == "hello"


async def test_time_cap_cancels_pending_input(config):
    import threading

    runner = build(config, [], immediate=True)
    await runner.capture(threading.Event())
    assert runner.console.cancelled
    assert runner.console.output[-1] == "[Mic OFF]"


async def test_global_hotkey_only_activates_when_armed_and_release_stops():
    hotkey = GlobalPushToTalk("unused")
    hotkey._loop = asyncio.get_running_loop()
    hotkey._listener = SimpleNamespace(canonical=lambda key: key, is_alive=lambda: True)
    hotkey._required = {"ctrl", "alt", "space"}
    for key in hotkey._required:
        hotkey._press(key)
    assert not hotkey._pressed.is_set()  # while busy / not armed
    for key in hotkey._required:
        hotkey._release(key)
    wait = asyncio.create_task(hotkey.wait_press())
    await asyncio.sleep(0)
    for key in hotkey._required:
        hotkey._press(key)
    release = await asyncio.wait_for(wait, 1)
    assert not release.is_set()
    hotkey._release("space")
    assert release.is_set()
