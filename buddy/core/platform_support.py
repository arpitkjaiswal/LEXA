"""The shipped companion targets the Apple Silicon ABI, not a list of chip names."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass

from buddy.core.errors import ConfigurationError

MIN_MACOS = (14, 4)
MIN_MACOS_VERSION = ".".join(map(str, MIN_MACOS))


@dataclass(frozen=True)
class HostSupport:
    supported: bool
    message: str


def version_tuple(value: str) -> tuple[int, ...]:
    parts = value.split(".")
    if not parts or any(not part.isdecimal() for part in parts):
        return ()
    return tuple(int(part) for part in parts)


def host_support(
    *, system: str | None = None, machine: str | None = None, version: str | None = None
) -> HostSupport:
    system = sys.platform if system is None else system
    machine = platform.machine().lower() if machine is None else machine.lower()
    if system != "darwin":
        return HostSupport(False, "The desktop/voice companion requires an Apple Silicon Mac.")
    if machine != "arm64":
        return HostSupport(
            False,
            "Use native arm64 Python or the Apple Silicon app. "
            "Intel and x86_64/Rosetta processes are outside this build target.",
        )
    version = platform.mac_ver()[0] if version is None else version
    if (version_tuple(version) + (0, 0))[:2] < MIN_MACOS:
        return HostSupport(False, f"Apple Silicon requires macOS {MIN_MACOS_VERSION} or later.")
    return HostSupport(True, f"Native Apple Silicon arm64 · macOS {version}")


def require_apple_silicon() -> None:
    support = host_support()
    if not support.supported:
        raise ConfigurationError(support.message)
