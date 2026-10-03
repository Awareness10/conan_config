import os
import textwrap

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.files import save

required_conan_version = ">=2.0"

LICENSE_URL = "https://go.microsoft.com/fwlink/?LinkId=2086102"

# Conan arch -> xwin arch
_XWIN_ARCH = {"x86_64": "x86_64", "x86": "x86", "armv8": "aarch64"}


class MsvcSysrootConan(ConanFile):
    """The MSVC CRT and Windows SDK headers and import libraries, unpacked by xwin.

    Use it as a tool_requires: the target architecture comes from the host profile
    (settings_target). Building it downloads ~1.7 GB from Microsoft and needs the
    Microsoft license to be accepted explicitly:

        -c:a user.msvc_sysroot:accept_license=True
    """

    name = "msvc-sysroot"
    description = "MSVC CRT + Windows SDK (headers and import libs) for cross-compiling to Windows"
    license = "LicenseRef-Microsoft-Visual-Studio"
    homepage = "https://github.com/Jake-Shadle/xwin"
    url = "https://github.com/Awareness10/conan_config"
    topics = ("windows", "msvc", "sdk", "crt", "cross-compiling")
    package_type = "unknown"
    upload_policy = "skip"  # Microsoft's license does not allow redistributing it

    def _target_arch(self):
        target = self.settings_target
        return (
            str(target.arch)
            if target is not None and target.get_safe("arch")
            else "x86_64"
        )

    def package_id(self):
        # Only the target architecture changes the content.
        self.info.settings_target = self.settings_target
        if self.info.settings_target is not None:
            for field in list(self.info.settings_target.fields):
                if field != "arch":
                    self.info.settings_target.rm_safe(field)

    def validate(self):
        target = self.settings_target
        if target is not None and target.get_safe("os") not in (None, "Windows"):
            raise ConanInvalidConfiguration(f"{self.ref} is for Windows targets only")
        if self._target_arch() not in _XWIN_ARCH:
            raise ConanInvalidConfiguration(
                f"{self.ref}: unsupported arch {self._target_arch()}"
            )

    def validate_build(self):
        if not self.conf.get("user.msvc_sysroot:accept_license", check_type=bool):
            raise ConanInvalidConfiguration(
                f"{self.ref} downloads the Microsoft CRT and Windows SDK. Read the license "
                f"at {LICENSE_URL} and accept it with -c:a user.msvc_sysroot:accept_license=True"
            )

    def build_requirements(self):
        self.tool_requires("xwin/0.10.0")

    def package(self):
        data = self.conan_data["versions"][self.version]
        # Persistent download cache (optional) so a rebuild doesn't download 1.7 GB again.
        cache = self.conf.get("user.msvc_sysroot:cache_dir") or os.path.join(
            self.build_folder, "xwin-cache"
        )
        self.run(
            f"xwin --accept-license --manifest-version {data['manifest']}"
            f" --crt-version {data['crt']} --sdk-version {data['sdk']}"
            f' --arch {_XWIN_ARCH[self._target_arch()]} --cache-dir "{cache}"'
            f' splat --copy --output "{self.package_folder}"'
        )
        save(
            self,
            os.path.join(self.package_folder, "licenses", "NOTICE"),
            textwrap.dedent(f"""\
                MSVC CRT {data["crt"]} and Windows SDK {data["sdk"]}, downloaded from
                Microsoft by xwin. Use is subject to the Microsoft license:
                {LICENSE_URL}
                Do not redistribute this package.
            """),
        )

    def package_info(self):
        self.cpp_info.includedirs = []
        self.cpp_info.libdirs = []
        self.cpp_info.bindirs = []
        self.conf_info.define_path("user.msvc_sysroot:path", self.package_folder)
        self.buildenv_info.define_path("MSVC_SYSROOT", self.package_folder)
