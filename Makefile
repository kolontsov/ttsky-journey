# Journey — build recipes

TOP_MODULE  := tt_um_kolontsov_journey
SRC_DIR     := src

SYNTH_SV    := $(SRC_DIR)/synth_engine.sv $(SRC_DIR)/synth_patterns.sv \
               $(SRC_DIR)/synth_kick.sv $(SRC_DIR)/synth_bass.sv \
               $(SRC_DIR)/synth_melody.sv $(SRC_DIR)/synth_noise.sv

SV_FILES    := $(SRC_DIR)/tt_um_kolontsov_journey.sv $(SRC_DIR)/clk_gen.sv \
               $(SRC_DIR)/vga_timing.sv \
               $(SRC_DIR)/pixel_shader.sv $(SRC_DIR)/cordic.sv \
               $(SRC_DIR)/reciprocal.sv \
               $(SRC_DIR)/bayer_dither.sv $(SRC_DIR)/palette.sv \
               $(SRC_DIR)/dim_fade.sv \
               $(SRC_DIR)/scroller.sv $(SRC_DIR)/scroller_rom.sv \
               $(SRC_DIR)/intro_phase.sv \
               $(SRC_DIR)/cat_sprite.sv $(SRC_DIR)/cat_speech.sv \
               $(SYNTH_SV) \
               $(SRC_DIR)/sigma_delta.sv

NPROC       := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu)

# Pinned char_idx permutation for the scroller ROM. Empty = let gen_scroller.py
# pick frequency order. Keep explicit so `make gen` is reproducible.
SCROLLER_CHAR_ORDER :=

# Tang Primer 20K + Dock
FPGA_DIR    := fpga
FPGA_FAMILY := GW2A-18C
FPGA_DEVICE := GW2A-LV18PG256C8/I7
FPGA_SV     := $(SV_FILES) $(FPGA_DIR)/tangprimer20k_top.sv
YOSYS_DEFINES := -DNO_SKY130_RESET_TREE -DNO_SKY130_CLK_SAMPLE_BUF
FPGA_DEFINES  := -DNO_SKY130_RESET_TREE -DNO_SKY130_CLK_SAMPLE_BUF

.PHONY: help \
        sim audio play-song record record-yt sim-build sim-clean lint \
        gen scroller speech synth-patterns cat-sprite test test-clean clean \
        fpga fpga-synth fpga-pnr fpga-pack fpga-flash \
        harden harden-setup harden-clean harden-open \
        sky-gpl sky-cells sky-gl-record sky-gl-record-clean \
        cells pins ltp \
        scroller-search scroller-list scroller-pick \
        speech-search \
        cat-sprite-search cat-sprite-list cat-sprite-pick

# ── Help ────────────────────────────────────────────────────

help:
	@echo "Journey — TTSKY26a demoscene entry"
	@echo ""
	@echo "Verilator (RTL sim):"
	@echo "  make sim          VGA + audio (SDL window)"
	@echo "  make audio        Audio-only (no VGA, faster)"
	@echo "  make record       Offline MP4 capture (30s, video + audio)"
	@echo "  make record-yt    Upscale to 1440p pillarboxed for YouTube uploads"
	@echo "  make play-song    Python engine_song preview (BARS=N to limit)"
	@echo "  make lint         Verilator lint"
	@echo ""
	@echo "Dev:"
	@echo "  make gen          Regenerate all generated Verilog (scroller, speech, synth, cat)"
	@echo "  make test         Cocotb smoke test"
	@echo "  make clean        Remove sim/test/fpga build artifacts"
	@echo ""
	@echo "FPGA (Tang Primer 20K + Dock):"
	@echo "  make fpga         Synth + PnR + flash"
	@echo ""
	@echo "ASIC / SKY130 flow (need 'make harden' artifacts unless noted):"
	@echo "  make harden       Full ASIC build — synth+PnR (Docker, ~5 min)"
	@echo "  make sky-gpl      Quick GPL util% probe — partial harden (~17 sec, no artifacts needed)"
	@echo "  make sky-cells    Cell counts + timing summary from last harden"
	@echo "  make sky-gl-record  Functional GL sim of harden netlist → MP4 (GL_FRAMES=N, default 30)"
	@echo "  make harden-setup Bootstrap/upgrade tt-support-tools + .venv-tt + librelane"
	@echo "  make harden-clean Wipe tt/ and .venv-tt/"
	@echo "  make harden-open  Open last hardened GDS in KLayout"
	@echo ""
	@echo "Probe (Yosys-only, no harden needed, ~5 sec):"
	@echo "  make cells        Flat total + per-module cell breakdown"
	@echo "  make pins         Per-module wire-bit count (pin-density proxy)"
	@echo "  make ltp          Per-module longest topological path (timing proxy)"
	@echo ""
	@echo "Search (autotuners, write src/*.sv on improvement):"
	@echo "  make scroller-search    Tune scroller char_idx (METRIC=gpl_util default, ~65 min)"
	@echo "                          GPL on every random + swap-2 trial"
	@echo "                          N_RANDOM=0 N_LOCAL=300 for swap-2 only"
	@echo "  make scroller-list      Top-10 candidates from last search"
	@echo "  make scroller-pick N=i  Install Nth-best candidate"
	@echo "  make speech-search      Tune cat_speech glyph_idx (METRIC=gpl_util, ~10-12 min)"
	@echo "                          SPEECH_TOP_N=20 for broader Stage C sweep"
	@echo "  make cat-sprite-search  Tune cat_frame encoding (CAT_TOPK=10, ~3 min)"
	@echo "  make cat-sprite-list    Top candidates from last cat-sprite-search"
	@echo "  make cat-sprite-pick N=i  Install Nth candidate"

