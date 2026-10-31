# BUDDY

**A talking desktop friend for macOS.** Built in Python, with local speech recognition,
streamed AI replies, natural speech, and an architecture that can grow into a desktop pet.

This repository is named **LEXA**. The companion's default name is **BUDDY**;
change `pet.name` in `config.yaml` whenever you like.

## Current release: Phase 1 — terminal voice MVP

**Works now:** deliberate push-to-talk → local faster-whisper → Claude / OpenAI / Ollama
→ streamed spoken reply. A text mode and a clearly labelled demo are included.

- Terminal PTT: Enter to start recording, Enter again to stop.
- Optional global hold-to-talk: Control + Option + Space; release to stop.
- Short, warm responses and configurable name/personality.
- Sentence-by-sentence speech starts while the LLM is still generating.
- Edge audio streams directly to mpv/ffplay. Local pyttsx3 and macOS `say` fallbacks.
- Bounded microphone capture, silence rejection, local resampling/recognition, and clear errors.
- `/mute`, `/unmute`, `/reset`, `/help`, `/quit`; Ctrl-C stops the app.
- Bounded conversation context in RAM. Local rotating action metadata logs.

**Planned:** wake word, computer-control skills, music, animated pet, SQLite memory,
reminders, notes, weather, screenshots, settings, startup integration, and packaging.
They are **not enabled** in this MVP. See [the phase roadmap](docs/ROADMAP.md).

## macOS setup

Use Python **3.11 or 3.12** for the voice dependencies. Both Apple Silicon and Intel
are intended targets; physical Mac audio and permissions need the manual checks below.

If you use Homebrew:

```bash
brew install python@3.11 portaudio mpv
git clone https://github.com/arpitkjaiswal/LEXA.git
cd LEXA
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Do not run with `sudo`. BUDDY does not need admin access.

### 1. Test the terminal without an API key or microphone

```bash
python -m buddy --demo --text --no-tts
```

Type anything, then `/quit`. This is a **canned demo response**, not an AI conversation.
For a one-command smoke check:

```bash
python -m buddy --demo --no-tts --once "Hello Buddy"
```

### 2. Configure one real AI provider

Open `.env` locally in your editor. Do not commit it or put keys in `config.yaml`.
Choose an exact model ID your account can access; BUDDY deliberately does not guess it.

| Brain | Required `.env` settings |
| --- | --- |
| Claude (default) | `BUDDY_PROVIDER=anthropic`, `BUDDY_MODEL=<your model ID>`, `ANTHROPIC_API_KEY=<your key>` |
| OpenAI / ChatGPT models via API | `BUDDY_PROVIDER=openai`, `BUDDY_MODEL=<your model ID>`, `OPENAI_API_KEY=<your key>` |
| Local Ollama | `BUDDY_PROVIDER=ollama`, `BUDDY_MODEL=<an installed model name>`, `OLLAMA_BASE_URL=http://127.0.0.1:11434` |

For Ollama, install it from its official distribution, start it, and pull your chosen
model before running BUDDY. Keep the endpoint on localhost for an offline setup.
Pointing it at another machine sends prompts to that machine.

```bash
python -m buddy --doctor
python -m buddy --text --no-tts
```

Try “Hey Buddy, help me get motivated to study.” A live reply should stream to the terminal.
The readiness report checks local configuration and package presence; it does not verify
API quota, model access, downloaded model weights, or OS permissions.

### 3. Try voice

```bash
python -m buddy
```

Whisper loads **before** the microphone opens. Its first run may download model weights.
Wait for `[Mic OFF]`, press Enter, speak, and press Enter again. Recording closes before
transcription and playback start. Capture also stops automatically after 25 seconds.
Whisper can detect the language automatically; set `stt.language: en` for English only.

When macOS asks, allow **Microphone** access for the application hosting Python
(Terminal, iTerm, or your editor). You can manage it under
**System Settings → Privacy & Security → Microphone**.

For a global hotkey:

```bash
python -m buddy --ptt global
```

