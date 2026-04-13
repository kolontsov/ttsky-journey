# SPDX-FileCopyrightText: (C) 2026 Vadim Kolontsov
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


@cocotb.test()
async def test_project(dut):
    dut._log.info("Start")

    # 25.175 MHz pixel clock (~39.7 ns period)
    clock = Clock(dut.clk, 39722, unit="ps")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1

    # Run a few lines worth of clocks and check hsync/vsync toggle
    dut._log.info("Running VGA timing check")
    await ClockCycles(dut.clk, 800 * 2)

    uo = dut.uo_out.value.to_unsigned()
    hsync = (uo >> 7) & 1
    vsync = (uo >> 3) & 1
    dut._log.info(f"uo_out=0x{uo:02x} hsync={hsync} vsync={vsync}")

    # After reset + 1600 clocks we should be in visible area:
    # vsync should be high (inactive), hsync depends on exact position
    assert vsync == 1, "vsync should be inactive during visible area"
