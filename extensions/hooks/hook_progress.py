"""Progress output for downloads, archive extraction/compression and git clone/fetch.

Conan prints little or nothing while it downloads files, extracts sources
(`get`/`unzip`), unpacks downloaded packages, compresses packages for upload or
runs `git clone`, so long steps look frozen. Hooks can only run before/after a whole step, so this module
instead patches those Conan functions when Conan loads the hooks (once per
command, before any recipe runs):

- conan.tools.files `unzip()`/`get()`: .tar.* and .zip sources
- package/recipe downloads from remotes (`tar_extract`)
- file downloads (`FileDownloader`): recipes/packages from remotes, `download()`/`get()`
  sources, `conan config install` archives; replaces Conan's every-10s "Downloaded" lines
- `compress_files()`: the archive written by `conan upload`/`conan cache save`
- conan.tools.scm `Git.clone()`/`Git.fetch_commit()`: git --progress, streamed

Lines are drawn by a theme from ./progress_themes (default paru, like pacman/paru
downloads), colored when Conan would color output:

     cmake/3.31.12 unpacking conan_package.tgz    43.0 MiB  17.2 MiB/s 00:01 [######------]  44%

Operations that finish within half a second print nothing. On a terminal it
draws a single updating line that stays below Conan's other messages (parallel
operations take turns: the first one owns the line, the others stay quiet until
it finishes); otherwise (CI logs) it prints a line every 5 seconds. Each patch checks the Conan internals it relies on and is
skipped, with one warning, if they changed.

Environment variables:
    CONAN_PROGRESS=0            disable all progress output
    CONAN_PROGRESS_THEME=<name> theme from ./progress_themes: paru (default), btop
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

# The terminal line (TTY only). Parallel downloads/uploads would overwrite each other's
# line, so the first to draw owns it and the others stay quiet until it finishes. Conan
# prints from other threads meanwhile: the _patch_output() writers clear the line first
# and redraw it below the message, so it never ends up glued to one or left half-done.
_line_lock = threading.RLock()  # held for every write to the terminal
_line_owner = None  # the _Progress that draws the line
_line_shown = ""  # the line as it is on screen now, "" when there is none
_line_held = False  # Conan left a line unfinished (a prompt): don't draw over it


def _enabled():
    if _theme is None:
        return False
    if os.environ.get("CONAN_PROGRESS", "1").lower() in ("0", "false", "no", "off"):
        return False
    try:
        from conan.api.output import LEVEL_STATUS

        return ConanOutput.level_allowed(LEVEL_STATUS)
    except ImportError:
        return True


def _load_theme():
    """Import the CONAN_PROGRESS_THEME theme from ./progress_themes (see its __init__.py).

    Done while Conan loads this hook: afterwards Conan drops modules imported from the
    hooks folder out of sys.modules, so nothing can be imported from there lazily.
    """
    import importlib.util

    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "progress_themes")
    name = "conan_config_progress_themes"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(folder, "__init__.py"), submodule_search_locations=[folder]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    theme, error = package.load(os.getenv("CONAN_PROGRESS_THEME", package.DEFAULT))
    if error:
        ConanOutput().warning(f"[hook_progress] {error}")
    return theme, sys.modules[f"{name}._common"].render


def _color_enabled():
    # Same rules as Conan's output: CLICOLOR_FORCE wins, then NO_COLOR, then TTY
    if os.getenv("CLICOLOR_FORCE", "0") != "0":
        return True
    if os.getenv("NO_COLOR") is not None:
        return False
    return sys.stderr.isatty()


class _State:
    """What a theme draws; see progress_themes/__init__.py."""

    scope = verb = name = detail = ""
    cells = None  # bar width, fixed per line by the theme renderer
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
        global _line_owner, _line_shown
        width = shutil.get_terminal_size().columns - 1 if self._tty else 100
        with _line_lock:
            if not self._tty:
                line = _render(
                    _theme.layout(self.state), self.state, width, self._color
                )
                sys.stderr.write(line + "\n")
                sys.stderr.flush()
                self._drawn = True
                return
            if _line_owner is None:
                _line_owner = self
            if _line_owner is not self or _line_held:
                return
            line = _render(_theme.layout(self.state), self.state, width, self._color)
            sys.stderr.write("\r\x1b[2K" + line)
            sys.stderr.flush()
            _line_shown = line
            self._drawn = True

    def done(self):
        if not self._drawn:
            return
        st = self.state
        st.finished, st.fraction, st.elapsed = True, 1.0, time.monotonic() - self._start
        st.done = st.total
        with _line_lock:  # the final line must not be cleared by the next writer
            self._draw()
            self.stop()

    def stop(self):
        """Leave the line where it is: the operation ended without finishing."""
        global _line_owner, _line_shown
        with _line_lock:
            if _line_owner is not self:
                return
            if _line_shown and not _line_held:
                sys.stderr.write("\n")
                sys.stderr.flush()
            _line_owner, _line_shown = None, ""


def _clear_line():
    """Before other output: take the progress line off the screen (caller holds the lock)."""
    if _line_shown and not _line_held:
        sys.stderr.write("\r\x1b[2K")
        sys.stderr.flush()


def _restore_line(ended_line):
    """After other output: draw the progress line again below it, unless the output
    stopped mid-line (a prompt), which the line would overwrite."""
    global _line_held
    _line_held = not ended_line
    if _line_shown and ended_line:
        sys.stderr.write(_line_shown)
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


def _patch_output():
    """Keep Conan's messages off the progress line: ConanOutput writes whole lines to
    stderr from any thread, which would land after the bar and leave it half-done."""
    import inspect

    for method, text_arg in (("write", "data"), ("_write_message", "msg")):
        original = getattr(ConanOutput, method, None)
        params = list(inspect.signature(original).parameters) if original else []
        if params[:2] != ["self", text_arg] or "newline" not in params:
            return f"Conan output ({method})"

    def wrap(original, text_arg):
        signature = inspect.signature(original)

        def method(self, *args, **kwargs):
            with _line_lock:
                if _line_owner is None and not _line_held:
                    return original(self, *args, **kwargs)
                call = signature.bind(self, *args, **kwargs)
                call.apply_defaults()
                ended_line = call.arguments["newline"] or str(
                    call.arguments[text_arg]
                ).endswith("\n")
                _clear_line()
                try:
                    return original(self, *args, **kwargs)
                finally:
                    _restore_line(ended_line)

        return method

    ConanOutput.write = wrap(ConanOutput.write, "data")
    ConanOutput._write_message = wrap(ConanOutput._write_message, "msg")


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


# -- downloads -----------------------------------------------------------------------------------

# Progress of the download the current thread is running (set by the _download_file patch)
_downloading = contextvars.ContextVar("progress_downloading", default=None)


class _DownloadRequester:
    """Stands in for FileDownloader's requester: counts what get() responses stream."""

    def __init__(self, requester, progress):
        self._requester, self._progress = requester, progress

    def __getattr__(self, name):
        return getattr(self._requester, name)

    def get(self, url, **kwargs):
        response = self._requester.get(url, **kwargs)
        if not kwargs.get("stream") or not getattr(response, "ok", False):
            return response
        # a resumed download starts at the Content-Range offset, of the full size
        headers = response.headers
        m = re.match(r"^bytes (\d+)-\d+/(\d+)", headers.get("Content-Range", ""))
        if m:
            done, total = int(m[1]), int(m[2])
        else:
            done, total = 0, int(headers.get("Content-Length") or 0)
        original_iter = response.iter_content
        progress = self._progress

        def iter_content(*args, **kw):
            nonlocal done
            for chunk in original_iter(*args, **kw):
                done += len(chunk)
                progress.update(done / total if total else 0.0, done, total)
                yield chunk

        response.iter_content = iter_content
        return response


