/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module sigma_delta (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [6:0] sample_in,   // unsigned 7-bit audio sample
    output logic      out          // 1-bit output at clk rate
);

    // First-order sigma-delta modulator.
    logic [7:0] accum_next;
    logic [6:0] accum;

    assign accum_next = {1'b0, accum} + {1'b0, sample_in};

    // accum has no reset: self-stabilises in a few samples, and `out`
    // (the only externally visible signal) is reset. Drops one reset
    // sink, saving GPL. Icarus needs an initial value to leave X-state.
`ifdef __ICARUS__
    initial accum = 7'd0;
`endif
    always_ff @(posedge clk) begin
        accum <= accum_next[6:0];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) out <= 1'b0;
        else        out <= accum_next[7];
    end

endmodule
