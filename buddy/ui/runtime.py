"""One asyncio worker owns audio, model requests, skills and reminder delivery."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import suppress
from typing import Any

from buddy.core.assistant import Assistant, State
from buddy.core.audio import Microphone
from buddy.core.audit import AuditLog
from buddy.core.brain import create_brain
from buddy.core.config import Config
from buddy.core.errors import BuddyError, ConfigurationError
from buddy.core.reminders import Reminders
from buddy.core.storage import Store
from buddy.core.stt import WhisperSTT
from buddy.core.tools import ToolRegistry
from buddy.core.tts import SpeechOutput
from buddy.core.wake import WakeDetector, download_models


class UnconfiguredBrain:
    async def stream(self, messages, system):
        raise ConfigurationError(
            "Open Settings to choose a provider, model and API key, then restart BUDDY."
        )
        yield ""  # defines an async generator without constructing an SDK client

    async def close(self):
        pass


class DesktopRuntime:
    def __init__(self, config: Config, emit, *, demo: bool = False, wake: bool = False) -> None:
        self.config, self.emit, self.demo = config, emit, demo
        self.wake_enabled = wake
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue | None = None
        self.active: asyncio.Task | None = None
        self.wake_task: asyncio.Task | None = None
        self.capture_stop: threading.Event | None = None
        self.wake_stop: threading.Event | None = None
        self.shutting_down = threading.Event()
        self.assistant: Assistant | None = None
        self.announcing = False

    def submit(self, command: str, payload: Any = None) -> None:
        if command == "quit":
            self.shutting_down.set()
        if self.loop and self.queue:
            with suppress(RuntimeError):
                self.loop.call_soon_threadsafe(self.queue.put_nowait, (command, payload))

    async def run(self) -> None:
        self.loop, self.queue = asyncio.get_running_loop(), asyncio.Queue()
        audit = store = registry = brain = None
        ticker = None
        try:
            audit = AuditLog(self.config)
            store = Store(self.config)
            registry = ToolRegistry(self.config, audit, store)
            try:
                brain = create_brain(self.config, demo=self.demo)
            except ConfigurationError as error:
                brain = UnconfiguredBrain()
                self.emit("notice", str(error))
            self.assistant = Assistant(
                self.config,
                brain,
                SpeechOutput(self.config.tts, lambda text: self.emit("notice", text)),
                audit,
                on_text=lambda text: None if self.announcing else self.emit("text", text),
                on_state=lambda state: self.emit("state", state.value),
                on_warning=lambda text: self.emit("notice", text),
                tools=None if self.demo else registry,
                store=store,
            )
            registry.on_pending = lambda pending: self.emit(
                "confirmation",
                {
                    "id": pending.identifier,
                    "tool": pending.tool,
                    "arguments": pending.arguments,
                    "seconds": self.config.skills.confirmation_seconds,
                },
            )
            self.registry = registry
            self.microphone, self.stt = Microphone(self.config.audio), WhisperSTT(self.config.stt)
            self.detector, self.reminders = WakeDetector(self.config), Reminders(store)
            ticker = asyncio.create_task(self._tick())
            self.emit("ready", None)
            self.emit(
                "notice",
                "DEMO: canned replies; laptop actions are disabled."
                if self.demo
                else "Double-click BUDDY to talk, or type in the chat. Wake listening is opt-in.",
            )
            while not self.shutting_down.is_set():
                command, payload = await self.queue.get()
                try:
                    await self._handle(command, payload)
                except BuddyError as error:
                    self.emit("notice", str(error))
                except Exception:
                    self.emit(
                        "notice", "That control failed. Check --doctor and your macOS permissions."
                    )
        except BuddyError as error:
            self.emit("fatal", str(error))
        except Exception:
            self.emit("fatal", "BUDDY could not start. Run --doctor to check setup.")
        finally:
            self.shutting_down.set()
            if ticker:
                ticker.cancel()
                with suppress(asyncio.CancelledError):
                    await ticker
            await self._pause_wake()
            await self._stop()
            if self.assistant:
                await self.assistant.close()
            elif brain:
                await brain.close()
            if registry and (not self.assistant or self.demo):
                await registry.close()
            if store:
                store.close()
            if audit:
                audit.close()
            self.emit("closed", None)

    async def _handle(self, command: str, payload) -> None:
        assistant = self.assistant
        if command == "quit":
            return
        if command == "mute":
            assistant.set_muted(bool(payload))
            if payload:
                await self._pause_wake()
                await self._stop()
                assistant.state(State.MUTED)
        elif command == "stop":
            await self._pause_wake()
            await self._stop()
        elif command == "sleep":
            assistant.set_muted(True)
            await self._pause_wake()
            await self._stop()
            assistant.state(State.SLEEPING)
        elif command == "wake":
            self.wake_enabled = bool(payload)
            await self._pause_wake()
            self.emit("wake_enabled", self.wake_enabled)
        elif command == "download_wake":
            if self.active:
                self.emit("notice", "Finish the current turn before downloading wake models.")
                return
            await self._pause_wake()
            self._begin(self._download_wake())
        elif command == "memory":
            self.emit(
                "memory",
                {
                    "facts": assistant.store.facts(),
                    "history": assistant.store.history(self.config.memory.history_turns),
                },
            )
        elif command == "reset":
            await self._stop()
            assistant.reset()
            self.emit("notice", "Current session cleared.")
        elif command == "cancel":
            if not payload or (
                self.registry.pending and self.registry.pending.identifier == payload
            ):
                self.registry.cancel()
            assistant.state(State.MUTED if assistant.muted else State.IDLE)
        elif command in {"text", "confirm", "tool"}:
            # An approval dialog can be accepted before the pending reply finishes speaking.
            if command == "confirm" and self.active and not self.capture_stop:
                active = self.active
                active.cancel()
                with suppress(asyncio.CancelledError, BuddyError):
                    await active
                self.active = None
            if self.active:
                self.emit("notice", "BUDDY is busy. Stop the current turn before starting another.")
                return
            await self._pause_wake()
            if command == "text":
                self._begin(self._respond(str(payload)))
            elif command == "confirm":
                self._begin(self._respond("/confirm " + str(payload)))
            elif not self.demo:
                self._begin(self._request_tool(payload))
        elif command == "talk":
            if self.capture_stop:
                self.capture_stop.set()
            elif assistant.muted:
                self.emit("notice", "Unmute BUDDY before recording.")
            elif self.active:
                self.emit("notice", "BUDDY is busy. Use Stop reply to interrupt.")
            else:
                await self._pause_wake()
                self._begin(self._voice(False))

    def _begin(self, coroutine) -> None:
        self.active = asyncio.create_task(coroutine)
        self.active.add_done_callback(self._finished)

    def _finished(self, task) -> None:
        if self.active is task:
            self.active = None
        if not task.cancelled() and (error := task.exception()):
            self.emit(
                "notice",
                str(error)
                if isinstance(error, BuddyError)
                else "The turn failed. Check dependencies, permissions and provider configuration.",
            )
        if self.assistant and not self.shutting_down.is_set():
            self.assistant.state(
                State.MUTED
                if self.assistant.muted
                else (State.CONFIRMING if self.registry.pending else State.IDLE)
            )

    async def _respond(self, text: str) -> None:
        if not text.startswith("/confirm "):
            self.emit("cancel_confirmations", None)
        self.emit("turn", text)
        await self.assistant.respond(text)
        self.emit("turn_end", None)

    async def _download_wake(self):
        self.emit("notice", "Downloading the selected wake model. Microphone is off.")
        await download_models(self.config)
        self.emit("notice", "Wake models downloaded. Enable wake-word listening in the menu.")

    async def _voice(self, auto: bool) -> None:
        self.emit("notice", "Preparing Whisper. Microphone is off until recording starts.")
        await self.stt.prepare()
        if self.assistant.muted:
            return
        self.capture_stop = threading.Event()
        self.microphone.silence_seconds = self.config.wake.silence_seconds if auto else None
        self.assistant.state(State.LISTENING)
        try:
            audio = await self.microphone.record(self.capture_stop)
        finally:
            self.capture_stop = None
        if self.assistant.muted:
            return
        if not audio.pcm:
            self.emit("notice", "No clear speech captured. Try again closer to the microphone.")
            return
        self.assistant.state(State.THINKING)
        text = await self.stt.transcribe(audio)
        if text:
            await self._respond(text)
        else:
            self.emit("notice", "Whisper did not detect speech. Try again.")

    async def _request_tool(self, payload) -> None:
        result = await self.registry.invoke(payload["name"], payload.get("arguments", {}))
        if not result.get("pending"):
            self.emit("notice", "Done." if result["ok"] else result["error"])

    async def _deliver_reminders(self):
        self.announcing = True
        try:
            await self.reminders.deliver(self.assistant, lambda text: self.emit("reminder", text))
        finally:
            self.announcing = False

    async def _pause_wake(self) -> None:
        if self.wake_stop:
            self.wake_stop.set()
        task, self.wake_task = self.wake_task, None
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError, BuddyError):
                await task

    async def _stop(self) -> None:
        if self.capture_stop:
            self.capture_stop.set()
        if self.assistant:
            if self.assistant.tools:
                self.assistant.tools.cancel()
            active, self.active = self.active, None
            if active:
                active.cancel()
                with suppress(asyncio.CancelledError, BuddyError):
                    await active
            await self.assistant.speaker.stop()

    async def _listen_wake(self) -> None:
        try:
            await self.detector.prepare()
            if self.assistant.muted or self.active or not self.wake_enabled:
                return
            self.wake_stop = threading.Event()
            self.assistant.state(State.WAKE)
            if await self.detector.wait(self.wake_stop):
                self.wake_task = None
                self._begin(self._voice(True))
        except BuddyError as error:
            self.wake_enabled = False
            self.emit("wake_enabled", False)
            self.emit("notice", str(error))
            self.assistant.state(State.IDLE)

    async def _tick(self) -> None:
        while not self.shutting_down.is_set():
            await asyncio.sleep(0.25)
            if self.registry.pending and self.registry.pending.expires < time.monotonic():
                self.registry.cancel()
                self.emit("cancel_confirmations", None)
                self.assistant.state(State.MUTED if self.assistant.muted else State.IDLE)
            if self.active or self.registry.pending:
                continue
            if self.assistant.store.due(time.time()):
                await self._pause_wake()
                self._begin(self._deliver_reminders())
            elif self.wake_enabled and not self.assistant.muted:
                if self.wake_task is None or self.wake_task.done():
                    self.wake_task = asyncio.create_task(self._listen_wake())
