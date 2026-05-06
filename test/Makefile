# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

# defaults
SIM ?= icarus
FST ?= -fst
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src

SYNTH_SV = synth_engine.sv synth_patterns.sv \
    synth_kick.sv synth_bass.sv synth_melody.sv synth_noise.sv

PROJECT_SOURCES = tt_um_kolontsov_journey.sv clk_gen.sv vga_timing.sv \
    pixel_shader.sv cordic.sv reciprocal.sv \
    bayer_dither.sv palette.sv dim_fade.sv \
    scroller.sv scroller_rom.sv intro_phase.sv cat_sprite.sv cat_speech.sv \
    $(SYNTH_SV) \
    sigma_delta.sv

# Enable SystemVerilog support in Icarus
COMPILE_ARGS += -g2012

ifneq ($(GATES),yes)

# RTL simulation:
SIM_BUILD				= sim_build/rtl
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))

else

# Gate level simulation:
SIM_BUILD				= sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DUSE_POWER_PINS
COMPILE_ARGS    += -DSIM
COMPILE_ARGS    += -DUNIT_DELAY=\#1
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v

# this gets copied in by the GDS action workflow
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v

endif

# Allow sharing configuration between design and testbench via `include`:
COMPILE_ARGS 		+= -I$(SRC_DIR)

# Include the testbench sources:
VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb

COCOTB_TEST_MODULES = test

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
