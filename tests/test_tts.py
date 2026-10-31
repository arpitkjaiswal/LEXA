import asyncio
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from buddy.core.errors import SpeechError, SpeechInterruptedError
from buddy.core.tts import SentenceBuffer, SpeechOutput


def test_sentence_buffer_emits_early_and_preserves_remainder():
    buffer = SentenceBuffer()
    assert buffer.feed("Hi") == []
    assert buffer.feed(" friend. ") == ["Hi friend."]
    assert buffer.feed("Another reply") == []
    assert buffer.flush() == "Another reply"
    assert buffer.flush() == ""


def test_punctuation_free_text_is_bounded():
    buffer = SentenceBuffer(limit=10)
    result = buffer.feed("x" * 35)
    assert all(len(piece) <= 10 for piece in result)
    assert "".join(result) + buffer.flush() == "x" * 35


async def test_fallback_is_local_and_cached(config, monkeypatch):
    speech = SpeechOutput(config.tts, lambda _: None)
    calls = []

    async def edge(text):
        calls.append("edge")
        raise SpeechError("network unavailable")

    async def local(text):
        calls.append("local")

    monkeypatch.setattr(speech, "_edge", edge)
    monkeypatch.setattr(speech, "_pyttsx3", local)
    await speech.speak("hello")
    await speech.speak("again")
    assert calls == ["edge", "local", "local"]


async def test_interrupted_phrase_is_not_repeated_by_fallback(config, monkeypatch):
    speech = SpeechOutput(config.tts, lambda _: None)
    fallback = []

    async def edge(text):
        raise SpeechInterruptedError("partial audio")

    async def local(text):
        fallback.append(text)

    monkeypatch.setattr(speech, "_edge", edge)
    monkeypatch.setattr(speech, "_pyttsx3", local)
    with pytest.raises(SpeechInterruptedError):
        await speech.speak("Do not repeat me.")
    assert fallback == []


async def test_edge_audio_chunks_are_piped_before_generation_finishes(config, monkeypatch):
    writes, args = [], []
    stream_finished = False

    class Input:
        def write(self, data):
            assert not stream_finished
            writes.append(data)

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    process = SimpleNamespace(stdin=Input(), returncode=None)

    async def wait():
        process.returncode = 0
        return 0

    process.wait = wait

    async def spawn(*command, **kwargs):
        args.append((command, kwargs))
        return process

    class Communicate:
        def __init__(self, *args, **kwargs):
            pass

        async def stream(self):
            nonlocal stream_finished
            yield {"type": "audio", "data": b"first"}
            yield {"type": "audio", "data": b"second"}
            stream_finished = True

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=Communicate))
    monkeypatch.setattr("buddy.core.tts.shutil.which", lambda _: "/mock/mpv")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await SpeechOutput(config.tts)._edge("hello")
    assert writes == [b"first", b"second"]
    assert args[0][0][0] == "/mock/mpv"
    assert "shell" not in args[0][1]


async def test_macos_say_receives_text_on_stdin_not_as_command(config, monkeypatch):
    calls = []
    speech = SpeechOutput(replace(config.tts, backend="say"))

    async def run_local(args, payload):
        calls.append((args, payload))

    monkeypatch.setattr("buddy.core.tts.sys.platform", "darwin")
    monkeypatch.setattr(speech, "_run_local", run_local)
    text = "$(do-not-run) --voice anything"
    await speech.speak(text)
    assert calls[0][0] == ["/usr/bin/say", "-r", "180"]
    assert calls[0][1] == text.encode()
