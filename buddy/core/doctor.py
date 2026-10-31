"""Read-only local readiness report; never opens a mic, downloads models or calls APIs."""

from __future__ import annotations

import importlib.util
import platform
import shutil
import sys

from buddy.core.brain import provider_ready
from buddy.core.config import Config
from buddy.core.platform_support import host_support


def report(config: Config) -> list[str]:
    lines = [
        f"BUDDY | Python {platform.python_version()} | {platform.system()} {platform.machine()}",
        "Target: Apple Silicon M1–M5 and compatible arm64 successors, macOS 14.4+.",
        host_support().message,
        "This check does not request permissions or contact AI services.",
        f"LLM provider: {config.brain.provider}",
        f"LLM model: {'configured' if config.brain.model.strip() else 'MISSING: set BUDDY_MODEL'}",
        f"LLM credentials: {'configured / not needed' if provider_ready(config) else 'NOT READY'}",
        f"TTS backend: {config.tts.backend}",
        f"Audit directory: {config.data_dir / 'logs'}",
    ]
    for module in ("faster_whisper", "sounddevice", "numpy", "edge_tts", "pyttsx3", "pynput"):
        available = importlib.util.find_spec(module) is not None
        status = "installed" if available else 'missing (pip install -e ".[voice]")'
        lines.append(f"{module}: {status}")
    for module, extra in (("PySide6", "desktop"), ("openwakeword", "wake"), ("yt_dlp", "music")):
        available = importlib.util.find_spec(module) is not None
        lines.append(f"{module}: {'installed' if available else f'missing (install .[{extra}])'}")
    from buddy.core.wake import effective_framework

    lines.append(f"Wake model: {config.wake.model} ({effective_framework(config)}); opt-in.")
    lines.append(
        f"Saved preferences: {config.memory.enabled}; chat retention: {config.memory.save_history}"
    )
    lines.append("Wake detection opens the mic while idle; PTT keeps it closed until activation.")
    player = shutil.which("mpv") or shutil.which("ffplay")
    lines.append(f"Streaming player: {'available' if player else 'missing (brew install mpv)'}")
    lines.append(f"macOS say fallback: {'available' if sys.platform == 'darwin' else 'macOS only'}")
    lines.append("Mic / hotkey permissions: verify manually in macOS Privacy & Security.")
    lines.append("Whisper model cache: not checked; voice startup loads it before opening the mic.")
    return lines
