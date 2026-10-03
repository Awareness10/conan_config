import os

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.files import copy

required_conan_version = ">=2.0"

# Conan arch -> (clang target triple, xwin library folder)
_TARGETS = {
    "x86_64": ("x86_64-pc-windows-msvc", "x86_64"),
    "x86": ("i686-pc-windows-msvc", "x86"),
    "armv8": ("aarch64-pc-windows-msvc", "aarch64"),
}


class ClangClCrossConan(ConanFile):
    """Cross-compile for Windows from Linux with clang-cl + lld-link + the MSVC sysroot.

    Use it as a tool_requires in a Windows host profile with compiler=clang and
    compiler.runtime set. It injects a CMake toolchain (user_toolchain) and the
    compiler paths (tools.build:compiler_executables); llvm and msvc-sysroot
    come with it.
    """

    name = "clang-cl-cross"
    description = (
        "clang-cl/lld-link toolchain for cross-compiling to Windows (MSVC ABI)"
    )
    license = "MIT"
    url = "https://github.com/Awareness10/conan_config"
    topics = ("clang-cl", "msvc", "windows", "cross-compiling", "toolchain")
    package_type = "build-scripts"
    exports_sources = "cmake/*"

    def requirements(self):
        self.requires("llvm/23.1.2", run=True)
        self.requires("msvc-sysroot/14.44.17.14")

    def validate(self):
        target = self.settings_target
        if target is None:
            return
        if target.get_safe("os") != "Windows":
            raise ConanInvalidConfiguration(f"{self.ref} only targets os=Windows")
        if target.get_safe("compiler") != "clang" or not target.get_safe(
            "compiler.runtime"
        ):
            raise ConanInvalidConfiguration(
                f"{self.ref} needs compiler=clang with compiler.runtime set (clang-cl)"
            )
        if target.get_safe("arch") not in _TARGETS:
            raise ConanInvalidConfiguration(
                f"{self.ref}: unsupported arch {target.get_safe('arch')}"
            )

    def package(self):
        copy(
            self,
            "*.cmake",
            os.path.join(self.source_folder, "cmake"),
            os.path.join(self.package_folder, "res"),
        )

    def package_info(self):
        self.cpp_info.includedirs = []
        self.cpp_info.libdirs = []
        self.cpp_info.bindirs = []

        arch = (
            self.settings_target.get_safe("arch") if self.settings_target else "x86_64"
        )
        triple, libarch = _TARGETS.get(arch, _TARGETS["x86_64"])
        llvm_bin = os.path.join(self.dependencies["llvm"].package_folder, "bin")
        msvc_sysroot = self.dependencies["msvc-sysroot"]
        sysroot = msvc_sysroot.package_folder
        # CRT 14.44 is the v144 toolset, i.e. MSVC 19.44 (_MSC_VER 1944). clang-cl can't
        # detect it without a Visual Studio install, so it's passed explicitly.
        crt = str(msvc_sysroot.ref.version).split(".")
        msvc_version = f"{int(crt[0]) + 5}.{crt[1]}"

        # Read by res/clang-cl-cross.cmake (CMake presets carry the build environment).
        self.buildenv_info.define_path("CLANG_CL_CROSS_LLVM_BIN", llvm_bin)
        self.buildenv_info.define_path("CLANG_CL_CROSS_SYSROOT", sysroot)
        self.buildenv_info.define("CLANG_CL_CROSS_TRIPLE", triple)
        self.buildenv_info.define("CLANG_CL_CROSS_LIBARCH", libarch)
        self.buildenv_info.define("CLANG_CL_CROSS_MSVC_VERSION", msvc_version)

        self.conf_info.append(
            "tools.cmake.cmaketoolchain:user_toolchain",
            os.path.join(self.package_folder, "res", "clang-cl-cross.cmake"),
        )
        clang_cl = os.path.join(llvm_bin, "clang-cl")
        self.conf_info.define(
            "tools.build:compiler_executables",
            {"c": clang_cl, "cpp": clang_cl, "rc": os.path.join(llvm_bin, "llvm-rc")},
        )
