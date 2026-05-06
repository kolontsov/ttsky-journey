/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Phase decoder over the free-running 11-bit frame counter (owned by
 * pixel_shader). Emits per-phase enables and the colour-wipe percent.
 *
 * Layout: 16 slots * 128 frames = 2048 frames (~34.1 s at 60 fps).
 * Natural wrap at ctr==2047 keeps the tunnel-scroll seam clean —
 * sd = ctr[7:0] + ctr[8:1] gives sd(2047)=254, sd(0)=0, same +2 step.
 *
 *   ctr[10:7]  phase        notes
 *   0000       BW_intro_1   tunnel only, cat hidden
 *   0001       BW_intro_2   (repeat — gives viewer's VGA time to lock)
 *   0010       CAT_IN       cat rises from below
 *   0011/0100  SPEECH       "LUMOS!" at full BW (read time)
 *   0101       WIPE_UP      0->63 colour wipe, no bubble
 *   0110-1011  COLOR        full colour, cat drifts, scroller readable
 *   1100       MEOW         "MEEOW!" bubble at full colour
 *   1101       CAT_OUT      cat exits upward
 *   1110       FADE_BW      reverse wipe 64->1
 *   1111       BW_outro     pure BW, cat hidden — clear scene reset
 */

`default_nettype none

module intro_phase (
    input  wire [10:0] ctr,
    output wire        cat_vis,
    output wire        speech_vis,
    output wire        speech_sel,   // 0 = LUMOS!, 1 = MEOW!
    output wire [6:0]  wipe_pct,     // 0 = full BW, 64 = full color
    output wire        wrap,         // ctr == 2047
    output wire        is_cat_in,    // cat rises
    output wire        is_cat_out,   // cat exits
    output wire        cat_in_start  // first frame of CAT_IN (reset cat_y)
);

    assign wrap = &ctr[10:0];

    // Slot index = ctr[10:7]. Bit-pattern matches, no magnitude compares.
    wire is_bw_intro = ~ctr[10] & ~ctr[9] & ~ctr[8];                  // 0-1
    wire is_bw_outro =  ctr[10] &  ctr[9] &  ctr[8] &  ctr[7];        // 15
    wire is_bw       = is_bw_intro | is_bw_outro;
    assign is_cat_in = ~ctr[10] & ~ctr[9] &  ctr[8] & ~ctr[7];        // 2
    wire is_sp_a     = ~ctr[10] & ~ctr[9] &  ctr[8] &  ctr[7];        // 3
    wire is_sp_b     = ~ctr[10] &  ctr[9] & ~ctr[8] & ~ctr[7];        // 4
    wire is_speech   = is_sp_a | is_sp_b;
    wire is_wipe_up  = ~ctr[10] &  ctr[9] & ~ctr[8] &  ctr[7];        // 5
    wire is_color    = (~ctr[10] &  ctr[9] &  ctr[8]) |               // 6-7
                       ( ctr[10] & ~ctr[9]);                          // 8-11
    wire is_meow     =  ctr[10] &  ctr[9] & ~ctr[8] & ~ctr[7];        // 12
    assign is_cat_out=  ctr[10] &  ctr[9] & ~ctr[8] &  ctr[7];        // 13
    wire is_fade     =  ctr[10] &  ctr[9] &  ctr[8] & ~ctr[7];        // 14
    wire is_full     = is_color | is_meow | is_cat_out;

    assign cat_vis      = ~is_bw & ~is_fade;
    assign speech_vis   = is_speech | is_meow;
    assign speech_sel   = is_meow;
    assign cat_in_start = is_cat_in & ~|ctr[6:0];

    // Wipe ramps over 128-frame slot: WIPE_UP 0->63, FADE_BW 64->1.
    wire [6:0] wipe_up_pct = {1'b0, ctr[6:1]};
    wire [6:0] fade_pct    = 7'd64 - {1'b0, ctr[6:1]};
    assign wipe_pct = is_wipe_up ? wipe_up_pct :
                      is_fade    ? fade_pct    :
                      is_full    ? 7'd64       : 7'd0;

endmodule
