"""Time each recipe step and print a summary when conan exits.

After source(), generate(), build() and package() of every package (including
test_package), a step that took 1 s or more gets a line, and a failed build
always does:

    demo/0.1: build finished in 12.4s

When the command ends, a pacman/paru-style summary lists the timed steps
(steps under 0.1 s are left out, but counted in the total):

    :: Step times
       demo/0.1                 source 0.8s  generate 0.1s  build 12.4s  package 0.2s   13.5s

Colors follow Conan's output settings (NO_COLOR, CLICOLOR_FORCE, -vquiet).

Environment variables:
    CONAN_TIMING=0   disable step timing
"""

import atexit
import os
import re
import time

from colorama import Style
from conan.api import output as output_mod
from conan.api.output import Color, ConanOutput

_REPORT_AFTER = 1.0  # seconds; quicker steps only show up in the summary


def _enabled():
    return os.environ.get("CONAN_TIMING", "1").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _state():
    """State shared by every load of this module (Conan may load hooks more than once)."""
    state = getattr(output_mod, "_conan_config_timing", None)
    if state is None:
        state = {
            "started": {},
            "steps": {},
        }  # steps: package -> [(step, seconds, failed)]
        output_mod._conan_config_timing = state
        atexit.register(_summary, state)
    return state


def _package(conanfile):
    """`demo/0.1`, or `demo/0.1 (test package)` for a test_package.

    Not display_name: Conan leaves it empty for source/generate/package, and while a
    hook runs it holds "[HOOK - ...] method()".
    """
    if conanfile.name:
        return f"{conanfile.name}/{conanfile.version}"
    tested = getattr(conanfile, "tested_reference_str", None)
    if tested:
        return f"{tested.split('#')[0]} (test package)"
    return re.sub(r"(: )?\[HOOK - .*$", "", conanfile.display_name or "") or "conanfile"


def _seconds(seconds):
    return (
        f"{seconds:.1f}s"
        if seconds < 60
        else f"{int(seconds // 60)}m{seconds % 60:02.0f}s"
    )


def _time_color(seconds):
    return Color.BRIGHT_GREEN if seconds < 60 else Color.BRIGHT_YELLOW


def _write(out, parts):
    for part in parts:
        text, color = part if isinstance(part, tuple) else (part, None)
        out.write(text, fg=color)
    out.write("", newline=True)


def _package_parts(package):
    """paru colors packages as bold name + green version: `cmake` `/` `3.31.12`."""
    ref, _, rest = package.partition(" ")
    name, _, version = ref.partition("/")
    parts = [(name, Style.BRIGHT)]
    if version:
        parts += ["/", (version, Color.BRIGHT_GREEN)]
    if rest:
        parts.append(f" {rest}")
    return parts


def _start(conanfile, step):
    if _enabled():
        _state()["started"][(_package(conanfile), step)] = time.monotonic()


def _finish(conanfile, step, failed=False):
    if not _enabled():
        return
    state = _state()
    package = _package(conanfile)
    started = state["started"].pop((package, step), None)
    if started is None:
        return
    seconds = time.monotonic() - started
    state["steps"].setdefault(package, []).append((step, seconds, failed))
    # ConanOutput.write() doesn't add the scope prefix, so write it like Conan does
    if failed:
        _write(
            ConanOutput(),
            [
                f"{package}: ",
                (step, Style.BRIGHT),
                " failed after ",
                (_seconds(seconds), Color.BRIGHT_RED),
            ],
        )
    elif seconds >= _REPORT_AFTER:
        _write(
            ConanOutput(),
            [
                f"{package}: ",
                (step, Style.BRIGHT),
                " finished in ",
                (_seconds(seconds), _time_color(seconds)),
            ],
        )


def _summary(state):
    if not state["steps"]:
        return
    out = ConanOutput()
    _write(out, [(":: ", Color.BRIGHT_BLUE), ("Step times", Style.BRIGHT)])
    width = max(len(package) for package in state["steps"])
    for package, steps in state["steps"].items():
        parts = ["   ", *_package_parts(package), " " * (width - len(package) + 2)]
        for step, seconds, failed in steps:
            if seconds < 0.1 and not failed:
                continue  # instant steps only clutter the line; the total includes them
            color = Color.BRIGHT_RED if failed else None
            parts += [(step, Style.DIM), " ", (_seconds(seconds), color), "  "]
        total = sum(seconds for _, seconds, _ in steps)
        parts += [" ", (_seconds(total), Style.BRIGHT + _time_color(total))]
        _write(out, parts)


def pre_source(conanfile):
    _start(conanfile, "source")


def post_source(conanfile):
    _finish(conanfile, "source")


def pre_generate(conanfile):
    _start(conanfile, "generate")


def post_generate(conanfile):
    _finish(conanfile, "generate")


def pre_build(conanfile):
    _start(conanfile, "build")


def post_build(conanfile):
    _finish(conanfile, "build")


def post_build_fail(conanfile):
    _finish(conanfile, "build", failed=True)


def pre_package(conanfile):
    _start(conanfile, "package")


def post_package(conanfile):
    _finish(conanfile, "package")
