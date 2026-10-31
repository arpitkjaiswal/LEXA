# Architecture

The terminal and Qt desktop share one serialized async Assistant. Qt stays on the main
thread. A separate asyncio worker owns the microphone, STT, model, skill registry, SQLite
store and speech processes; queued Qt signals carry state, text, approvals and reminders.

## Voice lifecycle

1. Load configuration; initialize local data and only the selected AI provider.
2. In PTT mode the microphone remains closed until an explicit gesture.
3. In optional wake mode, open a local 16 kHz mono detector; resample native device rates.
4. After detection, close the wake stream, then record the command with a silence/time cap.
5. Close recording before local Whisper transcription and model work.
6. Run a bounded tool/result loop if skills are enabled; emit only the final grounded answer.
7. Segment text into phrases and feed a bounded playback queue.
8. Resume wake detection only after capture, generation and playback finish.

Cancellation is cooperative for blocking capture: signal stop and await actual stream
closure. UI mute cancels active work, kills speech, closes wake capture and revokes pending
approvals. Record and reminder delivery are serialized by the desktop worker. Terminal
idle input races against due reminders, closing wake detection before an alert speaks.

## Tool boundary

Only module names in a constant built-in catalog can load. Each module registers a Tool
with a unique name, JSON schema, description, async function and a fixed confirmation policy.
Configuration selects an allowlist; the model cannot select an arbitrary import path.

Claude, OpenAI Responses and Ollama each send structured tool results back through their
native API format before producing final text. Tool loops have round/call/size/time limits.
Pre-action model text is not spoken as a completed action. Chat-only mode retains the
original streaming adapter; the deterministic demo never executes tools.

A sensitive proposal stores immutable canonical JSON, a random token and monotonic expiry.
Approval comes from a direct UI event or exact terminal command, never a model-exposed
confirmation tool. Tokens are consumed once, including failed matches; a new user turn,
mute, cancellation or expiry invalidates them. Stale dialog cancellation is bound to its ID.

OS calls use fixed executables and argument arrays. AppleScript is limited to fixed volume
templates containing validated numbers. App launch uses configured bundle IDs. Browser
navigation allows HTTPS only within configured domains. There is no shell, arbitrary file
reader, message sender, shutdown or recursive deletion tool.

## Data and scheduling

Store uses schema-versioned SQLite with parameterized statements and owner-only file
permissions. Facts and chat retention obey explicit settings; notes/reminders remain
independent records. Chat retention is off by default and bounded when enabled.
Facts are serialized as untrusted data in the prompt, never treated as system instructions.
Successful whole turns alone are eligible for retention; confirmation tokens are not retained.

Timers/reminders store epoch UTC deadlines and an acknowledgement state. Dated reminders
require an aware ISO timestamp. Polling against wall-clock time handles system sleep/restart;
delivery is at least once across a crash. No OS wake or cloud delivery is implied.
The metadata audit log excludes audio, text, tool arguments/results and credentials.

## Desktop and distribution

The pet is drawn and animated with QPainter, without art downloads. Frame painting never
makes network or OS-control calls. The chat panel, tray, settings, memory viewer and approval
dialogs remain responsive while the async worker runs. A desktop lock prevents duplicate
instances sharing the same data directory.

openWakeWord uses a writable user model cache. Apple Silicon defaults to the LiteRT
Interpreter via a process-local compatibility adapter for openWakeWord 0.6; other targets
default to ONNX. No site-packages files are rewritten.

Settings writes are atomic; secrets stay in a separate .env. A packaged app defaults to
Application Support configuration and restores known Homebrew directories to Finder's PATH.
PyInstaller collects the fixed plugin modules, native speech/recognition dependencies and,
on Apple Silicon, LiteRT. Large voice/wake weights are downloaded separately.
Login startup is installed only by an explicit --startup install command.
