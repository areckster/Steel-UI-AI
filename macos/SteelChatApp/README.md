# SteelChatApp (macOS Bundle)

This directory packages the existing SteelChat FastAPI server and web UI into a standalone macOS `.app` bundle. The bundle embeds the backend, launches it on a random loopback port, and loads the familiar `index.html` UI inside a WKWebView.

## Layout

```
macos/SteelChatApp/
├── build_app.sh                    # Helper script to produce SteelChat.app with py2app
├── macos_app_embedded/             # Python package reused by the bundle and dev shell
│   ├── backend.py                  # Spins up uvicorn with sandboxed paths
│   ├── main.py                     # py2app entry point
│   ├── ui.py                       # Shared ChatClient / NativeChatView / WKWebView loader
│   └── __init__.py
├── resources/
│   └── web/index.html              # Local copy of the web client served by WKWebView
└── pyproject.toml                  # py2app + setuptools configuration
```

The package reuses the same `server.py`, `tools.py`, `docstore.py`, and static assets from the repository root by shipping them as bundle resources and redirecting application storage to `~/Library/Application Support/SteelChatApp`.

## Building the `.app`

> **Note:** py2app only runs on macOS. Execute the script from a macOS workstation with Xcode command line tools installed.

```bash
cd macos/SteelChatApp
./build_app.sh
```

The script performs the following steps:

1. Creates an isolated virtual environment under `.venv-build`.
2. Installs backend dependencies (`requirements.txt`) plus the packaging toolchain (`py2app`).
3. Invokes `python -m build` so setuptools + py2app produce `dist/SteelChat.app`.
4. Copies any bundled resources into the app.

Once finished, `dist/SteelChat.app` can be launched directly from Finder. The first launch creates `~/Library/Application Support/SteelChatApp/` containing `docstore.db`, `tmp/`, and extracted static assets. Backend logs stream to `~/Library/Logs/SteelChatApp/backend.log`.

## Developer workflow

### Run the embedded entry point for debugging

```bash
python -m macos.SteelChatApp.macos_app_embedded.main
```

This mirrors how the bundle boots: it starts the uvicorn server on a random port, waits for `/api/health`, then loads `resources/web/index.html` inside a WKWebView.

### Updating dependencies

* Backend/runtime requirements live in the repository root `requirements.txt`. Keep the list aligned when packaging.
* When adding new Python modules that the bundle depends on, update `pyproject.toml` (the `[project] dependencies` block) and rerun `build_app.sh`.
* Static assets that the UI expects should be placed under `resources/` so the bundle can copy them into the sandbox on launch.

### Regenerating resources

If `index.html` or any web assets change, re-copy them into `resources/web/` (or re-run `cp index.html macos/SteelChatApp/resources/web/index.html`) before rebuilding the bundle.

### Logging and troubleshooting

* Backend stdout/stderr and uvicorn logs are written to `~/Library/Logs/SteelChatApp/backend.log`.
* Application data resides in `~/Library/Application Support/SteelChatApp/`. Removing this folder resets the bundled docstore and cached uploads.

## Testing the packaged app

1. Run `./build_app.sh` on macOS.
2. Open `dist/SteelChat.app`. The UI should mirror the browser experience.
3. Verify chat interactions complete without needing an external server.
4. Inspect `~/Library/Logs/SteelChatApp/backend.log` for runtime diagnostics.

Because this repository executes on Linux in CI, these steps must be performed manually on macOS for QA.
