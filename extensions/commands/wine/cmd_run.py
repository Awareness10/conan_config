"""Run a Windows program on Linux with the wine package from this config's recipes.

    conan wine:run app.exe [args...]
    conan wine:run --wine "[~11]" app.exe      # another wine version range
    conan wine:run --wayland game.exe          # native Wayland window, not XWayland
    conan wine:run --x11 game.exe              # X11 only (XWayland on a Wayland desktop)

Installs wine as a tool (the newest wine/* from the conan_config remote, built
from its recipe if needed; nothing to install by hand) and replaces this process
with its conan-wine wrapper, so the program's exit code is conan's. conan-wine
uses its own prefix (~/.cache/conan-wine-<version>), hides wine's debug output
and skips the Mono/Gecko install prompts; set WINEPREFIX/WINEDEBUG to override.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

from conan.api.output import ConanOutput
from conan.cli.command import conan_command
from conan.errors import ConanException


def _conan(*args):
    """The command line that runs conan again, with this Python and this Conan.

    Same as in sync/cmd_config.py (command modules can't import each other): a
    frozen conan (conan-bin, Conan's installers) is the interpreter and Conan in
    one; otherwise not sys.argv[0], which on Windows is a path that doesn't exist.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    # -P (3.11+): -m would put the current folder first on sys.path
    safe_path = ["-P"] if sys.version_info >= (3, 11) else []
    return [sys.executable, *safe_path, "-m", "conans.conan", *args]


def _install_wine(version_range):
    """Install wine/<range> as a tool; returns (reference, package folder)."""
    # The auto-sync and remote registration already ran for this command.
    env = {**os.environ, "CONAN_CONFIG_SYNC_SKIP": "1", "CONAN_CONFIG_INDEX_SKIP": "1"}
    with tempfile.TemporaryDirectory(
        prefix="conan-wine-"
    ) as tmp:  # generated env files
        cmd = _conan(
            "install",
            f"--tool-requires=wine/{version_range}",
            "--build=missing",
            "-of",
            tmp,
            "--format=json",
        )
        result = subprocess.run(
            cmd, check=False, capture_output=True, text=True, env=env
        )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise ConanException(f"Could not install wine/{version_range}")
    nodes = json.loads(result.stdout)["graph"]["nodes"].values()
    for node in nodes:
        if (node.get("ref") or "").startswith("wine/") and node.get("package_folder"):
            return node["ref"].split("#")[0], node["package_folder"]
    raise ConanException("conan install did not return the wine package folder")


@conan_command(group="Custom")
def run(conan_api, parser, *args):
    """
    Run a Windows program with wine from the conan_config recipes (Linux only).
    """
    parser.add_argument("program", help="Windows program (.exe) to run")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="its arguments")
    parser.add_argument(
        "--wine", default="[*]", help="wine version or range (default: newest)"
    )
    drivers = parser.add_mutually_exclusive_group()
    drivers.add_argument(
        "--wayland",
        action="store_true",
        help="use wine's Wayland driver instead of X11/XWayland (windows are "
        "placed by the compositor; fixes off-screen windows on e.g. Hyprland)",
    )
    drivers.add_argument(
        "--x11",
        action="store_true",
        help="use wine's X11 driver only (XWayland on a Wayland desktop), never "
        "falling back to its Wayland driver",
    )
    parsed = parser.parse_args(*args)
    if not sys.platform.startswith("linux"):
        raise ConanException("conan wine:run runs Windows programs on Linux")
    if not os.path.isfile(parsed.program):
        raise ConanException(f"No such file: {parsed.program}")
    env = dict(os.environ)
    if parsed.wayland:
        if not env.get("WAYLAND_DISPLAY"):
            raise ConanException("--wayland needs a Wayland session (WAYLAND_DISPLAY)")
        # Wine picks its X11 driver whenever DISPLAY is set.
        env.pop("DISPLAY", None)
    elif parsed.x11:
        if not env.get("DISPLAY"):
            raise ConanException("--x11 needs an X11 display (DISPLAY)")
        # Without a Wayland socket, wine can't fall back to winewayland.
        env.pop("WAYLAND_DISPLAY", None)

    ref, folder = _install_wine(parsed.wine)
    wine = os.path.join(folder, "bin", "conan-wine")
    driver = " (Wayland)" if parsed.wayland else " (X11)" if parsed.x11 else ""
    ConanOutput().info(f"Running {parsed.program} with {ref}{driver}")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(wine, [wine, parsed.program, *parsed.args], env)
