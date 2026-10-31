"""Explicitly opt-in per-user LaunchAgent installation and removal."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from buddy.core.errors import BuddyError

LABEL = "io.lexa.buddy"


def startup(action: str, config_path: Path, env_path: Path) -> str:
    if sys.platform != "darwin":
        raise BuddyError("Login startup is available on macOS only.")
    path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"

    def launchctl(*arguments):
        return subprocess.run(
            ["/bin/launchctl", *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        ).returncode

    if action == "status":
        installed = path.is_file()
        loaded = launchctl("print", f"{domain}/{LABEL}") == 0
        return f"Startup installed: {installed}. Registered with launchd: {loaded}."
    if action == "uninstall":
        launchctl("bootout", f"{domain}/{LABEL}")
        path.unlink(missing_ok=True)
        return "BUDDY login startup removed. Your settings and memories were preserved."
    if action != "install":
        raise BuddyError("Unknown startup action.")
    if not config_path.is_file():
        raise BuddyError("Save a config.yaml before installing login startup.")
    executable = str(Path(sys.executable).absolute())  # keep the virtualenv interpreter symlink
    arguments = [executable]
    if not getattr(sys, "frozen", False):
        arguments += ["-m", "buddy"]
    arguments += ["--desktop", "--config", str(config_path.resolve())]
    if env_path.is_file():
        arguments += ["--env-file", str(env_path.resolve())]
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "Label": LABEL,
        "ProgramArguments": arguments,
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
        "WorkingDirectory": str(config_path.parent.resolve()),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        },
    }
    launchctl("bootout", f"{domain}/{LABEL}")
    path.write_bytes(plistlib.dumps(payload))
    os.chmod(path, 0o600)
    if launchctl("bootstrap", domain, str(path)):
        path.unlink(missing_ok=True)
        raise BuddyError(
            "launchd rejected startup registration. Try from a logged-in macOS desktop session."
        )
    return "BUDDY will open at login. Remove it with python -m buddy --startup uninstall."
