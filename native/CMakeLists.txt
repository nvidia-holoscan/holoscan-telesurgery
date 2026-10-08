# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 4.0)
project(telesurgery_hsb LANGUAGES CXX CUDA)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
find_package(holoscan 5.0 REQUIRED CONFIG)
# CUDA tensor headers require CCCL; EA3 omits its target from cached-build exports.
find_package(CCCL 3.3.3 REQUIRED CONFIG)
find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module Development.SABIModule)
execute_process(COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
                OUTPUT_VARIABLE nanobind_DIR OUTPUT_STRIP_TRAILING_WHITESPACE
                COMMAND_ERROR_IS_FATAL ANY)
find_package(nanobind 3.0.1 EXACT CONFIG REQUIRED)
if(HOLOLINK_SOURCE_DIR)
  find_path(FUSA_INCLUDE_DIR NvFusaCaptureExternal.hpp
      PATHS /usr/src/jetson_sipl_api/sipl/fusa/include
            /usr/src/jetson_sipl_api/sipl/capture/include)
  find_library(FUSA_LIBRARY nvfusacapext PATHS /usr/lib/aarch64-linux-gnu/nvidia)
  if(CMAKE_SYSTEM_PROCESSOR STREQUAL "aarch64" AND FUSA_INCLUDE_DIR AND FUSA_LIBRARY)
    set(HOLOLINK_BUILD_FUSA ON CACHE BOOL "Build Thor FuSa CoE capture" FORCE)
  endif()
  set(HOLOLINK_BUILD_PYTHON OFF CACHE BOOL "" FORCE)
  set(HOLOLINK_BUILD_MODULE OFF CACHE BOOL "" FORCE)
  set(HOLOLINK_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
  set(HOLOLINK_BUILD_TESTS OFF CACHE BOOL "" FORCE)
  set(HOLOLINK_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
  set(HOLOLINK_BUILD_GPUNETIO_ROCE OFF CACHE BOOL "" FORCE)
  set(HOLOLINK_BUILD_CRC OFF CACHE BOOL "" FORCE)
  set(HOLOLINK_BUILD_EXPORT OFF CACHE BOOL "" FORCE)
  add_subdirectory("${HOLOLINK_SOURCE_DIR}" hololink)
else()
  find_package(Hololink REQUIRED CONFIG)
endif()
nanobind_add_module(_hsb STABLE_ABI capture.cpp bindings.cpp)
if(HOLOLINK_SOURCE_DIR)
  target_include_directories(_hsb PRIVATE
      "${HOLOLINK_SOURCE_DIR}/hololink_module/host/include"
      "${HOLOLINK_SOURCE_DIR}/hololink_module/module/core")
else()
  find_path(HOLOLINK_LEGACY_INCLUDE_DIR hsb_ip_2510_data_channel.hpp
    PATH_SUFFIXES hololink/module/core hololink_module/module/core REQUIRED)
  find_path(HOLOLINK_METADATA_INCLUDE_DIR capture_metadata_traits.hpp REQUIRED)
  target_include_directories(_hsb PRIVATE
    "${HOLOLINK_LEGACY_INCLUDE_DIR}" "${HOLOLINK_METADATA_INCLUDE_DIR}")
endif()
target_link_libraries(_hsb PRIVATE holoscan::core holoscan::sensor_io
    hololink::operators::linux_receiver_op hololink::operators::csi_to_bayer
    hololink::operators::image_processor hololink::sensors::native_imx274_camera_sensor)
if(TARGET hololink::operators::fusa_coe_capture)
  target_compile_definitions(_hsb PRIVATE TELESURGERY_HAS_FUSA)
  target_link_libraries(_hsb PRIVATE hololink::operators::fusa_coe_capture
      hololink::operators::packed_format_converter)
endif()
install(TARGETS _hsb LIBRARY DESTINATION telesurgery_runtime/backends/sdk5)
