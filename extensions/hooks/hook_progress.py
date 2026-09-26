"""Progress output for archive extraction and git clone/fetch.

Conan prints nothing while it extracts sources (`get`/`unzip`), unpacks
downloaded packages or runs `git clone`, so long steps look frozen. Hooks can
only run before/after a whole step, so this module instead patches those Conan
functions when Conan loads the hooks (once per command, before any recipe
runs):

- conan.tools.files `unzip()`/`get()`: .tar.* and .zip sources
- package/recipe downloads from remotes (`tar_extract`)
- conan.tools.scm `Git.clone()`/`Git.fetch_commit()`: git --progress, streamed

Lines look like pacman/paru downloads, colored when Conan would color output:

     cmake/3.31.12 unpacking conan_package.tgz    43.0 MiB  17.2 MiB/s 00:01 [######------]  44%

Operations that finish within half a second print nothing. On a terminal it
draws a single updating line; otherwise (CI logs) it prints a line every 5
seconds. Each patch checks the Conan internals it relies on and is
skipped, with one warning, if they changed.

Environment variables:
    CONAN_PROGRESS=0            disable all progress output
"""

import contextvars
import io
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from conan.api.output import ConanOutput

_MARKER = "_conan_config_progress"
_NON_TTY_INTERVAL = 5.0
_TTY_INTERVAL = 0.1
_SHOW_AFTER = 0.5  # seconds; quicker operations print nothing

# Package the current extraction belongs to, e.g. "cmake/3.31.12" (set by the patches)
_scope = contextvars.ContextVar("progress_scope", default="")


def _enabled():
    if os.environ.get("CONAN_PROGRESS", "1").lower() in ("0", "false", "no", "off"):
        return False
    try:
        from conan.api.output import LEVEL_STATUS

        return ConanOutput.level_allowed(LEVEL_STATUS)
    except ImportError:
        return True


