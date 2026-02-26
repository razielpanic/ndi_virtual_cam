# Setup

Complete installation and configuration guide for the NDI Virtual Camera Bridge.

## Prerequisites

### Hardware
- Mac with Apple Silicon (M1 or later) or Intel — ARM64 wheels are provided, Intel works too
- Network connection on the same subnet as NDI sources (wired Ethernet strongly recommended for reliability)

### Software

#### macOS
- macOS 14 (Sonoma), macOS 15 (Sequoia), or macOS 26 (Tahoe)
- macOS 26 requires pyvirtualcam 0.15.0+ (uses CMIOExtension for virtual camera)
- Earlier versions may work but are untested

#### Python 3.10+
Verify with:
```bash
python3 --version
```

If you need to install or manage Python versions, Homebrew is the simplest path:
```bash
brew install python@3.12 python-tk@3.12
```

The `python-tk` package is required for the GUI (tkinter is not included in Homebrew Python by default).

#### OBS Studio 30+
Download from https://obsproject.com

OBS is required **only for its virtual camera DAL plugin**. OBS does not need to be running when this app is in use.

#### NDI Tools
Download from https://ndi.tv/tools/

You need:
- **NDI Screen Capture** — captures a display or window and publishes it as an NDI source
- **NDI Virtual Input** — used in the other leg of the pipeline (NDI camera → Keynote)
- **NDI Monitor** (optional) — useful for verifying NDI sources during setup

### Pre-flight Check

Before proceeding with installation, verify these prerequisites:

1. **OBS Virtual Camera registered:**
   ```bash
   # macOS 14+ (CMIOExtension):
   systemextensionsctl list 2>&1 | grep -i obs
   # Legacy (DAL plugin):
   ls /Library/CoreMediaIO/Plug-Ins/DAL/ 2>/dev/null
   ```
   If neither shows OBS, install OBS Studio 30+ and run the virtual camera once (see Installation step 1).

2. **NDI runtime available:**
   ```bash
   ls /Library/NDI\ SDK\ for\ Apple/ 2>/dev/null || ls /usr/local/lib/libndi* 2>/dev/null
   ```
   If not found, install NDI Tools from https://ndi.tv/tools/

3. **Python 3.10+:**
   ```bash
   python3 --version
   ```

## Installation

### 1. Register the OBS Virtual Camera (one-time)

This step installs the DAL plugin that macOS needs to see "OBS Virtual Camera" as a camera device.

1. Launch OBS Studio
2. Click **Start Virtual Camera** (bottom right of the OBS window)
3. Click **Stop Virtual Camera**
4. Quit OBS

Verify the plugin is registered:
```bash
ls /Library/CoreMediaIO/Plug-Ins/DAL/
# Should show: obs-mac-virtualcam.plugin
```

On macOS 14+, OBS uses a Camera Extension (CMIOExtension) rather than the legacy DAL plugin. Both are handled by the same "Start Virtual Camera" step above.

### 2. Launch the application

**Double-click:** Open `NDI Virtual Cam.app` from the project directory (or copy it to `/Applications` first).

**Terminal:** Or run from the command line:
```bash
cd /path/to/ndi_virtual_cam
./run.sh
```

On first run, the launcher automatically:
- Creates an isolated Python environment (`.venv/`)
- Installs all required dependencies from `requirements.txt`

This installs:
- `cyndilib` — NDI SDK wrapper (pre-built wheels, no compilation needed)
- `pyvirtualcam` — virtual camera output
- `numpy` — frame data handling
- `Pillow` — preview image scaling

### 3. Verify (automatic)

The launcher verifies all dependencies before starting the app. No manual verification is needed.

To verify manually (optional):
```bash
.venv/bin/python3 -c "import cyndilib; print('cyndilib OK')"
.venv/bin/python3 -c "import pyvirtualcam; print('pyvirtualcam OK')"
```

### 4. Test the virtual camera independently

```bash
python3 -c "
import pyvirtualcam
import numpy as np
with pyvirtualcam.Camera(width=1280, height=720, fps=30) as cam:
    print(f'Virtual camera started: {cam.device}')
    for i in range(90):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[:, :, 1] = 128  # green tint
        cam.send(frame)
        cam.sleep_until_next_frame()
    print('Done — check if OBS Virtual Camera appeared in Zoom/FaceTime')
"
```

Open Zoom (or Photo Booth, or FaceTime) and check the camera dropdown while this runs. You should see "OBS Virtual Camera" producing a green frame for 3 seconds.

## Network configuration

NDI uses mDNS (Bonjour on macOS) for source discovery. For sources to be visible:

- All NDI sources and receivers must be on the **same subnet**
- If using VLANs, mDNS traffic must be allowed to cross, or use NDI Access Manager for manual source configuration
- macOS firewall: if enabled, allow incoming connections for Python when prompted on first run
- For same-machine use (all sources and this app on one Mac), no network configuration is needed — localhost NDI works out of the box

## Confirming the full pipeline

Before the event, verify end-to-end:

1. Start the NDI camera source
2. Start NDI Virtual Input → select the camera → confirm Keynote sees "NDI Video" as a camera
3. Open Keynote presentation with the camera feed + titles
4. Start NDI Screen Capture → select the Keynote window/display
5. Start `./run.sh` → select the NDI Screen Capture source → click Start
6. Open Zoom → select "OBS Virtual Camera" as the camera
7. Confirm the Keynote composite (titles + camera) appears in Zoom

## Auto-start at login

To have NDI Virtual Cam launch automatically when the Mac starts (alongside NDI Screen Capture, Zoom, etc.):

1. Open **System Settings > General > Login Items**
2. Click **+** under "Open at Login"
3. Navigate to the project directory and select `NDI Virtual Cam.app`
4. The app will now launch automatically at login

On first launch after a fresh macOS login, the Gatekeeper dialog may appear. Right-click the app > Open > Open to allow it. This is a one-time step.

## Uninstallation

Remove the Python environment:
```bash
rm -rf /path/to/ndi_virtual_cam/.venv
```

The OBS Virtual Camera DAL plugin can be removed by uninstalling OBS, or manually:
```bash
sudo rm -rf "/Library/CoreMediaIO/Plug-Ins/DAL/obs-mac-virtualcam.plugin"
```
