"""Terminal orchestration; microphone capture and speech playback never overlap."""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from typing import Any

from buddy.core.assistant import Assistant, State
from buddy.core.audio import Microphone, RecordedAudio
from buddy.core.console import Console
from buddy.core.errors import BuddyError
from buddy.core.hotkey import GlobalPushToTalk
from buddy.core.reminders import Reminders
from buddy.core.stt import WhisperSTT
from buddy.core.wake import WakeDetector

HELP = (
    "/help  /mute (mic + voice off)  /unmute  /reset  /confirm ID  /cancel  /memory  /quit\n"
    "Terminal PTT: Enter starts recording; Enter again stops. "
    "Global PTT: hold the configured chord.\n"
    "Capture always stops at audio.max_record_seconds. Ctrl-C exits and closes audio."
)


async def _cancel(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError, BuddyError):
        await task


class TerminalRunner:
    def __init__(
        self,
        assistant: Assistant,
        console: Console,
        microphone: Microphone,
        stt: WhisperSTT,
        *,
        text_mode: bool = False,
        hotkey: GlobalPushToTalk | None = None,
        wake: WakeDetector | None = None,
        reminders: Reminders | None = None,
    ) -> None:
        self.assistant, self.console, self.microphone, self.stt = (
            assistant,
            console,
            microphone,
            stt,
        )
        self.text_mode, self.hotkey = text_mode, hotkey
        self.wake, self.reminders = wake, reminders
        self.running = True

    def command(self, text: str) -> bool:
        command = text.strip().lower()
        if command == "/quit":
            self.running = False
        elif command == "/mute":
            self.assistant.set_muted(True)
            self.console.write("Muted: microphone capture and spoken replies are disabled.")
        elif command == "/unmute":
            self.assistant.set_muted(False)
        elif command == "/reset":
            self.assistant.reset()
            self.console.write(
                "Session cleared. Saved facts and retained history have separate deletion controls."
            )
        elif command == "/cancel":
            if self.assistant.tools:
                self.assistant.tools.cancel()
            self.console.write("Pending action cancelled.")
        elif command == "/memory":
            import json

            facts = self.assistant.store.facts() if self.assistant.store else []
            self.console.write(json.dumps(facts, ensure_ascii=False, indent=2))
        elif command.startswith("/confirm "):
            return False  # handled as an exact, user-originated token by Assistant
        elif command == "/help":
            self.console.write(HELP)
        elif command.startswith("/"):
            self.console.write("Unknown command. Type /help.")
        else:
            return False
        return True

    async def run(self) -> None:
        self.console.write(HELP)
        if not self.text_mode:
            self.console.write(
                "Preparing local Whisper (first run may download model weights). Mic OFF."
            )
            await self.stt.prepare()
            if self.hotkey:
                self.hotkey.start()
            if self.wake:
                try:
                    await self.wake.prepare()
                except BuddyError as error:
                    self.console.write(str(error))
                    self.wake = None
        try:
            while self.running:
                try:
                    if self.reminders:
                        await self.reminders.deliver(self.assistant)
                    if self.text_mode:
                        line = await self.read_idle("You > ")
                        if line == "__reminder__":
                            continue
                        if line is None:
                            break
                        if not self.command(line) and line.strip():
                            await self.reply(line)
                        continue
                    release = await self.wait_trigger()
                    if release is None or not self.running:
                        continue
                    if getattr(self, "_typed_confirmation", None):
                        text, self._typed_confirmation = self._typed_confirmation, None
                        await self.reply(text)
                        continue
                    if self.assistant.muted:
                        self.console.write("Microphone is muted. Type /unmute to enable it.")
                        continue
                    audio = await self.capture(release)
                    if self.assistant.muted or not self.running:
                        continue
                    if not audio.pcm:
                        self.console.write(
                            "No clear speech captured. Try again, closer to the microphone."
                        )
                        continue
                    self.assistant.state(State.THINKING)
                    text = await self.stt.transcribe(audio)
                    if text:
                        self.console.write(f"You > {text}")
                        await self.reply(text)
                    else:
                        self.console.write("No speech detected by Whisper. Try again.")
                except BuddyError as error:
                    self.console.write(f"BUDDY: {error}")
                    self.assistant.audit.record(
                        "turn_failed", error_type=type(error).__name__, ok=False
                    )
                finally:
                    self.assistant.state(State.MUTED if self.assistant.muted else State.IDLE)
        finally:
            if self.hotkey:
                await self.hotkey.close()

    async def wait_trigger(self) -> threading.Event | None:
        if (
            self.wake
            and not self.assistant.muted
            and not (self.assistant.tools and self.assistant.tools.pending)
        ):
            stop = threading.Event()
            self.assistant.state(State.WAKE)
            self.console.write(
                f"[WAKE — Mic ON locally] {self.assistant.config.wake.model}; Enter for PTT."
            )
            detection = asyncio.create_task(self.wake.wait(stop))
            control = asyncio.create_task(self.read_idle("Wake word / Enter / command > "))
            press = asyncio.create_task(self.hotkey.wait_press()) if self.hotkey else None
            try:
                done, _ = await asyncio.wait(
                    {detection, control} | ({press} if press else set()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if control in done:
                    return self._trigger_line(control.result())
                if press and press in done:
                    self.microphone.silence_seconds = None
                    return press.result()
                if detection.result():
                    self.microphone.silence_seconds = self.assistant.config.wake.silence_seconds
                    return threading.Event()
                return None
            except BuddyError as error:
                self.console.write(str(error) + " Falling back to push-to-talk.")
                self.wake = None
                return None
            finally:
                stop.set()
                await _cancel(detection)
                await _cancel(control)
                if press:
                    await _cancel(press)
                self.console.write("[Wake capture OFF]")
        if not self.hotkey:
            line = await self.read_idle("[Mic OFF] Enter to talk, or /help > ")
            return self._trigger_line(line)
        press = asyncio.create_task(self.hotkey.wait_press())
        control = asyncio.create_task(self.read_idle("[Mic OFF] Hold hotkey, or type /help > "))
        try:
            done, _ = await asyncio.wait({press, control}, return_when=asyncio.FIRST_COMPLETED)
            # Give explicit terminal commands priority over simultaneous hotkeys.
            if control in done:
                line = control.result()
                if line is None:
                    self.running = False
                elif line.strip() and not self.command(line):
                    if line.startswith("/confirm "):
                        self._typed_confirmation = line
                        return threading.Event()
                    if line != "__reminder__":
                        self.console.write("Hold the hotkey to talk; use --text to type chats.")
                return None
            return press.result()
        finally:
            await _cancel(press)
            await _cancel(control)

    def _trigger_line(self, line):
        self.microphone.silence_seconds = None
        if line is None:
            self.running = False
        elif line == "__reminder__":
            return None
        elif not self.command(line):
            if line.startswith("/confirm "):
                self._typed_confirmation = line
                return threading.Event()
            if line.strip():
                self.console.write(
                    "Press Enter on an empty line to talk; use --text to type chats."
                )
            else:
                return threading.Event()
        return None

    async def read_idle(self, prompt):
        if not self.reminders:
            return await self.console.readline(prompt)
        reading = asyncio.create_task(self.console.readline(prompt))
        due = asyncio.create_task(self.reminders.wait_due())
        try:
            done, _ = await asyncio.wait({reading, due}, return_when=asyncio.FIRST_COMPLETED)
            return reading.result() if reading in done else "__reminder__"
        finally:
            await _cancel(reading)
            await _cancel(due)

    async def capture(self, release: threading.Event) -> RecordedAudio:
        self.assistant.state(State.LISTENING)
        self.assistant.audit.record("capture_start", source="global" if self.hotkey else "terminal")
        self.console.write(
            "[LISTENING] Mic ON. Release hotkey or press Enter to finish; /mute aborts."
        )
        recording = asyncio.create_task(self.microphone.record(release))
        control = asyncio.create_task(self.console.readline(""))
        try:
            done, _ = await asyncio.wait({recording, control}, return_when=asyncio.FIRST_COMPLETED)
            if control in done:
                line = control.result()
                release.set()
                if line is None:
                    self.running = False
                elif line.strip():
                    self.command(line)
            audio = await recording
            self.assistant.audit.record(
                "capture_complete", duration_ms=int(audio.duration * 1000), ok=True
            )
            return audio
        finally:
            release.set()
            await _cancel(control)
            if not recording.done():
                await _cancel(recording)
            self.console.write("[Mic OFF]")

    async def reply(self, text: str) -> str:
        self.console.write(f"{self.assistant.config.pet.name} > ", end="")
        try:
            return await self.assistant.respond(text)
        finally:
            self.console.write("")
