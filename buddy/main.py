"""BUDDY terminal and native desktop entry points. Run python -m buddy --help."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import replace
from pathlib import Path

from buddy import __version__
from buddy.core.assistant import Assistant, State
from buddy.core.audio import Microphone, list_devices
from buddy.core.audit import AuditLog
from buddy.core.brain import create_brain
from buddy.core.config import default_data_dir, load_config
from buddy.core.console import Console
from buddy.core.doctor import report
from buddy.core.errors import BuddyError
from buddy.core.hotkey import GlobalPushToTalk
from buddy.core.platform_support import require_apple_silicon
from buddy.core.reminders import Reminders
from buddy.core.runner import TerminalRunner
from buddy.core.storage import Store
from buddy.core.stt_process import ProcessSTT as WhisperSTT
from buddy.core.tools import ToolRegistry
from buddy.core.tts import SpeechOutput
from buddy.core.wake import WakeDetector, download_models


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="BUDDY for macOS — voice companion, desktop pet and laptop controls."
    )
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument(
        "--config", type=Path, help="YAML config (default: ./config.yaml or built-in defaults)"
    )
    result.add_argument("--env-file", type=Path, help="Secrets file (default: .env beside config)")
    result.add_argument("--text", action="store_true", help="Type chats; never open a microphone")
    result.add_argument(
        "--no-tts", action="store_true", help="Disable all speech synthesis and playback"
    )
    result.add_argument(
        "--demo", action="store_true", help="Deterministic demo, without an LLM or API key"
    )
    result.add_argument(
        "--once", metavar="TEXT", help="One typed turn, then exit; never open a microphone"
    )
    result.add_argument("--ptt", choices=("terminal", "global"), default="terminal")
    result.add_argument("--doctor", action="store_true", help="Read-only dependency/config report")
    result.add_argument(
        "--list-devices", action="store_true", help="List PortAudio devices, then exit"
    )
    result.add_argument(
        "--desktop", action="store_true", help="Show the animated pet and menu-bar controls"
    )
    result.add_argument(
        "--wake", action="store_true", help="Enable local wake-word listening (mic on while idle)"
    )
    result.add_argument(
        "--download-wake-models",
        action="store_true",
        help="Download the configured built-in wake model, then exit",
    )
    result.add_argument(
        "--startup",
        choices=("install", "uninstall", "status"),
        help="Opt-in macOS login startup management",
    )
    result.add_argument("--stt-worker", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--voice-smoke-test", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--tts-worker", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--desktop-smoke-test", action="store_true", help=argparse.SUPPRESS)
    return result


async def run(args: argparse.Namespace) -> int:
    console = Console()
    config = load_config(args.config, args.env_file)
    if args.no_tts:
        config = replace(config, tts=replace(config.tts, backend="none"))
    if args.doctor:
        console.write("\n".join(report(config)))
        return 0
    if args.list_devices:
        console.write(list_devices())
        return 0
    if args.download_wake_models:
        await download_models(config)
        console.write("Wake models are ready. Run --wake to enable local listening.")
        return 0
    if args.startup:
        from buddy.core.startup import startup

        path = args.config or Path.cwd() / "config.yaml"
        console.write(startup(args.startup, path, args.env_file or path.parent / ".env"))
        return 0
    if not args.text and args.once is None:
        require_apple_silicon()
    brain = create_brain(config, demo=args.demo)
    audit: AuditLog | None = None
    assistant: Assistant | None = None
    store: Store | None = None
    stt = None
    try:
        audit = AuditLog(config)
        audit.record("startup", source="demo" if args.demo else "live", ok=True)
        store = Store(config)
        tools = None if args.demo else ToolRegistry(config, audit, store)

        def show_state(state: State) -> None:
            # Text is already streamed on one console line; readiness/listening is
            # announced by the runner; the desktop uses its own state observer.
            if state == State.MUTED:
                console.write("[MUTED]")

        speaker = SpeechOutput(config.tts, lambda text: console.write(f"\n[Voice] {text}"))
        assistant = Assistant(
            config,
            brain,
            speaker,
            audit,
            on_text=lambda text: console.write(text, end=""),
            on_state=show_state,
            on_warning=lambda text: console.write(f"\n[Voice] {text}"),
            tools=tools,
            store=store,
        )
        console.write(f"{config.pet.name} v{__version__} | Mic OFF until activated")
        if args.demo:
            console.write("DEMO: canned test response. No LLM or computer actions are connected.")
        else:
            console.write(f"AI: {config.brain.provider}. Text goes to this provider; STT is local.")
        if config.tts.backend == "edge":
            console.write(
                "Voice: Edge TTS (online). Set BUDDY_TTS_BACKEND=say for local macOS speech."
            )
        stt = WhisperSTT(config.stt)
        runner = TerminalRunner(
            assistant,
            console,
            Microphone(config.audio),
            stt,
            text_mode=args.text or args.once is not None,
            hotkey=GlobalPushToTalk(config.audio.hotkey)
            if args.ptt == "global" and not args.text and args.once is None
            else None,
            wake=WakeDetector(config) if args.wake else None,
            reminders=Reminders(store),
        )
        if args.once is not None:
            await runner.reply(args.once)
        else:
            await runner.run()
        return 0
    finally:
        if stt and hasattr(stt, "close"):
            await stt.close()
        if assistant:
            await assistant.close()
        else:
            await brain.close()
        if audit:
            audit.record("shutdown", ok=True)
            audit.close()
        if store:
            store.close()


def main() -> int:
    args = parser().parse_args()
    try:
        if args.stt_worker:
            from buddy.core.stt_process import worker_main

            return worker_main()
        if args.voice_smoke_test:
            from buddy.build_tools.voice_smoke import check_voice

            return asyncio.run(check_voice())
        if args.tts_worker:
            from buddy.core.tts import _worker

            return _worker()
        if args.wake and (args.text or args.once is not None):
            parser().error("--wake cannot be combined with --text or --once")
        if args.desktop and (args.text or args.once is not None or args.ptt == "global"):
            parser().error(
                "--desktop has its own Record control; omit --text, --once and --ptt global"
            )
        if args.desktop_smoke_test and not (args.desktop and args.demo and args.no_tts):
            parser().error("--desktop-smoke-test requires --desktop --demo --no-tts")
        frozen = getattr(sys, "frozen", False)
        if frozen and sys.platform == "darwin":
            # Finder launches do not inherit a shell's Homebrew PATH.
            os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get(
                "PATH", "/usr/bin:/bin"
            )
        if frozen and args.config is None:
            from buddy.core.config import Config
            from buddy.core.settings import save_settings

            args.config = default_data_dir() / "config.yaml"
            if not args.config.exists():
                save_settings(Config(), args.config)
        if args.desktop or (frozen and len(sys.argv) == 1):
            require_apple_silicon()
            try:
                from buddy.ui.app import run_desktop
            except ImportError:
                raise BuddyError(
                    "Install the desktop extra: python -m pip install -e '.[desktop]'"
                ) from None
            config = load_config(args.config, args.env_file)
            if args.no_tts:
                config = replace(config, tts=replace(config.tts, backend="none"))
            path = args.config or Path.cwd() / "config.yaml"
            return run_desktop(
                config,
                path,
                args.env_file or path.parent / ".env",
                demo=args.demo,
                wake=args.wake,
                smoke_test=args.desktop_smoke_test,
            )
        return asyncio.run(run(args))
    except BuddyError as error:
        Console().write(f"BUDDY: {error}")
        return 1
    except KeyboardInterrupt:
        Console().write("\nBUDDY stopped. Mic OFF.")
        return 130
    except Exception:
        # Raw SDK and OS errors can expose request data. Keep the public boundary
        # generic; the audit trail records only error categories inside turns.
        Console().write("BUDDY stopped unexpectedly. Run --doctor and check the setup guide.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
