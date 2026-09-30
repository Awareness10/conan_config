"""Preview the progress themes in your terminal (simulated, nothing is downloaded).

Usage: python dev/preview_progress.py [theme ...]   (no argument: every theme)
"""

import importlib.util
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "extensions", "hooks", "hook_progress.py")


def load_hook():
    spec = importlib.util.spec_from_file_location("hook_progress", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def archive(hook, scope, verb, name, size, seconds, transfer=False):
    p = hook._Progress(verb, name, scope=scope, transfer=transfer)
    steps = int(seconds / 0.05)
    for i in range(1, steps + 1):
        time.sleep(0.05)
        done = size * i // steps
        p.update(done / size, done, size)
    p.done()


def git_clone(hook, scope):
    p = hook._Progress("git clone", "", scope=scope)
    total = 157
    phases = [
        ("counting objects", 0.6, lambda n: f"({n}/{total})"),
        (
            "receiving objects",
            1.8,
            lambda n: f"({n}/{total}), {n * 0.0078:.2f} MiB | 2.30 MiB/s",
        ),
        ("resolving deltas", 0.5, lambda n: f"({n}/{total})"),
    ]
    for phase, seconds, detail in phases:
        p.state.name = phase
        steps = int(seconds / 0.05)
        for i in range(1, steps + 1):
            time.sleep(0.05)
            n = total * i // steps
            p.update(n / total, detail=detail(n))
    p.done()


def parallel(hook, verb, packages):
    """Transfers in threads, like core.download:parallel, with Conan chatter between."""
    from conan.api.output import ConanOutput

    def one(scope, size, seconds):
        ConanOutput(scope=scope).info(f"{verb.capitalize()} conan_package.tgz")
        archive(hook, scope, verb, "conan_package.tgz", size, seconds, transfer=True)
        ConanOutput(scope=scope).info("Package installed")

    threads = [threading.Thread(target=one, args=package) for package in packages]
    for thread in threads:
        thread.start()
        time.sleep(0.3)
    for thread in threads:
        thread.join()


def preview(theme):
    os.environ["CONAN_PROGRESS_THEME"] = theme
    hook = load_hook()  # the theme is picked when the hook loads
    print(f"\n=== CONAN_PROGRESS_THEME={theme} ===", file=sys.stderr)
    archive(hook, "cmake/3.31.12", "downloading", "conan_package.tgz", 45_100_000, 2.5)
    archive(hook, "cmake/3.31.12", "unpacking", "conan_package.tgz", 45_100_000, 2.5)
    archive(
        hook, "boost/1.86.0", "extracting", "boost_1_86_0.tar.bz2", 124_000_000, 3.0
    )
    archive(hook, "demo/0.1", "compressing", "conan_package.tgz", 88_000_000, 2.0)
    git_clone(hook, "demo/0.1")
    packages = [
        ("zlib/1.3.1", 12_000_000, 1.5),
        ("openssl/3.4.1", 48_000_000, 3.0),
        ("boost/1.86.0", 160_000_000, 4.0),
        ("fmt/11.1.4", 9_000_000, 1.2),
    ]
    parallel(hook, "downloading", packages)
    parallel(hook, "uploading", packages[:2])


if __name__ == "__main__":
    themes = sys.argv[1:]
    if len(themes) == 1:
        preview(themes[0])
    else:  # one process per theme: hook_progress patches Conan once per process
        folder = os.path.join(ROOT, "extensions", "hooks", "progress_themes")
        names = themes or sorted(
            f[:-3]
            for f in os.listdir(folder)
            if f.endswith(".py") and not f.startswith("_")
        )
        for name in names:
            subprocess.run([sys.executable, __file__, name], check=False)
