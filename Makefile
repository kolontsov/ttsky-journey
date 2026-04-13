# Journey - TTSKY26a demoscene competition entry

TOP_MODULE  := tt_um_kolontsov_journey
SRC_DIR     := src
SV_FILES    := $(SRC_DIR)/tt_um_kolontsov_journey.sv $(SRC_DIR)/vga_timing.sv

NPROC       := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu)

.PHONY: help sim sim-build sim-clean test test-clean lint clean

help:
	@echo "Journey - TTSKY26a demoscene competition entry"
	@echo ""
	@echo "  make sim          Verilator VGA sim (SDL window)"
	@echo "  make lint         Verilator lint"
	@echo "  make test         Cocotb smoke test"
	@echo "  make clean        Remove build artifacts"

.DEFAULT_GOAL := help

# ── Verilator + SDL simulation ──────────────────────────────

sim: sim-build
	./verilator/build/journey_sim

sim-build:
	cmake -S verilator -B verilator/build
	cmake --build verilator/build -j$(NPROC)

sim-clean:
	rm -rf verilator/build

# ── Testing ─────────────────────────────────────────────────

test:
	cd test && $(MAKE)

test-clean:
	cd test && rm -rf sim_build __pycache__ results.xml

# ── Linting ─────────────────────────────────────────────────

lint:
	verilator --lint-only -Wall --timing --top-module $(TOP_MODULE) $(SV_FILES)

# ── Utility ─────────────────────────────────────────────────

clean: sim-clean test-clean
