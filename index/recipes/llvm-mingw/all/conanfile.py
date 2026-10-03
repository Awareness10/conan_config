import os

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.files import copy, get

required_conan_version = ">=2.0"

# The tools clang-cl cross builds need. LLVM tools pick their mode from the name
# they're called by, so clang-cl is a link to clang (added in package()).
_TOOLS = [
    "clang",
    "clang++",
    "clang-[0-9]*",
    "lld",
    "lld-link",
    "ld.lld",
    "llvm-ar",
    "llvm-lib",
    "llvm-ranlib",
    "llvm-rc",
    "llvm-cvtres",
    "llvm-ml",
    "llvm-nm",
    "llvm-objdump",
    "llvm-readobj",
    "llvm-strip",
]


class LlvmMingwConan(ConanFile):
    """clang, lld and the LLVM binutils from mstorsjo's llvm-mingw release.

    Only the host tools and clang's resource headers are packaged (~175 MB of the
    616 MB archive): the MinGW sysroots aren't needed for clang-cl + MSVC targets.
    """

    name = "llvm-mingw"
    description = (
        "Prebuilt LLVM/Clang/LLD toolchain (subset used for clang-cl cross builds)"
    )
    license = "Apache-2.0 WITH LLVM-exception"
    homepage = "https://github.com/mstorsjo/llvm-mingw"
    url = "https://github.com/Awareness10/conan_config"
    topics = ("llvm", "clang", "clang-cl", "lld", "toolchain")
    package_type = "application"
    settings = "os", "arch"

    def _source(self):
        sources = self.conan_data["sources"][self.version]
        return sources.get(str(self.settings.os), {}).get(str(self.settings.arch))

    def validate(self):
        if self._source() is None:
            raise ConanInvalidConfiguration(
                f"No prebuilt llvm-mingw {self.version} for {self.settings.os}/{self.settings.arch}"
            )

    def build(self):
        get(self, **self._source(), strip_root=True)

    def package(self):
        bindir = os.path.join(self.package_folder, "bin")
        for pattern in _TOOLS:
            copy(self, pattern, os.path.join(self.build_folder, "bin"), bindir)
        libsrc = os.path.join(self.build_folder, "lib")
        libdst = os.path.join(self.package_folder, "lib")
        for pattern in ("libLLVM.so*", "libLLVM-*.so", "libclang-cpp.so*", "clang/*"):
            copy(self, pattern, libsrc, libdst)
        copy(
            self,
            "LICENSE.TXT",
            self.build_folder,
            os.path.join(self.package_folder, "licenses"),
        )
        if not os.path.lexists(os.path.join(bindir, "clang-cl")):
            os.symlink("clang", os.path.join(bindir, "clang-cl"))

    def package_info(self):
        self.cpp_info.includedirs = []
        self.cpp_info.libdirs = []
        self.cpp_info.bindirs = ["bin"]