Hold **Control + Option + Space**, speak, then release. Configure `audio.hotkey` to change it.
Depending on macOS and the terminal, pynput may require **Input Monitoring** and/or
**Accessibility** permission. If the listener does not work, use terminal PTT.
This app does not grant itself permissions. The global listener observes key events to
recognize its chord; it does not log keystrokes or capture audio while idle.
Hotkeys pressed while BUDDY is replying are ignored. Overlapping conversations are disabled.

### 4. Choose speech output

Default `tts.backend: edge` uses the configured Microsoft Edge voice and needs Internet
and `mpv` or `ffplay`. Audio chunks are piped to the player; no recording or TTS file is saved.
Edge TTS depends on an external service and can fail; local fallbacks keep the text reply usable.

For local macOS speech, add this to `.env`:

```dotenv
BUDDY_TTS_BACKEND=say
```

`say` uses installed macOS voices. Choose an installed voice with `tts.local_voice`.
`pyttsx3` is also supported; its OS engine runs in a child process so Cocoa has a main thread.
Piper is reserved for a later offline voice upgrade and is not implemented in Phase 1.

For a fully local runtime, use cached Whisper weights (`stt.local_files_only: true`),
Ollama on localhost with a downloaded model, and an installed local TTS voice.
Initial model/voice/package downloads still need a connection. Use `--no-tts` for silent replies.

## Controls and verification

| Command / key | Behavior |
| --- | --- |
| Enter, then Enter again | Terminal PTT start / stop |
| Hold configured global chord | Global PTT; release stops |
| `/mute` | Disable new microphone captures and spoken replies; during capture, stop and discard it |
| `/unmute` | Enable capture and speech again |
| `/reset` | Clear the in-memory conversation |
| `/help` | Show controls |
| `/quit` or Ctrl-C | Exit and close audio/player resources |

Terminal commands are accepted while idle and recording. While generating or speaking,
Ctrl-C exits immediately; the concurrent tray mute and stop controls arrive in Phase 3.
In text mode `/mute` still allows typed chat but suppresses speech.

Phase 1 manual acceptance checks on your Mac:

1. Run the demo above, then a real typed conversation with `--text --no-tts`.
2. In voice mode, check that the OS mic indicator is off while idle and during replies.
3. Start a recording, say a sentence, stop, and hear the reply. Try only silence as well.
4. Start recording and type `/mute`; the capture must be discarded. Enter while muted
   must not open the mic. `/unmute` restores capture.
5. Let a recording reach its time limit; the next prompt must remain usable.
6. Disconnect Internet: cloud brain errors must be readable and the mic must close.
7. Test `BUDDY_TTS_BACKEND=say`, then the global chord if you enable its permissions.
8. Press Ctrl-C during capture, generation, and speech; the mic indicator/player must stop.

These hardware/API checks cannot be established by mocked automated tests alone.

## Configuration and data

`config.yaml` controls pet/personality, audio, STT, provider, speech and logging.
The order is **environment variables → `.env` → YAML → defaults**.
The app reads `.env` beside the selected config; it does not search parent folders.
Run from the repository root, or pass explicit paths:

```bash
python -m buddy --config /absolute/path/config.yaml --env-file /absolute/path/.env
```

`--text` and `--once` never initialize a microphone or Whisper. `--no-tts` never calls TTS.
No conversation persists after exit in Phase 1. SQLite chat history and editable user facts
are planned for Phase 4; the configured name/personality already apply to each session.

Logs live at `~/Library/Application Support/BUDDY/logs/actions.jsonl` on macOS.
They contain timestamps, state transitions, success/error categories and lengths,
**not audio, transcripts, full replies, API keys or keystrokes**. Rotation is bounded.
Set `BUDDY_DATA_DIR` to change the data location, or `logging.enabled: false` to disable logging.

| Data | Destination in this release |
| --- | --- |
| Microphone PCM | RAM → local faster-whisper; never sent to a speech API |
| Current transcript + recent session context | Selected Claude/OpenAI API or configured Ollama endpoint |
| Reply text, with Edge selected | Configured Edge TTS service |
| Reply text, with pyttsx3 / say selected | Local OS speech engine |
| Action metadata | Local rotating log directory |
| Model/package downloads | Package registry and configured model distribution/cache |

