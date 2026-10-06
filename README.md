# conan_config

Example Conan 2 configuration repo for testing `conan config install`.

## Contents

| Path | Purpose |
|------|---------|
| `global.conf` | Global conf (default profiles, Ninja generator, parallel downloads) |
| `remotes.json` | Remotes: `conancenter` + a disabled placeholder internal remote |
| `settings_user.yml` | Adds `os.Linux.distro` sub-setting |
| `profiles/` | `base`, `linux-gcc-release`, `linux-gcc-debug`, `linux-clang-release`, `windows-msvc-release`, `windows-x64-clangcl` (cross from Linux, see below) |
| `index/recipes/` | Recipes for the Windows cross toolchain (`xwin`, `msvc-sysroot`, `llvm`, `clang-cl-cross`, `wine`), served as the `conan_config` remote |
| `extensions/commands/recipes/cmd_index.py` | Adds `index/` as the `conan_config` local-recipes-index remote before every conan command + `conan recipes:index` |
| `extensions/commands/wine/cmd_run.py` | `conan wine:run app.exe [args]`: runs a Windows program with the `wine` package (Linux) |
| `extensions/hooks/hook_check_license.py` | `pre_export` hook warning on missing `license` |
| `extensions/hooks/hook_progress.py` | Progress for downloads, uploads, source extraction, package unpacking, archive compression (`conan upload`, `conan cache save`) and `git clone`; parallel operations get a line each (`CONAN_PROGRESS=0` disables) |
| `extensions/hooks/progress_themes/` | Progress line themes: `paru` (default), `btop`; pick with `CONAN_PROGRESS_THEME` |
| `dev/preview_progress.py` | Simulated preview of every theme (`python dev/preview_progress.py [theme]`); not installed |
| `extensions/hooks/hook_timing.py` | Times source/generate/build/package per package; `Step times` section at exit (`CONAN_TIMING=0` disables) |
| `extensions/commands/example/cmd_hello.py` | Custom command: `conan example:hello [name]` |
| `extensions/commands/sync/cmd_config.py` | Auto-sync before every conan command + `conan sync:config` |
| `.conanignore` | Files not copied into `CONAN_HOME` |

## Usage

```bash
# Install into an isolated Conan home
export CONAN_HOME=$(mktemp -d)
conan config install /path/to/conan_config        # from local folder
conan config install https://host/conan_config.git # from git
conan config install <url> --args="-b <branch>"     # specific branch

conan profile list
conan remote list
conan example:hello
```

## Auto-sync

Once installed, every `conan` command first compares the remote `main` head
(`git ls-remote`) with the last installed commit
(`$CONAN_HOME/.conan_config_installed_rev`). If it moved, the config is
reinstalled and the command re-runs with the new config. `conan sync:config`
forces a check now.

- `CONAN_CONFIG_SYNC_INTERVAL=<s>`: seconds between checks (default 1800, `0` = every command; a check costs ~0.4s)
- `CONAN_CONFIG_SYNC_SKIP=1`: disable (CI, offline)
- `CONAN_CONFIG_SYNC_URL` / `CONAN_CONFIG_SYNC_BRANCH`: use another repo/branch

## Cross-compiling for Windows (`windows-x64-clangcl`)

Builds Windows x64 binaries (MSVC ABI) on Linux with clang-cl and lld-link, and
runs their tests under wine. Conan provides every tool; only Conan 2 itself must
be installed. The profile uses `compiler.version=23`, which is in Conan's default
settings from 2.33 on. `settings_user.yml` adds it for older versions, so Arch's
`conan` 2.32 works too (tested).

```bash
conan install . -pr:h windows-x64-clangcl --build=missing \
    -c:a user.msvc_sysroot:accept_license=True     # needed once, see below
conan build . -pr:h windows-x64-clangcl            # ctest runs the .exe tests through wine
```

The profile's `[tool_requires]`:

