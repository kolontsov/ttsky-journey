/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * 25 MHz clk → 11-bit accumulator (+3/cycle) → MSB tap = clk_sample at
 * 25e6 * 3 / 2048 = 36621.09 Hz. Declared as a generated clock in
 * constraints.sdc; CTS builds the audio-domain tree from it.
 *
 * No reset on the accumulator: free-running, MSB toggles regardless of
 * phase, so startup state is irrelevant.
 */

`default_nettype none

module clk_gen (
    input  wire clk,
    output wire clk_sample
);
    /*verilator public_module*/

    logic [10:0] clk_sample_div /* verilator public */;
    logic        clk_sample_ff;

    // Icarus 4-state sim needs an explicit init or the X-fed accumulator
    // stays X and clk_sample never fires.
`ifdef __ICARUS__
    initial begin
        clk_sample_div = 11'd0;
        clk_sample_ff  = 1'b0;
    end
`endif
    always_ff @(posedge clk) begin
        clk_sample_div <= clk_sample_div + 11'd3;
        clk_sample_ff  <= clk_sample_div[10];
    end

    assign clk_sample = clk_sample_ff;
endmodule
