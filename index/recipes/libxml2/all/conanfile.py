import os

from conan import ConanFile
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.files import copy, get, replace_in_file, rm, rmdir

required_conan_version = ">=2.4"


class Libxml2Conan(ConanFile):
    """libxml2, built with its own CMake build, for Linux and Windows (MSVC ABI).

    CMake consumers get libxml2's own libxml2-config.cmake, as with a normal install:
    find_package(LibXml2) gives LibXml2::LibXml2 plus the LIBXML2_* variables. LLVM
    (llvm-mt) needs both, including the target's library location, which
    Conan-generated CMake files don't provide.

    A static build with_icu/with_zlib puts those Conan targets in LIBXML2_LIBRARIES;
    configure checks (LLVM's HAVE_LIBXML2) then need
    -DCMAKE_TRY_COMPILE_CONFIGURATION=<build type> to link them.
    """

    name = "libxml2"
    description = "XML parser and toolkit from the GNOME project"
    license = "MIT"
    homepage = "https://gitlab.gnome.org/GNOME/libxml2"
    url = "https://github.com/Awareness10/conan_config"
    topics = ("xml", "parser", "validation")
    package_type = "library"
    settings = "os", "arch", "compiler", "build_type"
    languages = "C"
    # No fPIC option: the library is always built with POSITION_INDEPENDENT_CODE.
    options = {  # noqa: RUF012 - Conan reads these class attributes
        "shared": [True, False],
        "with_iconv": [True, False],
        "with_icu": [True, False],
        "with_zlib": [True, False],
        "programs": [True, False],
    }
    default_options = {  # noqa: RUF012
        "shared": False,
        "with_iconv": True,
        "with_icu": False,
        "with_zlib": False,
        "programs": False,
    }

    def config_options(self):
        # Without iconv, libxml2 still handles UTF-8/16, ASCII and ISO-8859-x itself.
        # Linux has iconv in glibc; Windows would need the libiconv package.
        if self.settings.os == "Windows":
            self.options.with_iconv = False

    def layout(self):
        cmake_layout(self, src_folder="src")

    def requirements(self):
        if self.options.with_iconv and self.settings.os != "Linux":
            self.requires("libiconv/[>=1.17 <2]")
        if self.options.with_icu:
            self.requires("icu/[>=70 <80]")
        if self.options.with_zlib:
            self.requires("zlib/[>=1.2.11 <2]")

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)
        # The GCC-style warning flags are added for any Clang, but clang-cl reads
        # -Wall as -Weverything (~14k warnings): leave clang-cl at its defaults.
        replace_in_file(
            self,
            os.path.join(self.source_folder, "CMakeLists.txt"),
            'if(CMAKE_C_COMPILER_ID MATCHES "Clang" OR',
            'if(NOT MSVC AND CMAKE_C_COMPILER_ID MATCHES "Clang" OR',
        )
        # The installed config lists "Bcrypt" while the build links "bcrypt": only
        # the latter exists on case-sensitive file systems (Windows SDK on Linux).
        replace_in_file(
            self,
            os.path.join(self.source_folder, "libxml2-config.cmake.cmake.in"),
            "LIBXML2_LIBRARIES Bcrypt)",
            "LIBXML2_LIBRARIES bcrypt)",
        )

    def generate(self):
        tc = CMakeToolchain(self)
        tc.cache_variables["LIBXML2_WITH_ICONV"] = self.options.with_iconv
        tc.cache_variables["LIBXML2_WITH_ICU"] = self.options.with_icu
        tc.cache_variables["LIBXML2_WITH_ZLIB"] = self.options.with_zlib
        tc.cache_variables["LIBXML2_WITH_PROGRAMS"] = self.options.programs
        tc.cache_variables["LIBXML2_WITH_TESTS"] = False
        tc.cache_variables["LIBXML2_WITH_DOCS"] = False
        tc.cache_variables["LIBXML2_WITH_PYTHON"] = False
        if self.settings.os == "Linux":
            # xmllint/xmlcatalog find the packaged libxml2.so, not the system's.
            # (In the toolchain file: cache_variables go through a shell as -D.)
            tc.variables["CMAKE_INSTALL_RPATH"] = "$ORIGIN/../lib"
        tc.generate()
        CMakeDeps(self).generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        copy(
            self,
            "Copyright",
            self.source_folder,
            os.path.join(self.package_folder, "licenses"),
        )
        CMake(self).install()
        # These hardcode the build machine's install prefix; Conan generates its own.
        rmdir(self, os.path.join(self.package_folder, "lib", "pkgconfig"))
        rm(self, "xml2-config", os.path.join(self.package_folder, "bin"))
        rmdir(self, os.path.join(self.package_folder, "share"))
        rm(self, "*.pdb", self.package_folder, recursive=True)

    @property
    def _msvc_like(self):
        # MSVC and clang-cl (compiler=clang with a runtime) follow the MSVC naming.
        return self.settings.compiler == "msvc" or (
            self.settings.os == "Windows"
            and self.settings.compiler == "clang"
            and self.settings.get_safe("compiler.runtime")
        )

    @property
    def _lib_name(self):
        if not self._msvc_like:
            return "xml2"  # libxml2.so / libxml2.a / MinGW libxml2.dll.a
        # libxml2.lib (DLL import library) or libxml2s.lib (static), "d" for Debug.
        name = "libxml2" if self.options.shared else "libxml2s"
        return name + "d" if self.settings.build_type == "Debug" else name

    def package_info(self):
        # CMake: libxml2's installed config (lib/cmake/libxml2), found via the prefix path.
        self.cpp_info.set_property("cmake_find_mode", "none")
        self.cpp_info.builddirs = ["."]
        self.cpp_info.set_property("pkg_config_name", "libxml-2.0")

        self.cpp_info.includedirs = [os.path.join("include", "libxml2")]
        self.cpp_info.libs = [self._lib_name]
        if self.settings.os == "Windows":
            self.cpp_info.system_libs = ["bcrypt"]
            if not self.options.shared:
                self.cpp_info.defines = ["LIBXML_STATIC"]
        elif self.settings.os == "Linux":
            self.cpp_info.system_libs = ["m", "dl", "pthread"]
