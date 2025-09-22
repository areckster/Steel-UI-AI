"""Setuptools entry-point for building the macOS SteelChat app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from setuptools import setup


def _load_py2app_config() -> Tuple[List[str], Dict[str, Any]] | None:
    """Load py2app configuration from pyproject.toml if available."""

    try:
        import tomllib  # type: ignore[attr-defined]
    except ModuleNotFoundError:  # pragma: no cover - fallback for older interpreters
        import tomli as tomllib  # type: ignore[no-redef]

    pyproject = Path(__file__).with_name("pyproject.toml")
    if not pyproject.exists():
        return None

    config = tomllib.loads(pyproject.read_text())
    tool_section = config.get("tool", {})
    py2app_section = tool_section.get("py2app", {})

    app_section = py2app_section.get("app", {})
    script = app_section.get("script")
    if not script:
        return None

    options_section = py2app_section.get("options", {})
    return [script], dict(options_section)


if __name__ == "__main__":
    kwargs: Dict[str, Any] = {}
    py2app_config = _load_py2app_config()
    if py2app_config:
        app, options = py2app_config
        kwargs["app"] = app
        if options:
            kwargs["options"] = {"py2app": options}

    setup(**kwargs)
