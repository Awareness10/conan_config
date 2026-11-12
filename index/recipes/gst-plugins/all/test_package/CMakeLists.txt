cmake_minimum_required(VERSION 3.18)
project(test_package LANGUAGES C)

find_package(GStreamer REQUIRED CONFIG)

add_executable(test_package test_package.c)
target_link_libraries(test_package PRIVATE GStreamer::gstreamer GStreamer::app GStreamer::rtsp-server)
