"""Themes for hook_progress.py.

A theme is a module in this folder (not starting with `_`) with one function:

    def layout(st) -> _common.Line

`st` is the progress state: scope ("cmake/3.31.12"), verb ("extracting"), name (file or
git phase), detail (git's counters), fraction (0..1), done/total bytes, rate (bytes/s),
eta and elapsed (seconds) and finished. The returned Line holds colored segments;
_common.render() fits it to the terminal width.

Select one with CONAN_PROGRESS_THEME=<name> (default: paru).
"""

import importlib
import os

DEFAULT = "paru"


def available():
    folder = os.path.dirname(__file__)
    return sorted(
        f[:-3]
        for f in os.listdir(folder)
        if f.endswith(".py") and not f.startswith("_")
    )


def load(name):
    """Returns (theme module, error message or None); unknown names fall back to DEFAULT."""
    error = None
    if name not in available():
        error = f"unknown CONAN_PROGRESS_THEME '{name}', using '{DEFAULT}' ({', '.join(available())})"
        name = DEFAULT
    return importlib.import_module(f"{__name__}.{name}"), error
