# Architecture

## Overview

NDI Virtual Camera Bridge is a single-process Python application with two threads: a tkinter GUI on the main thread and an NDI receiver/virtual camera frame pump on a background worker thread. Communication between threads is via shared state protected by locks, polled by the GUI at a fixed interval.

## System context

```
┌─────────────────────────────────────────────────────────────────────┐
│  macOS Host                                                         │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────────────────┐ │
│  │ NDI Camera   │───▶│ NDI Virtual  │───▶│ Keynote                │ │
│  │ (network)    │    │ Input        │    │ (composites titles     │ │
│  │              │    │ → "NDI Video"│    │  + camera feed)        │ │
│  └──────────────┘    └──────────────┘    └──────────┬─────────────┘ │
│                                                     │ fullscreen    │
│                                            ┌────────▼─────────┐    │
│                                            │ NDI Screen       │    │
│                                            │ Capture          │    │
│                                            │ (captures window │    │
│                                            │  as NDI source)  │    │
│                                            └────────┬─────────┘    │
│                                                     │ NDI          │
│                                          ┌──────────▼───────────┐  │
│                                          │ ndi_to_vcam.py       │  │
│                                          │ (this application)   │  │
│                                          │ → "OBS Virtual Cam"  │  │
│                                          └──────────┬───────────┘  │
│                                                     │ DAL plugin   │
│                                          ┌──────────▼───────────┐  │
│                                          │ Zoom Desktop Client  │  │
│                                          │ (selects OBS Virtual │  │
│                                          │  Camera as camera)   │  │
│                                          └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Component design

### NDIBridge (background thread)

Responsibilities:
- NDI source discovery via `cyndilib.Finder` (runs continuously)
- NDI frame reception via `cyndilib.Receiver` + `FrameSync`
- Color space conversion (RGBA → RGB)
- Frame delivery to OBS Virtual Camera via `pyvirtualcam`
- Downscaled preview generation for the GUI
- FPS calculation and statistics

The bridge runs a tight loop:
```
capture_video() → get_array() → reshape to RGBA → strip alpha → send(RGB) → sleep_until_next_frame()
```

Frame sync is handled by cyndilib's `FrameSync` wrapper, which implements NDI's time-base correction internally. This converts the "push" model of NDI (frames arrive whenever the sender sends them) into a "pull" model (we request the latest frame at our output cadence). This avoids the need for manual frame timing, jitter compensation, or drop/repeat logic.

### App (main thread)

Responsibilities:
- tkinter event loop
- Polls `NDIBridge.stats` and preview frame at 200ms intervals
- Source list refresh at 2000ms intervals
- User interaction (source selection, start/stop)

The GUI never touches NDI or virtual camera APIs directly. All AV work happens on the worker thread.

### Thread communication

```
Main thread (GUI)                    Worker thread (NDIBridge._run)
      │                                        │
      │──── start(source_name) ───────────────▶│
      │                                        │
      │    ┌─── polls at 200ms ───┐            │
      │    │  bridge.stats        │◀───────────│ (writes stats)
      │    │  bridge.get_preview()│◀───────────│ (writes preview frame)
      │    └──────────────────────┘            │
      │                                        │
      │──── stop() ──────────────────────────▶│ (sets _stop_event)
      │                                        │
```

Shared state:
- `BridgeStats` dataclass — written by worker, read by GUI. Individual field writes are atomic for Python primitive types.
- `_preview_frame` (numpy array) — protected by `_preview_lock`. Written by worker every 3rd frame. Read by GUI at poll interval.
- `_finder_sources` (list) — protected by `_lock`. Updated asynchronously by cyndilib's finder callback.
- `_stop_event` (threading.Event) — set by GUI, checked by worker loop.

### Virtual camera lifecycle

The OBS Virtual Camera DAL plugin is a CoreMediaIO plugin installed at:
```
/Library/CoreMediaIO/Plug-Ins/DAL/obs-mac-virtualcam.plugin
```

On macOS 14+, OBS 30 registers this as a Camera Extension (CMIOExtension). When `pyvirtualcam.Camera()` is instantiated, it connects to this plugin via Mach IPC and begins sending frames. When `.close()` is called (or the process exits), the virtual camera stops producing output and consuming apps see a black/frozen frame.

The plugin persists across reboots. OBS does not need to be running. The only requirement is that OBS was launched once and "Start Virtual Camera" was clicked to trigger the initial plugin registration.

### NDI discovery

`cyndilib.Finder` uses mDNS/Bonjour (on macOS) to discover NDI sources on the local network. Discovery is asynchronous — a callback fires when sources appear or disappear. The app exposes the current source list to the GUI for the dropdown.

Sources are identified by name strings in the format `"HOSTNAME (Source Name)"`, e.g. `"MACSTUDIO (NDI Screen Capture)"`.

## Error handling

| Condition | Behavior |
|---|---|
| Source not found within 10s | Error state, message shown, user can retry |
| Connection timeout (10s) | Error state, message shown |
| No frames received (10s) | Error state, message shown |
| Source disconnects mid-stream | Error state, message shown, user can restart |
| Resolution changes mid-stream | Virtual camera is recreated at new resolution |
| pyvirtualcam not installed | Exit with message at startup |
| OBS DAL plugin missing | Exception from pyvirtualcam on start, shown as error |

## Performance considerations

- Preview is downscaled to 384px wide and updated every 3rd frame to minimize CPU overhead on the main thread
- RGBA → RGB conversion uses numpy slicing (zero-copy view + one `.copy()` for contiguity)
- Frame timing is delegated to `pyvirtualcam.sleep_until_next_frame()` which adaptively tracks the target FPS
- cyndilib is Cython — NDI frame reception has minimal Python overhead
- Expected CPU usage: ~3-8% on Apple Silicon for 1080p30

## Dependencies

| Package | Role | Why this one |
|---|---|---|
| cyndilib | NDI SDK wrapper | Cython for performance, pre-built ARM64 macOS wheels, Python 3.10-3.14, actively maintained |
| pyvirtualcam | Virtual camera output | Writes to OBS DAL plugin, no OBS process needed, macOS 14+ compatible since v0.14 |
| numpy | Frame buffer | Required by both cyndilib and pyvirtualcam for frame data |
| Pillow | Preview generation | Image resize for the GUI thumbnail |
| tkinter | GUI | Ships with Python, no pip dependency, native macOS look |
