cmake_minimum_required(VERSION 3.18)
project(test_package LANGUAGES C)

# The same lookup LLVM (llvm-mt) does: the LIBXML2_* variables must link on their
# own, and the target must have a library location.
find_package(LibXml2 REQUIRED CONFIG)

include(CheckSymbolExists)
# A static libxml2 with ICU/zlib lists their Conan targets, which resolve only for
# a named configuration; check builds have none unless this is set.
set(CMAKE_TRY_COMPILE_CONFIGURATION ${CMAKE_BUILD_TYPE})
set(CMAKE_REQUIRED_INCLUDES ${LIBXML2_INCLUDE_DIRS})
set(CMAKE_REQUIRED_LIBRARIES ${LIBXML2_LIBRARIES})
set(CMAKE_REQUIRED_DEFINITIONS ${LIBXML2_DEFINITIONS})
check_symbol_exists(xmlReadMemory libxml/xmlreader.h HAVE_LIBXML2)
if(NOT HAVE_LIBXML2)
    message(FATAL_ERROR "Can't link xmlReadMemory with LIBXML2_LIBRARIES")
endif()

get_property(location TARGET LibXml2::LibXml2 PROPERTY LOCATION)
if(NOT EXISTS "${location}")
    message(FATAL_ERROR "LibXml2::LibXml2 has no library location")
endif()

add_executable(test_package test_package.c)
target_link_libraries(test_package PRIVATE LibXml2::LibXml2)

enable_testing()
add_test(NAME test_package COMMAND test_package)
