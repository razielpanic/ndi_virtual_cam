# Technical Decisions

A record of significant technical decisions, what was considered, and why each choice was made. Intended to help future maintainers understand the reasoning without having to re-derive it.

---

## D001: Virtual camera backend — OBS DAL plugin via pyvirtualcam

**Decision**: Use pyvirtualcam writing to the OBS Virtual Camera DAL plugin rather than building a custom DAL/CMIOExtension plugin.

**Context**: We need a second virtual camera device on macOS. NDI Virtual Input already occupies its own DAL plugin slot. The options were:
1. Build a custom CoreMediaIO DAL plugin or Camera Extension from scratch
2. Use the OBS Virtual Camera DAL plugin (already widely deployed) via pyvirtualcam
3. Use CamTwist or another legacy virtual camera utility

**Why OBS/pyvirtualcam**:
- OBS's DAL plugin is actively maintained, notarized, and compatible with macOS 14+
- pyvirtualcam provides a clean Python API to write frames to it without OBS running
- No custom kernel extensions, signing, or notarization hassle
- The plugin is a standard part of most production Mac setups already
- pyvirtualcam 0.14+ resolved macOS Sonoma compatibility issues

**Why not a custom plugin**:
- CoreMediaIO DAL plugins require careful signing and notarization
- Camera Extensions (CMIOExtension, macOS 14+) require an app bundle with specific entitlements
- Ongoing maintenance burden with every macOS update
- Not justified for a single-purpose internal tool

**Why not CamTwist**:
- Barely maintained, last meaningful update years ago
- No guarantee of compatibility with current/future macOS
- Unacceptable reliability risk for production use

**Trade-off**: Requires OBS to be installed on the client machine (but not running). This is a reasonable dependency for a production AV setup.

---

## D002: NDI SDK wrapper — cyndilib over ndi-python

**Decision**: Use cyndilib for NDI frame reception rather than ndi-python or direct NDI SDK bindings.

**Context**: Three Python NDI wrappers exist:
1. `ndi-python` (buresu) — pybind11 wrapper, PyPI wheels only up to Python 3.10, last updated 2022
2. `cyndilib` (nocarryr) — Cython wrapper, PyPI wheels for Python 3.10-3.14 including ARM64 macOS, v0.1.0 released 2025
3. `pySimpleNDI` — thin wrapper, limited platform support