class _QuietTimedOutput:
    """FileDownloader's output minus its every-10s "Downloaded 12 MiB 30% x.tgz" lines."""

    def __init__(self, output):
        self._output = output

    def __getattr__(self, name):
        return getattr(self._output, name)

    def info(self, msg, *args, **kwargs):
        if not str(msg).startswith("Downloaded "):
            self._output.info(msg, *args, **kwargs)


class _WhileDownloading:
    """FileDownloader attribute that reads back wrapped while this thread downloads.

    Parallel downloads share one FileDownloader, so the attribute can't be swapped on
    the instance; a contextvar tells each thread which download it is running.
    """

    def __init__(self, name, wrap):
        self._name, self._wrap = name, wrap

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        value = obj.__dict__[self._name]
        progress = _downloading.get()
        return value if progress is None else self._wrap(value, progress)

    def __set__(self, obj, value):
        obj.__dict__[self._name] = value


def _patch_downloads():
    """Progress while Conan downloads recipes and packages from remotes, `download()`
    sources and `conan config install` archives: all go through
    FileDownloader._download_file(), which streams the response to disk.
    """
    import inspect

    from conan.internal.rest import file_downloader

    cls = getattr(file_downloader, "FileDownloader", None)
    original = getattr(cls, "_download_file", None)
    expected = [
        "self",
        "url",
        "auth",
        "headers",
        "file_path",
        "verify_ssl",
        "try_resume",
    ]
    if original is None or list(inspect.signature(original).parameters) != expected:
        return "file downloads"
    if not {"_requester", "_output"} <= set(cls.__init__.__code__.co_names):
        return "file downloads (FileDownloader attributes)"

    def _download_file(
        self, url, auth, headers, file_path, verify_ssl, try_resume=False
    ):
        def run():
            return original(
                self, url, auth, headers, file_path, verify_ssl, try_resume=try_resume
            )

        # resuming calls _download_file() again: keep the outer call's line
        if not _enabled() or _downloading.get() is not None:
            return run()
        scope = getattr(self._output, "scope", "") or ""
        progress = _Progress("downloading", os.path.basename(file_path), scope=scope)
        token = _downloading.set(progress)
        try:
            result = run()
        except BaseException:
            progress.stop()
            raise
        else:
            progress.done()
            return result
        finally:
            _downloading.reset(token)

    cls._requester = _WhileDownloading("_requester", _DownloadRequester)
    cls._output = _WhileDownloading("_output", lambda out, _: _QuietTimedOutput(out))
    cls._download_file = _download_file


