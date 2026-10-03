import fnmatch
import os
import sys
import tarfile

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.files import copy, download

required_conan_version = ">=2.0"

# What clang-cl cross builds need from the 11.5 GiB release; nothing else is unpacked.
# LLVM tools pick their mode from the name they're called by (clang-cl -> clang).
_KEEP = [
    "bin/clang",
    "bin/clang++",
    "bin/clang-cl",
    "bin/clang-[0-9]*",
    "bin/lld",
    "bin/lld-link",
    "bin/ld.lld",
    "bin/llvm-ar",
    "bin/llvm-lib",
    "bin/llvm-ranlib",
    "bin/llvm-rc",
    "bin/llvm-mt",
    "bin/llvm-cvtres",
    "lib/clang/*/include/*",
]


class LlvmConan(ConanFile):
    """clang/clang-cl, lld/lld-link, llvm-lib, llvm-rc and llvm-mt from the official
    LLVM release (~550 MB packaged).

    The official Linux binaries are built on Ubuntu 22.04: lld and llvm-mt link
    ICU 70 (through libxml2), which newer distributions don't have. ICU 70.1 from
    ConanCenter is bundled into lib/, where their RUNPATH ($ORIGIN/../lib) finds it.
    """

    name = "llvm"
    description = (
        "Official LLVM release binaries (clang-cl, lld-link and the LLVM binutils)"
    )
    license = "Apache-2.0 WITH LLVM-exception"
    homepage = "https://llvm.org"
    url = "https://github.com/Awareness10/conan_config"
    topics = ("llvm", "clang", "clang-cl", "lld", "toolchain")
    package_type = "application"
    settings = "os", "arch"

    def _sources(self):
        sources = self.conan_data["sources"][self.version]
        return sources.get(str(self.settings.os), {}).get(str(self.settings.arch))

    def validate(self):
        if self._sources() is None:
            raise ConanInvalidConfiguration(
                f"No official LLVM {self.version} binaries for "
                f"{self.settings.os}/{self.settings.arch}"
            )

    def requirements(self):
        self.requires(
            "icu/70.1",
            options={"shared": True, "data_packaging": "library", "with_icuio": False},
            visible=False,
        )

    def build(self):
        # Python >= 3.14 reads zstd: 1.1 GiB to download instead of 1.9 GiB.
        archive = self._sources()["zst" if sys.version_info >= (3, 14) else "xz"]
        filename = os.path.basename(archive["url"])
        download(self, archive["url"], filename, sha256=archive["sha256"])
        self._extract(filename, os.path.join(self.build_folder, "llvm"))
        os.remove(filename)
        license_file = self.conan_data["license"][self.version]
        download(
            self, license_file["url"], "LICENSE.TXT", sha256=license_file["sha256"]
        )

    def _extract(self, archive, dest):
        """Stream the tarball and extract only the _KEEP paths (top folder stripped)."""
        if archive.endswith(".zst"):
            from compression import zstd

            # LLVM compresses with --long=30 (1 GiB window); decoders refuse windows
            # over 128 MiB by default, which is why conan's get() can't unpack it.
            options = {zstd.DecompressionParameter.window_log_max: 31}
            stream, mode = zstd.ZstdFile(archive, options=options), "r|"
        else:
            stream, mode = open(archive, "rb"), "r|xz"  # noqa: SIM115 - closed below
        extract_args = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        with stream, tarfile.open(fileobj=stream, mode=mode) as tar:
            for member in tar:
                rel = member.name.partition("/")[2]
                if not any(fnmatch.fnmatchcase(rel, p) for p in _KEEP):
                    continue
                member.name = rel
                if member.islnk():  # hard link targets are archive paths too
                    member.linkname = member.linkname.partition("/")[2]
                tar.extract(member, dest, **extract_args)

    def package(self):
        src = os.path.join(self.build_folder, "llvm")
        copy(
            self,
            "*",
            os.path.join(src, "bin"),
            os.path.join(self.package_folder, "bin"),
        )
        copy(
            self,
            "*",
            os.path.join(src, "lib", "clang"),
            os.path.join(self.package_folder, "lib", "clang"),
        )
        licenses = os.path.join(self.package_folder, "licenses")
        copy(self, "LICENSE.TXT", self.build_folder, licenses)

        icu = self.dependencies["icu"]
        for libdir in icu.cpp_info.libdirs:
            for lib in ("icuuc", "icui18n", "icudata"):  # what lld and llvm-mt link
                copy(
                    self,
                    f"lib{lib}.so.70*",
                    libdir,
                    os.path.join(self.package_folder, "lib"),
                )
        copy(
            self,
            "*",
            os.path.join(icu.package_folder, "licenses"),
            os.path.join(licenses, "icu"),
        )

    def package_info(self):
        self.cpp_info.includedirs = []
        self.cpp_info.libdirs = []
        self.cpp_info.bindirs = ["bin"]
