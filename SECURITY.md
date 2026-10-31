# Security and privacy

Phase 1 is a terminal chat/voice MVP. It cannot open apps, run shell commands, delete files,
send messages, lock/shut down the Mac or observe the desktop. No computer-control tools
are offered to the LLM. Fixed local subprocesses are used only for speech and audio playback.

Microphone access is deliberate and bounded. There is no wake-word/background audio
capture in this phase. Mute prevents new captures and discards a capture stopped by `/mute`.
Speech recognition and future wake phrases are not identity checks.

Whisper transcribes locally; the first model load may download weights. Prompts/session
context go to the selected AI endpoint; Edge TTS receives reply text only when selected.
Local speech fallbacks do not silently switch to a different online TTS provider.
Provider-side data policies still apply. Local OS voices may require a one-time download.

Runtime logs are local, bounded and metadata-only. Configuration secrets are excluded from
git and object representations. Do not attach `.env`, audio captures, API responses, chat
logs or database files to public issues. If you expose a key, revoke it at the provider.

Future laptop skills must enforce allowlisting and argument validation outside the LLM.
Risky operations must be denied unless a fresh, specific confirmation approves the exact
pending action. Arbitrary shell execution remains prohibited even with confirmation.
These policies are design requirements for later phases, not an implemented confirmation
system in the current chat-only MVP.

Report a suspected issue privately to the repository owner through an available private
channel. Do not publish secrets or exploit data in a public issue.