def _human(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _duration(seconds):
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# -- colors --------------------------------------------------------------------------------------


def _color_enabled():
    # Same rules as Conan's output: CLICOLOR_FORCE wins, then NO_COLOR, then TTY
    if os.getenv("CLICOLOR_FORCE", "0") != "0":
        return True
    if os.getenv("NO_COLOR") is not None:
        return False
    return sys.stderr.isatty()


BOLD, DIM, RESET = "\x1b[1m", "\x1b[2m", "\x1b[0m"
BLUE, GREEN = "\x1b[34m", "\x1b[32m"


def _scope_parts(scope):
    """paru colors packages as bold name + green version: `cmake` `/` `3.31.12`."""
    name, _, version = scope.partition("/")
    parts = [(name, BOLD)]
    if version:
        parts += [("/", None), (version, BOLD + GREEN)]
    return parts


# -- line layout ---------------------------------------------------------------------------------
# pacman/paru download line: `left ... right [####----]  45%`, flush right. left is a list of
# (text, sgr) segments, right a list of (kind, segments) groups that are dropped whole when the
# terminal is too narrow ("detail" first, then from the end), and bar(width) returns the
# segments of a bar of that many cells.


def _layout(st):
    left = [(" ", None)]
    if st.scope:
        left += [*_scope_parts(st.scope), (" ", None)]
    left += [(st.verb, DIM), (" ", None), (st.name, None)]
    right = []
    if st.detail:
        right.append(("detail", [(st.detail, None), (" ", None)]))
    if st.total:
        right.append(("size", [(f"{_human(st.total):>10}", None), (" ", None)]))
    if st.rate:
        right.append(("rate", [(f"{_human(st.rate) + '/s':>12}", None), (" ", None)]))
    seconds = st.elapsed if st.finished or st.eta is None else st.eta
    right.append(("time", [(_duration(seconds), None), (" ", None)]))
    pct_color = BOLD + GREEN if st.finished else BOLD

    def bar(width):
        filled = round(width * st.fraction)
        return [
            ("[", None),
            ("#" * filled, BOLD + BLUE),
            ("-" * (width - filled), DIM),
            ("]", None),
            (f" {int(st.fraction * 100):3d}%", pct_color),
        ]

    return left, right, bar


def _flat(groups):
    return [seg for _, segments in groups for seg in segments]


def _width(segments):
    return sum(len(text) for text, _ in segments)


class _State:
    scope = verb = name = detail = ""
    fraction = 0.0
    done = total = rate = 0
    eta = None
    elapsed = 0.0
    finished = False


class _Progress:
    """One progress line on stderr: redrawn in place on a TTY, periodic otherwise."""

    def __init__(self, verb, name, scope=None):
        self._tty = sys.stderr.isatty()
        self._color = _color_enabled()
        self._start = time.monotonic()
        self._last = 0.0
        self._drawn = False
        self._cells = None
        self.state = _State()
        self.state.verb, self.state.name = verb, name
        self.state.scope = _scope.get() if scope is None else scope

    def update(self, fraction, done=0, total=0, detail="", force=False):
        st = self.state
        st.fraction, st.done, st.total, st.detail = (
            min(max(fraction, 0.0), 1.0),
            done,
            total,
            detail,
        )
        now = time.monotonic()
        st.elapsed = now - self._start
        if done and st.elapsed > 0:
            st.rate = done / st.elapsed
            st.eta = (total - done) / st.rate if total and st.rate else None
        if not self._drawn and st.elapsed < _SHOW_AFTER:
            return
        if not force and now - self._last < (
            _TTY_INTERVAL if self._tty else _NON_TTY_INTERVAL
        ):
            return
        self._last = now
        self._draw()

    def _draw(self):
        left, right, bar = _layout(self.state)
        width = shutil.get_terminal_size().columns - 1 if self._tty else 100
        if self._cells is None:
            # Fixed for the whole line so the bar doesn't jitter as the numbers change
            reserve = 42  # room for the numbers on the right
            self._cells = max(10, min(40, width - _width(left) - reserve))
        bar_segments = bar(self._cells)

        # Too wide: drop git's counters first, then groups from the end
        def fits():
            return _width(left + _flat(right) + bar_segments) + 2 <= width

        if not fits():
            right = [group for group in right if group[0] != "detail"]
        while right and not fits():
            right = right[:-1]
        right = _flat(right)

        fill = max(1, width - _width(left + right + bar_segments))
        segments = left + [(" " * fill, None)] + right + bar_segments
        line = "".join(
            f"{sgr}{text}{RESET}" if sgr and self._color else text
            for text, sgr in segments
        )
        sys.stderr.write(("\r\x1b[2K" + line) if self._tty else (line + "\n"))
        sys.stderr.flush()
        self._drawn = True

    def done(self):
        if not self._drawn:
            return
        st = self.state
        st.finished, st.fraction, st.elapsed = True, 1.0, time.monotonic() - self._start
        st.done = st.total
        self._draw()
        if self._tty:
            sys.stderr.write("\n")
            sys.stderr.flush()


class _ProgressFile(io.FileIO):
    """Read-only file that reports how far it has been read.

    tarfile reads a compressed archive twice: extractall() first decompresses everything to
    list the members, then rewinds and decompresses again to extract them. Pass passes=2 and
    the bar covers both; a rewind from past the middle of the file starts the next pass.
    """

    def __init__(self, path, verb, mode="rb", passes=1):
        super().__init__(path, "r" if "r" in mode else mode)
        self._size = os.path.getsize(path)
        self._passes = passes
        self._pass = 0
        self._furthest = 0
        self._progress = _Progress(verb, os.path.basename(path)) if _enabled() else None

    def _report(self):
        pos = self.tell()
        self._furthest = max(self._furthest, pos)
        if self._progress and self._size:
            done = (min(self._pass, self._passes - 1) * self._size + pos) / self._passes
            self._progress.update(min(done / self._size, 1.0), int(done), self._size)

    def seek(self, offset, whence=io.SEEK_SET):
        pos = super().seek(offset, whence)
        if pos < self._furthest / 2 and self._furthest > self._size / 2:
            self._pass += 1
            self._furthest = pos
        return pos

    def read(self, size=-1):
        block = super().read(size)
        self._report()
        return block

    def readinto(self, b):
        n = super().readinto(b)
        self._report()
        return n

    def close(self):
        if self._progress and not self.closed:
            self._progress.done()
            self._progress = None
        super().close()


# -- archives ------------------------------------------------------------------------------------


def _patch_source_archives():
    import tarfile

    from conan.tools.files import files as files_mod

    if not hasattr(files_mod, "FileProgress") or not hasattr(files_mod, "untargz"):
        return "conan.tools.files unzip()"

    # zip: unzip() reads the archive through `FileProgress(filename, msg=..., mode=...)`
    class FileProgress(_ProgressFile):
        def __init__(self, path, msg="Unzipping", interval=None, *args, **kwargs):
            super().__init__(path, "extracting", kwargs.get("mode", "rb"))

    files_mod.FileProgress = FileProgress

    # tar: untargz() calls `tarfile.TarFile.open(filename, mode='r:*')`; hand it our file object
    original_untargz = files_mod.untargz

    def untargz(filename, *args, **kwargs):
        if not _enabled():
            return original_untargz(filename, *args, **kwargs)
        original_open = tarfile.TarFile.__dict__["open"]
        with _ProgressFile(filename, "extracting", passes=2) as fileobj:

            def open_(cls, name=None, mode="r", fileobj_=None, *a, **kw):
                if name == filename and fileobj_ is None and "fileobj" not in kw:
                    fileobj_ = fileobj
                return original_open.__func__(cls, name, mode, fileobj_, *a, **kw)

            tarfile.TarFile.open = classmethod(open_)
            try:
                return original_untargz(filename, *args, **kwargs)
            finally:
                tarfile.TarFile.open = original_open

    files_mod.untargz = untargz

    # unzip(conanfile, ...) knows the package: expose it to the progress line
    original_unzip = files_mod.unzip

    def unzip(conanfile, *args, **kwargs):
        who = (
            getattr(conanfile, "display_name", "")
            or getattr(conanfile, "ref", "")
            or ""
        )
        token = _scope.set(str(who))
        try:
            return original_unzip(conanfile, *args, **kwargs)
        finally:
            _scope.reset(token)

    import conan.tools.files as files_pkg

    files_mod.unzip = unzip
    if getattr(files_pkg, "unzip", None) is original_unzip:
        files_pkg.unzip = unzip


def _patch_package_downloads():
    from conan.internal.rest import remote_manager

    original = getattr(remote_manager, "tar_extract", None)
    if original is None:
        return "package download extraction"

    def tar_extract(fileobj, destination_dir):
        path = getattr(fileobj, "name", None)
        if not _enabled() or not isinstance(path, str) or not os.path.isfile(path):
            return original(fileobj, destination_dir)
        with _ProgressFile(path, "unpacking", passes=2) as f:
            return original(f, destination_dir)

    remote_manager.tar_extract = tar_extract

    # uncompress_file(src, dest, scope=str(ref)) calls tar_extract: pass the scope along
    original_uncompress = getattr(remote_manager, "uncompress_file", None)
    if original_uncompress is not None:

        def uncompress_file(src_path, dest_folder, scope=None):
            token = _scope.set(scope or "")
            try:
                return original_uncompress(src_path, dest_folder, scope=scope)
            finally:
                _scope.reset(token)

        remote_manager.uncompress_file = uncompress_file


# -- git -----------------------------------------------------------------------------------------

_GIT_PROGRESS = re.compile(
    r"^(?:remote: )?(?P<phase>[A-Z][\w ]+):\s+(?P<pct>\d+)%\s*(?P<rest>.*)$"
)


def _patch_git():
    import inspect

    from conan.api.output import Color
    from conan.errors import ConanException
    from conan.tools.files import chdir
    from conan.tools.scm import Git

    original_run = Git.run
    if list(inspect.signature(original_run).parameters) != [
        "self",
        "cmd",
        "hidden_output",
    ]:
        return "Git.clone()"

    def run(self, cmd, hidden_output=None):
        sub, _, rest = cmd.partition(" ")
        if sub not in ("clone", "fetch") or not _enabled():
            return original_run(self, cmd, hidden_output)
        print_cmd = (
            cmd if hidden_output is None else cmd.replace(hidden_output, "<hidden>")
        )
        self._conanfile.output.info(f"RUN: git {print_cmd}", fg=Color.BRIGHT_BLUE)
        cf = self._conanfile
        who = cf.display_name or (f"{cf.name}/{cf.version}" if cf.name else "")
        progress = _Progress(f"git {sub}", "", scope=who)
        with chdir(self._conanfile, self.folder):
            proc = subprocess.Popen(
                f"git {sub} --progress {rest}",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout = []
            reader = threading.Thread(target=lambda: stdout.append(proc.stdout.read()))
            reader.start()
            messages, buf = [], b""
            while chunk := proc.stderr.read1(4096):
                *lines, buf = re.split(rb"[\r\n]", buf + chunk)
                for line in (l.decode(errors="replace").strip() for l in lines):
                    if m := _GIT_PROGRESS.match(line):
                        progress.state.name = m["phase"].lower()
                        detail = m["rest"].removesuffix(", done.").strip()
                        progress.update(int(m["pct"]) / 100, detail=detail)
                    elif line:
                        messages.append(line)
            reader.join()
            proc.wait()
        progress.done()
        if proc.returncode:
            err = "\n".join(messages)
            if hidden_output:
                err = err.replace(hidden_output, "<hidden>")
            raise ConanException(
                f"Command 'git {print_cmd}' failed with errorcode "
                f"'{proc.returncode}'\n{err}"
            )
        return b"".join(stdout).decode(errors="replace").strip()

    Git.run = run


def _install():
    import conan.tools.files as files_pkg

    if getattr(files_pkg, _MARKER, False):
        return  # hooks can be loaded more than once per process
    setattr(files_pkg, _MARKER, True)
    skipped = []
    for patch in (_patch_source_archives, _patch_package_downloads, _patch_git):
        try:
            if failed := patch():
                skipped.append(failed)
        except Exception as e:  # noqa: BLE001 - progress output must never break conan
            skipped.append(f"{patch.__name__} ({e})")
    if skipped:
        ConanOutput().warning(
            f"[hook_progress] Conan internals changed, no progress for: "
            f"{', '.join(skipped)}"
        )


_install()
