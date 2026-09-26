"""Time each recipe step and print a summary when conan exits.

Times source(), generate(), build() and package() of every package (including
test_package) and, when the command ends, prints them the way Conan prints its
own sections (steps under 0.1 s are left out, but counted in the total):

    ======== Step times ========
        demo/0.1: source 0.6s, build 2.0s (total 2.6s)
        failing/0.1: build 1.2s FAILED (total 1.2s)

Output goes through ConanOutput, so NO_COLOR, CLICOLOR_FORCE and -vquiet apply.

Environment variables:
    CONAN_TIMING=0   disable step timing
"""

import atexit
import os
import re
import time

from conan.api import output as output_mod
from conan.api.output import Color, ConanOutput

_HIDE_BELOW = 0.1  # seconds; instant steps only clutter the line


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


def _summary(state):
    if not state["steps"]:
        return
    out = ConanOutput()
    out.title("Step times")
    for package, steps in state["steps"].items():
        shown = [
            f"{step} {_seconds(seconds)}" + (" FAILED" if failed else "")
            for step, seconds, failed in steps
            if failed or seconds >= _HIDE_BELOW
        ]
        total = _seconds(sum(seconds for _, seconds, _ in steps))
        failed = any(failed for _, _, failed in steps)
        line = f"    {package}: {', '.join(shown) or 'no slow steps'} (total {total})"
        out.info(line, fg=Color.BRIGHT_RED if failed else Color.BRIGHT_CYAN)


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
