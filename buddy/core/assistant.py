"""Serialized conversation turns with streaming text and bounded speech playback."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from enum import StrEnum
from typing import Protocol

from buddy.core.brain import Brain, Message, system_prompt
from buddy.core.config import Config
from buddy.core.errors import BrainError, BuddyError
from buddy.core.storage import Store
from buddy.core.tools import ToolRegistry
from buddy.core.tts import SentenceBuffer


class State(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    TALKING = "talking"
    MUTED = "muted"
    ERROR = "error"
    WAKE = "wake"
    HAPPY = "happy"
    SLEEPING = "sleeping"
    CONFIRMING = "confirming"


class Speaker(Protocol):
    async def speak(self, text: str) -> None: ...

    async def stop(self) -> None: ...


class Audit(Protocol):
    def record(self, event: str, **metadata: str | int | float | bool) -> None: ...


class Assistant:
    def __init__(
        self,
        config: Config,
        brain: Brain,
        speaker: Speaker,
        audit: Audit,
        *,
        on_text: Callable[[str], None] = print,
        on_state: Callable[[State], None] = lambda _: None,
        on_warning: Callable[[str], None] = print,
        tools: ToolRegistry | None = None,
        store: Store | None = None,
    ) -> None:
        self.config, self.brain, self.speaker, self.audit = config, brain, speaker, audit
        self.on_text, self.on_state, self.on_warning = on_text, on_state, on_warning
        self.tools, self.store = tools, store
        self.history: list[Message] = store.history(config.brain.history_turns) if store else []
        self.muted = False
        self._turn_lock = asyncio.Lock()

    def state(self, state: State) -> None:
        self.audit.record("state", state=state.value)
        self.on_state(state)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        if muted and self.tools:
            self.tools.cancel()
        self.audit.record("mute", ok=muted)
        self.state(State.MUTED if muted else State.IDLE)

    def reset(self) -> None:
        self.history.clear()
        if self.tools:
            self.tools.cancel()
        self.audit.record("session_reset", ok=True)

    async def respond(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        if len(text) > self.config.brain.max_input_chars:
            raise BrainError(
                "That message is too long; "
                f"limit is {self.config.brain.max_input_chars} characters."
            )
        async with self._turn_lock:
            self._skip_turn = False
            self.state(State.THINKING)
            self.audit.record(
                "reply_start", provider=self.config.brain.provider, characters=len(text)
            )
            messages = [*self.history, {"role": "user", "content": text}]
            queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4)
            playback = asyncio.create_task(self._speak_queue(queue))
            response: list[str] = []
            characters = 0
            buffer = SentenceBuffer()
            try:
                async for fragment in self._generate(text, messages):
                    if not isinstance(fragment, str):
                        raise BrainError("The provider returned invalid text.")
                    response.append(fragment)
                    characters += len(fragment)
                    if characters > 100_000:
                        raise BrainError("The provider exceeded the response size limit.")
                    self.on_text(fragment)
                    for phrase in buffer.feed(fragment):
                        await queue.put(phrase)
                answer = "".join(response).strip()
                if not answer:
                    raise BrainError("The provider returned an empty reply. Please try again.")
                if phrase := buffer.flush():
                    await queue.put(phrase)
                await queue.put(None)
                await playback
                if not self._skip_turn:
                    self.history.extend(
                        [
                            {"role": "user", "content": text},
                            {"role": "assistant", "content": answer},
                        ]
                    )
                    del self.history[: -2 * self.config.brain.history_turns]
                    if self.store:
                        self.store.save_turn(text, answer)
                self.audit.record("reply_complete", characters=len(answer), ok=True)
                return answer
            except BaseException as error:
                playback.cancel()
                with suppress(asyncio.CancelledError):
                    await playback
                await self.speaker.stop()
                self.audit.record("reply_failed", error_type=type(error).__name__, ok=False)
                if not isinstance(error, asyncio.CancelledError):
                    self.state(State.ERROR)
                raise
            finally:
                self.state(
                    State.MUTED
                    if self.muted
                    else (State.CONFIRMING if self.tools and self.tools.pending else State.IDLE)
                )

    async def _generate(self, text: str, messages: list[Message]):
        if self.tools and text.startswith("/confirm "):
            self._skip_turn = True
            if self.muted:
                yield "Unmute before approving an action."
                return
            result = await self.tools.confirm(text.removeprefix("/confirm ").strip())
            if result.get("ok") and result.get("tool") == "clear_saved_history":
                self.history.clear()
            if not result.get("ok"):
                yield result["error"]
            elif result.get("tool") == "take_screenshot":
                yield "Screenshot saved locally: " + result["result"]["saved_path"]
            elif result.get("tool") == "clear_saved_history":
                yield "Saved chat history deleted. The current conversation is cleared too."
            elif result.get("tool") == "forget_fact":
                yield "That saved preference has been forgotten."
            elif result.get("tool") == "delete_note":
                yield "The note has been deleted."
            else:
                yield "Done."
            return
        if self.tools:
            self.tools.cancel()  # any new user turn invalidates an older approval
            from buddy.core.tool_brain import stream_tools

            async for fragment in stream_tools(
                self.brain,
                messages,
                system_prompt(
                    self.config,
                    tools=bool(self.tools.tools),
                    memory=self.store.context() if self.store else "",
                ),
                self.tools,
            ):
                yield fragment
        else:
            async for fragment in self.brain.stream(messages, system_prompt(self.config)):
                yield fragment

    async def announce(self, text: str) -> None:
        """Reminder delivery shares the turn lock; never overlaps command recording or TTS."""
        async with self._turn_lock:
            self.on_text(text)
            if not self.muted and self.config.tts.backend != "none":
                self.state(State.TALKING)
                try:
                    await self.speaker.speak(text)
                except BuddyError as error:
                    self.on_warning(str(error))
                finally:
                    self.state(State.MUTED if self.muted else State.IDLE)

    async def _speak_queue(self, queue: asyncio.Queue[str | None]) -> None:
        failed = False
        while (phrase := await queue.get()) is not None:
            if failed or self.muted or self.config.tts.backend == "none":
                continue
            self.state(State.TALKING)
            try:
                await self.speaker.speak(phrase)
                self.audit.record("speech", characters=len(phrase), ok=True)
            except Exception as error:
                # Keep draining so a full queue cannot deadlock generation.
                failed = True
                self.audit.record("speech_failed", error_type=type(error).__name__, ok=False)
                self.on_warning(
                    str(error)
                    if isinstance(error, BuddyError)
                    else "Speech failed; the reply is still shown in the terminal."
                )

    async def close(self) -> None:
        await self.speaker.stop()
        await self.brain.close()
        if self.tools:
            await self.tools.close()
