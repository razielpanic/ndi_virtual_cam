# Contributing

Issues and pull requests are welcome.

## Development setup

```bash
brew install python@3.12 python-tk@3.12
git clone https://github.com/razielpanic/ndi_virtual_cam.git
cd ndi_virtual_cam
./run.sh
```

`run.sh` creates a `.venv/` in the project directory, installs dependencies, and launches the app. OBS Studio 30+ must be installed (for the virtual camera plugin).

## Rebuilding the launcher binary

The `.app` bundle uses a compiled C launcher. If you modify `launcher.c`:

```bash
clang -arch arm64 -arch x86_64 -O2 \
    -o "NDI Virtual Cam.app/Contents/MacOS/launcher" launcher.c
```

## Single file policy

The application is intentionally a single file (`src/ndi_to_vcam.py`). It's deployed to machines where inspectability matters more than code organization. Please don't split it into modules.
