#!/usr/bin/env python3
"""
NDI → Virtual Camera Bridge
Receives an NDI source and outputs it as a virtual camera (via OBS DAL plugin).
Designed for production use in AV installations.

Requirements:
    OBS Studio 30+ must be installed (for the virtual camera DAL plugin).
    OBS does NOT need to be running.
    Python dependencies are managed automatically by run.sh.

Usage:
    ./run.sh
"""

import atexit
import ctypes
import ctypes.util
import json
import logging
import os
import signal
import sys
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np

import pyvirtualcam
from cyndilib.finder import Finder
from cyndilib.receiver import Receiver
from cyndilib.video_frame import VideoFrameSync
from cyndilib.wrapper.ndi_recv import RecvColorFormat, RecvBandwidth
from PIL import Image, ImageTk


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    """Configure file logging to ~/Library/Logs/ndi_to_vcam.log."""
    log = logging.getLogger("ndi_to_vcam")
    log.setLevel(logging.INFO)
    try:
        log_dir = os.path.expanduser("~/Library/Logs")
        os.makedirs(log_dir, exist_ok=True)
        handler = logging.FileHandler(os.path.join(log_dir, "ndi_to_vcam.log"))
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        ))
        log.addHandler(handler)
    except OSError:
        log.addHandler(logging.NullHandler())
    return log

logger = _setup_logging()

# Module-level shutdown event for signal handlers
_shutdown_event = threading.Event()

# Preferences file path
_PREFS_PATH = os.path.expanduser("~/.config/ndi_virtual_cam/prefs.json")


def _load_prefs() -> dict:
    """Load user preferences from disk. Returns empty dict on any failure."""
    try:
        with open(_PREFS_PATH, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {}


def _save_prefs(prefs: dict):
    """Persist user preferences to disk. Silently ignores failures."""
    try:
        os.makedirs(os.path.dirname(_PREFS_PATH), exist_ok=True)
        with open(_PREFS_PATH, "w") as f:
            json.dump(prefs, f, indent=2)
    except OSError:
        logger.warning("Could not save preferences to %s", _PREFS_PATH)


def _set_macos_process_name(name: str):
    """Set the macOS process name so the menu bar shows our app name.

    Must be called BEFORE tk.Tk() is created — tkinter reads the process
    name at window creation time. Uses ctypes to call into the Objective-C
    runtime (Foundation framework). Silently does nothing on non-macOS or
    if the runtime calls fail.
    """
    if sys.platform != "darwin":
        return
    try:
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))

        # Configure objc_msgSend for id-returning calls
        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]

        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        # Create NSString from the name
        NSString = objc.objc_getClass(b"NSString")
        sel_string = objc.sel_registerName(b"stringWithUTF8String:")
        # Need a variant of objc_msgSend that accepts a c_char_p argument
        msgSend_str = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p
        )(("objc_msgSend", objc))
        ns_name = msgSend_str(NSString, sel_string, name.encode("utf-8"))

        # Get [NSProcessInfo processInfo]
        NSProcessInfo = objc.objc_getClass(b"NSProcessInfo")
        sel_processInfo = objc.sel_registerName(b"processInfo")
        process_info = objc.objc_msgSend(NSProcessInfo, sel_processInfo)

        # Call [processInfo setProcessName:ns_name]
        sel_setName = objc.sel_registerName(b"setProcessName:")
        msgSend_set = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )(("objc_msgSend", objc))
        msgSend_set(process_info, sel_setName, ns_name)
    except Exception:
        pass  # Non-critical — fall back to default "Python" menu name


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class BridgeState(Enum):
    IDLE = auto()
    CONNECTING = auto()
    RUNNING = auto()
    ERROR = auto()


@dataclass
class BridgeStats:
    state: BridgeState = BridgeState.IDLE
    source_name: str = ""
    resolution: str = "—"
    input_fps: float = 0.0
    output_fps: float = 0.0
    frames_sent: int = 0
    error_message: str = ""
    status_detail: str = ""
    low_fps_since: float = 0.0
    last_frame_time: float = 0.0


