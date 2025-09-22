"""Embedded backend orchestration for the macOS bundle."""

from __future__ import annotations

import logging
import os
import shutil
import socket
import sys
import threading
from contextlib import closing
from pathlib import Path
from typing import Optional

import uvicorn

LOG_DIR = Path.home() / "Library" / "Logs" / "SteelChatApp"
APP_SUPPORT_DEFAULT = Path.home() / "Library" / "Application Support" / "SteelChatApp"


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.getsockname()[1]


def _configure_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "backend.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)

    root = logging.getLogger("SteelChatApp")
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    root.propagate = False

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.handlers = [handler]
        logger.propagate = False

    logging.getLogger(__name__).info("Logging initialised at %s", log_path)
    return root


class EmbeddedBackend:
    """Manage a uvicorn server bound to a bundled FastAPI app."""

    def __init__(self, port: Optional[int] = None, app_support: Optional[Path] = None):
        self.port = port or _find_free_port()
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None
        self._app = None
        self._shutdown = threading.Event()
        self._logger = _configure_logging()
        self.app_support = app_support or APP_SUPPORT_DEFAULT
        self._app_module_ready = threading.Event()

    def _prepare_environment(self) -> None:
        support_dir = _ensure_directory(self.app_support)
        tmp_dir = _ensure_directory(support_dir / "tmp")

        os.environ.setdefault("DOCSTORE_DB", str(support_dir / "docstore.db"))
        os.environ.setdefault("STEELCHAT_APP_SUPPORT", str(support_dir))

        project_root = Path(__file__).resolve().parents[2]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        resources_dir = Path(__file__).resolve().parent.parent / "resources"
        web_dir = resources_dir / "web"
        if web_dir.exists():
            dest_index = support_dir / "index.html"
            src_index = web_dir / "index.html"
            if src_index.exists():
                shutil.copy2(src_index, dest_index)

        tmp_src = project_root / "tmp"
        if tmp_src.exists():
            for item in tmp_src.iterdir():
                dest = tmp_dir / item.name
                if not dest.exists():
                    if item.is_file():
                        shutil.copy2(item, dest)
                    elif item.is_dir():
                        shutil.copytree(item, dest)

        docstore_src = project_root / "docstore.db"
        docstore_dest = support_dir / "docstore.db"
        if docstore_src.exists() and not docstore_dest.exists():
            shutil.copy2(docstore_src, docstore_dest)

        import server  # type: ignore

        server.APP_DIR = str(support_dir)
        server.TMP_DIR = str(tmp_dir)
        self._app = server.app
        self._logger.info("Server APP_DIR redirected to %s", server.APP_DIR)
        self._app_module_ready.set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def _runner() -> None:
            try:
                self._prepare_environment()
                config = uvicorn.Config(
                    self._app,
                    host="127.0.0.1",
                    port=self.port,
                    log_config=None,
                    loop="asyncio",
                )
                self._server = uvicorn.Server(config)
                self._logger.info("Starting backend on port %s", self.port)
                self._server.run()
            except Exception:
                self._logger.exception("Backend crashed")
            finally:
                self._shutdown.set()
                self._logger.info("Backend thread exiting")

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float = 30.0) -> bool:
        return self._app_module_ready.wait(timeout)

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10.0)
        self._shutdown.set()
        self._logger.info("Backend stopped")


__all__ = ["EmbeddedBackend"]
