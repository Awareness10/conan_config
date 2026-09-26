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
| `extensions/commands/example/cmd_hello.py` | Custom command: `conan example:hello [name]` |
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
