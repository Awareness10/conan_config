"""Use the recipes in this config's index/ folder as a Conan remote.

`conan config install` copies index/ into $CONAN_HOME, but a local-recipes-index
remote needs an absolute path, which remotes.json can't know in advance. Conan
imports every custom command module on startup, so the module-level check below
runs ahead of every conan command: when the "conan_config" remote is missing (a
fresh install, or remotes.json was just replaced by a config sync) it is added in
front of the other remotes.

Environment variables:
    CONAN_CONFIG_INDEX_SKIP=1   don't add the remote automatically
"""

import json
import os
import subprocess
import sys

from conan.api.output import ConanOutput
from conan.cli.command import conan_command

REMOTE_NAME = "conan_config"
_SKIP_ENV = "CONAN_CONFIG_INDEX_SKIP"


def _conan_home():
    # Resolved without the Conan API: this runs while the CLI is still loading.
    return os.environ.get("CONAN_HOME") or os.path.join(
        os.path.expanduser("~"), ".conan2"
    )


def _index_dir():
    return os.path.join(_conan_home(), "index")


def _registered():
    try:
        with open(os.path.join(_conan_home(), "remotes.json")) as f:
            remotes = json.load(f).get("remotes", [])
    except (OSError, ValueError):
        return False
    return any(
        r.get("name") == REMOTE_NAME
        and r.get("url") == _index_dir()
        and r.get("remote_type") == "local-recipes-index"
        for r in remotes
    )


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


def register():
    """Add (or fix) the remote; returns True when it is registered afterwards."""
    if _registered():
        return True
    cmd = _conan(
        "remote",
        "add",
        REMOTE_NAME,
        _index_dir(),
        "--type=local-recipes-index",
        "--index=0",
        "--force",
    )
    env = {**os.environ, _SKIP_ENV: "1", "CONAN_CONFIG_SYNC_SKIP": "1"}
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        ConanOutput().warning(f"Could not add the '{REMOTE_NAME}' recipes remote")
        return False
    return True


def _auto_register():
    if os.environ.get(_SKIP_ENV) or not os.path.isdir(
        os.path.join(_index_dir(), "recipes")
    ):
        return
    args = sys.argv[1:]
    # Remotes are about to be replaced, or the user is managing them by hand.
    if args[:2] in (["config", "install"], ["config", "install-pkg"]) or args[:1] == [
        "remote"
    ]:
        return
    register()


_auto_register()


@conan_command(group="Custom commands")
def index(conan_api, parser, *args):
    """
    Add the 'conan_config' remote for the recipes shipped in this config (index/).
    """
    parser.parse_args(*args)
    out = ConanOutput()
    if not os.path.isdir(os.path.join(_index_dir(), "recipes")):
        out.error(f"No recipes in {_index_dir()}: is this config installed?")
        return
    if register():
        recipes = sorted(os.listdir(os.path.join(_index_dir(), "recipes")))
        out.success(f"Remote '{REMOTE_NAME}' -> {_index_dir()}")
        out.info(f"Recipes: {', '.join(recipes)}")
