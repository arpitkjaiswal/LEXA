import asyncio
import io
import struct
import sys

import pytest

from buddy.core.audio import RecordedAudio
from buddy.core.config import STTConfig
from buddy.core.errors import TranscriptionError
from buddy.core.stt_process import MAX_FRAME, ProcessSTT, _read_frame, encode_frame


def test_worker_protocol_rejects_oversized_and_truncated_frames():
    assert _read_frame(io.BytesIO(encode_frame({"ok": True}))) == {"ok": True}
    assert _read_frame(io.BytesIO()) is None
    for data in [struct.pack("!I", MAX_FRAME + 1), b"\x00", b"\x00\x00\x00\x08{}"]:
        with pytest.raises(ValueError):
            _read_frame(io.BytesIO(data))


async def test_managed_worker_uses_memory_pipe_reuses_model_and_closes(monkeypatch):
    real_spawn = asyncio.create_subprocess_exec
    spawned = []
    script = """
import base64, sys
from buddy.core.stt_process import _read_frame, encode_frame
config = _read_frame(sys.stdin.buffer)
assert config['config']['model'] == 'tiny'
sys.stdout.buffer.write(encode_frame({'ok': True})); sys.stdout.buffer.flush()
while (frame := _read_frame(sys.stdin.buffer)) is not None:
    assert base64.b64decode(frame['pcm']) == b'\\x01\\x00' * 20
    assert frame['sample_rate'] == 16000
    sys.stdout.buffer.write(encode_frame({'ok': True, 'text': 'test words'}))
    sys.stdout.buffer.flush()
"""

    async def spawn(*command, **kwargs):
        process = await real_spawn(sys.executable, "-u", "-c", script, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    stt = ProcessSTT(STTConfig(model="tiny"))
    await stt.prepare()
    audio = RecordedAudio(b"\x01\x00" * 20, 16000)
    assert await stt.transcribe(audio) == "test words"
    assert await stt.transcribe(audio) == "test words"
    assert len(spawned) == 1
    await stt.close()
    assert spawned[0].returncode is not None and stt.process is None


async def test_stop_kills_a_worker_stalled_during_first_model_download(monkeypatch):
    real_spawn = asyncio.create_subprocess_exec
    started = asyncio.Event()
    spawned = []

    async def spawn(*command, **kwargs):
        process = await real_spawn(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        spawned.append(process)
        started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    stt = ProcessSTT(STTConfig())
    task = asyncio.create_task(stt.prepare())
    await asyncio.wait_for(started.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert spawned[0].returncode is not None and stt.process is None
    await stt.close()


async def test_crashed_worker_returns_safe_error_and_can_be_retried(monkeypatch):
    real_spawn = asyncio.create_subprocess_exec
    processes = []

    async def spawn(*command, **kwargs):
        process = await real_spawn(sys.executable, "-c", "raise SystemExit(1)", **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    stt = ProcessSTT(STTConfig())
    for _ in range(2):
        with pytest.raises(TranscriptionError, match="Prepare voice"):
            await stt.prepare()
    assert len(processes) == 2 and all(p.returncode is not None for p in processes)
