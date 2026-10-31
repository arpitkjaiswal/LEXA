# BUDDY implementation roadmap

Each phase must remain runnable before the next phase is merged. Repository name: LEXA.
Phase 1 is implemented. Phases 2–5 below are planned, not completed features.

| Phase | Deliverable | Run / acceptance gate |
| --- | --- | --- |
| 1 | Terminal PTT, Whisper, streaming Claude/OpenAI/Ollama, TTS, errors and tests | `python -m buddy`; microphone closes before STT/reply; typed and demo modes work; automated checks pass; physical Mac checklist in README |
| 2 | openWakeWord, allowlisted skill registry, tool use, music/app/volume/time | New `--wake` entry point only after implementation; prove a tool result round trip, deny unknown skills and require confirmation for risky actions |
| 3 | PySide6 transparent draggable always-on-top sprite pet and tray | New desktop entry point; idle/listening/thinking/talking/happy/sleeping states, mouth motion, visible mic/mute, accessible tray Quit |
| 4 | SQLite facts/history, durable timers/reminders, notes, weather, screenshots | Restart preserves only intended records, local timezone is respected, weather errors are explicit, screenshots need an explicit command |
| 5 | Settings, macOS Login Items/LaunchAgent, PyInstaller app | Test clean install and uninstall on Apple Silicon/Intel, opt-in startup, signing/permissions, config migration |

## Phase 1 scope

- [x] Configurable friend name, user name, short-response personality.
- [x] Terminal recording toggle and optional global hold-to-talk.
- [x] Bounded on-demand microphone capture and silence rejection.
- [x] Local faster-whisper with native-rate in-memory WAV decoding.
- [x] Swappable streaming Claude, OpenAI and Ollama providers.
- [x] Streaming Edge audio with configured local speech fallbacks.
- [x] Text-only mode and an explicitly labelled deterministic demo.
- [x] Session context in RAM, reset, mute, diagnostics and metadata-only logs.
- [x] Automated tests and CI configuration.
- [ ] Manual microphone/hotkey/voice verification on the user's Mac.
- [ ] Live cloud-provider verification with the user's configured API access.

## Phase 2 specifics

openWakeWord continuously receives microphone frames **locally** to detect a supported
built-in phrase. Only after activation does command recording/transcription begin.
Do not promise that the microphone is closed while a wake-word detector is enabled.
A phrase such as “hey Aora” needs a matching trained model; arbitrary custom text is not
a built-in wake model. Expose the supported model identifier in config, not a misleading label.
Keep PTT available, and suspend wake detection while TTS plays to prevent self-activation.

Skills: `music.py`, `apps.py`, `system.py`, `web.py`, then Phase 4's `timers.py`,
`notes.py`, `screenshot.py`, `weather.py`. Discover module metadata, but activate only
configured allowlisted modules. Validate arguments before execution and return a structured
result to the model. Never report success without a successful skill result.

Music starts with yt-dlp + mpv, with pause/next/volume/stop under one managed player.
Spotify and local folders can follow after the first backend works.

Risky operations require an explicit, action-specific confirmation turn tied to the
exact pending arguments, with a short expiry. Deny by default on ambiguity or cancellation.
Destructive delete, shutdown, sending messages and general command execution remain
disabled until their own reviewed designs exist. Never add a general shell tool.

## Later acceptance notes

- Reminders are local to the Mac, not ChatGPT cloud automations. Specify timezone,
  persistence, sleep/restart behavior and missed reminders before enabling them.
- User memory must support inspection/deletion and explicit saved preferences.
- Pet motion should be code-driven/sprite-driven and independent of network requests.
- Startup integration is opt-in; no automatic launchd changes in the MVP.
- Packaging is not a substitute for signing/notarization and OS permission testing.