# ---------------------------------------------------------------------------
# NDI → Virtual Camera bridge (runs on a background thread)
# ---------------------------------------------------------------------------

class NDIBridge:
    """Receives NDI frames and pushes them to a virtual camera."""

    # Output geometry — matches standard HD webcam expectations
    OUTPUT_WIDTH = 1920
    OUTPUT_HEIGHT = 1080
    OUTPUT_FPS = 30
    FPS_WARN_THRESHOLD = 25       # FPS below this triggers color change
    FPS_WARN_SUSTAINED_SECS = 5   # seconds below threshold before error bar

    def __init__(self):
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.stats = BridgeStats()

        # NDI finder (always running for source discovery)
        self._finder = Finder()
        self._finder_sources: list[str] = []
        self._finder.set_change_callback(self._on_finder_change)
        self._finder.open()

        # Preview frame buffer (downscaled RGB for the UI)
        self._preview_lock = threading.Lock()
        self._preview_frame: Optional[np.ndarray] = None

        # FPS tracking
        self._fps_timestamps: deque = deque(maxlen=60)

    # -- Source discovery ---------------------------------------------------

    def _on_finder_change(self):
        """Called by cyndilib when NDI sources change on the network."""
        try:
            names = list(self._finder.get_source_names())
            with self._lock:
                self._finder_sources = names
        except Exception:
            pass

    def get_available_sources(self) -> list[str]:
        with self._lock:
            return list(self._finder_sources)

    # -- Bridge control -----------------------------------------------------

    def start(self, source_name: str):
        logger.info("Starting bridge to '%s'", source_name)
        if self._thread and self._thread.is_alive():
            self.stop()
        self._stop_event.clear()
        self.stats = BridgeStats(
            state=BridgeState.CONNECTING,
            source_name=source_name,
        )
        self._thread = threading.Thread(
            target=self._run, args=(source_name,), daemon=True
        )
        self._thread.start()

    def stop(self):
        logger.info("Stopping bridge")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        self.stats.state = BridgeState.IDLE
        self.stats.error_message = ""
        self.stats.low_fps_since = 0.0
        with self._preview_lock:
            self._preview_frame = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_preview_frame(self) -> Optional[np.ndarray]:
        with self._preview_lock:
            return self._preview_frame

    # -- Main bridge loop ---------------------------------------------------

    def _run(self, source_name: str):
        receiver = None
        vcam = None
        _devnull_fd = None
        _real_stderr_fd = None
        try:
            # Set up NDI receiver
            receiver = Receiver(
                color_format=RecvColorFormat.RGBX_RGBA,
                bandwidth=RecvBandwidth.highest,
            )
            video_frame = VideoFrameSync()
            receiver.frame_sync.set_video_frame(video_frame)

            # Find and connect to the named source
            self.stats.status_detail = "Searching for source..."
            source = None
            deadline = time.monotonic() + 5.0
            while not self._stop_event.is_set() and time.monotonic() < deadline:
                try:
                    with self._finder.notify:
                        source = self._finder.get_source(source_name)
                    if source is not None:
                        break
                except (KeyError, ValueError):
                    pass
                time.sleep(0.25)

            if source is None:
                logger.error("Source '%s' not found within timeout", source_name)
                self.stats.state = BridgeState.ERROR
                self.stats.error_message = f"Could not find '{source_name}' on the network. Check that the source computer is on and NDI is running, then try again."
                return

            logger.info("Found source '%s'", source_name)
            receiver.set_source(source)
            self.stats.status_detail = "Connecting..."

            # Wait for connection
            deadline = time.monotonic() + 5.0
            while not self._stop_event.is_set() and time.monotonic() < deadline:
                if receiver.is_connected():
                    break
                time.sleep(0.1)

            if not receiver.is_connected():
                logger.error("Connection to '%s' timed out", source_name)
                self.stats.state = BridgeState.ERROR
                self.stats.error_message = "Could not connect to the NDI source. Check the network connection and that the source is still available, then try again."
                return

            logger.info("Connected to '%s'", source_name)

            # Wait for first frame to determine resolution
            self.stats.status_detail = "Waiting for first frame..."
            first_frame = False
            deadline = time.monotonic() + 5.0
            while not self._stop_event.is_set() and time.monotonic() < deadline:
                receiver.frame_sync.capture_video()
                if video_frame.xres > 0 and video_frame.yres > 0:
                    first_frame = True
                    break
                time.sleep(0.033)

            if not first_frame:
                logger.error("No video frames received from '%s'", source_name)
                self.stats.state = BridgeState.ERROR
                self.stats.error_message = "Connected but not receiving video. Check that the source is sending video output, then try again."
                return

            logger.info("Receiving video: %dx%d", video_frame.xres, video_frame.yres)

            # Suppress native-layer stderr spam (e.g. pyvirtualcam's
            # "Pixel buffer size mismatch" printed every frame for some
            # resolutions on macOS CMIOExtension backend).
            _devnull_fd = os.open(os.devnull, os.O_WRONLY)
            _real_stderr_fd = os.dup(2)
            _stderr_suppressed = False
            _mismatch_warned = False

            def _send_frame(cam, frame):
                """Send frame, suppressing repetitive native stderr warnings."""
                nonlocal _stderr_suppressed, _mismatch_warned
                if not _stderr_suppressed:
                    # First call: capture stderr to detect native warnings
                    r_fd, w_fd = os.pipe()
                    os.set_blocking(r_fd, False)
                    os.dup2(w_fd, 2)
                    cam.send(frame)
                    os.dup2(_real_stderr_fd, 2)
                    os.close(w_fd)
                    captured = b""
                    try:
                        captured = os.read(r_fd, 4096)
                    except (OSError, BlockingIOError):
                        pass
                    os.close(r_fd)
                    if b"ixel buffer size mismatch" in captured:
                        if not _mismatch_warned:
                            logger.warning(
                                "Pixel buffer size mismatch from virtual camera "
                                "backend (resolution %dx%d) — suppressing further "
                                "warnings", cam.width, cam.height,
                            )
                            _mismatch_warned = True
                        _stderr_suppressed = True
                    elif captured:
                        # Pass through any other stderr content
                        os.write(_real_stderr_fd, captured)
                else:
                    # Suppress stderr for subsequent frames
                    os.dup2(_devnull_fd, 2)
                    cam.send(frame)
                    os.dup2(_real_stderr_fd, 2)

            # Open virtual camera at the incoming resolution
            out_w = video_frame.xres
            out_h = video_frame.yres
            vcam = pyvirtualcam.Camera(
                width=out_w,
                height=out_h,
                fps=self.OUTPUT_FPS,
                fmt=pyvirtualcam.PixelFormat.RGB,
                print_fps=False,
            )

            self.stats.state = BridgeState.RUNNING
            self.stats.resolution = f"{out_w}×{out_h}"
            self.stats.status_detail = ""
            self._fps_timestamps.clear()

            # --- Frame pump ---
            while not self._stop_event.is_set():
                if not receiver.is_connected():
                    logger.error("NDI source '%s' disconnected during streaming", source_name)
                    self.stats.state = BridgeState.ERROR
                    self.stats.error_message = "The NDI source stopped sending. Check the source application and try again."
                    break

                receiver.frame_sync.capture_video()

                if video_frame.xres == 0 or video_frame.yres == 0:
                    vcam.sleep_until_next_frame()
                    continue

                # Get the RGBA frame as a numpy array
                try:
                    raw = video_frame.get_array()
                    h, w = video_frame.yres, video_frame.xres
                    rgba = raw.reshape(h, w, 4)
                    rgb = rgba[:, :, :3].copy()
                except Exception:
                    vcam.sleep_until_next_frame()
                    continue

                # Handle resolution changes
                if w != out_w or h != out_h:
                    logger.info("Resolution changed to %dx%d", w, h)
                    out_w, out_h = w, h
                    self.stats.resolution = f"{out_w}×{out_h}"
                    # Recreate vcam at new resolution
                    try:
                        vcam.close()
                        vcam = pyvirtualcam.Camera(
                            width=out_w,
                            height=out_h,
                            fps=self.OUTPUT_FPS,
                            fmt=pyvirtualcam.PixelFormat.RGB,
                            print_fps=False,
                        )
                        _stderr_suppressed = False  # re-check for new resolution
                    except Exception:
                        logger.error("Failed to recreate virtual camera at %dx%d", out_w, out_h, exc_info=True)
                        self.stats.state = BridgeState.ERROR
                        self.stats.error_message = "Could not adjust to the new resolution. Stop and restart the bridge."
                        break

                # Send to virtual camera
                _send_frame(vcam, rgb)

                # Update stats
                now = time.monotonic()
                self._fps_timestamps.append(now)
                self.stats.frames_sent += 1
                self.stats.last_frame_time = now
                if len(self._fps_timestamps) > 1:
                    elapsed = self._fps_timestamps[-1] - self._fps_timestamps[0]
                    if elapsed > 0:
                        self.stats.output_fps = (len(self._fps_timestamps) - 1) / elapsed

                # Track sustained low FPS
                if self.stats.output_fps < self.FPS_WARN_THRESHOLD and len(self._fps_timestamps) > 10:
                    if self.stats.low_fps_since == 0.0:
                        self.stats.low_fps_since = now
                else:
                    self.stats.low_fps_since = 0.0

                # Build a downscaled preview (~every 3rd frame to save CPU)
                if self.stats.frames_sent % 3 == 0:
                    try:
                        preview = Image.fromarray(rgb)
                        # Scale to fit 384px wide
                        pw = 384
                        ph = int(h * (pw / w))
                        preview = preview.resize((pw, ph), Image.LANCZOS)
                        with self._preview_lock:
                            self._preview_frame = np.array(preview)
                    except Exception:
                        pass

                vcam.sleep_until_next_frame()

        except Exception:
            logger.error("Unexpected error in bridge loop", exc_info=True)
            self.stats.state = BridgeState.ERROR
            self.stats.error_message = "Something went wrong. Stop and restart the bridge. If the problem continues, restart this application."
        finally:
            logger.info("Bridge loop ended — cleaning up")
            # Restore stderr and close helper fds
            try:
                if _real_stderr_fd is not None:
                    os.dup2(_real_stderr_fd, 2)
                    os.close(_real_stderr_fd)
                if _devnull_fd is not None:
                    os.close(_devnull_fd)
            except Exception:
                pass
            if vcam is not None:
                try:
                    vcam.close()
                except Exception:
                    logger.warning("Error closing virtual camera", exc_info=True)
            if receiver is not None:
                try:
                    if receiver.is_connected():
                        receiver.disconnect()
                except Exception:
                    logger.warning("Error disconnecting receiver", exc_info=True)

    def shutdown(self):
        """Full teardown."""
        logger.info("Full shutdown — closing finder")
        self.stop()
        try:
            self._finder.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

