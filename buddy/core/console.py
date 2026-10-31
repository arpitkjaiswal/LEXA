"""Cancellable terminal input on macOS; no abandoned input() worker at record timeout."""

from __future__ import annotations

import asyncio
import sys


def safe_text(text: str) -> str:
    return "".join(
        char for char in text if char in "\n\t" or (ord(char) >= 32 and not 127 <= ord(char) < 160)
    )


class Console:
    def write(self, text: str, *, end: str = "\n") -> None:
        print(safe_text(text), end=end, flush=True)

    async def readline(self, prompt: str) -> str | None:
        self.write(prompt, end="")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str | None] = loop.create_future()

        def ready() -> None:
            if not future.done():
                line = sys.stdin.readline()
                future.set_result(line.rstrip("\r\n") if line else None)

        try:
            descriptor = sys.stdin.fileno()
            loop.add_reader(descriptor, ready)
        except (AttributeError, NotImplementedError, OSError, ValueError):
            # Windows console / redirected regular files lack add_reader support.
            line = await asyncio.to_thread(sys.stdin.readline)
            return line.rstrip("\r\n") if line else None
        try:
            return await future
        finally:
            loop.remove_reader(descriptor)
