# Operations

Day-of operating procedures, monitoring, troubleshooting, and failover for the NDI Virtual Camera Bridge.

## Startup sequence

Order matters. Start from the source end of the pipeline and work toward the output.

### 1. NDI camera
Power on and confirm it's publishing on the network. Use NDI Monitor to verify.

### 2. NDI Virtual Input
Launch from menu bar. Select the NDI camera source. Confirm it appears in the menu bar dropdown.

### 3. Keynote
Open the presentation. Verify the camera feed appears in the Keynote slide via the "NDI Video" camera source. Enter presentation mode (Play).

### 4. NDI Screen Capture
Launch from menu bar. Select the display or window showing the Keynote presentation. Verify it's publishing by checking NDI Monitor.

### 5. NDI Virtual Camera Bridge (this app)
Double-click `NDI Virtual Cam.app`, or from Terminal:
```bash
./run.sh
```
- Select the NDI Screen Capture source from the dropdown
- Click **Start**
- Confirm the status dot turns green ("Live")
- Confirm the preview shows the Keynote composite

### 6. Zoom
Launch Zoom and join the meeting. In Settings → Video, select **OBS Virtual Camera**. Confirm the Keynote composite appears in the Zoom preview.

## Monitoring during the event

The app provides at-a-glance status:

| Indicator | Meaning |
|---|---|
| Green dot, "Live" | Frames flowing normally |
| FPS readout | Should be ~30. Sustained drops below 25 indicate a problem |
| Frames Sent | Should increment steadily. If it stops, the pipeline has stalled |
| Preview thumbnail | Visual confirmation of what's going to Zoom |

### What to watch for
- **FPS drops**: Could indicate CPU load from other apps, network congestion, or the NDI source stuttering
- **Preview freezes but FPS still counting**: Possible color space or resolution change; usually self-corrects
- **Status goes red**: The NDI source disconnected or an error occurred. Read the error message, fix the upstream issue, click Start again

## Troubleshooting

### No NDI sources in the dropdown

**Cause**: NDI Screen Capture isn't running, or it's on a different subnet.

**Fix**:
1. Confirm NDI Screen Capture is running (check menu bar)
2. Open NDI Monitor — can you see the source there?
3. If same machine: this should always work. Restart NDI Screen Capture.
4. If cross-machine: check that both machines are on the same subnet and mDNS is not blocked.

### "OBS Virtual Camera is not installed"

**Cause**: The OBS DAL plugin / Camera Extension isn't registered.

**Fix**:
1. Launch OBS Studio 30+
2. Click Start Virtual Camera → Stop Virtual Camera
3. Quit OBS
4. Restart this app

### Zoom doesn't show "OBS Virtual Camera"

**Cause**: Zoom caches the camera device list at launch.

**Fix**: Quit Zoom entirely (Cmd+Q, not just close the window), start this app, then relaunch Zoom.

### Black frame in Zoom

**Cause**: The virtual camera is registered but no frames are being sent.

**Fix**:
1. Check this app — is it showing "Live" with frames counting?
2. If yes: try switching away from OBS Virtual Camera in Zoom and back
3. If no: the NDI source may have dropped. Check NDI Screen Capture.

### Resolution mismatch / stretched video

**Cause**: The NDI source changed resolution, or Keynote is in a non-16:9 mode.

**Fix**: The app automatically recreates the virtual camera at the new resolution. Zoom should adapt. If Zoom doesn't adapt, switch cameras away and back.

### High CPU usage

**Expected**: 3-8% on Apple Silicon for 1080p30.

**If higher**:
- Check if another app is consuming the OBS Virtual Camera (only one consumer at a time)
- Check Activity Monitor for runaway NDI processes
- Reduce to 720p output by modifying the NDI Screen Capture resolution

## Failover procedures

### NDI source drops mid-event

1. The app will show a red status with "NDI source disconnected"
2. Fix the upstream issue (restart NDI Screen Capture, check the camera, etc.)
3. Click **Start** in this app to reconnect
4. Zoom will show the last frame until new frames arrive, then resume automatically

### This app crashes

1. Zoom will show a frozen frame (last frame received)
2. Relaunch: `./run.sh`
3. Select the source, click Start
4. Zoom resumes automatically — no need to reselect the camera

### The entire Mac needs to restart

Follow the full startup sequence from the top of this document. The pipeline is stateless — there's nothing to recover, just start everything in order.

### HDMI fallback path

If the NDI pipeline fails entirely and cannot be restored in time:

1. The NDI camera also outputs HDMI
2. Connect HDMI to a capture dongle (Cam Link / Magewell) on the hot standby machine
3. In Zoom, switch camera to the capture device
4. This bypasses Keynote compositing — the audience sees raw camera without titles
5. Titles can be communicated verbally or via Zoom screen share as a stopgap

## Shutdown sequence

Reverse order from startup:

1. Leave the Zoom meeting (or stop video)
2. Close this app (click the window close button — this cleanly disconnects NDI and releases the virtual camera)
3. Stop NDI Screen Capture
4. Exit Keynote presentation mode
5. Quit NDI Virtual Input
6. Power down the NDI camera
