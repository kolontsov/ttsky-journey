/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * AUTO-GENERATED from scripts/song.json by scripts/gen_patterns.py.
 * Run `make gen` after editing the song; do not hand-edit.
 *
 * Combinational decode of arrangement / drums / bass / melody from
 * timing inputs.
 */

`default_nettype none

module synth_patterns (
    input  wire [2:0]  section_idx,
    input  wire [1:0]  bar_in_s,
    input  wire [3:0]  sixt_in_b,
    input  wire [2:0]  eighth_in_b,
    input  wire        sixt_edge,

    output wire        kick_trig_now,
    output wire        noise_trig_now,
    output wire        noise_mode,      // 0=hat, 1=snare (snare wins on overlap)
    output wire        mel_trig_now,

    output wire [2:0]  mel_idx_main_new,
    output wire [2:0]  mel_idx_arp_new,
    output wire        mel_ev_main_oct,
    output wire        mel_ev_arp_oct,
    output wire [7:0]  bass_inc
);

    // Note-increment table after HW phase-width scaling.
    function automatic logic [6:0] note_inc7(input logic [2:0] idx);
        case (idx)
            3'd0: note_inc7 = 7'h31;  // A
            3'd1: note_inc7 = 7'h36;  // B
            3'd2: note_inc7 = 7'h3A;  // C
            3'd3: note_inc7 = 7'h41;  // D
            3'd4: note_inc7 = 7'h49;  // E
            3'd5: note_inc7 = 7'h4E;  // F
            3'd6: note_inc7 = 7'h52;  // F#
            3'd7: note_inc7 = 7'h5D;  // G#
        endcase
    endfunction

    // Arrangement: section_idx 0..7 → variant 0..2
    //   A B A C A B A C
    logic [1:0] variant;
    always_comb case (section_idx)
        3'd0: variant = 2'd0;
        3'd1: variant = 2'd1;
        3'd2: variant = 2'd0;
        3'd3: variant = 2'd2;
        3'd4: variant = 2'd0;
        3'd5: variant = 2'd1;
        3'd6: variant = 2'd0;
        3'd7: variant = 2'd2;
        default: variant = 2'd0;
    endcase

    // Drum events: per-variant SOP decode. Drum rows repeat across the
    // four bars of a section; snare wins over hat on the same sixteenth.
    wire sixt_4_12 = ~sixt_in_b[0] & ~sixt_in_b[1] & sixt_in_b[2];

    logic drum_kick, drum_noise, drum_snare;
    always_comb begin
        case (variant)
            2'd0: begin
                drum_kick  = ~sixt_in_b[0] & ~sixt_in_b[1];
                drum_noise = ~sixt_in_b[0] & |sixt_in_b[2:1];
                drum_snare = sixt_4_12;
            end
            2'd1: begin
                drum_kick  = (~sixt_in_b[0] & ~sixt_in_b[1]) | (sixt_in_b[0] & sixt_in_b[1] & sixt_in_b[2] & sixt_in_b[3]);
                drum_noise = ~sixt_in_b[0] & |sixt_in_b[3:1];
                drum_snare = sixt_4_12 | ~sixt_in_b[0] & sixt_in_b[2] & sixt_in_b[3];
            end
            default: begin
                drum_kick  = ~sixt_in_b[0] & (~sixt_in_b[1] & (~sixt_in_b[2] | ~sixt_in_b[3]) | sixt_in_b[1] & sixt_in_b[2] & sixt_in_b[3]) | sixt_in_b[0] & sixt_in_b[1] & ~sixt_in_b[2] & sixt_in_b[3];
                drum_noise = ~sixt_in_b[0] | (sixt_in_b[1] & sixt_in_b[2] & ~sixt_in_b[3]);
                drum_snare = sixt_4_12 | sixt_in_b[0] & sixt_in_b[1] & sixt_in_b[2] & ~sixt_in_b[3];
            end
        endcase
    end

    assign kick_trig_now  = sixt_edge & drum_kick;
    assign noise_trig_now = sixt_edge & drum_noise;
    assign noise_mode     = drum_snare;

    // Bass = bar chord root + {variant, eighth_in_b} offset.
    // Bassline is transposed by bar; one turnaround offset is bar-specific.
    logic [2:0] bass_root;
    always_comb case (bar_in_s)
        2'd0: bass_root = 3'd0;
        2'd1: bass_root = 3'd6;
        2'd2: bass_root = 3'd1;
        2'd3: bass_root = 3'd4;
        default: bass_root = 3'd0;
    endcase

    logic [2:0] bass_offset;
    logic       bass_oct_bit;
    always_comb begin
        bass_offset  = 3'd0;
        bass_oct_bit = 1'b0;
        case ({variant, eighth_in_b})
            5'b00_010: begin
                bass_oct_bit = 1'b0;
                case (bar_in_s)
                    2'd0: bass_offset = 3'd4;
                    2'd1: bass_offset = 3'd4;
                    2'd2: bass_offset = 3'd5;
                    2'd3: bass_offset = 3'd5;
                    default: bass_offset = 3'd0;
                endcase
            end
            5'b00_110: begin
                bass_oct_bit = 1'b0;
                case (bar_in_s)
                    2'd0: bass_offset = 3'd4;
                    2'd1: bass_offset = 3'd4;
                    2'd2: bass_offset = 3'd5;
                    2'd3: bass_offset = 3'd5;
                    default: bass_offset = 3'd0;
                endcase
            end
            5'b00_111: begin bass_offset = 3'd0; bass_oct_bit = 1'b1; end
            5'b01_001: begin
                bass_oct_bit = 1'b0;
                case (bar_in_s)
                    2'd0: bass_offset = 3'd4;
                    2'd1: bass_offset = 3'd4;
                    2'd2: bass_offset = 3'd5;
                    2'd3: bass_offset = 3'd5;
                    default: bass_offset = 3'd0;
                endcase
            end
            5'b01_011: begin bass_offset = 3'd0; bass_oct_bit = 1'b1; end
            5'b01_100: begin
                bass_oct_bit = 1'b0;
                case (bar_in_s)
                    2'd0: bass_offset = 3'd4;
                    2'd1: bass_offset = 3'd4;
                    2'd2: bass_offset = 3'd5;
                    2'd3: bass_offset = 3'd5;
                    default: bass_offset = 3'd0;
                endcase
            end
            5'b01_110: begin bass_offset = 3'd3; bass_oct_bit = 1'b0; end
            5'b01_111: begin
                bass_oct_bit = 1'b0;
                case (bar_in_s)
                    2'd0: bass_offset = 3'd4;
                    2'd1: bass_offset = 3'd4;
                    2'd2: bass_offset = 3'd5;
                    2'd3: bass_offset = 3'd4;
                    default: bass_offset = 3'd0;
                endcase
            end
            5'b10_001: begin bass_offset = 3'd2; bass_oct_bit = 1'b0; end
            5'b10_010: begin bass_offset = 3'd3; bass_oct_bit = 1'b0; end
            5'b10_011: begin
                bass_oct_bit = 1'b0;
                case (bar_in_s)
                    2'd0: bass_offset = 3'd4;
                    2'd1: bass_offset = 3'd4;
                    2'd2: bass_offset = 3'd5;
                    2'd3: bass_offset = 3'd4;
                    default: bass_offset = 3'd0;
                endcase
            end
            5'b10_100: begin bass_offset = 3'd0; bass_oct_bit = 1'b1; end
            5'b10_101: begin
                bass_oct_bit = 1'b0;
                case (bar_in_s)
                    2'd0: bass_offset = 3'd4;
                    2'd1: bass_offset = 3'd4;
                    2'd2: bass_offset = 3'd5;
                    2'd3: bass_offset = 3'd4;
                    default: bass_offset = 3'd0;
                endcase
            end
            5'b10_110: begin bass_offset = 3'd3; bass_oct_bit = 1'b0; end
            5'b10_111: begin bass_offset = 3'd2; bass_oct_bit = 1'b0; end
            default: ;
        endcase
    end
    wire [2:0] bass_note_idx = bass_root + bass_offset;

    // Melody: per-bit SOP decode over {variant, bar_in_s, eighth_in_b}.
    // Stored fields: main_idx, main_oct, arp_idx, cross_oct.
    // Effective arp_oct = main_oct ^ cross_oct; invalid positions are
    // don't-cares except for `valid`.
    wire [6:0] mel_key = {variant, bar_in_s, eighth_in_b};

    wire mel_ev_valid = ~mel_key[6] & (mel_key[2] & (mel_key[5] & (mel_key[0] | (mel_key[3] & mel_key[4]))) | ~mel_key[1]) | ~mel_key[5] & (~mel_key[1] | mel_key[6]);
    wire mel_ev_main_idx_0 = mel_key[4] & (mel_key[0] & (~mel_key[1] & (~mel_key[6] | mel_key[3]) | ~mel_key[2] | (mel_key[1] & ~mel_key[5])) | ~mel_key[0] & (mel_key[2] & (mel_key[3] & (~mel_key[6] | mel_key[1]))) | ~mel_key[1] & ~mel_key[2] & ~mel_key[3]) | mel_key[1] & mel_key[3] & ~mel_key[4] & mel_key[5];
    wire mel_ev_main_idx_1 = mel_key[0] & (~mel_key[1] & (~mel_key[6] | ~mel_key[2]) | ~mel_key[4] & (~mel_key[5] | ~mel_key[3])) | mel_key[2] & (mel_key[4] & ((~mel_key[0] & ~mel_key[3]) | (~mel_key[1] & ~mel_key[6])) | mel_key[1] & mel_key[3] & ~mel_key[5]) | (~mel_key[1] & ~mel_key[2] & mel_key[3] & ~mel_key[4]) | (mel_key[1] & ~mel_key[3] & mel_key[4] & ~mel_key[5]);
    wire mel_ev_main_idx_2 = ~mel_key[0] & (~mel_key[2] & (mel_key[3] | mel_key[1]) | ~mel_key[1] & (mel_key[2] & (~mel_key[3] | mel_key[6])) | (mel_key[3] & ~mel_key[4]) | (mel_key[1] & ~mel_key[3] & mel_key[4])) | mel_key[0] & (mel_key[3] & (mel_key[4] & ((~mel_key[1] & ~mel_key[6]) | (mel_key[1] & mel_key[2] & ~mel_key[5])))) | mel_key[1] & ~mel_key[3] & mel_key[5];
    wire mel_ev_main_oct_i = mel_key[4] & (~mel_key[3] & (mel_key[0] & (~mel_key[1] | ~mel_key[5]) | ~mel_key[0] & mel_key[2]) | (~mel_key[0] & mel_key[1] & ~mel_key[5]) | (~mel_key[1] & ~mel_key[2] & mel_key[3] & mel_key[6])) | ~mel_key[0] & (mel_key[3] & ((~mel_key[1] & mel_key[2]) | (mel_key[1] & ~mel_key[2])));
    wire mel_ev_arp_idx_0 = mel_key[4] & (mel_key[3] & (~mel_key[0] & (mel_key[1] | mel_key[6]) | (mel_key[0] & ~mel_key[1] & ~mel_key[6]) | (mel_key[1] & mel_key[2] & ~mel_key[5])) | (~mel_key[0] & ~mel_key[1] & ~mel_key[2]) | (mel_key[1] & ~mel_key[3] & mel_key[5])) | mel_key[1] & mel_key[3] & ~mel_key[4] & mel_key[5];
    wire mel_ev_arp_idx_1 = ~mel_key[0] & (mel_key[3] & (mel_key[6] | ~mel_key[4]) | (~mel_key[1] & ~mel_key[2]) | (mel_key[1] & mel_key[2] & ~mel_key[4])) | mel_key[0] & (mel_key[4] & (~mel_key[6] | ~mel_key[3] | (mel_key[1] & mel_key[2]))) | mel_key[1] & mel_key[3] & mel_key[5];
    wire mel_ev_arp_idx_2 = mel_key[0] & (~mel_key[1] & (~mel_key[4] | (mel_key[3] & mel_key[6])) | ~mel_key[3] & (mel_key[4] & (~mel_key[6] | mel_key[1])) | (~mel_key[2] & mel_key[6]) | (~mel_key[4] & ~mel_key[5])) | mel_key[3] & (~mel_key[0] & (~mel_key[1] & (mel_key[2] | (mel_key[4] & ~mel_key[6])) | mel_key[1] & mel_key[4] & ~mel_key[5]) | mel_key[1] & ~mel_key[2]);
    wire mel_ev_cross_oct = ~mel_key[0] & (mel_key[2] & ((~mel_key[1] & ~mel_key[3] & ~mel_key[4]) | (mel_key[3] & mel_key[4] & mel_key[6])) | mel_key[1] & ((mel_key[3] & mel_key[4] & ~mel_key[5]) | (~mel_key[2] & ~mel_key[3] & ~mel_key[4]))) | mel_key[3] & (mel_key[4] & ((mel_key[0] & ~mel_key[2] & ~mel_key[6]) | (mel_key[1] & mel_key[2] & ~mel_key[5])));

    wire [2:0] mel_ev_main_idx = {mel_ev_main_idx_2, mel_ev_main_idx_1, mel_ev_main_idx_0};
    wire [2:0] mel_ev_arp_idx  = {mel_ev_arp_idx_2,  mel_ev_arp_idx_1,  mel_ev_arp_idx_0};
    assign mel_trig_now    = sixt_edge & ~sixt_in_b[0] & mel_ev_valid;
    assign mel_ev_main_oct = mel_ev_main_oct_i;
    assign mel_ev_arp_oct  = mel_ev_main_oct_i ^ mel_ev_cross_oct;

    /* verilator lint_off UNUSEDSIGNAL */
    wire [6:0] bass_note_inc     = note_inc7(bass_note_idx);
    /* verilator lint_on UNUSEDSIGNAL */
    assign bass_inc         = bass_oct_bit ? {bass_note_inc, 1'b0} : {1'b0, bass_note_inc};
    assign mel_idx_main_new = mel_ev_main_idx;
    assign mel_idx_arp_new  = mel_ev_arp_idx;

endmodule
