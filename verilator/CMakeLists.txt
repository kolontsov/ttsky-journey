cmake_minimum_required(VERSION 3.20)
project(journey_sim CXX)

if(POLICY CMP0144)
    cmake_policy(SET CMP0144 NEW)
endif()

find_package(verilator REQUIRED)
find_package(SDL2 REQUIRED)

set(SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../src")

set(SV_SOURCES
    ${SRC_DIR}/tt_um_kolontsov_journey.sv
    ${SRC_DIR}/clk_gen.sv
    ${SRC_DIR}/vga_timing.sv
    ${SRC_DIR}/pixel_shader.sv
    ${SRC_DIR}/cordic.sv
    ${SRC_DIR}/reciprocal.sv
    ${SRC_DIR}/bayer_dither.sv
    ${SRC_DIR}/palette.sv
    ${SRC_DIR}/dim_fade.sv
    ${SRC_DIR}/scroller.sv
    ${SRC_DIR}/scroller_rom.sv
    ${SRC_DIR}/intro_phase.sv
    ${SRC_DIR}/cat_sprite.sv
    ${SRC_DIR}/cat_speech.sv
    ${SRC_DIR}/synth_engine.sv
    ${SRC_DIR}/synth_patterns.sv
    ${SRC_DIR}/synth_kick.sv
    ${SRC_DIR}/synth_bass.sv
    ${SRC_DIR}/synth_melody.sv
    ${SRC_DIR}/synth_noise.sv
    ${SRC_DIR}/sigma_delta.sv
)
set(CMAKE_BUILD_TYPE Release)
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -flto -DNDEBUG")
set(CMAKE_EXE_LINKER_FLAGS_RELEASE "-flto")
set(VERILATOR_COMMON_ARGS -Wall -Wno-UNUSEDSIGNAL -O3 --x-assign fast --x-initial fast --noassert)

# --- VGA + Audio sim ---
add_executable(journey_sim tb_top.cpp)
target_link_libraries(journey_sim PRIVATE SDL2::SDL2)
verilate(journey_sim
    SOURCES     ${SV_SOURCES}
    TOP_MODULE  tt_um_kolontsov_journey
    PREFIX      Vtop
    VERILATOR_ARGS ${VERILATOR_COMMON_ARGS}
)

# --- Audio-only sim ---
add_executable(journey_audio audio_tb.cpp)
target_link_libraries(journey_audio PRIVATE SDL2::SDL2)
verilate(journey_audio
    SOURCES     ${SV_SOURCES}
    TOP_MODULE  tt_um_kolontsov_journey
    PREFIX      Vaud
    VERILATOR_ARGS ${VERILATOR_COMMON_ARGS}
)

# --- Offline MP4 recorder (no SDL) ---
add_executable(journey_record tb_record.cpp)
verilate(journey_record
    SOURCES     ${SV_SOURCES}
    TOP_MODULE  tt_um_kolontsov_journey
    PREFIX      Vrec
    VERILATOR_ARGS ${VERILATOR_COMMON_ARGS}
)

