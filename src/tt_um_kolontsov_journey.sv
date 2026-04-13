/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_kolontsov_journey (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    // --- VGA timing ---
    wire       hsync, vsync, display_active;
    /* verilator lint_off UNUSEDSIGNAL */
    wire [9:0] pixel_x, pixel_y;
    /* verilator lint_on UNUSEDSIGNAL */

    vga_timing vga_gen (
        .clk            (clk),
        .rst_n          (rst_n),
        .hsync          (hsync),
        .vsync          (vsync),
        .display_active (display_active),
        .pixel_x        (pixel_x),
        .pixel_y        (pixel_y)
    );

    // --- Color XOR pattern ---
    wire [1:0] r = display_active ? pixel_x[7:6] : 2'd0;
    wire [1:0] g = display_active ? pixel_y[7:6] : 2'd0;
    wire [1:0] b = display_active ? (pixel_x[7:6] ^ pixel_y[7:6]) : 2'd0;

    // Tiny VGA Pmod pinout:
    //   uo[0]=R1  uo[1]=G1  uo[2]=B1  uo[3]=vsync
    //   uo[4]=R0  uo[5]=G0  uo[6]=B0  uo[7]=hsync
    assign uo_out = {hsync, b[0], g[0], r[0],
                     vsync, b[1], g[1], r[1]};

    assign uio_out = 8'd0;
    assign uio_oe  = 8'd0;

    wire _unused = &{ena, ui_in, uio_in, 1'b0};

endmodule
