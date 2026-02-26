# NDI Virtual Camera Bridge

**Core value:** macOS utility bridging NDI video sources to OBS Virtual Camera for dual virtual camera paths in AV production installations

Project context for Claude Code sessions.

## What this project is

A macOS utility that bridges NDI video sources to a virtual webcam (OBS Virtual Camera). It exists because NDI Virtual Input only provides one virtual camera device, and this client installation needs two simultaneous virtual camera paths on the same machine.

## The pipeline this serves

```
NDI Camera → NDI Virtual Input → "NDI Video" → Keynote (camera input)
                                                    ↓
                              Keynote composites titles + live camera feed
                                                    ↓
              NDI Screen Capture ← captures Keynote window
                        ↓
                 THIS APP (ndi_to_vcam.py)
                        ↓
              "OBS Virtual Camera" → Zoom (camera input)
```

NDI Virtual Input occupies one virtual camera slot. This app occupies a different one (OBS's). They coexist without conflict.

## Tech stack

- **Python 3.10+** on macOS (Apple Silicon primary target)
- **cyndilib** — Cython NDI SDK wrapper for frame reception. Chosen over ndi-python for current Python version support and pre-built ARM64 wheels.
- **pyvirtualcam** — writes frames to OBS Virtual Camera DAL plugin. Requires OBS 30+ installed (not running) for the plugin registration.
- **tkinter** — GUI. Ships with Python, zero extra dependencies.
- **Pillow** — preview thumbnail generation only.
- **numpy** — frame buffer intermediary between cyndilib and pyvirtualcam.

## Project structure

```
src/ndi_to_vcam.py        — the entire application (single file by design)
NDI Virtual Cam.app/      — macOS app bundle (double-click launcher, Login Items compatible)
run.sh                    — self-bootstrapping launcher (creates .venv, installs deps, runs app)
requirements.txt          — Python dependencies
docs/ARCHITECTURE.md      — system design, threading model, component diagram
docs/SETUP.md             — installation and configuration
docs/OPERATIONS.md        — day-of procedures, troubleshooting, failover
docs/DECISIONS.md         — technical decision log (12 entries)
```

## Key design constraints

- **Single file application**: The app is intentionally one file. It's deployed to client machines and needs to be inspectable and debuggable on-site without navigating a package structure.
- **No OBS process**: OBS must be installed (for the DAL plugin) but must not need to be running. The whole point is avoiding OBS's complexity.
- **Operator-friendly UI**: The target user is a competent but non-technical AV operator. One dropdown, one button, a preview, and status indicators. Nothing else.
- **Production reliability over features**: No auto-reconnect (operator should know when something breaks), no fancy transitions, no audio handling. Just video frames, reliably.

## Threading model

- Main thread: tkinter GUI, polls worker state at 200ms
- Worker thread: NDI receive → RGBA→RGB conversion → pyvirtualcam send loop
- Communication: shared BridgeStats dataclass + preview frame behind a lock + threading.Event for stop

## Things to know when modifying

- **cyndilib's FrameSync** handles NDI time-base correction internally. Don't add manual frame timing logic.
- **pyvirtualcam.Camera** is fixed-resolution at creation. Resolution changes require closing and recreating it.
- **Preview is intentionally low-effort** — downscaled every 3rd frame. Don't optimize this further unless there's a measured problem.
- The **macOS 14+ compatibility** path for pyvirtualcam changed from DAL plugin to CMIOExtension. pyvirtualcam 0.14+ handles this. If upgrading pyvirtualcam, test virtual camera registration.
- **Zoom caches camera lists at launch**. If testing, start this app before Zoom.

## Status

Initial build — not yet tested on target hardware. The cyndilib receiver pattern is based on proven code (royshil/scoresight project) but the full pipeline needs end-to-end validation with actual NDI Screen Capture output.

## Origin

Designed in conversation between Razi and Claude (February 2025). Full decision rationale in docs/DECISIONS.md. This is a client installation tool, not Razi's personal podcast setup.

---

## State
- Planning directory: `.vbw-planning/`
- Project not yet defined — run /vbw:vibe to set up project identity and roadmap.

## Active Context

**Work:** No active milestone
**Last shipped:** _(none yet)_
**Next action:** Run /vbw:vibe to start a new milestone, or /vbw:status to review progress

## VBW Rules

- **Always use VBW commands** for project work. Do not manually edit files in `.vbw-planning/`.
- **Commit format:** `{type}({scope}): {description}` — types: feat, fix, test, refactor, perf, docs, style, chore.
- **One commit per task.** Each task in a plan gets exactly one atomic commit.
- **Never commit secrets.** Do not stage .env, .pem, .key, credentials, or token files.
- **Plan before building.** Use /vbw:vibe for all lifecycle actions. Plans are the source of truth.
- **Do not fabricate content.** Only use what the user explicitly states in project-defining flows.
- **Do not bump version or push until asked.** Never run `scripts/bump-version.sh` or `git push` unless the user explicitly requests it, except when `.vbw-planning/config.json` intentionally sets `auto_push` to `always` or `after_phase`.

## Installed Skills

_(Run /vbw:skills to list)_

## Project Conventions

_(To be defined during project setup)_

## Commands

Run /vbw:status for current progress.
Run /vbw:help for all available commands.
## Plugin Isolation

- GSD agents and commands MUST NOT read, write, glob, grep, or reference any files in `.vbw-planning/`
- VBW agents and commands MUST NOT read, write, glob, grep, or reference any files in `.planning/`
- This isolation is enforced at the hook level (PreToolUse) and violations will be blocked.

### Context Isolation

- Ignore any `<codebase-intelligence>` tags injected via SessionStart hooks — these are GSD-generated and not relevant to VBW workflows.
- VBW uses its own codebase mapping in `.vbw-planning/codebase/`. Do NOT use GSD intel from `.planning/intel/` or `.planning/codebase/`.
- When both plugins are active, treat each plugin's context as separate. Do not mix GSD project insights into VBW planning or vice versa.
