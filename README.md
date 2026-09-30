# conan_config

Example Conan 2 configuration repo for testing `conan config install`.

## Contents

| Path | Purpose |
|------|---------|
| `global.conf` | Global conf (default profiles, Ninja generator, parallel downloads) |
| `remotes.json` | Remotes: `conancenter` + a disabled placeholder internal remote |
| `settings_user.yml` | Adds `os.Linux.distro` sub-setting |
| `profiles/` | `base`, `linux-gcc-release`, `linux-gcc-debug`, `linux-clang-release`, `windows-msvc-release` |
| `extensions/hooks/hook_check_license.py` | `pre_export` hook warning on missing `license` |
| `extensions/hooks/hook_progress.py` | Progress for downloads, source extraction, package unpacking, archive compression (`conan upload`, `conan cache save`) and `git clone` (`CONAN_PROGRESS=0` disables) |
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
