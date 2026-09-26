"""Keep this Conan config in sync with its git repo.

Conan imports every custom command module on startup, before parsing the
command line, so the module-level check below runs ahead of *every* conan
command. It compares the remote head of the config repo (`git ls-remote`, one
network round trip) with the last installed commit, stored in
$CONAN_HOME/.conan_config_installed_rev. When they differ it reinstalls the
config and re-executes the original command, so that command sees the new
profiles, remotes, conf and extensions.

Environment variables:
    CONAN_CONFIG_SYNC_SKIP=1        disable the automatic check (CI, offline work)
    CONAN_CONFIG_SYNC_INTERVAL=<s>  seconds between remote checks (default 1800, 0 = every command)
    CONAN_CONFIG_SYNC_URL, CONAN_CONFIG_SYNC_BRANCH  override the repo/branch (testing, forks)
"""

import itertools
import os
import subprocess
import sys
import time

from colorama import Style
from conan.api.output import Color, ConanOutput
from conan.cli.command import conan_command

CONFIG_REPO = os.environ.get(
    "CONAN_CONFIG_SYNC_URL", "https://github.com/Awareness10/conan_config.git"
)
CONFIG_BRANCH = os.environ.get("CONAN_CONFIG_SYNC_BRANCH", "main")
REV_FILENAME = ".conan_config_installed_rev"
_SKIP_ENV = "CONAN_CONFIG_SYNC_SKIP"


def _say(*parts):
    """One pacman/paru-style line on stderr, e.g. `:: Message  main 26a77c8 -> 2aaaa88`.

    Each part is plain text or (text, color); Conan decides whether colors are shown
    (TTY, NO_COLOR, CLICOLOR_FORCE, CONAN_COLOR_DARK) and hides it all with -vquiet.
    """
    if _silenced():
        return
    out = ConanOutput()
    for part in parts:
        text, color = part if isinstance(part, tuple) else (part, None)
        out.write(text, fg=color)
    out.write("", newline=True)


def _silenced():
    # The auto-sync runs before Conan parses -v, so honour -vquiet/-verror/-vwarning here.
    args = sys.argv[1:]
    levels = {a[2:] for a in args if a.startswith("-v")}
    levels |= {b for a, b in itertools.pairwise(args) if a == "-v"}
    return bool(levels & {"quiet", "error", "warning"})


def _short(rev):
    return rev[:7] if rev else "none"


def _conan_home():
    # Resolved without the Conan API: this runs while the CLI is still loading.
    return os.environ.get("CONAN_HOME") or os.path.join(
        os.path.expanduser("~"), ".conan2"
    )


def _rev_file():
    return os.path.join(_conan_home(), REV_FILENAME)


def _read_rev():
    try:
        with open(_rev_file()) as f:
            return f.read().strip() or None
    except OSError:
        return None


def _write_rev(rev):
    with open(_rev_file(), "w") as f:
        f.write(rev + "\n")


def _remote_rev():
    try:
        result = subprocess.run(
            ["git", "ls-remote", CONFIG_REPO, f"refs/heads/{CONFIG_BRANCH}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = result.stdout.split()
    return out[0] if result.returncode == 0 and out else None


def _install(rev):
    """Run `conan config install` with the same interpreter and conan entry point."""
    _say(
        (":: ", Color.BRIGHT_BLUE),
        ("Remote conan config has been updated", Style.BRIGHT),
        "  ",
        (CONFIG_BRANCH, Color.BRIGHT_CYAN),
        " ",
        (_short(_read_rev()), Color.RED),
        " -> ",
        (_short(rev), Color.BRIGHT_GREEN),
    )
    _say("   running ", ("conan config install", Color.BRIGHT_BLUE), f" {CONFIG_REPO}")
    cmd = [
        sys.executable,
        sys.argv[0],
        "config",
        "install",
        CONFIG_REPO,
        "--type=git",
        f"--args=-b {CONFIG_BRANCH}",
    ]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, _SKIP_ENV: "1"},
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        ConanOutput().warning(
            "conan config install failed, continuing with the current config"
        )
        return False
    _write_rev(rev)
    _say(
        (":: ", Color.BRIGHT_BLUE),
        ("Conan config is now at ", Style.BRIGHT),
        (_short(rev), Color.BRIGHT_GREEN),
        " (",
        (CONFIG_BRANCH, Color.BRIGHT_CYAN),
        ")",
    )
    return True


def sync(force=False):
    """Returns 'updated', 'up-to-date' or 'offline'."""
    rev_file = _rev_file()
    if not force:
        interval = int(os.environ.get("CONAN_CONFIG_SYNC_INTERVAL", "1800"))
        try:
            if time.time() - os.stat(rev_file).st_mtime < interval:
                return "up-to-date"
        except OSError:
            pass
    remote = _remote_rev()
    if remote is None:
        return "offline"
    if remote == _read_rev():
        os.utime(rev_file)  # mtime is the last-check time for the interval
        return "up-to-date"
    return "updated" if _install(remote) else "offline"


def _auto_sync():
    if os.environ.get(_SKIP_ENV):
        return
    args = sys.argv[1:]
    # Don't fight an explicit install, and let `sync:config` do its own check.
    if args[:2] in (["config", "install"], ["config", "install-pkg"]) or args[:1] == [
        "sync:config"
    ]:
        return
    if sync() == "updated":
        # Re-run the original command in a fresh process so it loads the new config.
        os.environ[_SKIP_ENV] = "1"
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(sys.executable, [sys.executable, *sys.argv])


_auto_sync()


@conan_command(group="Custom commands")
def config(conan_api, parser, *args):
    """
    Check the conan_config repo now and reinstall it if the remote has new commits.
    """
    parser.parse_args(*args)
    status = sync(force=True)
    if status == "updated":
        return  # _install() already reported the new revision
    rev = (_short(_read_rev()), Color.BRIGHT_GREEN)
    branch = (CONFIG_BRANCH, Color.BRIGHT_CYAN)
    if status == "up-to-date":
        _say(
            (":: ", Color.BRIGHT_BLUE),
            ("Conan config is up to date ", Style.BRIGHT),
            rev,
            " (",
            branch,
            ")",
        )
    else:
        _say(
            (":: ", Color.BRIGHT_YELLOW),
            ("Remote conan config unreachable", Style.BRIGHT),
            ", keeping ",
            rev,
            " (",
            branch,
            ")  ",
            CONFIG_REPO,
        )
