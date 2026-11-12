# conan_config

Example Conan 2 configuration repo for testing `conan config install`.

## Contents

| Path | Purpose |
|------|---------|
| `global.conf` | Global conf (default profiles, Ninja generator, parallel downloads) |
| `remotes.json` | Remotes: `conancenter` + a disabled placeholder internal remote |
| `settings_user.yml` | Adds `os.Linux.distro` sub-setting |
| `profiles/` | `base`, `linux-gcc-release`, `linux-gcc-debug`, `linux-clang-release`, `windows-msvc-release`, `windows-x64-clangcl` (cross from Linux, see below), `jetson-orin` (cross for Jetson, see [GStreamer](#gstreamer-gst-plugins)) |
| `index/recipes/` | Recipes for the Windows cross toolchain (`xwin`, `msvc-sysroot`, `llvm`, `clang-cl-cross`, `wine`), `libxml2` (2.15.x, Linux + Windows) and `gst-plugins` (GStreamer 1.28.9 + gst-rtsp-server, Linux), served as the `conan_config` remote |
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
| `llvm` | 23.1.2 | clang-cl, lld-link, llvm-lib, llvm-rc, llvm-mt and llvm-ml (MASM) from the [official LLVM release](https://github.com/llvm/llvm-project/releases/tag/llvmorg-23.1.2). The download is 1.1 GiB `.tar.zst` with Python ≥ 3.14, otherwise 1.9 GiB `.tar.xz`. Only the needed files are extracted, ~640 MB packaged. Bundles ICU 70.1 (from ConanCenter, built from source): the official binaries are built on Ubuntu 22.04, and lld/llvm-mt link its ICU 70 |
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

## GStreamer: `gst-plugins`

One package holds GStreamer core plus gst-plugins-base, -good, -bad and
gst-rtsp-server, built from the five official tarballs on
<https://gstreamer.freedesktop.org/src/>. They're
unpacked as Meson subprojects of a two-line parent project, the way the GStreamer
monorepo builds them: one configure, one build, and the modules always have the
same version. Bumping it means a new `conandata.yml` entry with five URLs and hashes.

```bash
conan create index/recipes/gst-plugins/all --version 1.28.9 --build=missing
```

The build runs with `auto_features=disabled`, and the recipe lists the plugins to
build (`PLUGINS` in the `conanfile.py`). pkg-config sees only Conan's packages and
the system X11/GL modules the options ask for (`SYSTEM_PC`), so nothing turns on
just because a library happens to be installed on the build machine. Without that
limit, the `timecode` plugin quietly linked Arch's `libltc`. To add a plugin, add
its Meson option to `PLUGINS`, plus a requirement if it needs one.

| Option | Default | What it builds | Needs |
|---|---|---|---|
| `with_x11` | `True` | `ximagesink`, GL on X11/GLX | libX11, libX11-xcb, libxcb, libXext from the system |
| `with_gl` | `True` | gst-gl (`glimagesink`, ...), CUDA ↔ GL interop | EGL, GL, GLES from the system (libglvnd) |
| `with_nvcodec` | `True` | `nvh264enc`, `nvh265enc`, `nvh264dec`, ..., `cudaupload`, `cudaconvert` | nothing at build time |
| `with_v4l2` | `True` | `v4l2src`, V4L2 encoders/decoders | kernel headers |

GLib and zlib come from ConanCenter. GLib has to be shared (`glib/*:shared=True`
is the default here), because the plugins and the libraries must share one GLib
type system.

**X11 and GL are always system libraries.** No Conan package provides them, and
they're never packaged here. A native build (RHEL 9: `libX11-devel libXext-devel
libxcb-devel libglvnd-devel`) uses the build machine's own. A cross build uses
the ones in the sysroot. Either way, the target must have them at runtime: L4T
and any desktop do. The recipe copies those `.pc` files, and the ones they
require, next to Conan's. Conan's `pkgconf` searches only
`/lib/pkgconfig:/share/pkgconfig`, so on RHEL 9 (`/usr/lib64`) it wouldn't find
them on its own.

`profiles/base` turns off GLib's introspection
(`glib/*:tools.meson.mesontoolchain:extra_variables`). ConanCenter's glib leaves it
on `auto`, so it uses the machine's gobject-introspection, whose scanner crashed on
the system's gvfs modules. Profiles that don't include `base` (e.g. a cross
profile) need the same line if gobject-introspection is installed on the build
machine.

**nvcodec** needs no CUDA SDK. It loads `libcuda.so` and `libnvidia-encode.so`
at runtime, and its encoders and decoders register only when the NVIDIA driver
provides those libraries. `gst-inspect-1.0 nvcodec` shows what registered.

**Consumers:** `find_package(GStreamer)` gives one target per library, named after
its pkg-config module: `GStreamer::gstreamer`, `GStreamer::app`, `GStreamer::video`,
`GStreamer::gl`, `GStreamer::rtsp-server`, and so on. PkgConfigDeps gives the upstream names
(`gstreamer-1.0`, `gstreamer-video-1.0`, ...). The components come from the
installed `.pc` files, so they follow the options with no hand-kept list. The
run environment (`conanrun`) points `GST_PLUGIN_SYSTEM_PATH_1_0` and
`GST_PLUGIN_SCANNER_1_0` at the package, so a system GStreamer's plugins are never
loaded by mistake. Add other plugin folders with `GST_PLUGIN_PATH_1_0`.

It also sets `GIO_MODULE_DIR`, for the same reason. ConanCenter's glib is built
with prefix `/`, so GIO otherwise scans `/lib/gio/modules` (proxy resolvers,
gvfs, dconf, TLS) as soon as a program touches the network or a `GFile`. On Arch
that loads the system's modules, built against the system GLib. On RHEL `/lib` is
32-bit, and each module prints `wrong ELF class: ELFCLASS32`. System modules you
do want go in `GIO_EXTRA_MODULES`, e.g. glib-networking for `rtsps://`:
`GIO_EXTRA_MODULES=/usr/lib64/gio/modules` (RHEL) or `/usr/lib/gio/modules` (Arch).

### NVENC/NVDEC pipelines

Starting points for `nvh264dec` and `nvh264enc` on Ada GPUs (RTX 40 series, RTX
4000 Ada, ...). The same properties exist on `nvh265enc` and `nvav1enc`;
`gst-inspect-1.0 nvh264enc` lists them all.

**Low latency (live RTP/RTSP/WebRTC):**

```bash
... ! h264parse ! nvh264dec max-display-delay=0 discard-corrupted-frames=true \
  ! 'video/x-raw(memory:CUDAMemory)' \
  ! nvh264enc preset=p2 tune=ultra-low-latency rc-mode=cbr bitrate=8000 \
      vbv-buffer-size=267 zerolatency=true bframes=0 gop-size=120 repeat-sequence-header=true \
  ! h264parse config-interval=-1 ! rtph264pay ...
```

- `vbv-buffer-size` ≈ bitrate / fps (here 8000 / 30) is one frame of buffering:
  even frame sizes, low latency. Raise it if scene changes look bad.
- `repeat-sequence-header` and `config-interval=-1` let a receiver that joins
  mid-stream start at the next keyframe.
- `max-display-delay=0` stops the decoder from holding frames back.

**Quality (files, VOD):**

```bash
... ! h264parse ! nvh264dec ! 'video/x-raw(memory:CUDAMemory)' \
  ! nvh264enc preset=p6 tune=high-quality rc-mode=vbr const-quality=23 max-bitrate=20000 \
      rc-lookahead=20 bframes=3 b-adapt=true spatial-aq=true temporal-aq=true \
      multi-pass=two-pass-quarter gop-size=120 \
  ! h264parse ! mp4mux ! filesink location=out.mp4
```

- `const-quality` works like x264's CRF: lower is better and bigger. For a target
  size, use `bitrate` + `max-bitrate` instead.
- Lookahead and B-frames add frames of delay, so leave them out of live pipelines.

**What matters most**, measured with this package on an RTX 4070 Ti SUPER (1080p60
H.264 transcode, synthetic test clip, `fakesink sync=false`):

| Pipeline | fps |
|---|---|
| decode only | ~935 |
| `preset=p1 tune=ultra-low-latency` | ~890 |
| `preset=p4` | ~515 |
| `preset=p7 tune=high-quality`, lookahead, B-frames, AQ, two-pass | ~290 |
| 2 × `preset=p4` in parallel | ~925 total |

- The preset sets the speed: p1 to p7 is about 3×.
- One stream uses one NVENC engine. Ada cards with two engines (4070 Ti and up,
  RTX 4000 Ada) only reach full throughput with two or more streams at once.
- Keep frames in `memory:CUDAMemory` from decoder to encoder: no `videoconvert`
  or `videoscale` in between. Scale on the GPU:
  `cudaconvertscale ! 'video/x-raw(memory:CUDAMemory),width=1280,height=720'`. For one 1080p stream
  the encoder is the limit and a round trip through system memory cost nothing
  measurable. With 4K or many streams, it does.
- Feed the encoder NV12. RGBA/BGRx are converted on the GPU; Y444 gives the
  `high-4:4:4` profile.
- If the input changes resolution, set `init-max-width`/`init-max-height` on
  `nvh264dec` so it doesn't rebuild the decoder.
- H.264 tops out at 4096×4096 here. Use `nvh265enc` or `nvav1enc` beyond that;
  Ada's AV1 also gives better quality per bit.
- `nvidia-smi dmon -s u` shows encoder/decoder load. An encoder near 100% means
  a faster preset or more parallel streams.

### Cross-compiling for Jetson (L4T)

`profiles/jetson-orin` targets JetPack 6 (L4T R36: Ubuntu 22.04, glibc 2.35,
GCC 11). It needs your cross GCC and a sysroot that matches the target, e.g. the
L4T sample rootfs or a copy of a Jetson's `/usr` and `/lib`:

```bash
export JETSON_TOOLCHAIN=/opt/toolchains/aarch64-gcc11   # the folder with bin/
export JETSON_SYSROOT=/opt/l4t/rootfs
export JETSON_CROSS_PREFIX=aarch64-linux-gnu-           # the default; NVIDIA's Bootlin
                                                        # toolchain: aarch64-buildroot-linux-gnu-
conan create index/recipes/gst-plugins/all --version 1.28.9 -pr:h jetson-orin --build=missing
```

Ubuntu keeps libraries and some headers in multiarch folders
(`aarch64-linux-gnu`). A Debian/Ubuntu cross GCC searches them; a generic
toolchain (Bootlin, Arm GNU) doesn't. For one of those, uncomment the flags at the
end of the profile.

The X11/GL `.pc` files come from the sysroot, with their absolute paths moved into
it. `PKG_CONFIG_SYSROOT_DIR` can't do this, because pkgconf would also prefix
Conan's own package paths. The build machine's x86_64 libraries can't leak in.
`-Wl,-rpath-link` to the sysroot's multiarch dirs lets ld resolve libX11's own
dependencies.

If the sysroot has no X11 (or GL) development files, build with
`-o "gst-plugins/*:with_x11=False"` (and `with_gl=False` if EGL/GLES are missing
too). With `with_x11=False`, GL still works headless or on EGL
(`gl_winsys=egl,surfaceless`).

**Hardware encoding on Orin:** upstream nvcodec's NVENC/NVDEC elements are for
desktop GPUs. Upstream compiles them out on Tegra builds that have NVMM support,
and Orin's JetPack drivers don't provide `libnvidia-encode.so`. On Orin, the
encoder is NVIDIA's `nvv4l2h264enc`/`nvv4l2h265enc` from L4T
(`/usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstnvvideo4linux2.so`). It's an
ordinary 1.x plugin that runs on this core:
`GST_PLUGIN_PATH_1_0=/usr/lib/aarch64-linux-gnu/gstreamer-1.0`.
`h264parse`, `rtph264pay`, `mpegtsmux` etc. still come from this package.
