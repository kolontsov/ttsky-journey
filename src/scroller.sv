/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Scroller text overlay — owns scroll position, band check, and ROM lookup.
 * Drives a 32-row-tall band (8 font rows x 4x vertical scale) near the
 * bottom of the screen. scroller_rom is the generated font+text ROM.
 */

`default_nettype none

module scroller (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        frame_tick,
    input  wire        scroll_en,       // freeze scroll_x while low (BW phases)
    input  wire [9:0]  pixel_x,
    input  wire [9:0]  pixel_y,
    input  wire        display_active,
    input  wire        bayer_hi,
    output wire        show_text,
    output wire [1:0]  text_r,
    output wire [1:0]  text_g,
    output wire [1:0]  text_b
);

    localparam [9:0] SCROLL_TOP = 10'd442;

    // scroll_x: quarter-pixel units, 10 bits → wraps at 4096 px. +1/frame
    // at 60 fps = 4 px/frame = 240 px/s. ROM is laid out so reset (=0) sits
    // in a blank lead-in zone, so the message slides in from the right.
    // scroll_armed is latched sticky on the first scroll_en so subsequent
    // BW slots don't pause the scroll — only the very first does.
    logic       scroll_armed;
    logic [9:0] scroll_x;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            scroll_armed <= 1'b0;
            scroll_x     <= 10'd0;
        end else begin
            if (scroll_en)
                scroll_armed <= 1'b1;
            if (frame_tick & scroll_armed)
                scroll_x <= scroll_x + 10'd1;
        end
    end

    // One subtract drives both band check and text_y. Underflow when
    // pixel_y < SCROLL_TOP makes the high bits nonzero, so the 5-bit NOR
    // rejects both above- and below-band pixels.
    wire [9:0] text_v_offset = pixel_y - SCROLL_TOP;
    wire       in_band       = (text_v_offset[9:5] == 5'd0);
    wire [2:0] text_y        = text_v_offset[4:2];  // 4x vertical scale

    // {scroll_x,2'b0} shape lets yosys drop the bottom two adder bits.
    wire [11:0] text_x = {2'b0, pixel_x} + {scroll_x, 2'b0};

    wire text_pixel;
    scroller_rom rom_inst (
        .text_y (text_y),
        .text_x (text_x),
        .pixel  (text_pixel)
    );

    assign show_text = display_active & in_band & text_pixel;

    // Edge dither at megapixel seams: on the bottom/top sub-row of a
    // megapixel, half the pixels (bayer_hi) borrow the neighbour band's
    // colour, giving a 2-real-px dithered transition. Suppressed at
    // outermost rows so it doesn't wrap.
    wire on_bot_edge = (text_v_offset[1:0] == 2'b11) && (text_y != 3'd7);
    wire on_top_edge = (text_v_offset[1:0] == 2'b00) && (text_y != 3'd0);
    logic [2:0] eff_y;
    always_comb begin
        if (on_bot_edge && bayer_hi)
            eff_y = text_y + 3'd1;
        else if (on_top_edge && !bayer_hi)
            eff_y = text_y - 3'd1;
        else
            eff_y = text_y;
    end

    // Gold gradient over 8 font rows in 2-row bands.
    logic [1:0] grad_r, grad_g, grad_b;
    always_comb begin
        case (eff_y[2:1])
            2'd0: {grad_r, grad_g, grad_b} = {2'd3, 2'd3, 2'd2}; // warm white
            2'd1: {grad_r, grad_g, grad_b} = {2'd3, 2'd3, 2'd0}; // pure yellow
            2'd2: {grad_r, grad_g, grad_b} = {2'd3, 2'd2, 2'd0}; // amber
            2'd3: {grad_r, grad_g, grad_b} = {2'd2, 2'd1, 2'd0}; // dark amber
        endcase
    end
    assign text_r = grad_r;
    assign text_g = grad_g;
    assign text_b = grad_b;

    wire _unused = &{text_v_offset[1:0], eff_y[0], 1'b0};

endmodule
