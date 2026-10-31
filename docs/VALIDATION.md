# Validation

Local verification on 2026-10-31: Python 3.12.14 on Linux, 95 tests passed;
Ruff lint/format and diff checks passed. The Qt smoke test rendered real widgets
offscreen and closed the worker cleanly. Mac CI has not run for this new implementation.

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
- Real Qt widgets in a separate offscreen process: pet states, chat, settings, approval dialog,
  and complete worker shutdown, without a microphone or network request.
- Settings/key separation, environment override synchronization and opt-in startup manifests.

The companion CI runs checks on Ubuntu and macOS with Python 3.11/3.12. The packaging workflow
builds development .app artifacts on Mac runners. Check the workflow result for the exact
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
   hide/show chat, settings restart and single-instance behavior.
10. Explicitly install/status/uninstall the LaunchAgent from a logged-in desktop session.
    Verify the correct virtualenv/app launches and removal preserves data.
11. Build on Intel and Apple Silicon separately. Launch from Finder with a clean user profile,
    configure the provider, download models into Application Support and repeat audio checks.
    A distribution release additionally needs signing/notarization and Gatekeeper testing.

No physical Mac or live paid API credential is available in the build workspace.
These final hardware/account checks must be recorded separately; they are not claimed complete.
