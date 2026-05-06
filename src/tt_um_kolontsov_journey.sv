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
    // Keep hierarchy visible to Verilator testbenches; otherwise the small
    // null-synth top gets inlined into root.
    /*verilator public_module*/

    // Reset synchronizer: async assert, sync de-assert. Gives STA real
    // recovery/removal checks on rst_*  → flop.R paths.
    logic rst_sync1, rst_sync2;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rst_sync1 <= 1'b0;
            rst_sync2 <= 1'b0;
        end else begin
            rst_sync1 <= 1'b1;
            rst_sync2 <= rst_sync1;
        end
    end
    // Reset distribution: two domain branches share an upstream delay cell.
    // The clkdlybuf4s25_1 (~150 ps FF / ~275 ps TT) gives FF-corner hold
    // margin on reset removal; without it, harden reports ~40 FF hold
    // violations on flop/RESET_B paths. Branch buf_12s keep each branch
    // under the 0.40 pF cap limit. Mapped cells (not kept wires) so OpenROAD
    // sees them as real placeable instances; Verilator sim takes the
    // straight-wire branch to stay PDK-free.
    wire rst_n_visual;
    wire rst_n_audio;
`ifdef SYNTHESIS
`ifndef NO_SKY130_RESET_TREE
    wire rst_sync2_dly;
    sky130_fd_sc_hd__clkdlybuf4s25_1 u_rst_n_sync_dly (
        .A(rst_sync2),
        .X(rst_sync2_dly)
    );
    sky130_fd_sc_hd__buf_12 u_rst_n_visual_buf (
        .A(rst_sync2_dly),
        .X(rst_n_visual)
    );
    sky130_fd_sc_hd__buf_12 u_rst_n_audio_buf (
        .A(rst_sync2_dly),
        .X(rst_n_audio)
    );
`else
    assign rst_n_visual = rst_sync2;
    assign rst_n_audio  = rst_sync2;
`endif
`else
    assign rst_n_visual = rst_sync2;
    assign rst_n_audio  = rst_sync2;
`endif

    wire clk_sample;

    clk_gen u_clk_gen (
        .clk        (clk),
        .clk_sample (clk_sample)
    );

    wire       hsync, vsync, display_active;
    wire [9:0] pixel_x, pixel_y;

    vga_timing vga_gen (
        .clk            (clk),
        .rst_n          (rst_n_visual),
        .hsync          (hsync),
        .vsync          (vsync),
        .display_active (display_active),
        .pixel_x        (pixel_x),
        .pixel_y        (pixel_y)
    );

    wire [1:0] tun_r, tun_g, tun_b;
    wire       kick_active;

    pixel_shader shader (
        .clk            (clk),
        .rst_n          (rst_n_visual),
        .pixel_x        (pixel_x),
        .pixel_y        (pixel_y),
        .display_active (display_active),
        .vsync          (vsync),
        .kick_active    (kick_active),
        .r              (tun_r),
        .g              (tun_g),
        .b              (tun_b)
    );

    // Synth state resets from the audio branch; the 25 MHz σΔ modulator
    // uses the visual branch instead, which also keeps audio branch cap
    // under the 0.40 pF limit.
    wire audio_out;
`ifdef VERILATOR
    wire [15:0] synth_sample_unused;
`endif

    synth_engine synth (
        .clk_sample    (clk_sample),
        .clk_sd        (clk),
        .rst_n         (rst_n_audio),
        .rst_n_sd      (rst_n_visual),
        .audio_out     (audio_out),
        .kick_active_o (kick_active)
`ifdef VERILATOR
       ,.sample_out (synth_sample_unused)
`endif
    );

    // Pipeline outputs once before the pads to suppress combinational glitches.
    logic [1:0] r_reg, g_reg, b_reg;
    logic       hsync_reg, vsync_reg;

    always_ff @(posedge clk or negedge rst_n_visual) begin
        if (!rst_n_visual) begin
            r_reg     <= 2'd0;
            g_reg     <= 2'd0;
            b_reg     <= 2'd0;
            hsync_reg <= 1'b1;
            vsync_reg <= 1'b1;
        end else begin
            r_reg     <= tun_r;
            g_reg     <= tun_g;
            b_reg     <= tun_b;
            hsync_reg <= hsync;
            vsync_reg <= vsync;
        end
    end

    // Tiny VGA PMOD pinout:
    //   uo[0]=R1  uo[1]=G1  uo[2]=B1  uo[3]=vsync
    //   uo[4]=R0  uo[5]=G0  uo[6]=B0  uo[7]=hsync
    assign uo_out = {hsync_reg, b_reg[0], g_reg[0], r_reg[0],
                     vsync_reg, b_reg[1], g_reg[1], r_reg[1]};

    // Audio on uio[7], all other bidir pins as inputs
    assign uio_out = {audio_out, 7'd0};
    assign uio_oe  = 8'b1000_0000;

`ifdef VERILATOR
    wire _unused = &{ena, ui_in, uio_in, synth_sample_unused, 1'b0};
`else
    wire _unused = &{ena, ui_in, uio_in, 1'b0};
`endif

endmodule
