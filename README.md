# NDI Virtual Camera Bridge

A lightweight macOS utility that receives an NDI video source and presents it as a virtual webcam via the OBS Virtual Camera DAL plugin. Built for production AV installations where NDI Virtual Input is already in use and a second, independent virtual camera path is needed.

## Why this exists

The NDI ecosystem provides **NDI Virtual Input**, which presents a single NDI source as a virtual webcam. But it only registers one virtual camera device, and you can only select one source at a time. If your workflow already uses NDI Virtual Input for one leg of a pipeline, you have no way to simultaneously route a *second* NDI source to a *different* virtual camera — unless you bring in OBS or another full production suite.

This app fills that gap. It uses the **OBS Virtual Camera** DAL plugin (which is a separate virtual camera device from NDI Virtual Input) to create an independent, concurrent virtual camera output from any NDI source on your network. No OBS process running, no OBS configuration — just OBS's DAL plugin as plumbing, and a small Python app doing the work.

## The specific problem this solves

```
NDI Camera ──→ NDI Virtual Input ──→ "NDI Video" ──→ Keynote (camera input)
                                                          │
                                                     Keynote composites
                                                     titles + live camera
                                                          │
NDI Screen Capture ←── captures Keynote window ───────────┘
         │
   ndi_to_vcam.py (this app)
         │
   "OBS Virtual Camera" ──→ Zoom (camera input)
```

Two virtual cameras. Two independent pipelines. Same machine. No conflict.

| Virtual Camera Device | Registered By | Used For |
|---|---|---|
| NDI Video | NDI Virtual Input | NDI camera → Keynote |
| OBS Virtual Camera | OBS DAL plugin | Keynote output → Zoom |

## Quick start

```bash
# Install Python dependencies
pip install -r requirements.txt

# One-time: register OBS Virtual Camera (see docs/SETUP.md)

# Run
python3 src/ndi_to_vcam.py
```

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, pipeline topology, component responsibilities, threading model |
| [docs/SETUP.md](docs/SETUP.md) | Prerequisites, installation steps, one-time configuration |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Day-of operating procedures, troubleshooting, failover |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Technical decision log — why each choice was made and what was rejected |

## Requirements

- macOS 14 (Sonoma) or later
- Python 3.10+
- OBS Studio 30+ (installed, not running)
- NDI Tools (NDI Screen Capture, NDI Virtual Input)
- See [docs/SETUP.md](docs/SETUP.md) for full details

## License

Internal tooling. See your organization's policies.

---

*NDI® is a registered trademark of Vizrt NDI AB.*
