"""Entrypoint for the SteelChat macOS bundle."""

from __future__ import annotations

import time
import importlib
import pathlib
import sys

import httpx
from Cocoa import (
    NSApplication,
    NSApp,
    NSBackingStoreBuffered,
    NSObject,
    NSWindow,
    NSWindowStyleMask,
)
from Foundation import NSAutoreleasePool, NSMakeRect
from PyObjCTools import AppHelper


def _load_components():
    """Load backend and UI components, working both as a package and as a script."""
    package_dir = pathlib.Path(__file__).resolve().parent
    package_name = package_dir.name
    module_base = __package__ or package_name

    try:
        # Try importing with the detected package/module base
        backend_module = importlib.import_module(f"{module_base}.backend")
        ui_module = importlib.import_module(f"{module_base}.ui")
        return backend_module.EmbeddedBackend, ui_module.build_web_chat_view
    except ModuleNotFoundError:
        # Fallback: ensure parent directory is on sys.path
        parent_dir = package_dir.parent
        parent_str = str(parent_dir)
        if parent_str not in sys.path:
            sys.path.insert(0, parent_str)

        backend_module = importlib.import_module(f"{package_name}.backend")
        ui_module = importlib.import_module(f"{package_name}.ui")
        return backend_module.EmbeddedBackend, ui_module.build_web_chat_view


EmbeddedBackend, build_web_chat_view = _load_components()


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, _notification):
        self.backend = EmbeddedBackend()
        self.backend.start()
        self.backend.wait_ready()
        self._await_backend()

        mask = (
            NSWindowStyleMask.titled
            | NSWindowStyleMask.closable
            | NSWindowStyleMask.resizable
        )
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(200.0, 200.0, 900.0, 640.0), mask, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("SteelChat")

        self.web = build_web_chat_view(self.backend.port)
        self.window.setContentView_(self.web)
        self.window.makeKeyAndOrderFront_(None)

    def _await_backend(self, timeout: float = 30.0) -> None:
        base = f"http://127.0.0.1:{self.backend.port}"
        deadline = time.time() + timeout
        with httpx.Client(timeout=1.0) as client:
            while time.time() < deadline:
                try:
                    resp = client.get(f"{base}/api/health")
                    if resp.status_code == 200:
                        return
                except Exception:
                    pass
                time.sleep(0.5)

    def applicationShouldTerminate_(self, _app) -> bool:
        if hasattr(self, "backend"):
            self.backend.stop()
        return True


def main() -> None:
    pool = NSAutoreleasePool.alloc().init()
    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    NSApp.activateIgnoringOtherApps_(True)
    AppHelper.runEventLoop()
    pool.drain()


if __name__ == "__main__":
    main()