There is no telemetry, arbitrary shell executor, autonomous desktop access or remote
computer-control endpoint. Subprocesses launch only fixed speech engines/players with
argument arrays and text over stdin. AI-generated text is never executed.
See [SECURITY.md](SECURITY.md) for the boundary planned for computer-control skills.

## Project structure

```text
buddy/
  main.py
  core/
    config.py       # typed YAML/.env loading and validation
    console.py      # cancellable macOS terminal input
    hotkey.py       # optional global hold-to-talk
    audio.py        # bounded, on-demand, in-memory recording
    stt.py          # local faster-whisper
    brain.py        # Claude / OpenAI / Ollama / labelled demo
    tts.py          # streaming Edge and local speech fallbacks
    assistant.py    # turn orchestration, state events, RAM context
    runner.py       # terminal controls and capture lifecycle
    audit.py        # privacy-filtered action logs
    doctor.py       # read-only setup diagnostics
  skills/           # Phase 2: no actions loaded yet
  ui/               # Phase 3: no desktop overlay yet
tests/
docs/
config.yaml
.env.example
requirements.txt
pyproject.toml
```

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Automated tests exercise provider streams using real SDKs against mock HTTP transports,
audio and STT lifecycle doubles, privacy, cancellation, muted capture, speech failures,
and the CLI. They do not make paid API calls, download model weights, or open real microphones.
CI targets Python 3.11 and 3.12, including macOS. A green CI job is not a physical audio test.

### Adding skills (Phase 2 contract)

The MVP does not register or execute skills. The planned plugin interface is a Python
module in `buddy/skills/`, exporting `name`, `description`, `schema`, and async `run()`:

```python
# Planned interface; not executable by the Phase 1 assistant.
name = "get_time"
description = "Get the laptop's current local time."
schema = {"type": "object", "properties": {}, "additionalProperties": False}


async def run(arguments: dict[str, object]) -> dict[str, object]:
    from datetime import datetime

    return {"time": datetime.now().astimezone().isoformat()}
```

Phase 2 will add schema validation, explicit registration/allowlisting, audit logging,
provider tool-result round trips and confirmation enforcement. Do not add shell executors
or dynamically execute LLM output. Details and phase acceptance tests are in
[ARCHITECTURE.md](docs/ARCHITECTURE.md) and [ROADMAP.md](docs/ROADMAP.md).

## Troubleshooting

- **No mic / permission denied:** allow your terminal's Microphone permission; run
  `python -m buddy --list-devices` and set `audio.device` to an input index.
- **Whisper too slow:** try `stt.model: tiny`; CPU `int8` is the default. Check RAM/disk.
- **Whisper cannot download:** check model-network access. Cache weights before setting
  `local_files_only: true`; that switch does not download them.
- **Model/key error:** confirm `BUDDY_MODEL`, provider selection and API access locally.
  API exception bodies are deliberately not printed or logged.
- **No speech output:** `brew install mpv`, or choose local `say`. On an unavailable
  voice/backend, text replies remain visible. Use `--no-tts` while diagnosing.
- **Global hotkey does nothing:** check macOS Input Monitoring / Accessibility or use
  `--ptt terminal`. Avoid a chord already reserved by macOS or your applications.
- **Background noise is captured:** tune `audio.silence_rms`, use a headset and verify
  the transcript. Speech recognition is not an authentication mechanism.
- **Windows/Linux:** config paths and core code account for these systems, but macOS
  is the first target. Global keys, OS voices, PortAudio and terminal cancellation
  need platform-specific testing before support is claimed.

## Upstream references

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Anthropic streaming SDK](https://github.com/anthropics/anthropic-sdk-python/blob/main/helpers.md)
- [OpenAI response streaming](https://developers.openai.com/api/docs/guides/streaming-responses)
- [Ollama chat API](https://docs.ollama.com/api/chat)
- [edge-tts](https://github.com/rany2/edge-tts)
- [python-sounddevice](https://python-sounddevice.readthedocs.io/)

No license grant has been selected for this repository yet.
