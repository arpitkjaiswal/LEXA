# Implementation roadmap

Repository: LEXA. Companion: BUDDY. Version 0.2 adds the remaining application layers.
“Implemented” here describes source, not completion of physical Mac release certification.
Distribution targets native arm64 Apple Silicon M1–M5 and compatible successors on macOS 15.2+.

| Phase | Source status | Remaining validation |
| --- | --- | --- |
| 1 · terminal voice | Implemented: PTT, local Whisper, provider adapters, TTS, errors and audit | Live provider/audio/hotkey checks on a physical Mac |
| 2 · wake and skills | Implemented: local detection, Apple Silicon LiteRT path, tool loops, allowlist, confirmations, apps/web/volume/time/music | Wake accuracy, Homebrew playback, app IDs and OS permission behavior |
| 3 · desktop pet | Implemented: transparent draggable animated pet, states, chat, tray, concurrent mute/stop, approval UI | Window behavior across displays/Spaces and assistive access |
| 4 · durable features | Implemented: explicit facts, optional history, notes, UTC timers/reminders, weather, confirmed screenshots | Sleep/restart delivery and Screen Recording on real hardware |
| 5 · settings/distribution | Implemented: native editor, .env separation, schema guard, opt-in LaunchAgent, arm64 app/DMG, transitive binary audit and cross-OS smoke tests | Clean install/uninstall and audio on physical M1–M5 devices, Developer ID signing and notarization |

## Accepted limits

- “Hey Jarvis” is a trained built-in model; “hey Aora” needs separately trained weights.
- PTT is always available when wake dependencies, models or device accuracy are unsuitable.
- Built-in music controls operate on BUDDY's own mpv player, not arbitrary applications.
- Local reminders require BUDDY running; missed alerts appear after resume/restart.
- Chat retention is optional; explicit facts are inspectable and deletable.
- There is no general shell, destructive file deletion, message-sending or shutdown feature.
- Packaging does not grant TCC permissions, include personal API keys, or imply notarization.
- Cloud access and microphone accuracy cannot be established by mocked tests.

Future work after physical acceptance: custom wake training tools, broader music sources,
signed/notarized distribution, and optional encrypted storage with a reviewed key lifecycle.
