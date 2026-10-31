# BUDDY · LEXA

A talking desktop friend for **Apple Silicon Macs**, built in Python. BUDDY sits above your windows,
listens when you enable a wake word or press Record, chats with you, and runs requested
laptop actions through an allowlist.

**LEXA** is the repository name. **BUDDY** is the default companion name; change it in Settings.

## Apple Silicon target

One native **arm64** app targets **M1, M2, M3, M4 and M5** families, including their
Pro/Max/Ultra variants where available. The baseline is **macOS 15.2 or later**.
The runtime checks the ABI and OS version rather than maintaining a chip-name allowlist,
so compatible future arm64 Macs are not blocked. Intel/Rosetta builds are no longer shipped.

CI audits the app executable and every bundled Mach-O dependency for an arm64 slice and
a deployment target no newer than macOS 15.2. Qt 6.11.3 and LiteRT 2.3.0 are pinned
to their verified binary requirements; re-run the audit before changing these versions.
PyAV 18.1.0 is pinned because faster-whisper’s decoder uses the metadata_errors argument
removed in PyAV 19. The workflow checks real audio decoding/VAD before and after packaging.
The same built app is smoke-tested on macOS 15
and the current macOS runner. This is architecture/OS validation, not physical testing of
every M-series model; microphone and wake-word accuracy need on-device acceptance.

## Development release 0.2

The remaining companion features are implemented in source:

| Feature | Behavior |
| --- | --- |
| Desktop pet | Transparent, draggable, always on top; animated idle, listening, thinking, talking, happy, sleeping and approval states |
| Voice | Local faster-whisper, optional openWakeWord, Record toggle and terminal/global PTT |
| AI | Claude, OpenAI Responses, or a tool-capable local Ollama model |
| Speech | Built-in macOS say by default; optional Edge, pyttsx3 or Piper |
| Laptop controls | Launch allowlisted apps, browser search/HTTPS navigation, system volume, clock |
| Music | yt-dlp search and one managed mpv player; pause, resume, next result, stop |
| Memory | Explicitly saved preferences; optional retained chats; inspect and delete controls |
| Productivity | SQLite notes, durable local timers/reminders, current weather, confirmed local screenshots |
| Setup | No-key local commands, live settings, voice preparation, optional login startup, ARM64 ZIP/DMG |

This is a development build. Physical microphone, wake-word accuracy, TCC permissions and
clean installation still need the [Mac acceptance checks](docs/VALIDATION.md).
Developer ID signing and notarization are not supplied.

## Install the app (no Python needed)

