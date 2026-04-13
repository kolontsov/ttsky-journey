/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module vga_timing (
    input  wire        clk,
    input  wire        rst_n,
    output logic       hsync,
    output logic       vsync,
    output logic       display_active,
    output logic [9:0] pixel_x,
    output logic [9:0] pixel_y
);

    // 640x480 @ 60 Hz VGA timing
    localparam H_VISIBLE = 640;
    localparam H_FRONT   = 16;
    localparam H_SYNC    = 96;
    localparam H_TOTAL   = 800;

    localparam V_VISIBLE = 480;
    localparam V_FRONT   = 10;
    localparam V_SYNC    = 2;
    localparam V_TOTAL   = 525;

    logic [9:0] h_count, v_count;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            h_count <= 10'd0;
            v_count <= 10'd0;
        end else begin
            if (h_count == H_TOTAL - 1) begin
                h_count <= 10'd0;
                v_count <= (v_count == V_TOTAL - 1) ? 10'd0 : v_count + 10'd1;
            end else begin
                h_count <= h_count + 10'd1;
            end
        end
    end

    always_comb begin
        hsync          = ~(h_count >= H_VISIBLE + H_FRONT &&
                           h_count <  H_VISIBLE + H_FRONT + H_SYNC);
        vsync          = ~(v_count >= V_VISIBLE + V_FRONT &&
                           v_count <  V_VISIBLE + V_FRONT + V_SYNC);
        display_active = (h_count < H_VISIBLE) && (v_count < V_VISIBLE);
        pixel_x        = h_count;
        pixel_y        = v_count;
    end

endmodule
