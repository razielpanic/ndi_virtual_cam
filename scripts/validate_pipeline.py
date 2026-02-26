#!/usr/bin/env python3
"""
Incremental pipeline validation for NDI Virtual Camera Bridge.

Runs validation stages independently to isolate issues:
  Stage 0: Environment and dependency check
  Stage 1: NDI source discovery (Finder)
  Stage 2: NDI connection and frame receipt (Receiver)
  Stage 3: Full frame pump to virtual camera (pyvirtualcam)
  Stage 4: Sustained performance test (5-minute FPS stability)

Usage:
    python scripts/validate_pipeline.py --stage 0
    python scripts/validate_pipeline.py --stage 1
    python scripts/validate_pipeline.py --stage 2 --source "MACHINENAME (NDI Screen Capture)"
    python scripts/validate_pipeline.py --stage 3 --source "MACHINENAME (NDI Screen Capture)"
    python scripts/validate_pipeline.py --stage 4 --source "MACHINENAME (NDI Screen Capture)"
    python scripts/validate_pipeline.py                    # runs all stages sequentially
"""

import argparse
import os
import subprocess
import sys
import time
from collections import deque


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_header(stage_num: int, title: str):
    print()
    print("=" * 60)
    print(f"  Stage {stage_num}: {title}")
    print("=" * 60)


def _pass(msg: str):
    print(f"  [PASS] {msg}")


def _fail(msg: str):
    print(f"  [FAIL] {msg}")


def _info(msg: str):
    print(f"  [INFO] {msg}")


# ---------------------------------------------------------------------------
# Stage 0: Environment and dependency check
# ---------------------------------------------------------------------------

