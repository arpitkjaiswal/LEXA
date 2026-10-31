"""Managed Whisper process: Stop/Quit can interrupt model downloads and inference.

Only STT configuration and in-memory PCM cross the bounded framed pipe. The child
does not receive API keys through the protocol and never writes recorded audio.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import sys
from contextlib import suppress
from dataclasses import asdict

from buddy.core.audio import RecordedAudio
from buddy.core.config import STTConfig
from buddy.core.errors import BuddyError, TranscriptionError

MAX_FRAME = 32 * 1024 * 1024


def encode_frame(value: dict) -> bytes:
    payload = json.dumps(value).encode("utf-8")
    if len(payload) > MAX_FRAME:
        raise ValueError("STT frame exceeds the limit")
    return struct.pack("!I", len(payload)) + payload


class ProcessSTT:
    def __init__(self, config: STTConfig):
        self.config = config
        self.process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def _exchange(self, value: dict) -> dict:
        self.process.stdin.write(encode_frame(value))
        await self.process.stdin.drain()
        size = struct.unpack("!I", await self.process.stdout.readexactly(4))[0]
        if size > MAX_FRAME:
            raise ValueError("Invalid STT response size")
        reply = json.loads(await self.process.stdout.readexactly(size))
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            raise TranscriptionError(
                "Whisper could not prepare or transcribe. Check the model, network, disk/RAM "
                "and voice dependencies, then try Prepare voice again."
            )
        return reply

    async def _ready(self):
        if self.process is not None and self.process.returncode is None:
            return
        command = (
            [sys.executable, "--stt-worker"]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "buddy.core.stt_process"]
        )
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await self._exchange({"config": asdict(self.config)})

    async def _request(self, audio: RecordedAudio | None = None) -> str:
        async with self._lock:
            try:
                async with asyncio.timeout(300):
                    await self._ready()
                    if audio is None:
                        return ""
                    reply = await self._exchange(
                        {
                            "pcm": base64.b64encode(audio.pcm).decode("ascii"),
                            "sample_rate": audio.sample_rate,
                        }
                    )
                    if not isinstance(reply.get("text"), str):
                        raise ValueError("Invalid STT text")
                    return reply["text"]
            except BaseException as error:
                await self._close()
                if isinstance(error, (asyncio.CancelledError, BuddyError)):
                    raise
                if not isinstance(error, Exception):
                    raise
                raise TranscriptionError(
                    "The Whisper worker stopped or timed out. Check voice dependencies, "
                    "the model download and available memory, then try Prepare voice again."
                ) from None

    async def prepare(self) -> None:
        await self._request()

    async def transcribe(self, audio: RecordedAudio) -> str:
        return await self._request(audio) if audio.pcm else ""

    async def _close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            await process.wait()

    async def close(self):
        async with self._lock:
            await self._close()


def _read_frame(stream) -> dict | None:
    prefix = stream.read(4)
    if not prefix:
        return None
    if len(prefix) != 4:
        raise ValueError("Truncated STT frame")
    size = struct.unpack("!I", prefix)[0]
    if size > MAX_FRAME:
        raise ValueError("Invalid STT frame size")
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("Truncated STT frame")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Invalid STT frame")
    return value


def worker_main() -> int:
    from buddy.core.stt import WhisperSTT

    # Windowed PyInstaller apps have sys.stdin/sys.stdout set to None.
    with os.fdopen(0, "rb", closefd=False) as source, os.fdopen(1, "wb", closefd=False) as sink:
        try:
            request = _read_frame(source)
            if request is None:
                return 0
            stt = WhisperSTT(STTConfig(**request["config"]))
            stt._load()
            sink.write(encode_frame({"ok": True}))
            sink.flush()
            while (request := _read_frame(source)) is not None:
                rate = request["sample_rate"]
                if not isinstance(rate, int) or not 8000 <= rate <= 192000:
                    raise ValueError("Invalid sample rate")
                audio = RecordedAudio(base64.b64decode(request["pcm"], validate=True), rate)
                text = stt._transcribe(audio)
                sink.write(encode_frame({"ok": True, "text": text}))
                sink.flush()
            return 0
        except Exception:
            sink.write(encode_frame({"ok": False}))
            sink.flush()
            return 1


if __name__ == "__main__":
    raise SystemExit(worker_main())
