# Phase 1 validation

Recorded: 31 October 2026. Runtime used for local checks: Linux x86_64, Python 3.12.14.
macOS is the product's first target; this environment is not a physical Mac.

- 64 automated tests passed.
- Ruff lint and formatting checks passed; source syntax checked against Python 3.11.
- Editable base/dev package and voice libraries installed successfully, excluding
  Linux's optional global keyboard listener dependency.
- Real Anthropic and OpenAI SDKs exercised against mock HTTP transports; no paid API calls.
- Ollama streaming exercised against a mock HTTP transport; no local model server claimed.
- On-demand capture, native audio rate fallback, silence, cancellation, muted capture,
  in-memory WAV/STT lifecycle and global hotkey state tested with synthetic inputs/doubles.
- Streaming TTS pipe behavior and local fallback policy checked without claiming audible output.
- Demo CLI, interactive text commands, missing-key errors and read-only diagnostics checked.

The full voice extra on this Linux executor encountered a missing `clang` build dependency
for pynput's Linux `evdev` package. This is separate from the macOS installation path.
The other voice libraries installed successfully. The executor also lacks the native
PortAudio library; the real device-list command returned the documented setup error
without a traceback. macOS setup explicitly installs PortAudio with Homebrew.
No claim is made that macOS-specific
PyObjC, hotkeys, speech voices or microphone permissions were tested here.

Still requires verification on the user's Mac:

- Real microphone recording, OS permission indicators, global chord and release behavior.
- Whisper weight download and transcription quality/speed with the user's microphone.
- Live AI credentials, accessible model IDs and provider quota.
- Audible Edge / pyttsx3 / macOS say playback and Ctrl-C cleanup with OS audio devices.
- Apple Silicon and Intel packaging, signing, startup and UI (later phases).

CI configuration targets macOS and Ubuntu with Python 3.11/3.12. Its results are separate
from the local checks recorded above and must be read from the actual workflow run.