.DEFAULT_GOAL := help

# ── Verilator + SDL simulation ──────────────────────────────

sim: sim-build
	./verilator/build/journey_sim

audio: sim-build
	./verilator/build/journey_audio

play-song:
	uv run scripts/play_song.py $(if $(BARS),--bars $(BARS))

record: sim-build
	./verilator/build/journey_record

record-yt: sim-build
	./verilator/build/journey_record -d 120 --upscale -o journey_yt.mp4

sim-build:
	cmake -S verilator -B verilator/build
	cmake --build verilator/build -j$(NPROC)

sim-clean:
	rm -rf verilator/build

lint:
	verilator --lint-only -Wall --timing --top-module $(TOP_MODULE) $(SV_FILES)

# ── Dev: code generation, test, clean ───────────────────────

gen: scroller speech synth-patterns cat-sprite

scroller:
	uv run scripts/gen_scroller.py --font scripts/data/08X08-F5.png \
	    --font-layout cols \
	    $(if $(strip $(SCROLLER_CHAR_ORDER)),--char-order '$(SCROLLER_CHAR_ORDER)',)

speech:
	uv run scripts/gen_speech.py

synth-patterns:
	uv run scripts/gen_patterns.py

cat-sprite:
	uv run scripts/gen_cat_sprite.py

test:
	cd test && $(MAKE)

test-clean:
	cd test && rm -rf sim_build __pycache__ results.xml

