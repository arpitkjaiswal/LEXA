"""Streaming Edge audio with local fallbacks. No shell or model-supplied commands."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sys
from collections.abc import Callable
from typing import Any

from buddy.core.config import TTSConfig
from buddy.core.errors import SpeechError, SpeechInterruptedError


class SentenceBuffer:
    """Emit phrases while generation continues; cap long punctuation-free phrases."""

    def __init__(self, limit: int = 220) -> None:
        self._pending = ""
        self.limit = limit

    def feed(self, text: str) -> list[str]:
        import re

        self._pending += text
        output = []
        while self._pending:
            match = re.search(r"(?<=[.!?])\s+|\n+", self._pending)
            if match:
                cut = match.end()
            elif len(self._pending) >= self.limit:
                cut = self._pending.rfind(" ", 0, self.limit) + 1
                if cut <= 0:
                    cut = self.limit
            else:
                break
            phrase, self._pending = self._pending[:cut].strip(), self._pending[cut:]
            if phrase:
                output.append(phrase)
        return output

    def flush(self) -> str:
        result, self._pending = self._pending.strip(), ""
        return result


class SpeechOutput:
    def __init__(self, config: TTSConfig, warning: Callable[[str], None] = print) -> None:
        self.config = config
        self.warning = warning
        self._process: asyncio.subprocess.Process | None = None
        self._synth: asyncio.subprocess.Process | None = None
        self._selected = config.backend
        self._warned: set[str] = set()

    async def speak(self, text: str) -> None:
        if self.config.backend == "none" or not text.strip():
            return
        choices = list(dict.fromkeys([self._selected, *self.config.fallback]))
        for backend in choices:
            # A selected local backend must never fall back to an online service.
            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    if backend == "edge":
                        await self._edge(text)
                    elif backend == "pyttsx3":
                        await self._pyttsx3(text)
                    elif backend == "say":
                        await self._say(text)
                    elif backend == "piper":
                        await self._piper(text)
                    else:
                        raise SpeechError("Unknown speech backend.")
                self._selected = backend
                return
            except asyncio.CancelledError:
                await self.stop()
                raise
            except SpeechInterruptedError:
                await self.stop()
                raise
            except Exception:
                await self.stop()
                if backend not in self._warned:
                    self.warning(
                        f"{backend} speech unavailable; trying a configured local fallback."
                    )
                    self._warned.add(backend)
        raise SpeechError("Speech output is unavailable. Read the reply above or use --no-tts.")

    async def _edge(self, text: str) -> None:
        try:
            import edge_tts
        except ImportError:
            raise SpeechError("Install the voice extra for Edge TTS.") from None
        if executable := shutil.which("mpv"):
            command = [
                executable,
                "--no-terminal",
                "--really-quiet",
                "--no-video",
                "--cache=no",
                "-",
            ]
        elif executable := shutil.which("ffplay"):
            command = [executable, "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", "pipe:0"]
        else:
            raise SpeechError("Streaming Edge speech needs mpv or ffplay on PATH.")
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        process = self._process
        assert process.stdin is not None
        received_audio = False
        communicate = edge_tts.Communicate(text, self.config.voice, rate=self.config.rate)
        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    received_audio = True
                    process.stdin.write(chunk["data"])
                    await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            code = await process.wait()
            if not received_audio or code:
                raise SpeechError("Edge audio playback failed.")
        except Exception:
            # Avoid replaying a partially spoken phrase through a different voice.
            if received_audio:
                await self.stop()
                raise SpeechInterruptedError(
                    "Edge audio was interrupted; the text remains visible."
                ) from None
            raise
        finally:
            if process.returncode is not None:
                self._process = None

    async def _say(self, text: str) -> None:
        if sys.platform != "darwin":
            raise SpeechError("The say backend is available on macOS only.")
        args = ["/usr/bin/say", "-r", str(self.config.local_rate)]
        if self.config.local_voice:
            args.extend(["-v", self.config.local_voice])
        await self._run_local(args, text.encode("utf-8"))

    async def _pyttsx3(self, text: str) -> None:
        if importlib.util.find_spec("pyttsx3") is None:
            raise SpeechError("pyttsx3 is not installed.")
        payload = json.dumps(
            {"text": text, "voice": self.config.local_voice, "rate": self.config.local_rate}
        ).encode("utf-8")
        # OS voice engines need a main thread/run loop on macOS. Isolate that engine
        # in a child process instead of running Cocoa in an asyncio worker thread.
        command = (
            [sys.executable, "--tts-worker"]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "buddy.core.tts", "--worker"]
        )
        await self._run_local(command, payload)

    async def _piper(self, text: str) -> None:
        from pathlib import Path

        executable, player = shutil.which("piper"), shutil.which("mpv")
        if (
            not executable
            or not player
            or not await asyncio.to_thread(Path(self.config.piper_model).is_file)
        ):
            raise SpeechError("Piper needs its CLI, a local tts.piper_model and mpv.")
        self._synth = await asyncio.create_subprocess_exec(
            executable,
            "--model",
            self.config.piper_model,
            "--output-raw",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._process = await asyncio.create_subprocess_exec(
            player,
            "--no-config",
            "--no-terminal",
            "--really-quiet",
            "--no-video",
            "--demuxer=rawaudio",
            "--demuxer-rawaudio-format=s16le",
            "--demuxer-rawaudio-channels=mono",
            f"--demuxer-rawaudio-rate={self.config.piper_sample_rate}",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        synth, output = self._synth, self._process
        assert synth.stdin and synth.stdout and output.stdin
        synth.stdin.write((text + "\n").encode())
        await synth.stdin.drain()
        synth.stdin.close()
        received = False
        try:
            while chunk := await synth.stdout.read(65536):
                received = True
                output.stdin.write(chunk)
                await output.stdin.drain()
            output.stdin.close()
            await output.stdin.wait_closed()
            if await synth.wait() or await output.wait() or not received:
                raise SpeechError("Piper playback failed.")
        except Exception:
            await self.stop()
            if received:
                raise SpeechInterruptedError("Piper speech was interrupted.") from None
            raise
        self._synth = self._process = None

    async def _run_local(self, args: list[str], payload: bytes) -> None:
        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        process = self._process
        await process.communicate(payload)
        if process.returncode:
            raise SpeechError("Local speech engine failed.")
        self._process = None

    async def stop(self) -> None:
        children = (self._process, self._synth)
        self._process = self._synth = None
        for process in children:
            if process and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()


def _worker() -> int:
    try:
        import os

        import pyttsx3

        source = sys.stdin.buffer if sys.stdin is not None else os.fdopen(0, "rb", closefd=False)
        payload: dict[str, Any] = json.loads(source.read(100_000))
        engine = pyttsx3.init()
        engine.setProperty("rate", int(payload["rate"]))
        if payload.get("voice"):
            engine.setProperty("voice", payload["voice"])
        engine.say(str(payload["text"]))
        engine.runAndWait()
        engine.stop()
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(_worker() if sys.argv[1:] == ["--worker"] else 2)
