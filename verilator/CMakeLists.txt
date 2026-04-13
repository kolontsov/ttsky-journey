cmake_minimum_required(VERSION 3.20)
project(journey_sim CXX)

find_package(verilator REQUIRED)
find_package(SDL2 REQUIRED)

set(SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../src")
set(SV_SOURCES
    ${SRC_DIR}/tt_um_kolontsov_journey.sv
    ${SRC_DIR}/vga_timing.sv
)
set(CMAKE_BUILD_TYPE Release)
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -flto -DNDEBUG")
set(CMAKE_EXE_LINKER_FLAGS_RELEASE "-flto")

add_executable(journey_sim tb_top.cpp)
target_link_libraries(journey_sim PRIVATE SDL2::SDL2)
verilate(journey_sim
    SOURCES     ${SV_SOURCES}
    TOP_MODULE  tt_um_kolontsov_journey
    PREFIX      Vtop
    VERILATOR_ARGS -Wall -Wno-UNUSEDSIGNAL -O3 --x-assign fast --x-initial fast --noassert
)
