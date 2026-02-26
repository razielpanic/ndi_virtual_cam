# Conversation Context

How this project came to exist — the problem-solving chain that led here. Useful for understanding the "why" behind the "what" if you're picking this up cold.

## The original question

"Is there a Zoom product that directly ingests NDI as a contributor instead of using Virtual Camera?"

## What we found

- **Zoom Rooms** supports native NDI (input and output) via Custom AV, but requires a per-room license ($49/month) and a dedicated kiosk-mode setup
- **Zoom desktop client** does not natively accept NDI — only USB UVC devices and virtual cameras
- A **Zoom + NDI strategic partnership** was announced December 2025 that will expand NDI support to more Zoom products, but nothing shipping yet for the desktop client
- Zoom Rooms licenses are **per-room, not floating** — can't share one license across machines

## The actual pipeline requirement

The client installation needs:

1. An NDI camera feed composited with titles in Keynote (Keynote uses NDI Virtual Input as its camera source)
2. The composited Keynote output sent to Zoom as the contributor's camera feed (not as screen share — this IS the face + titles, not a presentation alongside a face)

Both paths need to be on the same Mac for failover simplicity.

## The constraint that created this project

NDI Virtual Input is already consumed at the **front** of the pipeline (feeding Keynote). It can't simultaneously serve the **back** of the pipeline (feeding Zoom). It's a single-instance app with one virtual camera device.

## Options we evaluated

1. **HDMI loopback** (capture card out → capture card in) — already consumed by the hot standby path
2. **Zoom native screen share** — presents as content, not as a camera tile. Rejected because the Keynote output IS the contributor's video
3. **OBS as a thin shim** — would work but brings a full production UI that an operator could misconfigure
4. **Second NDI Virtual Input instance** — not possible, single-instance app
5. **Custom DAL plugin from scratch** — too much build/sign/notarize overhead for a single-purpose tool
6. **pyvirtualcam + OBS DAL plugin** — bingo. OBS's virtual camera is a separate device from NDI Virtual Input's. Python script receives NDI, pushes frames to OBS Virtual Camera. No OBS process needed.

## What "cyndilib" is and why not "ndi-python"

Two Python NDI wrappers exist. ndi-python has stale PyPI wheels (Python 3.10 max). cyndilib is Cython-based with current ARM64 macOS wheels through Python 3.14. cyndilib also wraps NDI's FrameSync (time-base corrector), which we need for smooth frame delivery.

## Open items at handoff to Claude Code

- [ ] End-to-end test on actual Mac hardware with NDI Screen Capture
- [ ] Validate cyndilib FrameSync behavior with NDI Screen Capture's output timing
- [ ] Confirm pyvirtualcam + OBS 30 CMIOExtension works on target macOS version
- [ ] Determine if preview frame rate (every 3rd frame) is adequate for operator confidence
- [ ] Consider whether auto-reconnect should be an option (currently manual restart by design)
- [ ] Evaluate whether this should be packaged as a .app bundle for easier launching (currently script + run.sh)