| Package | Version | What it is |
|---------|---------|------------|
| `clang-cl-cross` | 1.0 | Injects a CMake toolchain (`user_toolchain`) and the compiler paths (`tools.build:compiler_executables`); requires the next two |
| `llvm` | 23.1.2 | clang-cl, lld-link, llvm-lib, llvm-rc and llvm-mt from the [official LLVM release](https://github.com/llvm/llvm-project/releases/tag/llvmorg-23.1.2). The download is 1.1 GiB `.tar.zst` with Python ≥ 3.14, otherwise 1.9 GiB `.tar.xz`. Only the needed files are extracted, ~590 MB packaged. Bundles ICU 70.1 (from ConanCenter, built from source): the official binaries are built on Ubuntu 22.04, and lld/llvm-mt link its ICU 70 |
| `msvc-sysroot` | 14.44.17.14 | MSVC CRT 14.44 + Windows SDK 10.0.26100 headers and import libraries, unpacked by `xwin` (~1.7 GB download, ~640 MB packaged) |
| `xwin` | 0.10.0 | [xwin](https://github.com/Jake-Shadle/xwin), used to build `msvc-sysroot` |
| `wine` | 11.18 | Portable WoW64 wine, vanilla (unpatched WineHQ source) from [Kron4ek's builds](https://github.com/Kron4ek/Wine-Builds), 100 MB download; see [Sources](#sources). Becomes `CMAKE_CROSSCOMPILING_EMULATOR`; `conan-wine` is wine with quiet defaults and its own prefix (`~/.cache/conan-wine-11.18`) |
| `cmake`, `ninja` | ConanCenter | |

All downloads are checked against SHA-256 hashes, except the CRT/SDK files, which
xwin checks against Microsoft's manifest.

### Sources

Official sources are used wherever they exist:

| Package | Source | How it's verified |
|---------|--------|-------------------|
| `llvm` | LLVM project's GitHub release | SHA-256 pinned. Build provenance checked when pinning: the archives are attested by `llvm/llvm-project`'s `release-binaries.yml` at the release tag (`gh attestation verify <archive> --repo llvm/llvm-project --bundle <archive>.jsonl`). Do this again when bumping the version |
| ICU 70.1 (in `llvm`) | ConanCenter recipe, built from the official ICU source | ConanCenter's pinned hash |
| `msvc-sysroot` | Microsoft's Visual Studio manifest, via xwin | xwin checks each file's hash from the manifest |
| `xwin` | xwin's GitHub release (official) | SHA-256 pinned, matches the published `.sha256` |
| `wine` | Kron4ek's builds (third party, see below) | SHA-256 pinned, matches the release's published `sha256sums.txt` |

**Why wine is the exception:** WineHQ publishes only source code and distribution
packages, not a portable build. Kron4ek's `vanilla` builds compile the official
WineHQ source tarball without patches, inside Ubuntu 18.04 chroots, so they need
only glibc 2.27 or newer. The build scripts are public (MIT). The trade-offs:

- One maintainer.
- The releases are built and uploaded by hand: no CI provenance and no signatures.
- The pinned hash proves only that the file hasn't changed since it was pinned.

The package is used only to run test programs. If that ever isn't enough, build
it yourself with Kron4ek's `create_ubuntu_bootstraps.sh` + `build_wine.sh`, or
write a recipe that builds wine from the WineHQ source.

**Microsoft license:** `msvc-sysroot` downloads the MSVC CRT and Windows SDK, which
are covered by the [Microsoft license](https://go.microsoft.com/fwlink/?LinkId=2086102).
Its build stops until you accept that license with
`-c:a user.msvc_sysroot:accept_license=True`. You only need this when the package is
built; after that it comes from the cache. The package has `upload_policy = "skip"`,
so `conan upload` never redistributes it.

**Download cache:** to keep the 1.7 GB of downloads across cache cleanups, add
`-c:a user.msvc_sysroot:cache_dir=/some/dir`.

**Limits:** Release only, because xwin doesn't include the debug CRT. The tools
are prebuilt for Linux x86_64 only. `profiles/base` skips ICU 70's own tests
(`icu/70.*:tools.build:skip_test=True`), which fail on Python ≥ 3.13.

### Running Windows programs: `conan wine:run`

```bash
conan wine:run build/Release/app.exe --some-arg
conan wine:run --wine "[~11]" app.exe      # another wine version or range
conan wine:run --wayland game.exe          # GUI programs on a Wayland desktop
conan wine:run --x11 game.exe              # force X11 (XWayland on a Wayland desktop)
```

The command:

- **Installs wine:** the newest `wine/*` from the `conan_config` remote, as a tool.
  It's built from the recipe the first time, then reused from the cache.
- **Runs the program with `conan-wine`:** its own prefix in
  `~/.cache/conan-wine-<version>`, no debug output, and no Mono/Gecko prompts.
  Set `WINEPREFIX` or `WINEDEBUG` to override those.
- **Hands over the process:** the program's exit code becomes conan's, so the
  command works in scripts.

It works with every Conan setup: the pacman/pip package, a venv, or a standalone
`conan-bin`. You don't need to install wine yourself.

#### GUI programs: `--wayland` or `--x11`

Wine has two graphics drivers on Linux: X11 (`winex11`) and Wayland
(`winewayland`). Without a flag, wine uses X11 whenever `DISPLAY` is set, so on a
Wayland desktop it draws through XWayland. The flags choose the driver:

| | no flag | `--wayland` | `--x11` |
|---|---|---|---|
| Driver | X11 if `DISPLAY` is set, else Wayland | Wayland | X11 only |
| Environment | unchanged | removes `DISPLAY` | removes `WAYLAND_DISPLAY` |
| Needs | either | `WAYLAND_DISPLAY` | `DISPLAY` |
| Window placement | the program (XWayland's monitor layout) | the compositor | the program (XWayland's monitor layout) |

The two flags can't be combined.

**Use `--wayland` when** the window opens off-screen or on the wrong monitor on a
Wayland desktop. The compositor's and XWayland's idea of the monitor layout can
differ. On Hyprland with two monitors, XWayland listed them in the opposite order,
so a game centred on "monitor 0" landed at x = −1440, off every screen. With
`--wayland`, the compositor places the window, and it opens on-screen. OpenGL
still runs on the real GPU (tested with an NVIDIA RTX 4070 Ti SUPER).

One harmless message may appear: `listener function for opcode 3 of
zwlr_data_control_device_v1 is NULL`. It comes from wine's clipboard helper; the
program keeps running.

**Use `--x11` when** the program needs control over its own windows, or misbehaves
under the Wayland driver. X11 is wine's older, more complete driver. Wayland
doesn't let programs place their own windows or read global screen coordinates,
so these behave as intended only on X11:

- programs that position their own windows, for example to restore saved window
  positions or to put a tool palette next to the main window
- programs that rely on features `winewayland` doesn't support yet

`--x11` fails early if there is no `DISPLAY`. It removes `WAYLAND_DISPLAY`, so
wine can't fall back to Wayland. Without a flag, wine already prefers X11, so the
flag mainly makes that choice explicit and strict. Neither flag overrides a
`Graphics` driver setting in the wine prefix's registry.

**Rule of thumb:** start without a flag. If the window is misplaced on a Wayland
desktop, try `--wayland`. If something breaks under `--wayland`, go back with
`--x11`.

### The `conan_config` remote

`conan config install` copies `index/` into `$CONAN_HOME`. A local-recipes-index
remote needs an absolute path, so `extensions/commands/recipes/cmd_index.py` adds
the remote itself. It runs before every conan command, does nothing if the remote
already exists, and puts it first. This also covers the auto-sync, which replaces
`remotes.json`.

- `conan recipes:index` adds the remote now and lists the recipes.
- `CONAN_CONFIG_INDEX_SKIP=1` turns the automatic step off.
- To add another recipe, create `index/recipes/<name>/config.yml` and
  `index/recipes/<name>/all/conanfile.py`, using the ConanCenter layout.

Test it end to end with `uv run win64-cross-demo/run.py --accept-msvc-license`
in the [conan-dev](../conan-dev) sandbox.
