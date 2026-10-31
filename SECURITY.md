# Security and privacy

BUDDY is a local desktop application with optional network services. Its skill boundary
reduces what a model can request; it is not an OS sandbox or a guarantee against model errors.

## Actions

- Only a fixed built-in module catalog and configured tool/app/domain allowlists are used.
- All arguments pass JSON schema validation outside the model.
- OS launches use argument arrays, with no shell. Volume uses fixed AppleScript templates.
- Screenshots and saved note/memory deletion require exact, expiring, single-use approval.
- A generic “yes,” a model tool call, a stale dialog or a mismatched ID cannot approve an action.
- Mute, stop, cancellation and a new conversation turn revoke pending approvals.
- There is no arbitrary file access, shell execution, shutdown, outgoing messaging or
  destructive filesystem deletion tool. Screenshots are never uploaded by a tool.

Only install locally trusted skills/code. The settings file is trusted local configuration;
do not import someone else's configuration or trained model without reviewing it.

## Data

Microphone PCM stays in RAM and is transcribed locally. Wake listening keeps the mic open
locally while idle and is suspended during replies; PTT leaves the idle microphone closed.
Captured audio and transcripts are not written to the audit log.

Explicit facts, requested notes/reminders and optionally retained chats live in SQLite.
Saved facts/context/tool results go to the selected AI provider when relevant. Online Edge
TTS receives reply text; local voices do not. Weather and music/browser actions contact their
respective services. Localhost Ollama with cached models/local speech supports offline chat.

.env, database and screenshot files are owner-readable; storage is not encrypted at rest.
Chat retention defaults off. Disabling retention does not delete prior records. Use the
memory deletion controls to remove saved facts/history; notes have separate deletion.
The metadata audit log contains states, lengths, fixed skill names, success and error categories;
it excludes credentials, tool arguments/results, audio, notes and conversation text.

## Credentials and distribution

Never commit .env or API keys. The settings editor does not display saved keys and does not
write them to YAML. Packaged apps create private per-user configuration; personal keys and
model weights are not bundled. Login startup is explicitly opt-in and per-user.

Unsigned development app artifacts are not notarized releases. macOS manages microphone,
Screen Recording and Accessibility permissions. BUDDY cannot grant itself permission.
Review permissions and use the physical checklist before relying on voice controls.

For a security report, avoid publishing keys, audio, conversations or screenshots in an issue.
Provide a minimal reproduction with synthetic data and the relevant version instead.
