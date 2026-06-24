# NDI Virtual Cam

> **⚠️ SUPERSEDED for the Temple Isaiah deployment (2026-06).** TIPD2 runs **OBS.app directly** for the output virtual camera (OBS screen-captures Keynote → OBS Virtual Camera → Zoom), so this standalone util is **not in the live TI path**. It remains a valid general-purpose tool. As-built reference: TIPD2 `.planning/AS_BUILT_PIPELINE.md`.

A lightweight macOS utility that receives an NDI video source and outputs it as a virtual webcam via OBS Virtual Camera. Built for production AV installations where NDI Virtual Input is already in use and a second, independent virtual camera path is needed.

## Why this exists

NDI Virtual Input registers one virtual camera device and handles one source at a time. If your workflow already uses it, there's no way to simultaneously route a second NDI source to a different virtual camera without bringing in OBS or another full production suite.

This app fills that gap. It uses the **OBS Virtual Camera** plugin (a separate device from NDI Virtual Input) to create an independent, concurrent virtual camera output from any NDI source on your network. OBS does not need to be running — just installed.

```
NDI Camera ──→ NDI Virtual Input ──→ "NDI Video" ──→ Keynote (camera input)
                                                          │
                                                     Keynote composites
                                                     titles + live camera
                                                          │
NDI Screen Capture ←── captures Keynote window ───────────┘
         │
   NDI Virtual Cam (this app)
         │
   "OBS Virtual Camera" ──→ Zoom (camera input)
```

Two virtual cameras. Two independent pipelines. Same machine. No conflict.

## Features

- **One-click source selection** — pick any NDI source from the menu bar and streaming starts immediately
- **Live preview** — full-window video preview with resolution and FPS telemetry overlaid on the image
- **Auto-reconnect** — if an NDI source drops and comes back, the bridge reconnects automatically
- **Remembers your setup** — window position, size, and last-used source persist across launches
- **macOS app bundle** — double-click `NDI Virtual Cam.app` to launch, or add to Login Items for auto-start
- **Self-bootstrapping** — first run creates a Python virtual environment and installs all dependencies automatically
- **OBS install check** — shows a native dialog with download link if OBS isn't installed
- **Graceful error handling** — action-oriented error messages tell the operator what to do, not what failed technically
- **Diagnostic logging** — session history written to `~/Library/Logs/ndi_to_vcam.log` for post-event diagnosis
- **Clean shutdown** — signal handlers and atexit hooks ensure reliable teardown with no orphaned processes

## Requirements

- macOS 14 (Sonoma) or later
- Python 3.10+ with tkinter
- OBS Studio 30+ (installed, not running)
- NDI Tools (NDI Screen Capture and/or other NDI sources on the network)

## Installation

### 1. Install prerequisites

**Python** (via Homebrew):
```bash
brew install python@3.12 python-tk@3.12
```

**OBS Studio**: download from [obsproject.com](https://obsproject.com). Launch OBS once and click **Start Virtual Camera** → **Stop Virtual Camera** to register the camera device, then quit OBS.

**NDI Tools**: download from [ndi.tv/tools](https://ndi.tv/tools).

### 2. Clone and run

```bash
git clone https://github.com/razielpanic/ndi_virtual_cam.git
cd ndi_virtual_cam
./run.sh
```

On first run, `run.sh` automatically creates a `.venv/`, installs dependencies, verifies imports, and launches the app. No manual `pip install` needed.

### Standalone deployment

The `.app` bundle is fully self-contained. Copy **NDI Virtual Cam.app** anywhere (Desktop, Applications, another machine) and double-click. First launch creates a virtual environment in `~/Library/Application Support/NDI Virtual Cam/` and installs dependencies automatically. If prerequisites are missing, a native dialog tells the operator exactly what to install.

### Auto-start at login (optional)

1. Open **System Settings → General → Login Items**
2. Click **+** and select `NDI Virtual Cam.app`
3. The app launches automatically on login alongside your other AV tools

## Usage

1. Launch the app
2. Open the **Sources** menu in the menu bar
3. Click an NDI source name — streaming starts immediately
4. Open Zoom (or any app) and select **OBS Virtual Camera** as the camera input

The window title shows the active source. Close the window to stop.

## Project structure

```
src/ndi_to_vcam.py            — the entire application (single file)
NDI Virtual Cam.app/          — self-contained macOS app bundle
  Contents/Resources/run.sh   — bundled launcher (venv in Application Support)
  Contents/Resources/src/     — symlinks to repo source (resolved on copy)
launcher.c                    — source for the native Mach-O launcher stub
run.sh                        — development launcher (venv in project dir)
requirements.txt              — Python dependencies
docs/                         — architecture, setup, operations, decisions
```

## Network notes

NDI uses mDNS (Bonjour) for source discovery. All NDI devices must be on the same subnet. If using VLANs, allow mDNS traffic or configure sources manually via NDI Access Manager. For same-machine use, no network configuration is needed.

## Tech stack

- **[cyndilib](https://github.com/nocarryr/cyndilib)** — Cython NDI SDK wrapper for frame reception
- **[pyvirtualcam](https://github.com/letmaik/pyvirtualcam)** — writes frames to OBS Virtual Camera
- **tkinter** — GUI (ships with Python)
- **Pillow** — preview thumbnail generation
- **numpy** — frame buffer intermediary

## License

MIT — see [LICENSE](LICENSE).

---

*NDI is a registered trademark of Vizrt NDI AB.*
