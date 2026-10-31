"""BUDDY Phase 1 CLI. Run `python -m buddy --help`."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from pathlib import Path

from buddy import __version__
from buddy.core.assistant import Assistant, State
from buddy.core.audio import Microphone, list_devices
from buddy.core.audit import AuditLog
from buddy.core.brain import create_brain
from buddy.core.config import load_config
from buddy.core.console import Console
from buddy.core.doctor import report
from buddy.core.errors import BuddyError
from buddy.core.hotkey import GlobalPushToTalk
from buddy.core.runner import TerminalRunner
from buddy.core.stt import WhisperSTT
from buddy.core.tts import SpeechOutput


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="BUDDY for macOS — Phase 1 terminal voice companion."
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
    brain = create_brain(config, demo=args.demo)
    audit: AuditLog | None = None
    assistant: Assistant | None = None
    try:
        audit = AuditLog(config)
        audit.record("startup", source="demo" if args.demo else "live", ok=True)

        def show_state(state: State) -> None:
            # Text is already streamed on one console line; readiness/listening is
            # announced by the runner. UI observers can subscribe in Phase 3.
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
        )
        console.write(f"{config.pet.name} v{__version__} | Phase 1 | Mic OFF")
        if args.demo:
            console.write("DEMO: canned test response. No LLM or computer actions are connected.")
        else:
            console.write(f"AI: {config.brain.provider}. Text goes to this provider; STT is local.")
        if config.tts.backend == "edge":
            console.write(
                "Voice: Edge TTS (online). Set BUDDY_TTS_BACKEND=say for local macOS speech."
            )
        runner = TerminalRunner(
            assistant,
            console,
            Microphone(config.audio),
            WhisperSTT(config.stt),
            text_mode=args.text or args.once is not None,
            hotkey=GlobalPushToTalk(config.audio.hotkey)
            if args.ptt == "global" and not args.text and args.once is None
            else None,
        )
        if args.once is not None:
            await runner.reply(args.once)
        else:
            await runner.run()
        return 0
    finally:
        if assistant:
            await assistant.close()
        else:
            await brain.close()
        if audit:
            audit.record("shutdown", ok=True)
            audit.close()


def main() -> int:
    args = parser().parse_args()
    try:
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
