from conan import ConanFile
from conan.tools.build import can_run
from conan.tools.cmake import CMake, cmake_layout
from conan.tools.files import copy


class TestPackageConan(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    generators = "CMakeDeps", "CMakeToolchain"
    test_type = "explicit"

    def requirements(self):
        self.requires(self.tested_reference_str)

    def layout(self):
        cmake_layout(self)

    def generate(self):
        # Put DLLs next to the test, where Windows (and wine) look for them.
        if self.settings.os == "Windows":
            for dep in self.dependencies.host.values():
                for bindir in dep.cpp_info.bindirs:
                    copy(self, "*.dll", bindir, self.build_folder, keep_path=False)

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def test(self):
        args = ["--output-on-failure", "--verbose"]
        if can_run(self):
            CMake(self).ctest(args)
            return
        # Cross build: ctest runs the test through CMAKE_CROSSCOMPILING_EMULATOR (wine).
        # The run environment is for the target (.bat), so only the build one is used.
        variables = self.conf.get(
            "tools.cmake.cmaketoolchain:extra_variables", default={}, check_type=dict
        )
        if variables.get("CMAKE_CROSSCOMPILING_EMULATOR"):
            CMake(self).ctest(args, env="conanbuild")