clean: sim-clean test-clean
	rm -rf $(FPGA_DIR)/build $(FPGA_DIR)/*.fs

# ── FPGA (Tang Primer 20K + Dock) ──────────────────────────

fpga: fpga-pack
	openFPGALoader -b tangprimer20k $(FPGA_DIR)/tangprimer20k.fs

fpga-synth:
	mkdir -p $(FPGA_DIR)/build
	yosys -p "read_verilog -sv $(FPGA_DEFINES) $(FPGA_SV); \
	          synth_gowin -top tangprimer20k_top -json $(FPGA_DIR)/build/synth.json"

fpga-pnr: fpga-synth
	nextpnr-himbaechel --device $(FPGA_DEVICE) \
	    --json $(FPGA_DIR)/build/synth.json \
	    --write $(FPGA_DIR)/build/pnr.json \
	    --vopt family=$(FPGA_FAMILY) \
	    --vopt cst=$(FPGA_DIR)/tangprimer20k.cst

fpga-pack: fpga-pnr
	gowin_pack -d $(FPGA_FAMILY) -o $(FPGA_DIR)/tangprimer20k.fs $(FPGA_DIR)/build/pnr.json

fpga-flash:
	openFPGALoader -b tangprimer20k $(FPGA_DIR)/tangprimer20k.fs

# ── ASIC / SKY130 flow ──────────────────────────────────────

# tt-support-tools has no tags; pin to a known-good main commit.
# Bump these two together when upgrading; `make harden-setup` reapplies both.
TT_TOOLS_REPO := https://github.com/TinyTapeout/tt-support-tools
TT_TOOLS_REF  := b7acfdc
LIBRELANE_VER := 3.0.0

HARDEN_ENV := PATH="$(CURDIR)/.venv-tt/bin:$(PATH)" DYLD_FALLBACK_LIBRARY_PATH="$$(brew --prefix)/lib"

harden:
	@$(HARDEN_ENV) .venv-tt/bin/python tt/tt_tool.py --create-user-config
	@$(HARDEN_ENV) .venv-tt/bin/python tt/tt_tool.py --harden

harden-setup:
	@command -v brew >/dev/null || { echo "brew required (for cairo)"; exit 1; }
	@command -v uv   >/dev/null || { echo "uv required";              exit 1; }
	@brew list cairo >/dev/null 2>&1 || brew install cairo
	@test -d tt/.git || git clone $(TT_TOOLS_REPO) tt
	@cd tt && git fetch --quiet origin && git checkout --quiet $(TT_TOOLS_REF)
	@test -d .venv-tt || uv venv .venv-tt
	@VIRTUAL_ENV=$(CURDIR)/.venv-tt uv pip sync -q tt/requirements.txt
	@VIRTUAL_ENV=$(CURDIR)/.venv-tt uv pip install -q librelane==$(LIBRELANE_VER)
	@echo "harden-setup: tt @ $(TT_TOOLS_REF), librelane $(LIBRELANE_VER)"

harden-clean:
	rm -rf tt .venv-tt

HARDEN_GDS := runs/wokwi/final/gds/$(TOP_MODULE).gds
harden-open:
	@test -f $(HARDEN_GDS) || { echo "no GDS at $(HARDEN_GDS) — run 'make harden' first"; exit 1; }
	open -a klayout $(HARDEN_GDS)

# Run librelane only through global_placement; print util% as JSON on stdout.
# Closer to the 1×2 binding constraint than `make cells`, much faster than
# full harden — use as a search metric and gate before committing to harden.
sky-gpl:
	@$(HARDEN_ENV) uv run scripts/util/sky_gpl.py

sky-cells:
	@uv run scripts/util/sky_cells.py

# Functional GL sim of post-PnR netlist through Icarus + SKY130 cell models.
# Catches Yosys/PnR bugs that RTL sim won't (un-reset state, dropped logic,
# mis-translated resets) at ~100x slower than Verilator. Sweet spot is 1-2
# seconds; full demo would take many hours.
PDK_ROOT      ?= $(HOME)/.volare
SKY130_VLOG   := $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog
GL_NETLIST    := runs/wokwi/final/pnl/$(TOP_MODULE).pnl.v
GL_OUT        := gl_capture
GL_FRAMES     ?= 30

sky-gl-record:
	@test -f $(GL_NETLIST) || { echo "no netlist at $(GL_NETLIST) — run 'make harden' first"; exit 1; }
	@test -f $(SKY130_VLOG)/sky130_fd_sc_hd.v || { echo "PDK Verilog missing at $(SKY130_VLOG); set PDK_ROOT or run librelane once"; exit 1; }
	@command -v ffmpeg >/dev/null || { echo "ffmpeg required for post-process"; exit 1; }
	uv run scripts/gen_gl_init.py
	mkdir -p $(GL_OUT)
	iverilog -g2012 -o $(GL_OUT)/sim.vvp \
	    -DFUNCTIONAL -DUSE_POWER_PINS -DUNIT_DELAY=\#1 \
	    -I test \
	    test/tb_record_gl.v \
	    $(SKY130_VLOG)/primitives.v \
	    $(SKY130_VLOG)/sky130_fd_sc_hd.v \
	    $(GL_NETLIST)
	cd $(GL_OUT) && uv run --no-project ../scripts/util/gl_progress.py \
	    vvp sim.vvp +frames=$(GL_FRAMES) +out_dir=.
	ffmpeg -y -loglevel warning \
	    -f rawvideo -pixel_format rgb24 -video_size 640x480 -framerate 1250/21 \
	    -i $(GL_OUT)/frames.bin \
	    -f u8 -ar 25000000 -ac 1 -i $(GL_OUT)/audio.bin \
	    -af "lowpass=8000,aresample=48000" \
	    -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
	    -c:a aac -b:a 192k -shortest \
	    $(GL_OUT)/gl_capture.mp4
	@echo "[sky-gl-record] done: $(GL_OUT)/gl_capture.mp4"

sky-gl-record-clean:
	rm -rf $(GL_OUT) test/gl_init_force.vh test/gl_init_release.vh

# ── Probe (Yosys-only, no harden artifacts) ─────────────────

# Flat total (the truth for before/after diffs), then per-module breakdown.
# Hierarchical numbers are useful for "where to attack next" but DO NOT
# subtract them across changes — they shift on module-boundary reshuffles.
cells:
	@yosys -p "read_verilog -sv $(YOSYS_DEFINES) $(SV_FILES); synth -top $(TOP_MODULE) -flatten; stat" 2>&1 | \
		awk '/ cells$$/{c=$$1} !w && / wire bits$$/{w=$$1} \
		     END{printf "%5d TOTAL (flat)\n%5d WIRES (flat)\n\n", c, w}'
	@yosys -p "read_verilog -sv $(YOSYS_DEFINES) $(SV_FILES); synth -top $(TOP_MODULE); tee -q -o /tmp/journey_stats.txt stat" >/dev/null 2>&1
	@awk 'BEGIN{n=0} \
	      /=== design hierarchy ===/{f=1; next} \
	      f && /\+---.*Count/{c++; if(c==2) exit; next} \
	      f && /^[[:space:]]*\|/{next} \
	      f && NF>=2 && $$2=="$(TOP_MODULE)"{next} \
	      f && NF>=2 {cnt[n]=$$1+0; nm[n]=$$2; n++} \
	      END { \
	        for (i=0;i<n;i++) for (j=i+1;j<n;j++) \
	          if (cnt[j]>cnt[i]) {t=cnt[i];cnt[i]=cnt[j];cnt[j]=t; s=nm[i];nm[i]=nm[j];nm[j]=s} \
	        for (i=0;i<n;i++) printf "%5d %s\n", cnt[i], nm[i] \
	      }' /tmp/journey_stats.txt

# Per-module wire-bit count — proxy for internal pin density. Modules at
# the top of this list contribute disproportionately to GPL pin-density
# padding. Attack the top when hitting GPL-0301.
pins:
	@yosys -p "read_verilog -sv $(YOSYS_DEFINES) $(SV_FILES); synth -top $(TOP_MODULE); tee -q -o /tmp/journey_pins.txt stat" >/dev/null 2>&1
	@awk '/^=== / { \
	        gsub(/=/,"",$$0); gsub(/ /,"",$$0); \
	        mod=$$0; \
	        if (mod=="designhierarchy") mod=""; \
	        have=0; next \
	      } \
	      /wire bits/ && !have && mod!="" { \
	        wb[mod]=$$1; names[n++]=mod; have=1; mod="" \
	      } \
	      END { \
	        for (i=0;i<n;i++) for (j=i+1;j<n;j++) \
	          if (wb[names[j]]>wb[names[i]]) {t=names[i];names[i]=names[j];names[j]=t} \
	        for (i=0;i<n;i++) printf "%5d  %s\n", wb[names[i]], names[i] \
	      }' /tmp/journey_pins.txt

# Longest Topological Path — deepest gate chain between flops, per module.
# Proxy for combinational timing (no cell delays, just gate count). Watch
# after touching anything pipelined (CORDIC, synth_engine).
ltp:
	@yosys -p "read_verilog -sv $(YOSYS_DEFINES) $(SV_FILES); synth -top $(TOP_MODULE); ltp" 2>&1 | \
		grep -E "Longest topological path in .* \(length=" | \
		sed -E 's/Longest topological path in (.*) \(length=([0-9]+)\):/\2 \1/' | \
		sort -nr | awk '{printf "%5d  %s\n", $$1, $$2}'

# ── Search (autotuners) ─────────────────────────────────────

# Defaults: GPL util metric, 200 random + 100 swap-2. Override per-run with
# e.g. METRIC=cells (faster, mismatched with GPL) or N_RANDOM=0 for swap-2 only.
METRIC ?= gpl_util
N_RANDOM ?= 200
N_LOCAL ?= 100

scroller-search:
	uv run scripts/search/search_scroller.py \
	    --metric $(METRIC) \
	    $(if $(PIN_WEIGHT),--pin-weight $(PIN_WEIGHT),) \
	    $(N_RANDOM) $(N_LOCAL)

scroller-list:
	uv run scripts/search/search_scroller.py --list

scroller-pick:
	uv run scripts/search/search_scroller.py --pick $(N)

# Exhaustive 9! prefilter by SOP cost, then measures top-N by chosen metric.
# Restores src/cat_speech.sv at end. Default: GPL util on top-20 (~7 min).
SPEECH_TOP_N  ?=

speech-search:
	uv run scripts/search/search_speech.py \
	    --metric $(METRIC) \
	    $(if $(strip $(SPEECH_TOP_N)),--top-n $(SPEECH_TOP_N),)

# Phase 1: enumerate all 20160 cat_frame 6-state→3-bit encodings by SOP cost.
# Phase 2: measure top-K via `make sky-gpl` for full-design ranking.
# Restores baseline if nothing improves.
CAT_TOPK ?= 10

cat-sprite-search:
	uv run scripts/search/search_cat_sprite.py --topk $(CAT_TOPK)

cat-sprite-list:
	uv run scripts/search/search_cat_sprite.py --list

cat-sprite-pick:
	uv run scripts/search/search_cat_sprite.py --pick $(N)