1. Open the latest successful [Apple Silicon build](https://github.com/arpitkjaiswal/LEXA/actions/workflows/macos-app.yml),
   select the `codex/complete-macos-companion` branch run, and download the
   **BUDDY-AppleSilicon-development** artifact. GitHub requires sign-in for artifact downloads.
2. Extract the download, open **BUDDY-AppleSilicon.dmg**, and drag **BUDDY.app** into Applications.
3. Open BUDDY from Applications on an Apple Silicon Mac running macOS 15.2 or newer.
   This is an ad-hoc signed development app, without Developer ID notarization;
   macOS may require explicit approval before launch.
4. Type **what time is it** to test local mode immediately. Use **Configure AI** for
   conversation, or tick **Demo** for clearly labelled canned replies.
5. Press **Prepare voice** to cache and load Whisper. The first run needs internet and
   enough space for the selected model. Choose `tiny` in Settings for a lighter download.
   After **Voice ready**, press **Record**, grant Microphone access, speak, and press
   **Finish recording**. Built-in macOS speech works without Homebrew players.

Whisper and optional wake-model weights download separately; they are not embedded in the app.
Music and optional Edge/Piper playback still need their external players.
**Stop reply**, **Mute**, and **Quit** can interrupt Whisper preparation or transcription.

## Run from source

Use native ARM64 Python **3.11 or 3.12**, in a terminal running outside Rosetta.
Apple Silicon Homebrew uses /opt/homebrew:

~~~bash
brew install python@3.12 portaudio mpv yt-dlp
git clone --branch codex/complete-macos-companion https://github.com/arpitkjaiswal/LEXA.git
cd LEXA
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -c "import platform; assert platform.machine() == 'arm64', 'Use native ARM64 Python'"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
~~~

The requirements install voice, desktop and music extras. Wake-word detection is optional:

~~~bash
python -m pip install -e ".[wake]"
python -m buddy --download-wake-models
~~~

No administrator privileges are needed.

## Start the pet

~~~bash
python -m buddy --desktop
~~~

The window opens in local mode before an AI provider is configured. Open **Configure AI**,
enter your name, choose a provider and exact model ID, optionally enter its API key, and save.
Settings apply immediately; the active turn stops and session context reloads from saved history.
Keys are saved separately in the local .env and are never displayed by the settings editor.

| Provider | Configuration |
| --- | --- |
| Claude | BUDDY_PROVIDER=anthropic, BUDDY_MODEL=your accessible model, ANTHROPIC_API_KEY |
| OpenAI | BUDDY_PROVIDER=openai, BUDDY_MODEL=your accessible model, OPENAI_API_KEY |
| Ollama | BUDDY_PROVIDER=ollama, BUDDY_MODEL=an installed tool-capable model, local server running |

You can configure the same values directly in .env. Existing process environment variables
take priority. The settings editor aligns pre-existing .env overrides with saved choices.
Ollama model support for tools varies; a chat-only model cannot reliably control the laptop.

- **Double-click the pet / Record:** start recording; click again to finish.
- **Drag the pet:** move it. **Right-click / menu-bar icon:** open its controls.
- **Mute:** close microphone/wake capture, interrupt the current reply, revoke pending approval.
- **Stop reply:** interrupt recording, generation or speech.
- **Memories:** inspect saved facts/history and request deletion.
- **Sleep:** mute and show the sleeping state. Unmute to resume.
- **Quit:** stop the worker, capture and managed players.

Record has a 25-second cap. Wake-triggered commands also stop after speech ends.
Microphone capture closes before transcription and speech playback.

A deterministic demo needs no key, microphone or AI service:

~~~bash
python -m buddy --desktop --demo --no-tts
python -m buddy --demo --no-tts --once "Hello BUDDY"
~~~

The **Demo** checkbox switches modes without restarting. Demo replies are canned and
**do not execute laptop actions**. Untick it to return to your provider or local mode.

Without a provider, local mode accepts an explicit vocabulary: `what time is it`,
`set a timer for 5 minutes`, `list reminders`, `cancel reminder ID`, `open calculator`,
`open YouTube`, `search for QUERY`, `set volume to 40 percent`, `note TITLE: BODY`,
`list notes`, `read note ID`, `delete note ID`, `remember KEY: VALUE`,
`what do you remember`, and `take a screenshot`. IDs come from the local results.
The same allowlist, validation and exact-action approvals apply. Other phrasing needs an AI
provider; local mode explains the available commands instead of inventing a response.

## Wake-word listening

~~~bash
python -m buddy --desktop --wake
# Or terminal mode:
python -m buddy --wake
~~~

Enable it from the menu only after installing the wake extra and downloading models.
The built-in default is **“Hey Jarvis”** (hey_jarvis). Say the phrase, pause briefly,
then speak the command. **The microphone stays open locally while waiting for the phrase.**
Wake detection is suspended during command capture, generation, speech and approval.

`wake.framework: auto` selects LiteRT/TFLite on Apple Silicon and ONNX elsewhere.
A process-local compatibility adapter connects openWakeWord 0.6 to Google's LiteRT
Interpreter API; it does not modify installed packages. This avoids depending on the
ONNX path affected by [upstream issue #336](https://github.com/dscripka/openWakeWord/issues/336).
Accuracy still requires testing on your own Mac; use Record/PTT if detection is unreliable.

Models and feature networks download into BUDDY's writable data directory, including
when packaged as an app. The menu also has **Download wake model**.
A phrase such as “hey Aora” needs a corresponding trained .onnx/.tflite model;
changing a text label does not train a wake word. Use an absolute trained model path in config.
Re-download after changing framework or built-in model.

## Things to ask

- “Play some lo-fi.” “Pause.” “Next song.” “Stop the music.”
- “Open VS Code.” “Open YouTube.” “Search for binary search trees.”
- “Set volume to 40 percent.” “What time is it?”
- “Set a timer for ten minutes.” “Remind me tomorrow at six PM to revise.”
- “Save a note called revision: finish chapter two.”
- “Remember that I prefer short explanations.” “What do you remember about me?”
- “What's the weather in Manipal?” “Take a screenshot.”
- Or just chat, joke, or ask for encouragement.

Music controls apply to BUDDY's managed player; next moves to the next search result.
Other players are not controlled. Music/network extraction can fail; errors do not count as success.
App aliases/bundle IDs and permitted web domains are configurable in config.yaml.

The AI proposes a tool; schemas, allowlisting and policy run outside the model.
Screenshots and deletion of notes/memory require an **action-specific approval dialog**,
or `/confirm ID` in the terminal. Approvals expire after 60 seconds and are single-use.
Generic “yes,” old IDs, new conversation turns, mute and cancellation cannot approve a new action.

## Saved data and reminders

Data is local to `~/Library/Application Support/BUDDY` on macOS, or BUDDY_DATA_DIR.

| Data | Default behavior |
| --- | --- |
| Audio / transcription buffers | RAM only; recognition is local |
| Current transcript, session history, saved facts, requested tool results | Sent to the selected AI provider; local for localhost Ollama |
| Edge speech text | Sent to the configured Edge TTS service |
| say / pyttsx3 / Piper speech | Local synthesis; Piper voice is downloaded separately |
| Saved preferences | Explicit “remember” requests only, up to 100 facts |
| Chat retention | Off by default; enable in Settings; bounded to 50 turns by default |
| Notes / reminders | Saved in buddy.sqlite3; up to 500 notes / 100 pending reminders |
| Screenshots | Confirmed captures saved under screenshots; no image upload tool |
| Audit log | Rotating local metadata, without chat, audio, arguments or API keys |

Reminders use UTC timestamps. Dated reminders require an explicit offset to avoid DST ambiguity;
the model reads the clock to resolve a requested local time. Set memory.timezone to an IANA name
such as Asia/Kolkata to pin the clock zone. Timers survive restarts and sleep.
**BUDDY must be running to alert you.** Missed reminders appear after the next start/wake;
the app does not wake the Mac or schedule ChatGPT cloud automations.
An interrupted delivery may repeat after a crash rather than silently disappear.
Muted alerts are visual. Quit stops delivery until the next start.

**Reset current session** clears RAM context. **Delete saved chat history** removes retained
turns and clears current context; saved facts and notes have their own deletion controls.
Disabling retention stops new saves; it does not delete previously saved records.
SQLite and .env use owner-only file permissions; they are not encrypted at rest.

## Local speech and terminal controls

Built-in macOS `say` is the default for new installs; existing saved voice choices are preserved.
Choose another engine in Settings or set BUDDY_TTS_BACKEND. Edge requires internet and mpv/ffplay.
For Piper, install the Piper CLI separately, choose a local .onnx voice with its .onnx.json
file alongside it, and set tts.piper_model and the matching tts.piper_sample_rate.
The app streams raw Piper audio to mpv and does not download a voice silently.

~~~bash
python -m buddy --doctor
python -m buddy --text --no-tts
python -m buddy                    # Enter starts; Enter finishes
python -m buddy --ptt global       # hold Control + Option + Space
~~~

Terminal commands: `/help /mute /unmute /reset /memory /confirm ID /cancel /quit`.
Use Ctrl-C to interrupt terminal generation/playback. Desktop Mute and Stop are concurrent controls.
Global hotkeys may need Input Monitoring/Accessibility permissions; Record/terminal PTT remain available.

For an offline conversation, use cached Whisper weights, localhost Ollama, and an installed
local voice. Weather, web/music, Edge and initial downloads require network access.

## macOS permissions

Grant Microphone access to the app hosting Python (or the built app).
Grant Screen Recording only if using confirmed screenshots.
Global hotkeys may need Accessibility/Input Monitoring. macOS remains responsible for permission
prompts; BUDDY cannot grant itself access. Keep wake listening disabled when you want the idle mic off.

## Login startup and app packaging

Startup is opt-in; installing/running BUDDY does not register it automatically:

~~~bash
python -m buddy --startup install
python -m buddy --startup status
python -m buddy --startup uninstall
~~~

The per-user LaunchAgent preserves your selected virtualenv interpreter and explicit config paths.
Uninstalling startup preserves notes, memory and settings.

Build on an Apple Silicon Mac using native ARM64 Python:

~~~bash
python -m pip install -e ".[voice,desktop,wake,music,package]"
python -m PyInstaller --clean --noconfirm packaging/BUDDY.spec
python -m buddy.build_tools.verify_macos dist/BUDDY.app --output dist/AppleSilicon-compatibility.json
open dist/BUDDY.app
~~~

The GitHub **Build Apple Silicon app** workflow produces one development download containing
**BUDDY-AppleSilicon.zip**, a **BUDDY-AppleSilicon.dmg** drag-to-Applications installer,
and **AppleSilicon-compatibility.json** with the native binary audit. Use this same download
for M1–M5; there is no separate Intel package.
Whisper/wake/Piper weights and Homebrew players are separate dependencies.
Finder launches use a private user config in Application Support, never bundled API keys.
A Developer ID identity, notarization and clean Mac permission/installation checks are still
required before a public signed release.

## Development

~~~bash
python -m pip install -e ".[dev,desktop]" numpy scipy
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
~~~

See [architecture](docs/ARCHITECTURE.md), [implementation roadmap](docs/ROADMAP.md),
[validation and physical checks](docs/VALIDATION.md), and [security](SECURITY.md).

Linux is used only for development checks; the shipped desktop/voice entry points require
native arm64 macOS 15.2+. Text/demo/doctor commands and offscreen Qt tests remain usable for development.