**Why cyndilib**:
- Pre-built wheels for current Python versions and ARM64 macOS
- Cython implementation means minimal overhead for real-time frame handling
- Includes FrameSync wrapper (NDI's built-in time-base corrector) which handles frame timing, jitter correction, and push-to-pull conversion
- Proven in production (used by the scoresight project)
- Actively maintained with current releases

**Why not ndi-python**:
- PyPI wheels stale at Python 3.10 — would require building from source on modern Python
- Depends on having the NDI SDK installed for compilation
- Lower-level API without FrameSync convenience

---

## D003: GUI framework — tkinter

**Decision**: Use tkinter for the application GUI.

**Context**: Options considered:
1. tkinter (ships with Python)
2. PyQt / PySide (full-featured, heavy)
3. Dear ImGui (immediate mode, requires OpenGL context)
4. Web-based (Flask/Electron — overkill)
5. SwiftUI with Python bridge (native but complex)

**Why tkinter**:
- Zero additional dependencies — ships with Python on macOS
- Adequate for the UI requirements (dropdown, button, preview, status labels)
- Keeps the dependency footprint minimal for a client deployment
- Operators don't need a beautiful UI — they need a readable, reliable one

**Why not PyQt/PySide**:
- Adds a ~50MB dependency
- Licensing complexity (GPL/LGPL/commercial)
- Overkill for a source picker + preview + status display

**Trade-off**: tkinter looks dated compared to native macOS apps. The dark theme and careful layout mitigate this, but it will never feel truly native. Acceptable for a production utility that spends most of its time minimized.

---

## D004: Threading model — single worker thread

**Decision**: Run NDI reception and virtual camera output on a single background thread, with the GUI on the main thread polling for updates.

**Context**: Options:
1. Single worker thread (chosen)
2. Separate threads for NDI receive and vcam send with a queue between them
3. asyncio-based
4. multiprocessing

**Why single worker**:
- The frame pump is a tight sequential loop: receive → convert → send
- Adding a queue between receive and send adds latency and complexity for no benefit
- cyndilib's FrameSync handles all timing internally
- Keeps the threading model simple and auditable

**Why not asyncio**:
- NDI reception is blocking (cyndilib doesn't expose an async API)
- pyvirtualcam is blocking
- Would need `run_in_executor` for everything, defeating the purpose

**Why not multiprocessing**:
- Frame data would need to be serialized across process boundaries
- At 1080p30 RGB, that's ~177MB/s of frame data
- Shared memory is possible but adds significant complexity

---

## D005: Preview strategy — downscaled, every 3rd frame

**Decision**: Generate a 384px-wide preview thumbnail every 3rd frame using Pillow, and deliver it to the GUI via a locked numpy array.

**Why not every frame**:
- PIL.Image.resize with LANCZOS at 1080p is ~2ms per frame
- At 30fps that's 60ms/s of CPU just for preview — wasteful
- Every 3rd frame gives ~10fps preview which is visually smooth enough for monitoring

**Why not OpenCV**:
- Would add another large dependency (opencv-python is ~50MB)
- Pillow is already needed for ImageTk (tkinter image display)
- For a simple resize operation, Pillow is sufficient

**Why not skip the preview entirely**:
- Operators need visual confirmation that video is flowing and correct
- "Trust but verify" — the stats alone don't tell you if the right content is going out

---

## D006: Frame format — RGBA from NDI, strip to RGB for vcam

**Decision**: Request RGBX_RGBA from cyndilib, strip the alpha channel to produce RGB for pyvirtualcam.

**Context**: NDI internally uses various formats. cyndilib can request conversion on receive.

**Why RGBX_RGBA**:
- cyndilib's `RecvColorFormat.RGBX_RGBA` is the most portable option
- Produces a consistent 4-channel numpy array regardless of source format
- Stripping alpha is a single numpy slice operation: `rgba[:, :, :3]`

**Why not request RGB directly**:
- cyndilib doesn't offer a 3-channel RGB receive format
- NDI's native formats are UYVY/NV12/BGRA — all require conversion anyway
- Letting NDI handle the conversion to RGBA is more efficient than doing it in Python

---

## D007: Resolution handling — match input, recreate vcam on change

**Decision**: Create the virtual camera at the incoming NDI resolution. If the resolution changes, close and recreate the virtual camera.

**Why not fixed output resolution**:
- Scaling in Python (even with Pillow/numpy) adds latency and CPU cost
- The consuming app (Zoom) handles resolution adaptation already
- Preserves maximum quality from the NDI source

**Why recreate on change**:
- pyvirtualcam.Camera is initialized with fixed dimensions
- The API doesn't support runtime resolution changes
- Recreation is fast (<100ms) and transparent to consumers — they see a brief freeze then resume

**When does resolution change**:
- Keynote switches between slide aspect ratios
- NDI Screen Capture switches between displays
- In practice, this should be rare during a live event

---

## D008: Error recovery — manual restart rather than auto-reconnect

**Decision**: When the NDI source disconnects, show an error and require the operator to click Start again. Do not auto-reconnect.

**Why not auto-reconnect**:
- If the source disappeared, there's usually an upstream problem that needs human attention
- Auto-reconnect can mask issues — the operator should know something went wrong
- Auto-reconnect to the wrong source after a brief network glitch could send unintended content to Zoom
- Manual restart is a single click — fast enough for production recovery

**Future consideration**: Auto-reconnect could be added as an opt-in toggle if operational experience shows it's needed.

---

## D009: Deployment — script, not packaged app

**Decision**: Deploy as a Python script run from the terminal, not as a packaged .app bundle.

**Why not py2app / PyInstaller**:
- Packaging adds build complexity and platform-specific debugging
- The OBS DAL plugin and NDI runtime need to be installed separately regardless
- Python is already present on production Macs (or trivially installed via Homebrew)
- A script is easier to update, inspect, and debug on-site

**Trade-off**: Requires a terminal to launch. Could wrap in a shell script or Automator action if double-click launch is needed.

---

## D010: Why not just use OBS

**Decision**: Build this app rather than running OBS with a single Window Capture → Virtual Camera configuration.

**Why not OBS**:
- OBS is a full production suite with hundreds of options an operator could accidentally change
- OBS's UI invites tinkering — scenes, sources, filters, transitions are all one click away
- A client installation needs the minimum possible surface area for mistakes
- OBS consumes significantly more memory and CPU than this lightweight script
- This app has exactly one job and one button. OBS has hundreds.

**When OBS would be better**:
- If the operator needs to composite, add overlays, or switch between sources at the Zoom output stage
- If the pipeline becomes more complex than a single NDI source → single virtual camera

---

## D011: Dependency management — self-bootstrapping venv in run.sh

**Decision**: Have `run.sh` automatically create a virtual environment and install dependencies rather than requiring manual `pip install`.

**Context**: UAT revealed that the "install dependencies manually via pip" approach was unacceptable for production deployment. The target operator should not need to interact with pip or a terminal beyond running `./run.sh`.

**What run.sh does**:
1. Checks for Python 3.10+ availability
2. Creates `.venv/` via `python3 -m venv` if it doesn't exist
3. Installs dependencies from `requirements.txt` into the venv (skipped when a marker file `.venv/.deps-installed` is newer than `requirements.txt`)
4. Verifies critical imports succeed
5. Launches the app using the venv's Python

**Why a venv and not system pip**:
- System pip installs can conflict with other Python tools on the machine
- A venv is self-contained — delete `.venv/` to reset, no side effects
- The venv pattern is standard Python practice and well-understood

**Why not conda/pipx/uv**:
- Each adds another tool the operator would need to install
- `python3 -m venv` is built into Python's standard library — zero additional dependencies
- The bootstrapping pattern is simple enough that exotic tooling adds no value

**Why a marker file instead of always running pip**:
- `pip install -r requirements.txt` takes 2-5 seconds even when everything is up-to-date
- The marker file (`touch .venv/.deps-installed`) makes subsequent launches instant
- The marker is invalidated when `requirements.txt` is modified, triggering a reinstall

**Trade-off**: First launch takes 10-30 seconds for venv creation and package installation. This is acceptable since it only happens once per deployment (or when dependencies change).

---

## D012: App bundle wrapper — shell-based .app for Login Items

**Decision**: Ship a lightweight macOS `.app` bundle (`NDI Virtual Cam.app`) that wraps `run.sh`, enabling double-click launch and Login Items integration.

**Context**: The production pipeline requires multiple apps to auto-start at login (NDI Screen Capture, NDI Virtual Input, Keynote, Zoom). This app needs to fit the same pattern — added to System Settings > Login Items alongside the others.

**How it works**:
- `NDI Virtual Cam.app/Contents/MacOS/launcher` is a shell script that resolves the project root relative to its own location and runs `run.sh`
- `Info.plist` declares the bundle metadata (name, identifier, minimum macOS version)
- The .app lives in the project directory. Copy to `/Applications` or add directly to Login Items.

**Why a shell-based .app and not py2app/PyInstaller**:
- Zero build step — the .app is just directories and text files
- The launcher script is visible and debuggable on-site (open in any text editor)
- run.sh handles all the real work (venv, deps, launch) — the .app is just a thin entry point
- No code signing or notarization needed for a local deployment

**Why not Automator**:
- Automator .app workflows are opaque binary plists — harder to inspect and version control
- A hand-crafted .app bundle is simpler, smaller, and fully transparent

**Trade-off**: The .app is not signed or notarized. On first launch, macOS Gatekeeper may block it. The operator right-clicks > Open > Open to bypass. This is a one-time step per machine.
