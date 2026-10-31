"""Exercise packaged Whisper/CTranslate2/PyAV/VAD without a microphone or paid API."""

import asyncio

from buddy.core.audio import RecordedAudio
from buddy.core.config import STTConfig
from buddy.core.stt_process import ProcessSTT


async def check_voice() -> int:
    stt = ProcessSTT(STTConfig(model="tiny.en", language="en"))
    try:
        await stt.prepare()
        # Silence should produce no hallucinated words; VAD and audio decoding still run.
        text = await stt.transcribe(RecordedAudio(bytes(16000 * 2 * 2), 16000))
        if text.strip():
            return 1
        print("Local Whisper, PyAV and VAD smoke passed; no microphone opened.")
        return 0
    finally:
        await stt.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check_voice()))
