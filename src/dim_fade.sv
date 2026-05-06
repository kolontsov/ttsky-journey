/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Dim fade — 50% shade in a band that wraps the scroller text
 * with equal margin above and runs to the bottom of the screen.
 * At RGB222 precision, x>>1 is the only useful dim level.
 */

`default_nettype none

module dim_fade (
    input  wire [9:0] v_count,
    input  wire [1:0] r_in, g_in, b_in,
    output wire [1:0] r_out, g_out, b_out
);

    localparam [9:0] BAND_TOP = 10'd431;

    wire in_band = (v_count >= BAND_TOP);

    assign r_out = in_band ? (r_in >> 1) : r_in;
    assign g_out = in_band ? (g_in >> 1) : g_in;
    assign b_out = in_band ? (b_in >> 1) : b_in;

endmodule
