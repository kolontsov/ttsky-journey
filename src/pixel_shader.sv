/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Per-pixel combinational video pipeline. Owns the shared frame counter
 * (ctr) + vsync edge detect; cat position/animation state lives inside
 * cat_sprite.
 */

`default_nettype none

module pixel_shader (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [9:0]  pixel_x,
    input  wire [9:0]  pixel_y,
    input  wire        display_active,
    input  wire        vsync,
    input  wire        kick_active,    // from synth_engine, clk_sample domain
    output wire [1:0]  r,
    output wire [1:0]  g,
    output wire [1:0]  b
);

    logic prev_vsync;
    wire  frame_tick = prev_vsync & ~vsync;

    // Free-running 0..2047 frame counter, shared by intro_phase, sd scroll,
    // and cat_sprite animation.
    logic [10:0] ctr;

    wire       phase_cat_vis, phase_speech_vis, phase_speech_sel;
    wire [6:0] phase_wipe_pct;
    wire       phase_wrap, phase_is_cat_in, phase_is_cat_out, phase_cat_in_start;

    // sd = ctr[7:0] + ctr[8:1] ≡ floor(3*N/2) mod 256 — 1.5 px/frame depth
    // scroll without an accumulator. Wraps cleanly at ctr=2047.
    wire [7:0] sd = ctr[7:0] + ctr[8:1];

    // Cat balloon drift: 8-step triangle waves on different periods so the
    // motion isn't diagonal. x cycles ~4.3 s, y ~8.5 s. cat_sprite scales <<2.
    // Speech bubble inherits the drift via cat_rel_x.
    wire [3:0] drift_cx    = ctr[7:4];
    wire [3:0] drift_cy    = ctr[8:5];
    wire [2:0] cat_drift_x = drift_cx[3] ? ~drift_cx[2:0] : drift_cx[2:0];
    wire [2:0] cat_drift_y = drift_cy[3] ? ~drift_cy[2:0] : drift_cy[2:0];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            prev_vsync <= 1'b1;
        else
            prev_vsync <= vsync;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            ctr <= 11'd0;
        else if (frame_tick)
            ctr <= phase_wrap ? 11'd0 : ctr + 11'd1;
    end

    // Beat-synced radial zoom on the BW bookends (slots 0 and 15):
    // kick_active 2FF-syncs into pixel-clk, rising edge during a BW slot
    // reloads kick_env=7, frame_tick decrements to 0 (~135 ms decay).
    // env's top bits scale vx outward so the tunnel "pumps" on each kick.
    // first_slot0_done suppresses the first slot 0 (monitor still locking).
    wire is_slot0    = ~|ctr[10:7];
    wire is_slot15   =  &ctr[10:7];
    logic first_slot0_done;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)         first_slot0_done <= 1'b0;
        else if (~is_slot0) first_slot0_done <= 1'b1;
    end
    wire is_bw_pulse = (is_slot15 | is_slot0) & first_slot0_done;
    logic kick_sync1, kick_sync2;
    logic kick_prev;
    logic [2:0] kick_env;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            {kick_sync2, kick_sync1} <= 2'b00;
            kick_prev                <= 1'b0;
            kick_env                 <= 3'd0;
        end else begin
            {kick_sync2, kick_sync1} <= {kick_sync1, kick_active};
            if (frame_tick) begin
                kick_prev <= kick_sync2;
                if (is_bw_pulse & kick_sync2 & ~kick_prev)
                    kick_env <= 3'd7;
                else if (|kick_env)
                    kick_env <= kick_env - 3'd1;
            end
        end
    end

    intro_phase intro_inst (
        .ctr          (ctr),
        .cat_vis      (phase_cat_vis),
        .speech_vis   (phase_speech_vis),
        .speech_sel   (phase_speech_sel),
        .wipe_pct     (phase_wipe_pct),
        .wrap         (phase_wrap),
        .is_cat_in    (phase_is_cat_in),
        .is_cat_out   (phase_is_cat_out),
        .cat_in_start (phase_cat_in_start)
    );

    // Centered coordinates: px in -320..319, py in -240..239.
    wire signed [9:0] px = $signed(pixel_x - 10'd320);
    wire signed [9:0] py = $signed(pixel_y - 10'd240);

    wire [9:0] vx;
    wire [7:0] angle_8bit;

    cordic cordic_inst (
        .px    (px),
        .py    (py),
        .vx    (vx),
        .angle (angle_8bit)
    );

    // kick_env scales vx outward: bits[2]=+25%, [1]=+12.5%, else off.
    // Stays in 10b range (vx_max ~660). Outside BW slots env=0, vx_zoomed==vx.
    wire [9:0] vx_zoom_add = kick_env[2] ? {2'b0, vx[9:2]} :
                             kick_env[1] ? {3'b0, vx[9:3]} :
                                           10'd0;
    wire [9:0] vx_zoomed = vx + vx_zoom_add;

    wire [7:0] depth;

    reciprocal recip_inst (
        .v_in    (vx_zoomed),
        .depth   (depth)
    );

    wire [5:0] bayer_value;

    bayer_dither bayer_inst (
        .bx          (pixel_x[2:0]),
        .by          (pixel_y[2:0]),
        .bayer_value (bayer_value)
    );

    wire [3:0] bv_scaled = bayer_value[5:2];

    wire [7:0] scroll_dither = sd + {4'b0, bv_scaled};
    wire [7:0] d8            = depth + scroll_dither;
    wire [7:0] a8            = angle_8bit + depth + {scroll_dither[6:0], 1'b0};

    wire [7:0] palette_idx = d8 ^ a8;
`ifdef VERILATOR
    // Coverage TB needs a /*verilator public*/ logic alias.
    logic [7:0] palette_idx_cov /* verilator public */;
    always_comb palette_idx_cov = palette_idx;
