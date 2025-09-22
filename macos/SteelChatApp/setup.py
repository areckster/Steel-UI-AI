"""Setuptools entry-point for building the macOS SteelChat app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from setuptools import setup


def _resolve_paths(entries: Iterable[str]) -> List[str]:
    """Resolve resource paths relative to the project tree.

    Py2app expects real filesystem locations; however, the configuration in
    ``pyproject.toml`` lists resources relative to the repository root. When
    ``setup.py`` executes from ``macos/SteelChatApp`` these files appear to be
    missing (for example ``server.py``), triggering the observed packaging
    failure.  This helper searches upward from the setup directory to locate
    the referenced files and returns their absolute paths for py2app.
    """

    base_dir = Path(__file__).resolve().parent
    search_roots = [base_dir, *base_dir.parents]

    resolved: List[str] = []
    for entry in entries:
        path = Path(entry)
        if path.is_absolute() and path.exists():
            resolved.append(str(path))
            continue

        for root in search_roots:
            candidate = (root / path).resolve()
            if candidate.exists():
                resolved.append(str(candidate))
                break
        else:
            raise FileNotFoundError(f"Resource path '{entry}' could not be located relative to {base_dir}")

    return resolved


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
    resolved_script = _resolve_paths([script])

    options: Dict[str, Any] = dict(options_section)
    resources = options.get("resources")
    if resources:
        options["resources"] = _resolve_paths(resources)

    return resolved_script, options


if __name__ == "__main__":
    kwargs: Dict[str, Any] = {}
    py2app_config = _load_py2app_config()
    if py2app_config:
        app, options = py2app_config
        kwargs["app"] = app
        if options:
            kwargs["options"] = {"py2app": options}

    setup(**kwargs)
