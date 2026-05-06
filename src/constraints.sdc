# PNR_SDC_FILE replaces base.sdc rather than appending, so source it to keep
# Librelane's standard clock / IO / derate setup.
source $::env(FALLBACK_SDC)

# Relaxed from the default 10. Reset distribution is the widest non-clock net
# (rst_n_visual ~71 sinks), driven by an explicit RTL buf_12 — not by
# RepairDesign, which would otherwise insert redundant buffers. Headroom
# above 71 absorbs minor future growth. Clock trees are owned by CTS and
# unaffected by this.
set_max_fanout 80 [current_design]

# Default 0.75 ns is pessimistic at 25 MHz / 1.8 V typ. 5 ns is still 12.5%
# of the master period and tiny vs clk_sample's 27 us.
set_max_transition 5.0 [current_design]

# Tight enough to catch route drift past measured branch loads (master clock
# ~0.286 pF, audio reset branch ~0.330 pF at FF). The split into two reset
# branches in RTL is what keeps each below this ceiling.
set_max_capacitance 0.40 [current_design]

# clk_sample is a signal-routed pseudo-clock (11-bit accum, +3/cycle, MSB tap;
# see clk_gen.sv). Declaring it lets STA check the ~109 audio-domain register
# pins that would otherwise be unclocked.
#
# divide_by 683: MSB toggles every 2*1024/3 ≈ 682.67 cycles; 683 is the
# closest integer and slightly conservative for setup.
#
# Source pin looked up by net so this survives Yosys-renamed instance names.
create_generated_clock -name clk_sample \
    -source [get_ports clk] \
    -divide_by 683 \
    [get_pins -filter {direction == output} -of_objects [get_nets clk_sample]]

# All clk <-> clk_sample paths go through 2FF synchronizers (e.g. kick_active
# in pixel_shader.sv). Mark the domains async so STA skips setup/hold across
# the crossing. CTS still builds a small tree on clk_sample; skew is
# irrelevant at 27 us period.
set_clock_groups -asynchronous \
    -group [get_clocks clk] \
    -group [get_clocks clk_sample]