# Color palette — muted, professional, high-contrast status colors
COLORS = {
    "bg": "#1a1a1e",
    "surface": "#26262c",
    "surface_alt": "#2e2e36",
    "border": "#3a3a44",
    "text": "#e0e0e6",
    "text_dim": "#888894",
    "accent": "#5b8def",
    "running": "#3ddb85",
    "error": "#ef5b5b",
    "idle": "#888894",
    "warning": "#e8a838",
    "preview_bg": "#111114",
    "overlay_fg": "#ffffff",
    "overlay_shadow": "#000000",
}

FONT_FAMILY = "SF Pro Display, Helvetica Neue, Helvetica, Arial"
FONT_MONO = "SF Mono, Menlo, Monaco, Consolas"
FONT_OVERLAY = (FONT_MONO, 12)


class App:
    POLL_INTERVAL = 200  # ms — UI refresh rate
    SOURCE_REFRESH = 2000  # ms — NDI source list refresh

    def __init__(self):
        self.bridge = NDIBridge()
        self._closing = False
        self._geometry_save_timer = None
        self._last_error_message: Optional[str] = None
        self.root = tk.Tk()
        self.root.title("NDI Virtual Cam")
        self.root.configure(bg=COLORS["bg"])
        self.root.resizable(True, True)
        self.root.geometry("640x360")
        self.root.minsize(480, 270)
        self.root.option_add('*tearOff', False)

        # Load saved preferences (window geometry, last source)
        self._prefs = _load_prefs()
        saved_geometry = self._prefs.get("geometry")
        if isinstance(saved_geometry, str) and saved_geometry:
            try:
                self.root.geometry(saved_geometry)
            except tk.TclError:
                pass  # Invalid geometry string — use default
        self._auto_connect_source: Optional[str] = self._prefs.get("last_source")

        self._build_ui()
        self._schedule_polls()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(500, self._poll_signal)
        # Save geometry on window move or resize (debounced)
        self.root.bind("<Configure>", self._on_window_configure)

    # -- UI construction ----------------------------------------------------

    def _build_ui(self):
        # ---- Menu bar with Sources cascade ----
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        self.sources_menu = tk.Menu(menubar)
        menubar.add_cascade(label="Sources", menu=self.sources_menu)
        self.sources_menu.add_command(label="Searching for sources...", state="disabled")

        # ---- Preview canvas (fills entire window) ----
        self.preview_canvas = tk.Canvas(
            self.root, bg=COLORS["preview_bg"], highlightthickness=0,
        )
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        self._preview_image_ref = None
        self._canvas_width = 640
        self._canvas_height = 360

        self.preview_canvas.bind("<Configure>", self._on_canvas_configure)

        # ---- Overlay text items (shadow + foreground pairs) ----
        self._overlay_ids = {}
        w = self._canvas_width
        h = self._canvas_height

        # Status — top-left
        self._overlay_ids["status_shadow"] = self.preview_canvas.create_text(
            13, 13, text="Idle", font=FONT_OVERLAY,
            fill=COLORS["overlay_shadow"], anchor="nw",
        )
        self._overlay_ids["status"] = self.preview_canvas.create_text(
            12, 12, text="Idle", font=FONT_OVERLAY,
            fill=COLORS["idle"], anchor="nw",
        )

        # Source name — top-left below status
        self._overlay_ids["source_shadow"] = self.preview_canvas.create_text(
            13, 33, text="", font=FONT_OVERLAY,
            fill=COLORS["overlay_shadow"], anchor="nw",
        )
        self._overlay_ids["source"] = self.preview_canvas.create_text(
            12, 32, text="", font=FONT_OVERLAY,
            fill=COLORS["overlay_fg"], anchor="nw",
        )

        # Resolution — top-right
        self._overlay_ids["resolution_shadow"] = self.preview_canvas.create_text(
            w - 11, 13, text="", font=FONT_OVERLAY,
            fill=COLORS["overlay_shadow"], anchor="ne",
        )
        self._overlay_ids["resolution"] = self.preview_canvas.create_text(
            w - 12, 12, text="", font=FONT_OVERLAY,
            fill=COLORS["overlay_fg"], anchor="ne",
        )

        # FPS — bottom-left
        self._overlay_ids["fps_shadow"] = self.preview_canvas.create_text(
            13, h - 11, text="", font=FONT_OVERLAY,
            fill=COLORS["overlay_shadow"], anchor="sw",
        )
        self._overlay_ids["fps"] = self.preview_canvas.create_text(
            12, h - 12, text="", font=FONT_OVERLAY,
            fill=COLORS["overlay_fg"], anchor="sw",
        )

        # Frames — bottom-right
        self._overlay_ids["frames_shadow"] = self.preview_canvas.create_text(
            w - 11, h - 11, text="", font=FONT_OVERLAY,
            fill=COLORS["overlay_shadow"], anchor="se",
        )
        self._overlay_ids["frames"] = self.preview_canvas.create_text(
            w - 12, h - 12, text="", font=FONT_OVERLAY,
            fill=COLORS["overlay_fg"], anchor="se",
        )

        # Error — center
        self._overlay_ids["error_shadow"] = self.preview_canvas.create_text(
            w // 2 + 1, h // 2 + 1, text="", font=FONT_OVERLAY,
            fill=COLORS["overlay_shadow"], anchor="center", width=400,
        )
        self._overlay_ids["error"] = self.preview_canvas.create_text(
            w // 2, h // 2, text="", font=FONT_OVERLAY,
            fill=COLORS["error"], anchor="center", width=400,
        )

        # ---- "No signal" placeholder (centered) ----
        self.preview_canvas.create_text(
            w // 2, h // 2, text="No signal",
            font=(FONT_FAMILY, 14), fill=COLORS["text_dim"],
            tags="placeholder",
        )

    def _on_canvas_configure(self, event):
        self._canvas_width = event.width
        self._canvas_height = event.height
        c = self.preview_canvas
        w, h = event.width, event.height
        # Top-right overlays
        c.coords(self._overlay_ids["resolution_shadow"], w - 11, 13)
        c.coords(self._overlay_ids["resolution"], w - 12, 12)
        # Bottom-left overlays
        c.coords(self._overlay_ids["fps_shadow"], 13, h - 11)
        c.coords(self._overlay_ids["fps"], 12, h - 12)
        # Bottom-right overlays
        c.coords(self._overlay_ids["frames_shadow"], w - 11, h - 11)
        c.coords(self._overlay_ids["frames"], w - 12, h - 12)
        # Center overlays (error)
        c.coords(self._overlay_ids["error_shadow"], w // 2 + 1, h // 2 + 1)
        c.coords(self._overlay_ids["error"], w // 2, h // 2)
        # Center placeholder
        for item in c.find_withtag("placeholder"):
            c.coords(item, w // 2, h // 2)

    def _on_window_configure(self, event):
        """Debounced save of window geometry on move or resize."""
        # Only respond to root window events, not child widgets
        if event.widget is not self.root:
            return
        if self._geometry_save_timer is not None:
            self.root.after_cancel(self._geometry_save_timer)
        self._geometry_save_timer = self.root.after(
            1000, lambda: self._save_pref("geometry", self.root.geometry())
        )

    def _poll_signal(self):
        """Check if a signal requested shutdown."""
        if _shutdown_event.is_set():
            self._on_close()
        else:
            self.root.after(500, self._poll_signal)

    def _save_pref(self, key: str, value):
        """Update a single preference key and persist to disk immediately."""
        try:
            prefs = _load_prefs()
            prefs[key] = value
            _save_prefs(prefs)
        except Exception:
            logger.warning("Failed to save pref %s", key, exc_info=True)

    def _on_close(self):
        if self._closing:
            return
        self._closing = True
        logger.info("Shutting down")
        # Save final geometry (prefs are otherwise saved incrementally)
        try:
            self._save_pref("geometry", self.root.geometry())
        except Exception:
            pass
        self.bridge.shutdown()
        self.root.destroy()

    def _on_source_selected(self, source_name: str):
        """Called when user selects a source from the menu bar."""
        # Cancel any pending auto-connect so it can't race with this selection
        self._auto_connect_source = None
        # Persist source choice to disk immediately — don't rely on exit-time save
        self._save_pref("last_source", source_name)
        # Stop any running or connecting bridge before starting a new one
        if (self.bridge.is_running()
                or self.bridge.stats.state in (BridgeState.CONNECTING,
                                               BridgeState.ERROR)):
            self.bridge.stop()
        # Clear error and placeholder from canvas
        self.preview_canvas.delete("placeholder")
        # Start bridge with selected source
        self.bridge.start(source_name)
        # Update window title to show current source
        self.root.title(f"NDI Virtual Cam \u2014 {source_name}")

    # -- Polling / refresh --------------------------------------------------

    def _schedule_polls(self):
        self._poll_stats()
        self._poll_sources()

    def _poll_sources(self):
        """Refresh the NDI sources menu."""
        sources = self.bridge.get_available_sources()
        self.sources_menu.delete(0, "end")
        if sources:
            for source in sources:
                self.sources_menu.add_command(
                    label=source,
                    command=lambda s=source: self._on_source_selected(s),
                )
            # Auto-connect to last used source (once, on startup)
            if (self._auto_connect_source
                    and self.bridge.stats.state == BridgeState.IDLE
                    and self._auto_connect_source in sources):
                source = self._auto_connect_source
                self._auto_connect_source = None
                logger.info("Auto-connecting to last source '%s'", source)
                self._on_source_selected(source)
            # Auto-reconnect when a previously connected source reappears
            elif (self.bridge.stats.state == BridgeState.ERROR
                    and self.bridge.stats.source_name
                    and self.bridge.stats.source_name in sources):
                source_name = self.bridge.stats.source_name
                logger.info("Source '%s' reappeared — auto-reconnecting", source_name)
                self._on_source_selected(source_name)
        else:
            self.sources_menu.add_command(label="Searching for sources...", state="disabled")
        self.root.after(self.SOURCE_REFRESH, self._poll_sources)

    def _poll_stats(self):
        """Refresh overlay telemetry and preview image on the canvas."""
        stats = self.bridge.stats
        canvas = self.preview_canvas
        ids = self._overlay_ids
        cw = self._canvas_width
        ch = self._canvas_height

        # -- Status overlay (top-left) --
        # Track error messages across state transitions for reconnect UX
        if stats.state == BridgeState.ERROR and stats.error_message:
            self._last_error_message = stats.error_message
        elif stats.state == BridgeState.RUNNING:
            self._last_error_message = None

        # Detect reconnect: CONNECTING state with a prior error still tracked
        is_reconnecting = (stats.state == BridgeState.CONNECTING
                           and self._last_error_message is not None)

        state_colors = {
            BridgeState.IDLE: COLORS["idle"],
            BridgeState.CONNECTING: COLORS["accent"],
            BridgeState.RUNNING: COLORS["running"],
            BridgeState.ERROR: COLORS["error"],
        }
        state_labels = {
            BridgeState.IDLE: "Idle",
            BridgeState.CONNECTING: "Connecting...",
            BridgeState.RUNNING: "Live",
            BridgeState.ERROR: "Error",
        }
        status_color = state_colors.get(stats.state, COLORS["idle"])
        status_text = state_labels.get(stats.state, "")
        if is_reconnecting:
            status_text = "Reconnecting..."
        elif stats.state == BridgeState.CONNECTING and stats.status_detail:
            status_text = stats.status_detail
        canvas.itemconfig(ids["status"], text=status_text, fill=status_color)
        canvas.itemconfig(ids["status_shadow"], text=status_text, fill=COLORS["overlay_shadow"])

        # -- Source name overlay (below status) --
        # Source name is in the title bar during normal operation; show it
        # here during ERROR or reconnect states where it gives useful context.
        source_text = stats.source_name if (stats.state == BridgeState.ERROR
                                            or is_reconnecting) else ""
        canvas.itemconfig(ids["source"], text=source_text, fill=COLORS["overlay_fg"])
        canvas.itemconfig(ids["source_shadow"], text=source_text, fill=COLORS["overlay_shadow"])

        # -- Resolution overlay (top-right) --
        res_text = stats.resolution if stats.state == BridgeState.RUNNING else ""
        canvas.itemconfig(ids["resolution"], text=res_text, fill=COLORS["overlay_fg"])
        canvas.itemconfig(ids["resolution_shadow"], text=res_text, fill=COLORS["overlay_shadow"])

        # -- FPS overlay (bottom-left) --
        if stats.state == BridgeState.RUNNING:
            fps_text = f"{stats.output_fps:.0f} fps"
            if stats.output_fps < NDIBridge.FPS_WARN_THRESHOLD and stats.frames_sent > 30:
                fps_color = COLORS["warning"]
            else:
                fps_color = COLORS["overlay_fg"]
        else:
            fps_text = ""
            fps_color = COLORS["overlay_fg"]
        canvas.itemconfig(ids["fps"], text=fps_text, fill=fps_color)
        canvas.itemconfig(ids["fps_shadow"], text=fps_text, fill=COLORS["overlay_shadow"])

        # -- Frames overlay (bottom-right) --
        # Frame count not shown — FPS + "Live" status already confirm flow.
        # Canvas items kept in _overlay_ids; just never populated.
        canvas.itemconfig(ids["frames"], text="")
        canvas.itemconfig(ids["frames_shadow"], text="")

        # -- Error overlay (center) --
        # Persist error text during reconnect so it doesn't flash away
        if stats.state == BridgeState.ERROR and stats.error_message:
            error_text = stats.error_message
        elif is_reconnecting:
            error_text = self._last_error_message
        else:
            error_text = ""
        canvas.itemconfig(ids["error"], text=error_text, fill=COLORS["error"])
        canvas.itemconfig(ids["error_shadow"], text=error_text, fill=COLORS["overlay_shadow"])

        # -- Window title (IDLE and ERROR states; CONNECTING/RUNNING set by _on_source_selected) --
        if stats.state == BridgeState.IDLE:
            self.root.title("NDI Virtual Cam")
        elif stats.state == BridgeState.ERROR:
            self.root.title("NDI Virtual Cam \u2014 Error")

        # -- Preview image --
        preview = self.bridge.get_preview_frame()
        if preview is not None:
            try:
                canvas.delete("placeholder")
                img = Image.fromarray(preview)
                iw, ih = img.size
                scale = min(cw / iw, ch / ih)
                nw, nh = int(iw * scale), int(ih * scale)
                img = img.resize((nw, nh), Image.LANCZOS)
                self._preview_image_ref = ImageTk.PhotoImage(img)
                canvas.delete("preview")
                canvas.create_image(
                    cw // 2, ch // 2,
                    image=self._preview_image_ref, tags="preview",
                )
                canvas.tag_lower("preview")
            except Exception:
                pass
        elif stats.state == BridgeState.IDLE:
            canvas.delete("preview")
            if not canvas.find_withtag("placeholder"):
                canvas.create_text(
                    cw // 2, ch // 2, text="No signal",
                    font=(FONT_FAMILY, 14), fill=COLORS["text_dim"],
                    tags="placeholder",
                )
        elif stats.state == BridgeState.ERROR:
            canvas.delete("preview")

        self.root.after(self.POLL_INTERVAL, self._poll_stats)

    # -- Run ----------------------------------------------------------------

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    def _signal_handler(signum, frame):
        _shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    # SIGHUP: terminal closed — ensure prefs are saved
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _signal_handler)

    _set_macos_process_name("NDI Virtual Cam")

    app = App()
    # atexit safety net: ensure bridge teardown even if _on_close doesn't run
    atexit.register(app.bridge.shutdown)
    logger.info("Application started")
    app.run()


if __name__ == "__main__":
    main()
