# SPDX-FileCopyrightText: © 2026 Vadim Kolontsov
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge


@cocotb.test()
async def test_vga_and_audio_smoke(dut):
    """Verify VGA hsync toggles and audio output is active after reset."""
    clock = Clock(dut.clk, 40, unit="ns")  # 25 MHz
    cocotb.start_soon(clock.start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    # rst_n_sync zero-inits in sim, so a naked rst_n=1→0 on the port produces
    # no negedge and submodule async-resets (e.g. synth_noise LFSR seed) never
    # fire. Pulse rst_n=1 first to push rst_n_sync→1, then drop to create one.
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 4)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1

    # Let VGA counters run a few lines (1 line = 800 clocks at 25 MHz pix=master)
    await ClockCycles(dut.clk, 8_000)

    # In GL sim the unused uo_out / uio_out bits sit at X (tie cells), so
    # we sample bit 7 via binstr[0] (MSB) instead of converting the whole bus.
    # Sample at intervals spread across ~3 line periods to catch hsync toggle
    hsync_vals = set()
    for _ in range(30):
        await ClockCycles(dut.clk, 250)
        hsync_vals.add(dut.uo_out.value.binstr[0])

    assert hsync_vals == {"0", "1"}, f"hsync not toggling: only saw {hsync_vals}"

    # Verify uio_oe bit 7 is 1 (audio output enable)
    assert dut.uio_oe.value.binstr[0] == "1", "uio_oe[7] should be 1 (audio output)"

    # σΔ repeats on a 4-cycle pattern per amplitude — sample adjacent clocks
    # to dodge aliasing.
    audio_vals = set()
    for _ in range(32):
        await RisingEdge(dut.clk)
        audio_vals.add(dut.uio_out.value.binstr[0])

    assert audio_vals == {"0", "1"}, f"audio not toggling: only saw {audio_vals}"

    dut._log.info("Smoke test passed")
