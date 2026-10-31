import asyncio
from dataclasses import replace

import pytest
from conftest import AuditDouble, BrainDouble, SpeakerDouble

from buddy.core.assistant import Assistant, State
from buddy.core.errors import BrainError, SpeechError


def build(config, brain=None, speaker=None):
    states, text, warnings = [], [], []
    app = Assistant(
        config,
        brain or BrainDouble(),
        speaker or SpeakerDouble(),
        AuditDouble(),
        on_text=text.append,
        on_state=states.append,
        on_warning=warnings.append,
    )
    return app, states, text, warnings


async def test_streamed_reply_and_bounded_successful_history(config):
    config = replace(config, brain=replace(config.brain, history_turns=1))
    app, states, text, _ = build(config)
    answer = await app.respond("Hello")
    assert answer == "Hey friend. You have got this!"
    assert "".join(text) == answer
    assert app.speaker.phrases == ["Hey friend.", "You have got this!"]
    assert states[0] == State.THINKING and states[-1] == State.IDLE
    await app.respond("Second turn")
    assert len(app.history) == 2
    assert app.history[0]["content"] == "Second turn"
    assert len(app.brain.calls[1][0]) == 3
    assert "NO tools" in app.brain.calls[0][1]
    app.reset()
    assert app.history == []


async def test_partial_provider_failure_is_not_saved_and_stops_speech(config):
    app, states, _, _ = build(config, BrainDouble(failure=BrainError("network failure")))
    with pytest.raises(BrainError):
        await app.respond("Hello")
    assert app.history == []
    assert app.speaker.stopped
    assert State.ERROR in states and states[-1] == State.IDLE


async def test_speech_failure_does_not_deadlock_full_queue_or_lose_text(config):
    brain = BrainDouble(chunks=["A sentence. "] * 30)
    speaker = SpeakerDouble(failure=SpeechError("Audio unavailable"))
    app, _, _, warnings = build(config, brain, speaker)
    answer = await asyncio.wait_for(app.respond("Hello"), timeout=2)
    assert answer.count("A sentence.") == 30
    assert len(warnings) == 1 and len(speaker.phrases) == 1
    assert len(app.history) == 2


async def test_muted_text_chat_never_invokes_tts(config):
    app, states, _, _ = build(config)
    app.set_muted(True)
    await app.respond("Hello")
    assert app.speaker.phrases == []
    assert states[-1] == State.MUTED


async def test_no_tts_disables_all_speech_calls(config):
    config = replace(config, tts=replace(config.tts, backend="none"))
    app, _, _, _ = build(config)
    await app.respond("Hello")
    assert app.speaker.phrases == []


async def test_cancellation_closes_playback_and_keeps_history_atomic(config):
    playing = asyncio.Event()

    class BlockingBrain(BrainDouble):
        async def stream(self, messages, system):
            yield "First sentence. "
            await asyncio.Event().wait()

    class BlockingSpeaker(SpeakerDouble):
        async def speak(self, text):
            playing.set()
            await asyncio.Event().wait()

    speaker = BlockingSpeaker()
    app, states, _, _ = build(config, BlockingBrain(), speaker)
    turn = asyncio.create_task(app.respond("Hello"))
    await asyncio.wait_for(playing.wait(), timeout=1)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn
    assert speaker.stopped and app.history == [] and states[-1] == State.IDLE


async def test_empty_and_oversized_messages_do_not_call_provider(config):
    config = replace(config, brain=replace(config.brain, max_input_chars=5))
    app, _, _, _ = build(config)
    assert await app.respond("   ") == ""
    with pytest.raises(BrainError):
        await app.respond("Too long")
    assert app.brain.calls == []


async def test_concurrent_turns_are_serialized(config):
    app, _, _, _ = build(config)
    await asyncio.gather(app.respond("one"), app.respond("two"))
    assert [message["role"] for message in app.history] == ["user", "assistant"] * 2
    assert len(app.brain.calls[1][0]) == 3