`endif

    wire [1:0] pal_r, pal_g, pal_b, pal_gray;

    palette palette_inst (
        .idx  (palette_idx),
        .r    (pal_r),
        .g    (pal_g),
        .b    (pal_b),
        .gray (pal_gray)
    );

    // Per-pixel colour-wipe mixer: random threshold reveals colour over gray.
    wire [5:0] pseudo_rand = bayer_value ^ palette_idx[7:2];
    wire       show_color  = {1'b0, pseudo_rand} < phase_wipe_pct;

    wire [1:0] mix_r = show_color ? pal_r : pal_gray;
    wire [1:0] mix_g = show_color ? pal_g : pal_gray;
    wire [1:0] mix_b = show_color ? pal_b : pal_gray;

    wire [1:0] dim_r, dim_g, dim_b;

    dim_fade dim_inst (
        .v_count   (pixel_y),
        .r_in      (mix_r),
        .g_in      (mix_g),
        .b_in      (mix_b),
        .r_out     (dim_r),
        .g_out     (dim_g),
        .b_out     (dim_b)
    );

    wire show_text;
    wire [1:0] text_r, text_g, text_b;
    scroller scroller_inst (
        .clk            (clk),
        .rst_n          (rst_n),
        .frame_tick     (frame_tick),
        .scroll_en      (phase_cat_vis),
        .pixel_x        (pixel_x),
        .pixel_y        (pixel_y),
        .display_active (display_active),
        .bayer_hi       (bayer_value[5]),
        .show_text      (show_text),
        .text_r         (text_r),
        .text_g         (text_g),
        .text_b         (text_b)
    );

    // Scroller wipe uses bayer alone, not palette_idx, so the threshold is
    // time-stable on static text — palette_idx XOR would read as flicker.
    // Gray side is flat 2'd2 so the gold gradient appears during the wipe.
    wire show_color_text = {1'b0, bayer_value} < phase_wipe_pct;
    wire [1:0] text_disp_r = show_color_text ? text_r : 2'd2;
    wire [1:0] text_disp_g = show_color_text ? text_g : 2'd2;
    wire [1:0] text_disp_b = show_color_text ? text_b : 2'd2;

    wire [9:0] cat_rel_x, cat_rel_y;

    wire [1:0] cat_r, cat_g, cat_b;
    wire       cat_visible;
    wire       anim_sub_tick  = (ctr[1:0] == 2'b11);
    wire       phase_cat_move = phase_is_cat_in | phase_is_cat_out;

    cat_sprite cat_inst (
        .clk                (clk),
        .rst_n              (rst_n),
        .frame_tick         (frame_tick),
        .phase_cat_vis      (phase_cat_vis),
        .phase_cat_in_start (phase_cat_in_start),
        .phase_cat_move     (phase_cat_move),
        .anim_sub_tick      (anim_sub_tick),
        .drift_x            (cat_drift_x),
        .drift_y            (cat_drift_y),
        .pixel_x            (pixel_x),
        .pixel_y            (pixel_y),
        .cat_rel_x          (cat_rel_x),
        .cat_rel_y          (cat_rel_y),
        .r                  (cat_r),
        .g                  (cat_g),
        .b                  (cat_b),
        .visible            (cat_visible)
    );

    wire show_cat = display_active & phase_cat_vis & cat_visible;

    // Speech bubble offset chains off cat_rel_{x,y} so it inherits cat
    // position and shares the main pixel_y - cat_y_r subtract.
    localparam int SPEECH_DX_PX = 15 * 4;
    localparam int SPEECH_DY_PX = 14 * 4;
    localparam int SPEECH_PX_W  = 46 * 2;
    localparam int SPEECH_PX_H  = 19 * 2;
    wire [9:0] speech_rel_x = cat_rel_x - 10'(SPEECH_DX_PX);
    wire [9:0] speech_rel_y = cat_rel_y - 10'(SPEECH_DY_PX);
    wire [5:0] speech_sx    = speech_rel_x[6:1];
    wire [4:0] speech_sy    = speech_rel_y[5:1];
    wire       speech_in    = (speech_rel_x < 10'(SPEECH_PX_W))
                            & (speech_rel_y < 10'(SPEECH_PX_H));

    wire [1:0] speech_r, speech_g, speech_b;
    wire       speech_visible;
    cat_speech speech_inst (
        .sel     (phase_speech_sel),
        .sx      (speech_sx),
        .sy      (speech_sy),
        .r       (speech_r),
        .g       (speech_g),
        .b       (speech_b),
        .visible (speech_visible)
    );

    wire show_speech_px = display_active & phase_speech_vis
                        & speech_in & speech_visible;

    wire _unused_speech = &{speech_rel_x[9:7], speech_rel_x[0],
                            speech_rel_y[9:6], speech_rel_y[0],
                            1'b0};

    // Layer priority: speech bubble > cat > scroller > dimmed tunnel.
    assign r = show_speech_px ? speech_r :
               show_cat       ? cat_r    :
               show_text      ? text_disp_r :
               (display_active ? dim_r : 2'd0);
    assign g = show_speech_px ? speech_g :
               show_cat       ? cat_g    :
               show_text      ? text_disp_g :
               (display_active ? dim_g : 2'd0);
    assign b = show_speech_px ? speech_b :
               show_cat       ? cat_b    :
               show_text      ? text_disp_b :
               (display_active ? dim_b : 2'd0);

    wire _unused = &{bayer_value[1:0], 1'b0};

endmodule
