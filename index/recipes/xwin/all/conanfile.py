import os

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.files import copy, get

required_conan_version = ">=2.0"


class XwinConan(ConanFile):
    name = "xwin"
    description = (
        "Downloads and repackages the MSVC CRT and Windows SDK for cross-compiling"
    )
    license = ("MIT", "Apache-2.0")
    homepage = "https://github.com/Jake-Shadle/xwin"
    url = "https://github.com/Awareness10/conan_config"
    topics = ("windows", "msvc", "sdk", "cross-compiling")
    package_type = "application"
    settings = "os", "arch"

    def _source(self):
        sources = self.conan_data["sources"][self.version]
        return sources.get(str(self.settings.os), {}).get(str(self.settings.arch))

    def validate(self):
        if self._source() is None:
            raise ConanInvalidConfiguration(
                f"No prebuilt xwin {self.version} for {self.settings.os}/{self.settings.arch}"
            )

    def build(self):
        get(self, **self._source(), strip_root=True)

    def package(self):
        copy(
            self,
            "LICENSE-*",
            self.build_folder,
            os.path.join(self.package_folder, "licenses"),
        )
        copy(self, "xwin", self.build_folder, os.path.join(self.package_folder, "bin"))

    def package_info(self):
        self.cpp_info.includedirs = []
        self.cpp_info.libdirs = []
        self.cpp_info.bindirs = ["bin"]
