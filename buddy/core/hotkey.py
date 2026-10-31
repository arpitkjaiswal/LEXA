"""Optional global hold-to-talk listener; it never opens an audio device."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from buddy.core.errors import AudioError


class GlobalPushToTalk:
    def __init__(self, hotkey: str) -> None:
        self.hotkey = hotkey
        self._listener: Any = None
        self._required: set[Any] = set()
        self._down: set[Any] = set()
        self._pressed = asyncio.Event()
        self._released = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._armed = False
        self._held = False

    def start(self) -> None:
        try:
            from pynput import keyboard

            self._required = set(keyboard.HotKey.parse(self.hotkey))
            if not self._required:
                raise ValueError("Empty hotkey")
            self._loop = asyncio.get_running_loop()
            self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
            self._listener.start()
        except Exception:
            raise AudioError(
                "Global hotkey unavailable. Use --ptt terminal, or install the voice extra and "
                "allow "
                "your terminal under macOS Privacy & Security > Input Monitoring / Accessibility."
            ) from None

    def _press(self, key: Any) -> None:
        key = self._listener.canonical(key)
        self._down.add(key)
        if self._armed and not self._held and self._required <= self._down:
            self._armed = False
            self._held = True
            self._released.clear()
            assert self._loop is not None
            self._loop.call_soon_threadsafe(self._pressed.set)

    def _release(self, key: Any) -> None:
        self._down.discard(self._listener.canonical(key))
        if self._held and not self._required <= self._down:
            self._held = False
            self._released.set()

    async def wait_press(self) -> threading.Event:
        self._pressed.clear()
        self._armed = True
        try:
            # A listener can stop after an OS permission error.
            while not self._pressed.is_set():
                if not self._listener.is_alive():
                    raise AudioError("The hotkey listener stopped. Try --ptt terminal.")
                try:
                    await asyncio.wait_for(self._pressed.wait(), timeout=0.5)
                except TimeoutError:
                    pass
            return self._released
        finally:
            self._armed = False

    async def close(self) -> None:
        self._armed = False
        self._released.set()
        if self._listener is not None:
            self._listener.stop()
            await asyncio.to_thread(self._listener.join, 1)
