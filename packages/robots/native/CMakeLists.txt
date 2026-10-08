# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.30)
project(telesurgery_franka LANGUAGES CXX)
find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module Development.SABIModule)
execute_process(COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
    OUTPUT_VARIABLE nanobind_DIR OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
find_package(nanobind 3.0.1 CONFIG REQUIRED)
find_package(Franka REQUIRED CONFIG)
find_package(Threads REQUIRED)
include(FetchContent)
set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(BUILD_CLOUD_CLIENT OFF CACHE BOOL "" FORCE)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
fetchcontent_declare(ruckig
    GIT_REPOSITORY https://github.com/pantor/ruckig.git
    GIT_TAG a8db97a4e9c55e5160a3855f739fa3b270df8e4c
    EXCLUDE_FROM_ALL)
fetchcontent_makeavailable(ruckig)
nanobind_add_module(_franka STABLE_ABI controller.cpp)
target_compile_features(_franka PRIVATE cxx_std_17)
target_link_libraries(_franka PRIVATE Franka::Franka Threads::Threads ruckig::ruckig)
set_target_properties(_franka PROPERTIES INSTALL_RPATH "${Franka_DIR}/../../../lib")
install(TARGETS _franka LIBRARY DESTINATION telesurgery_robots/franka)

option(BUILD_TESTING "Build hardware-free motion checks" OFF)
if(BUILD_TESTING)
    enable_testing()
    add_executable(test_franka_jog ../../../tests/native/test_franka_jog.cpp)
    target_include_directories(test_franka_jog PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_compile_features(test_franka_jog PRIVATE cxx_std_17)
    target_compile_options(test_franka_jog PRIVATE -UNDEBUG)
    target_link_libraries(test_franka_jog PRIVATE ruckig::ruckig)
    add_test(NAME franka_jog COMMAND test_franka_jog)
endif()
