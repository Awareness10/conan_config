"""Progress output for archive extraction and git clone/fetch.

Conan prints nothing while it extracts sources (`get`/`unzip`), unpacks
downloaded packages or runs `git clone`, so long steps look frozen. Hooks can
only run before/after a whole step, so this module instead patches those Conan
functions when Conan loads the hooks (once per command, before any recipe
runs):

- conan.tools.files `unzip()`/`get()`: .tar.* and .zip sources
- package/recipe downloads from remotes (`tar_extract`)
- conan.tools.scm `Git.clone()`/`Git.fetch_commit()`: git --progress, streamed

Operations that finish within half a second print nothing. On a terminal it draws a single updating line; otherwise (CI logs) it prints a
line every 5 seconds. Each patch checks the Conan internals it relies on and is
skipped, with one warning, if they changed.

Environment variables:
    CONAN_PROGRESS=0   disable all progress output
"""

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


def _enabled():
    if os.environ.get("CONAN_PROGRESS", "1").lower() in ("0", "false", "no", "off"):
        return False
    try:
        from conan.api.output import LEVEL_STATUS
        return ConanOutput.level_allowed(LEVEL_STATUS)
    except ImportError:
        return True


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class _Progress:
    """One progress line on stderr: redrawn in place on a TTY, periodic otherwise."""

    def __init__(self, label):
        self._label = label
        self._tty = sys.stderr.isatty()
        self._start = time.monotonic()
        self._last = 0.0
        self._text = ""
        self._drawn = False

    def update(self, text, force=False):
        self._text = text
        now = time.monotonic()
        if not self._drawn and now - self._start < _SHOW_AFTER:
            return
        if not force and now - self._last < (_TTY_INTERVAL if self._tty else _NON_TTY_INTERVAL):
            return
        self._last = now
        line = f"{self._label} {text}"
        if self._tty:
            width = shutil.get_terminal_size().columns - 1
            sys.stderr.write("\r\x1b[2K" + line[:width])
        else:
            sys.stderr.write(line + "\n")
        sys.stderr.flush()
        self._drawn = True

    def done(self, text=None):
        if not self._drawn:
            return
        if text is not None or self._tty:
            self.update(text if text is not None else self._text, force=True)
        if self._tty:
            sys.stderr.write("\n")
            sys.stderr.flush()


class _ProgressFile(io.FileIO):
    """Read-only file that reports how much of it has been read."""

    def __init__(self, path, label, mode="rb"):
        super().__init__(path, "r" if "r" in mode else mode)
        self._size = os.path.getsize(path)
        self._read = 0
        self._progress = _Progress(f"{label} {os.path.basename(path)}") if _enabled() else None

    def _report(self, n, force=False):
        self._read += n
        if self._progress:
            pct = min(100, int(self._read * 100 / self._size)) if self._size else 100
            bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
            self._progress.update(f"[{bar}] {pct:3d}% of {_human(self._size)}", force=force)

    def read(self, size=-1):
        block = super().read(size)
        self._report(len(block))
        return block

    def readinto(self, b):
        n = super().readinto(b)
        self._report(n or 0)
        return n

    def close(self):
        if self._progress and not self.closed:
            self._read = self._size
            self._report(0, force=True)
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
            super().__init__(path, "Extracting", kwargs.get("mode", "rb"))

    files_mod.FileProgress = FileProgress

    # tar: untargz() calls `tarfile.TarFile.open(filename, mode='r:*')`; hand it our file object
    original_untargz = files_mod.untargz

    def untargz(filename, *args, **kwargs):
        if not _enabled():
            return original_untargz(filename, *args, **kwargs)
        original_open = tarfile.TarFile.__dict__["open"]
        with _ProgressFile(filename, "Extracting") as fileobj:
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


def _patch_package_downloads():
    from conan.internal.rest import remote_manager

    original = getattr(remote_manager, "tar_extract", None)
    if original is None:
        return "package download extraction"

    def tar_extract(fileobj, destination_dir):
        path = getattr(fileobj, "name", None)
        if not _enabled() or not isinstance(path, str) or not os.path.isfile(path):
            return original(fileobj, destination_dir)
        with _ProgressFile(path, "Decompressing") as f:
            return original(f, destination_dir)

    remote_manager.tar_extract = tar_extract


# -- git -----------------------------------------------------------------------------------------

_GIT_PROGRESS = re.compile(r"^(remote: )?[A-Z][\w ]+:\s+\d+%")


def _patch_git():
    import inspect
    from conan.api.output import Color
    from conan.errors import ConanException
    from conan.tools.files import chdir
    from conan.tools.scm import Git

    original_run = Git.run
    if list(inspect.signature(original_run).parameters) != ["self", "cmd", "hidden_output"]:
        return "Git.clone()"

    def run(self, cmd, hidden_output=None):
        sub, _, rest = cmd.partition(" ")
        if sub not in ("clone", "fetch") or not _enabled():
            return original_run(self, cmd, hidden_output)
        print_cmd = cmd if hidden_output is None else cmd.replace(hidden_output, "<hidden>")
        self._conanfile.output.info(f"RUN: git {print_cmd}", fg=Color.BRIGHT_BLUE)
        cf = self._conanfile
        who = cf.display_name or (f"{cf.name}/{cf.version}" if cf.name else "")
        progress = _Progress(f"{who}: git {sub}:" if who else f"git {sub}:")
        with chdir(self._conanfile, self.folder):
            proc = subprocess.Popen(f"git {sub} --progress {rest}", shell=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout = []
            reader = threading.Thread(target=lambda: stdout.append(proc.stdout.read()))
            reader.start()
            messages, buf = [], b""
            while chunk := proc.stderr.read1(4096):
                *lines, buf = re.split(rb"[\r\n]", buf + chunk)
                for line in (l.decode(errors="replace").strip() for l in lines):
                    if _GIT_PROGRESS.match(line):
                        progress.update(line.removeprefix("remote: "))
                    elif line:
                        messages.append(line)
            reader.join()
            proc.wait()
        progress.done()
        if proc.returncode:
            err = "\n".join(messages)
            if hidden_output:
                err = err.replace(hidden_output, "<hidden>")
            raise ConanException(f"Command 'git {print_cmd}' failed with errorcode "
                                 f"'{proc.returncode}'\n{err}")
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
        except Exception as e:  # never break conan because of progress output
            skipped.append(f"{patch.__name__} ({e})")
    if skipped:
        ConanOutput().warning(f"[hook_progress] Conan internals changed, no progress for: "
                              f"{', '.join(skipped)}")


_install()
