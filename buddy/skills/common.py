"""Small OS helpers. Callers supply fixed executables and separate argument arrays."""

from __future__ import annotations

import asyncio
import sys

from buddy.core.errors import BuddyError


def mac_only() -> None:
    if sys.platform != "darwin":
        raise BuddyError("This laptop control is available on macOS only.")


async def process(
    args: list[str],
    *,
    payload: bytes | None = None,
    deadline_seconds: float = 15,
    max_output: int = 2_000_000,
) -> bytes:
    child = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if payload is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(deadline_seconds):
            if child.stdin is not None:
                child.stdin.write(payload or b"")
                await child.stdin.drain()
                child.stdin.close()
            assert child.stdout is not None
            chunks, length = [], 0
            while chunk := await child.stdout.read(65536):
                length += len(chunk)
                if length > max_output:
                    raise BuddyError("The action returned too much data.")
                chunks.append(chunk)
            if await child.wait():
                raise BuddyError(
                    "The application could not complete this action. Check permissions."
                )
            return b"".join(chunks)
    finally:
        if child.returncode is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
            await child.wait()
