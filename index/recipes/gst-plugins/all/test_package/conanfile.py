import os

from conan import ConanFile
from conan.tools.build import can_run
from conan.tools.cmake import CMake, cmake_layout


class TestPackageConan(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    generators = "CMakeDeps", "CMakeToolchain"
    test_type = "explicit"

    def requirements(self):
        self.requires(self.tested_reference_str)

    def layout(self):
        cmake_layout(self)

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def test(self):
        if not can_run(self):
            return
        nvcodec = str(self.dependencies[self.tested_reference_str].options.with_nvcodec)
        test = os.path.join(self.cpp.build.bindir, "test_package")
        self.run(f"{test} {nvcodec}", env="conanrun")
        self.run("gst-inspect-1.0 --version", env="conanrun")
