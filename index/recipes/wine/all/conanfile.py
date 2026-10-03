import os
import stat
import textwrap

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.files import copy, get, save

required_conan_version = ">=2.0"


class WineConan(ConanFile):
    """Portable Wine, to run cross-compiled Windows programs (tests) on Linux.

    Adds `conan-wine` (wine with quiet, prompt-free defaults and its own prefix) and
    makes it CMake's CMAKE_CROSSCOMPILING_EMULATOR, so ctest runs Windows tests.
    The prefix defaults to ~/.cache/conan-wine-<version>; set WINEPREFIX to override.
    """

    name = "wine"
    description = "Portable Wine build, used as the CMake cross-compiling emulator"
    license = "LGPL-2.1-or-later"
    homepage = "https://www.winehq.org"
    url = "https://github.com/Awareness10/conan_config"
    topics = ("wine", "windows", "emulator", "cross-compiling", "testing")
    package_type = "application"
    settings = "os", "arch"

    def _source(self):
        sources = self.conan_data["sources"][self.version]
        return sources.get(str(self.settings.os), {}).get(str(self.settings.arch))

    def validate(self):
        if self._source() is None:
            raise ConanInvalidConfiguration(
                f"No prebuilt wine {self.version} for {self.settings.os}/{self.settings.arch}"
            )

    def build(self):
        get(self, **self._source(), strip_root=True)

    def package(self):
        for folder in ("bin", "lib", "share"):
            copy(
                self,
                "*",
                os.path.join(self.build_folder, folder),
                os.path.join(self.package_folder, folder),
            )
        save(
            self,
            os.path.join(self.package_folder, "licenses", "NOTICE"),
            textwrap.dedent(f"""\
            Wine {self.version} is licensed under the LGPL-2.1-or-later:
            https://gitlab.winehq.org/wine/wine/-/blob/wine-{self.version}/COPYING.LIB
            Binaries from https://github.com/Kron4ek/Wine-Builds
        """),
        )
        wrapper = os.path.join(self.package_folder, "bin", "conan-wine")
        save(
            self,
            wrapper,
            textwrap.dedent(f"""\
            #!/bin/sh
            # wine with defaults for running console programs non-interactively.
            here=$(dirname "$(readlink -f "$0")")
            : "${{WINEPREFIX:=${{XDG_CACHE_HOME:-$HOME/.cache}}/conan-wine-{self.version}}}"
            : "${{WINEDEBUG:=-all}}"
            : "${{WINEDLLOVERRIDES:=mscoree,mshtml=}}"  # no Mono/Gecko install prompts
            export WINEPREFIX WINEDEBUG WINEDLLOVERRIDES
            mkdir -p "$(dirname "$WINEPREFIX")"
            exec "$here/wine" "$@"
        """),
        )
        os.chmod(
            wrapper,
            os.stat(wrapper).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
        )

    def package_info(self):
        self.cpp_info.includedirs = []
        self.cpp_info.libdirs = []
        self.cpp_info.bindirs = ["bin"]
        emulator = os.path.join(self.package_folder, "bin", "conan-wine")
        self.conf_info.update(
            "tools.cmake.cmaketoolchain:extra_variables",
            {"CMAKE_CROSSCOMPILING_EMULATOR": emulator},
        )