# -- compression ---------------------------------------------------------------------------------

# Counter for the archive the current thread is writing (set by the compress_files patch)
_compressing = contextvars.ContextVar("progress_compressing", default=None)


class _Counter:
    """Bytes of input the files of one archive have contributed so far."""

    def __init__(self, progress, total):
        self._progress, self._total, self._done = progress, total, 0

    def add(self, size):
        self._done += size
        self._progress.update(
            self._done / self._total if self._total else 0.0, self._done, self._total
        )


class _CountingReader:
    """Source file for TarFile.addfile(), reporting what the archive reads from it."""

    def __init__(self, fileobj, counter):
        self._fileobj, self._counter = fileobj, counter

    def read(self, size=-1):
        block = self._fileobj.read(size)
        self._counter.add(len(block))
        return block


def _content_size(files, recursive):
    """Bytes tar will read: the files themselves, plus their trees when recursive."""
    total = 0
    for path in files.values():
        try:
            if os.path.islink(path):
                continue  # stored as a symlink, no content is read
            if os.path.isfile(path):
                total += os.path.getsize(path)
            elif recursive and os.path.isdir(path):
                for root, _, names in os.walk(path):
                    for name in names:
                        child = os.path.join(root, name)
                        if not os.path.islink(child):
                            total += os.path.getsize(child)
        except OSError:  # a file that vanished only skews the total
            pass
    return total


def _patch_compression():
    """Progress while `conan upload`/`conan cache save` write a .tgz/.txz/.tzst.

    The bar measures the uncompressed input: compress_files() sizes up the files first,
    then every format funnels their contents through TarFile.addfile(), whichever
    Python version is running. A format this Python cannot write (.tzst needs 3.14+)
    is rejected by Conan before compress_files() starts, so no line is drawn.
    """
    import inspect
    import tarfile

    from conan.api.subapi import cache as cache_mod
    from conan.internal.api import uploader

    original = getattr(uploader, "compress_files", None)
    expected = ["files", "name", "dest_dir", "compresslevel", "scope", "recursive"]
    if original is None or list(inspect.signature(original).parameters) != expected:
        return "archive compression"

    original_addfile = tarfile.TarFile.addfile
    if list(inspect.signature(original_addfile).parameters) != [
        "self",
        "tarinfo",
        "fileobj",
    ]:
        return "archive compression (tarfile.TarFile.addfile)"

    def addfile(self, tarinfo, fileobj=None):
        counter = _compressing.get()
        if counter is not None and fileobj is not None:
            fileobj = _CountingReader(fileobj, counter)
        return original_addfile(self, tarinfo, fileobj)

    tarfile.TarFile.addfile = addfile

    def compress_files(
        files, name, dest_dir, compresslevel=None, scope=None, recursive=False
    ):
        def run():
            return original(
                files,
                name,
                dest_dir,
                compresslevel=compresslevel,
                scope=scope,
                recursive=recursive,
            )

        # uploads can compress in parallel threads; each gets its own contextvar
        if not _enabled() or _compressing.get() is not None:
            return run()
        progress = _Progress("compressing", name, scope=scope or "")
        token = _compressing.set(_Counter(progress, _content_size(files, recursive)))
        try:
            result = run()
        except BaseException:
            progress.stop()  # a half-written archive is not 100% done
            raise
        else:
            progress.done()
            return result
        finally:
            _compressing.reset(token)

    uploader.compress_files = compress_files

    # `conan cache save` imported the function by name before this hook loaded
    if getattr(cache_mod, "compress_files", None) is original:
        cache_mod.compress_files = compress_files


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
    patches = (
        _patch_output,
        _patch_source_archives,
        _patch_package_downloads,
        _patch_downloads,
        _patch_compression,
        _patch_git,
    )
    for patch in patches:
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


try:
    _theme, _render = _load_theme()
except Exception as e:  # noqa: BLE001 - a broken theme must not break conan
    ConanOutput().warning(
        f"[hook_progress] can't load progress theme, no progress: {e}"
    )
    _theme = _render = None
_install()