def stage0_environment() -> bool:
    """Stage 0: Verify environment and dependencies."""
    _print_header(0, "Environment and dependency check")
    ok = True

    # Python version
    v = sys.version_info
    if v >= (3, 10):
        _pass(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _fail(f"Python {v.major}.{v.minor}.{v.micro} — requires 3.10+")
        ok = False

    # cyndilib
    try:
        import cyndilib
        version = getattr(cyndilib, "__version__", "unknown")
        _pass(f"cyndilib {version}")
    except ImportError:
        _fail("cyndilib not importable — run: pip install cyndilib")
        ok = False

    # pyvirtualcam
    try:
        import pyvirtualcam
        version = getattr(pyvirtualcam, "__version__", "unknown")
        _pass(f"pyvirtualcam {version}")
    except ImportError:
        _fail("pyvirtualcam not importable — run: pip install 'pyvirtualcam>=0.15.0'")
        ok = False

    # numpy
    try:
        import numpy as _np
        _pass(f"numpy {_np.__version__}")
    except ImportError:
        _fail("numpy not importable — run: pip install numpy")
        ok = False

    # OBS Virtual Camera registration
    obs_found = False

    # Check CMIOExtension (macOS 14+)
    try:
        result = subprocess.run(
            ["systemextensionsctl", "list"],
            capture_output=True, text=True, timeout=5,
        )
        combined = result.stdout + result.stderr
        if "obs" in combined.lower():
            _pass("OBS Virtual Camera registered (CMIOExtension)")
            obs_found = True
    except Exception:
        pass

    # Check DAL plugin (legacy)
    if not obs_found:
        dal_path = "/Library/CoreMediaIO/Plug-Ins/DAL/obs-mac-virtualcam.plugin"
        if os.path.exists(dal_path):
            _pass("OBS Virtual Camera registered (DAL plugin)")
            obs_found = True

    if not obs_found:
        _fail("OBS Virtual Camera not detected — install OBS Studio 30+ and run virtual camera once")
        ok = False

    # Summary
    print()
    if ok:
        _pass("All prerequisites met")
    else:
        _fail("Some prerequisites missing — see above")
    return ok


# ---------------------------------------------------------------------------
# Stage 1: NDI source discovery
# ---------------------------------------------------------------------------

def stage1_discovery() -> bool:
    """Stage 1: Verify NDI source discovery via Finder."""
    _print_header(1, "NDI source discovery")

    try:
        from cyndilib.finder import Finder
    except ImportError:
        _fail("Cannot import cyndilib.finder — is cyndilib installed?")
        return False

    finder = Finder()
    try:
        finder.open()
        _info("Finder opened, waiting up to 10 seconds for sources...")

        deadline = time.monotonic() + 10.0
        sources: list[str] = []
        while time.monotonic() < deadline:
            try:
                names = list(finder.get_source_names())
                if names:
                    sources = names
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if sources:
            _pass(f"Found {len(sources)} NDI source(s):")
            for name in sources:
                print(f"         - {name}")
            return True
        else:
            _fail("No NDI sources found within 10 seconds")
            _info("Ensure NDI sources are active on the network")
            return False
    finally:
        try:
            finder.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Stage 2: NDI connection and frame receipt
# ---------------------------------------------------------------------------

def stage2_connection(source_name: str) -> bool:
    """Stage 2: Connect to an NDI source and receive frames."""
    _print_header(2, "NDI connection and frame receipt")

    try:
        from cyndilib.finder import Finder
        from cyndilib.receiver import Receiver
        from cyndilib.video_frame import VideoFrameSync
        from cyndilib.wrapper.ndi_recv import RecvColorFormat, RecvBandwidth
    except ImportError:
        _fail("Cannot import cyndilib components")
        return False

    finder = Finder()
    receiver = None
    try:
        finder.open()
        _info(f"Looking for source: {source_name}")

        # Find the named source
        source = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                with finder.notify:
                    source = finder.get_source(source_name)
                if source is not None:
                    break
            except (KeyError, ValueError):
                pass
            time.sleep(0.25)

        if source is None:
            _fail(f"Source '{source_name}' not found within 10 seconds")
            return False
        _pass(f"Source found: {source_name}")

        # Create receiver (same pattern as main app)
        receiver = Receiver(
            color_format=RecvColorFormat.RGBX_RGBA,
            bandwidth=RecvBandwidth.highest,
        )
        video_frame = VideoFrameSync()
        receiver.frame_sync.set_video_frame(video_frame)
        receiver.set_source(source)

        # Wait for connection
        _info("Connecting...")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if receiver.is_connected():
                break
            time.sleep(0.1)

        if not receiver.is_connected():
            _fail("Failed to connect to NDI source")
            return False
        _pass("Connected to NDI source")

        # Wait for first frame
        _info("Waiting for first frame...")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            receiver.frame_sync.capture_video()
            if video_frame.xres > 0 and video_frame.yres > 0:
                break
            time.sleep(0.033)

        if video_frame.xres == 0 or video_frame.yres == 0:
            _fail("No video frames received within 10 seconds")
            return False

        w, h = video_frame.xres, video_frame.yres
        _pass(f"First frame received: {w}x{h}")

        # Validate frame data
        try:
            raw = video_frame.get_array()
            rgba = raw.reshape(h, w, 4)
            _pass(f"Frame shape: {rgba.shape} (RGBA, 4 channels)")
        except Exception as exc:
            _fail(f"Frame data error: {exc}")
            return False

        # Capture frames for 5 seconds and report FPS
        _info("Capturing frames for 5 seconds...")
        frame_count = 0
        start = time.monotonic()
        end = start + 5.0
        while time.monotonic() < end:
            receiver.frame_sync.capture_video()
            if video_frame.xres > 0 and video_frame.yres > 0:
                frame_count += 1

        elapsed = time.monotonic() - start
        fps = frame_count / elapsed if elapsed > 0 else 0.0
        _pass(f"Received {frame_count} frames in {elapsed:.1f}s ({fps:.1f} FPS)")

        # Optionally save first frame as PNG
        try:
            from PIL import Image
            receiver.frame_sync.capture_video()
            if video_frame.xres > 0 and video_frame.yres > 0:
                raw = video_frame.get_array()
                rgba = raw.reshape(video_frame.yres, video_frame.xres, 4)
                img = Image.fromarray(rgba)
                png_path = os.path.join(os.path.dirname(__file__), "stage2_capture.png")
                img.save(png_path)
                _info(f"Saved capture to {png_path}")
        except Exception:
            _info("Could not save PNG capture (Pillow may not be installed)")

        return True

    finally:
        if receiver is not None:
            try:
                if receiver.is_connected():
                    receiver.disconnect()
            except Exception:
                pass
        try:
            finder.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Stage 3: Virtual camera output
# ---------------------------------------------------------------------------

def stage3_vcam_output(source_name: str) -> bool:
    """Stage 3: Receive NDI frames and send to virtual camera."""
    _print_header(3, "Virtual camera output")

    try:
        from cyndilib.finder import Finder
        from cyndilib.receiver import Receiver
        from cyndilib.video_frame import VideoFrameSync
        from cyndilib.wrapper.ndi_recv import RecvColorFormat, RecvBandwidth
        import pyvirtualcam
    except ImportError as exc:
        _fail(f"Cannot import required module: {exc}")
        return False

    finder = Finder()
    receiver = None
    vcam = None
    try:
        finder.open()
        _info(f"Looking for source: {source_name}")

        # Find the named source
        source = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                with finder.notify:
                    source = finder.get_source(source_name)
                if source is not None:
                    break
            except (KeyError, ValueError):
                pass
            time.sleep(0.25)

        if source is None:
            _fail(f"Source '{source_name}' not found")
            return False
        _pass(f"Source found: {source_name}")

        # Create receiver
        receiver = Receiver(
            color_format=RecvColorFormat.RGBX_RGBA,
            bandwidth=RecvBandwidth.highest,
        )
        video_frame = VideoFrameSync()
        receiver.frame_sync.set_video_frame(video_frame)
        receiver.set_source(source)

        # Wait for connection
        _info("Connecting...")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if receiver.is_connected():
                break
            time.sleep(0.1)

        if not receiver.is_connected():
            _fail("Failed to connect to NDI source")
            return False
        _pass("Connected")

        # Wait for first frame
        _info("Waiting for first frame...")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            receiver.frame_sync.capture_video()
            if video_frame.xres > 0 and video_frame.yres > 0:
                break
            time.sleep(0.033)

        if video_frame.xres == 0 or video_frame.yres == 0:
            _fail("No video frames received")
            return False

        w, h = video_frame.xres, video_frame.yres
        _pass(f"First frame: {w}x{h}")

        # Open virtual camera at received resolution
        vcam = pyvirtualcam.Camera(
            width=w,
            height=h,
            fps=30,
            fmt=pyvirtualcam.PixelFormat.RGB,
            print_fps=False,
        )
        _pass(f"Virtual camera opened: {vcam.device}")
        _info("Sending 150 frames (~5 seconds at 30fps)...")
        _info("Check Zoom / Photo Booth / FaceTime to verify the virtual camera output")

        # Send 150 frames
        TARGET_FRAMES = 150
        frames_sent = 0
        start = time.monotonic()

        while frames_sent < TARGET_FRAMES:
            receiver.frame_sync.capture_video()

            if video_frame.xres == 0 or video_frame.yres == 0:
                vcam.sleep_until_next_frame()
                continue

            try:
                raw = video_frame.get_array()
                fh, fw = video_frame.yres, video_frame.xres
                rgba = raw.reshape(fh, fw, 4)
                rgb = rgba[:, :, :3].copy()
            except Exception:
                vcam.sleep_until_next_frame()
                continue

            vcam.send(rgb)
            frames_sent += 1
            vcam.sleep_until_next_frame()

        elapsed = time.monotonic() - start
        avg_fps = frames_sent / elapsed if elapsed > 0 else 0.0

        _pass(f"Sent {frames_sent} frames in {elapsed:.1f}s (avg {avg_fps:.1f} FPS)")
        _pass(f"Virtual camera device: {vcam.device}")
        return True

    finally:
        if vcam is not None:
            try:
                vcam.close()
            except Exception:
                pass
        if receiver is not None:
            try:
                if receiver.is_connected():
                    receiver.disconnect()
            except Exception:
                pass
        try:
            finder.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Stage 4: Sustained performance test
# ---------------------------------------------------------------------------

def stage4_performance(source_name: str, duration: int) -> bool:
    """Stage 4: Sustained pipeline performance test."""
    _print_header(4, f"Sustained performance test ({duration}s)")

    try:
        from cyndilib.finder import Finder
        from cyndilib.receiver import Receiver
        from cyndilib.video_frame import VideoFrameSync
        from cyndilib.wrapper.ndi_recv import RecvColorFormat, RecvBandwidth
        import pyvirtualcam
    except ImportError as exc:
        _fail(f"Cannot import required module: {exc}")
        return False

    finder = Finder()
    receiver = None
    vcam = None
    try:
        finder.open()
        _info(f"Looking for source: {source_name}")

        # Find the named source
        source = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                with finder.notify:
                    source = finder.get_source(source_name)
                if source is not None:
                    break
            except (KeyError, ValueError):
                pass
            time.sleep(0.25)

        if source is None:
            _fail(f"Source '{source_name}' not found")
            return False
        _pass(f"Source found: {source_name}")

        # Create receiver
        receiver = Receiver(
            color_format=RecvColorFormat.RGBX_RGBA,
            bandwidth=RecvBandwidth.highest,
        )
        video_frame = VideoFrameSync()
        receiver.frame_sync.set_video_frame(video_frame)
        receiver.set_source(source)

        # Wait for connection
        _info("Connecting...")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if receiver.is_connected():
                break
            time.sleep(0.1)

        if not receiver.is_connected():
            _fail("Failed to connect to NDI source")
            return False
        _pass("Connected")

        # Wait for first frame
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            receiver.frame_sync.capture_video()
            if video_frame.xres > 0 and video_frame.yres > 0:
                break
            time.sleep(0.033)

        if video_frame.xres == 0 or video_frame.yres == 0:
            _fail("No video frames received")
            return False

        w, h = video_frame.xres, video_frame.yres
        _pass(f"First frame: {w}x{h}")

        # Open virtual camera
        vcam = pyvirtualcam.Camera(
            width=w,
            height=h,
            fps=30,
            fmt=pyvirtualcam.PixelFormat.RGB,
            print_fps=False,
        )
        _pass(f"Virtual camera opened: {vcam.device}")
        _info(f"Running sustained test for {duration} seconds...")
        print()

        # FPS tracking with deque (same pattern as main app)
        EXPECTED_INTERVAL = 1.0 / 30.0  # ~33ms at 30fps
        DROP_THRESHOLD = EXPECTED_INTERVAL * 2.0  # >66ms = dropped frame

        fps_timestamps: deque = deque(maxlen=60)
        total_frames = 0
        total_drops = 0
        report_interval = 30.0  # Report every 30 seconds
        interval_fps_values: list[float] = []

        test_start = time.monotonic()
        test_end = test_start + duration
        next_report = test_start + report_interval
        last_frame_time = test_start

        while time.monotonic() < test_end:
            if not receiver.is_connected():
                _fail("NDI source disconnected during test")
                return False

            receiver.frame_sync.capture_video()

            if video_frame.xres == 0 or video_frame.yres == 0:
                vcam.sleep_until_next_frame()
                continue

            try:
                raw = video_frame.get_array()
                fh, fw = video_frame.yres, video_frame.xres
                rgba = raw.reshape(fh, fw, 4)
                rgb = rgba[:, :, :3].copy()
            except Exception:
                vcam.sleep_until_next_frame()
                continue

            vcam.send(rgb)

            now = time.monotonic()
            total_frames += 1
            fps_timestamps.append(now)

            # Detect dropped frames
            gap = now - last_frame_time
            if total_frames > 1 and gap > DROP_THRESHOLD:
                total_drops += 1
            last_frame_time = now

            # Compute current FPS
            current_fps = 0.0
            if len(fps_timestamps) > 1:
                elapsed = fps_timestamps[-1] - fps_timestamps[0]
                if elapsed > 0:
                    current_fps = (len(fps_timestamps) - 1) / elapsed
            interval_fps_values.append(current_fps)

            # Periodic report
            if now >= next_report:
                elapsed_total = now - test_start
                min_fps = min(interval_fps_values) if interval_fps_values else 0.0
                max_fps = max(interval_fps_values) if interval_fps_values else 0.0
                print(f"  [{elapsed_total:6.0f}s] FPS: {current_fps:5.1f}  "
                      f"min: {min_fps:5.1f}  max: {max_fps:5.1f}  "
                      f"frames: {total_frames:6d}  drops: {total_drops}")
                interval_fps_values.clear()
                next_report = now + report_interval

            vcam.sleep_until_next_frame()

        # Final summary
        total_elapsed = time.monotonic() - test_start
        avg_fps = total_frames / total_elapsed if total_elapsed > 0 else 0.0
        all_fps = interval_fps_values  # remaining samples
        min_fps = min(all_fps) if all_fps else avg_fps
        max_fps = max(all_fps) if all_fps else avg_fps

        print()
        print("  " + "-" * 50)
        print(f"  SUMMARY")
        print(f"    Duration:     {total_elapsed:.1f}s")
        print(f"    Total frames: {total_frames}")
        print(f"    Average FPS:  {avg_fps:.1f}")
        print(f"    Min FPS:      {min_fps:.1f}")
        print(f"    Max FPS:      {max_fps:.1f}")
        print(f"    Dropped:      {total_drops}")
        print("  " + "-" * 50)

        # Pass/fail criteria
        passed = avg_fps >= 28.0 and total_drops < 10
        if passed:
            _pass(f"Performance test passed (avg FPS {avg_fps:.1f} >= 28, drops {total_drops} < 10)")
        else:
            reasons = []
            if avg_fps < 28.0:
                reasons.append(f"avg FPS {avg_fps:.1f} < 28")
            if total_drops >= 10:
                reasons.append(f"drops {total_drops} >= 10")
            _fail(f"Performance test failed: {', '.join(reasons)}")
        return passed

    finally:
        if vcam is not None:
            try:
                vcam.close()
            except Exception:
                pass
        if receiver is not None:
            try:
                if receiver.is_connected():
                    receiver.disconnect()
            except Exception:
                pass
        try:
            finder.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="NDI Virtual Camera pipeline validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
stages:
  0  Environment and dependency check
  1  NDI source discovery (Finder)
  2  NDI connection and frame receipt (Receiver)
  3  Full frame pump to virtual camera (pyvirtualcam)
  4  Sustained performance test (5-minute FPS stability)
""",
    )
    parser.add_argument(
        "--stage", type=int, choices=[0, 1, 2, 3, 4], default=None,
        help="Run specific stage (default: all stages sequentially)",
    )
    parser.add_argument(
        "--source", type=str, default=None,
        help="NDI source name (required for stages 2-4)",
    )
    parser.add_argument(
        "--duration", type=int, default=300,
        help="Duration in seconds for stage 4 performance test (default: 300)",
    )
    args = parser.parse_args()

    # Validate --source requirement for stages 2-4
    if args.stage in (2, 3, 4) and not args.source:
        parser.error(f"--source is required for stage {args.stage}")

    # Determine which stages to run
    if args.stage is not None:
        stages = [args.stage]
    else:
        stages = [0, 1, 2, 3, 4]
        if not args.source:
            # Without --source, can only run stages 0 and 1
            _info("No --source specified, running stages 0 and 1 only")
            _info("Provide --source to run stages 2-4")
            stages = [0, 1]

    print()
    print("NDI Virtual Camera Bridge — Pipeline Validation")
    print("=" * 60)

    results: dict[int, bool] = {}

    for stage in stages:
        # Stage 0 always runs first as prereq when running higher stages
        if stage > 0 and 0 not in results:
            results[0] = stage0_environment()
            if not results[0]:
                _fail("Stage 0 prereq check failed — aborting")
                sys.exit(1)

        if stage == 0:
            results[0] = stage0_environment()
        elif stage == 1:
            results[1] = stage1_discovery()
        elif stage == 2:
            results[2] = stage2_connection(args.source)
        elif stage == 3:
            results[3] = stage3_vcam_output(args.source)
        elif stage == 4:
            results[4] = stage4_performance(args.source, args.duration)

    # Final summary
    print()
    print("=" * 60)
    print("  RESULTS")
    print("=" * 60)
    all_passed = True
    for stage_num in sorted(results):
        status = "PASS" if results[stage_num] else "FAIL"
        if not results[stage_num]:
            all_passed = False
        print(f"  Stage {stage_num}: {status}")
    print("=" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
