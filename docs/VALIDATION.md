# Validation

Apple Silicon target update on 2026-10-31: Python 3.12.14 on Linux, 123 tests passed;
Ruff lint/format and diff checks passed. The Qt smoke test rendered real widgets
offscreen and closed the worker cleanly. CI results are tied to the exact commit in the PR.

Run these checks from the repository root:

~~~bash
python -m pip install -e ".[dev,desktop]" numpy scipy
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m buddy --demo --no-tts --once "Hello BUDDY"
python -m buddy --doctor
~~~

## Automated coverage

The original 64 Phase 1 tests remain, with additional checks for:

- Unknown/disabled tools, invalid arguments and URL allowlist escapes.
- Immutable action arguments, one-use/expired/mismatched approvals, mute revocation.
- Actual Claude/OpenAI SDK payloads using mock HTTP transports; native tool-result round trips.
- Ollama tool results, blocked tools and incomplete provider output.
- SQLite persistence, optional bounded history, notes, UTC reminders and overdue recovery.
- Deleting saved history without recreating it through the confirmation turn.
- Native-rate wake frames, consecutive detections and cancellation waiting for microphone closure.
- Desktop mute during wake/capture and during speech; partial turns do not persist.
- First-launch local timers, notes and memory without a provider, disabled-skill enforcement,
  and local actions sharing the same exact approval rules.
- Live provider/key reconfiguration, pending-approval revocation and demo switching.
- Managed Whisper pipe framing, real child-process reuse, crashes/retry and cancellation
  during a stalled model download; no abandoned inference/download thread blocks shutdown.
- A real worker process with windowed-app standard streams and noisy progress output;
  dependency diagnostics exclude private exception content.
- Real Qt widgets in a separate offscreen process: pet states, chat, settings, approval dialog,
  and complete worker shutdown, without a microphone or network request.
- Settings/key separation, environment override synchronization and opt-in startup manifests.
- Apple Silicon host/OS checks, Rosetta rejection, future arm64 compatibility, and
  Mach-O audit failures for Intel-only dependencies or too-new deployment targets.

The companion CI runs checks on Ubuntu and native ARM64 macOS 15/current macOS with Python 3.11/3.12.
The Apple Silicon packaging workflow explicitly builds arm64, audits every bundled Mach-O
against the macOS 15.2 minimum, creates a ZIP/DMG, and smoke-tests the same packaged app on
macOS 15 and the current macOS runner. Source and frozen voice checks download `tiny.en`,
loads real faster-whisper/CTranslate2, and sends in-memory silence through PyAV/VAD
in its managed subprocess. This verifies native model loading and the packaged pipe;
it does not measure speech accuracy. PyAV 18.1.0 is pinned after reproducing PyAV 19’s
incompatible removal of the decoder’s metadata_errors argument. Check the workflow result for the exact
commit; a source test pass is not evidence of audible speech or real microphone recognition.

## Physical Mac acceptance

1. Install in a fresh virtualenv. Run doctor, demo, a real typed chat, and native desktop mode.
2. Approve Microphone for the terminal/app. Record, finish, transcribe and hear a short response.
   Confirm the mic indicator closes before STT and speech. Try silence and the recording cap.
3. Mute during wake listening, recording, provider generation and playback. Confirm audio stops,
   no captured command runs, and old approvals fail. Check Stop reply and Quit in every state.
4. Download the configured wake model. Test “Hey Jarvis,” false activations, room noise, native
   sample rates, suspend-during-speech and PTT fallback on the actual device. On Apple Silicon,
   verify LiteRT is selected. Upstream ONNX reports do not guarantee this Mac's accuracy.
5. Ask to open an allowed installed app, navigate/search, set volume and play/pause/next/stop
   music. Missing applications/dependencies/network must produce an error, never false success.
6. Save and inspect a fact/note, restart, and inspect again. Test history retention on/off,
   fact/note deletion, expired confirmation and complete history deletion.
7. Set a short timer and an offset-aware reminder. Test while idle, busy, muted, asleep and after
   restarting past its deadline. Verify overdue alerts, timezone and explicit acknowledgement.
8. Test weather online/offline. Request a screenshot, cancel it, then explicitly approve another.
   Grant Screen Recording only for the approved capture. Verify only a local PNG is produced.
9. Drag the pet across displays/Spaces, check always-on-top/reduced motion, tray visibility,
   hide/show chat, settings applying without restart and single-instance behavior.
10. Explicitly install/status/uninstall the LaunchAgent from a logged-in desktop session.
    Verify the correct virtualenv/app launches and removal preserves data.
11. Use the same Apple Silicon build on physical M1, M2, M3, M4 and M5-family devices as available.
    Launch from Finder with a clean user profile, configure the provider, download models into
    Application Support and repeat audio checks. The binary audit proves ABI/deployment metadata,
    not per-device wake detection or physical microphone compatibility.
    A distribution release additionally needs signing/notarization and Gatekeeper testing.

No physical M1–M5 device inventory or live paid API credential is available in the build workspace.
These final hardware/account checks must be recorded separately; they are not claimed complete.
