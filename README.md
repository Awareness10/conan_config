# conan_config

Example Conan 2 configuration repo for testing `conan config install`.

## Contents

| Path | Purpose |
|------|---------|
| `global.conf` | Global conf (default profiles, Ninja generator, parallel downloads) |
| `remotes.json` | Remotes: `conancenter` + a disabled placeholder internal remote |
| `settings_user.yml` | Adds `os.Linux.distro` sub-setting |
| `profiles/` | `base`, `linux-gcc-release`, `linux-gcc-debug`, `linux-clang-release`, `windows-msvc-release`, `windows-x64-clangcl` (cross from Linux, see below) |
| `index/recipes/` | Recipes for the Windows cross toolchain (`xwin`, `msvc-sysroot`, `llvm-mingw`, `clang-cl-cross`, `wine`), served as the `conan_config` remote |
| `extensions/commands/recipes/cmd_index.py` | Adds `index/` as the `conan_config` local-recipes-index remote before every conan command + `conan recipes:index` |
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
runs their tests under wine. Conan provides every tool; only Conan itself must be
installed (2.33.0 or newer: the profile uses `compiler.version=23`).

```bash
conan install . -pr:h windows-x64-clangcl --build=missing \
    -c:a user.msvc_sysroot:accept_license=True     # needed once, see below
conan build . -pr:h windows-x64-clangcl            # ctest runs the .exe tests through wine
```

The profile's `[tool_requires]`:

| Package | Version | What it is |
|---------|---------|------------|
| `clang-cl-cross` | 1.0 | Injects a CMake toolchain (`user_toolchain`) and the compiler paths (`tools.build:compiler_executables`); requires the next two |
| `llvm-mingw` | 20260922 | clang/clang-cl, lld-link, llvm-lib, llvm-rc from LLVM 23.1.2 ([llvm-mingw](https://github.com/mstorsjo/llvm-mingw) release, 80 MB download, ~175 MB packaged) |
| `msvc-sysroot` | 14.44.17.14 | MSVC CRT 14.44 + Windows SDK 10.0.26100 headers and import libraries, unpacked by `xwin` (~1.7 GB download, ~640 MB packaged) |
| `xwin` | 0.10.0 | [xwin](https://github.com/Jake-Shadle/xwin), used to build `msvc-sysroot` |
| `wine` | 11.18 | Portable WoW64 wine ([Kron4ek builds](https://github.com/Kron4ek/Wine-Builds), 100 MB download). Becomes `CMAKE_CROSSCOMPILING_EMULATOR`; `conan-wine` is wine with quiet defaults and its own prefix (`~/.cache/conan-wine-11.18`) |
| `cmake`, `ninja` | ConanCenter | |

All downloads are checked against SHA-256 hashes, except the CRT/SDK files, which
xwin checks against Microsoft's manifest.

**Microsoft license:** `msvc-sysroot` downloads the MSVC CRT and Windows SDK, which
are covered by the [Microsoft license](https://go.microsoft.com/fwlink/?LinkId=2086102).
Its build stops until you accept that license with
`-c:a user.msvc_sysroot:accept_license=True`. You only need this when the package is
built; after that it comes from the cache. The package has `upload_policy = "skip"`,
so `conan upload` never redistributes it.

**Download cache:** to keep the 1.7 GB of downloads across cache cleanups, add
`-c:a user.msvc_sysroot:cache_dir=/some/dir`.

**Limits:** Release only, because xwin doesn't include the debug CRT. The tools
are prebuilt for Linux x86_64 only.

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
