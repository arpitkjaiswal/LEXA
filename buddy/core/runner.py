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
from buddy.core.stt import WhisperSTT

HELP = (
    "/help  /mute (mic + voice off)  /unmute  /reset (clear session)  /quit\n"
    "Terminal PTT: Enter starts recording; Enter again stops. "
    "Global PTT: hold the configured chord.\n"
    "Capture always stops at audio.max_record_seconds. Ctrl-C exits and closes audio."
)


async def _cancel(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
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
    ) -> None:
        self.assistant, self.console, self.microphone, self.stt = (
            assistant,
            console,
            microphone,
            stt,
        )
        self.text_mode, self.hotkey = text_mode, hotkey
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
            self.console.write("Session cleared. Phase 1 does not save conversations to disk.")
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
        try:
            while self.running:
                try:
                    if self.text_mode:
                        line = await self.console.readline("You > ")
                        if line is None:
                            break
                        if not self.command(line) and line.strip():
                            await self.reply(line)
                        continue
                    release = await self.wait_trigger()
                    if release is None or not self.running:
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
        if not self.hotkey:
            line = await self.console.readline("[Mic OFF] Enter to talk, or /help > ")
            if line is None:
                self.running = False
            elif not self.command(line):
                if line.strip():
                    self.console.write(
                        "Press Enter on an empty line to talk; use --text to type chats."
                    )
                else:
                    return threading.Event()
            return None
        press = asyncio.create_task(self.hotkey.wait_press())
        control = asyncio.create_task(
            self.console.readline("[Mic OFF] Hold hotkey, or type /help > ")
        )
        try:
            done, _ = await asyncio.wait({press, control}, return_when=asyncio.FIRST_COMPLETED)
            # Give explicit terminal commands priority over simultaneous hotkeys.
            if control in done:
                line = control.result()
                if line is None:
                    self.running = False
                elif line.strip() and not self.command(line):
                    self.console.write("Hold the hotkey to talk; use --text to type chats.")
                return None
            return press.result()
        finally:
            await _cancel(press)
            await _cancel(control)

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
