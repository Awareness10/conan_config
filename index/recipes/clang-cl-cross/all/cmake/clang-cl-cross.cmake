# Cross-compile for Windows with clang-cl + lld-link and the MSVC CRT/Windows SDK
# from the msvc-sysroot package. Injected by the clang-cl-cross Conan package,
# which sets the CLANG_CL_CROSS_* environment variables (also in CMake presets).
#
# The values are cached on the first configure, so re-running cmake/ninja later
# without the Conan environment still works.

set(CMAKE_SYSTEM_NAME Windows)

foreach(_var LLVM_BIN SYSROOT TRIPLE LIBARCH MSVC_VERSION)
    if(NOT CLANG_CL_CROSS_${_var} AND DEFINED ENV{CLANG_CL_CROSS_${_var}})
        set(CLANG_CL_CROSS_${_var} "$ENV{CLANG_CL_CROSS_${_var}}" CACHE STRING "" FORCE)
    endif()
    if(NOT CLANG_CL_CROSS_${_var})
        message(FATAL_ERROR "CLANG_CL_CROSS_${_var} is not set: use this toolchain "
                            "through the clang-cl-cross Conan package")
    endif()
endforeach()
# try_compile() projects re-read this file: pass the values through.
list(APPEND CMAKE_TRY_COMPILE_PLATFORM_VARIABLES
     CLANG_CL_CROSS_LLVM_BIN CLANG_CL_CROSS_SYSROOT CLANG_CL_CROSS_TRIPLE CLANG_CL_CROSS_LIBARCH
     CLANG_CL_CROSS_MSVC_VERSION)

set(_bin "${CLANG_CL_CROSS_LLVM_BIN}")
set(_root "${CLANG_CL_CROSS_SYSROOT}")
set(_arch "${CLANG_CL_CROSS_LIBARCH}")

set(CMAKE_C_COMPILER   "${_bin}/clang-cl")
set(CMAKE_CXX_COMPILER "${_bin}/clang-cl")
set(CMAKE_RC_COMPILER  "${_bin}/llvm-rc")
set(CMAKE_LINKER       "${_bin}/lld-link")
set(CMAKE_AR           "${_bin}/llvm-lib")
set(CMAKE_MT           "${_bin}/llvm-mt")

set(_flags "--target=${CLANG_CL_CROSS_TRIPLE} -fms-compatibility-version=${CLANG_CL_CROSS_MSVC_VERSION}")
foreach(_dir crt/include sdk/include/ucrt sdk/include/um sdk/include/shared sdk/include/winrt)
    string(APPEND _flags " /imsvc\"${_root}/${_dir}\"")
endforeach()
set(CMAKE_C_FLAGS_INIT   "${_flags}")
set(CMAKE_CXX_FLAGS_INIT "${_flags}")

set(_libpaths "")
foreach(_dir crt/lib/${_arch} sdk/lib/um/${_arch} sdk/lib/ucrt/${_arch})
    string(APPEND _libpaths " /libpath:\"${_root}/${_dir}\"")
endforeach()
set(CMAKE_EXE_LINKER_FLAGS_INIT    "${_libpaths}")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "${_libpaths}")
set(CMAKE_MODULE_LINKER_FLAGS_INIT "${_libpaths}")

# xwin ships no debug CRT (msvcrtd.lib): compiler checks must use the release one.
set(CMAKE_TRY_COMPILE_CONFIGURATION Release)

# Only Windows packages: never the build machine's Linux libraries.
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(ENV{PKG_CONFIG_LIBDIR} "${_root}/pkgconfig-none")
set(ENV{PKG_CONFIG_PATH} "")
