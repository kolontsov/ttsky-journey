/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Melody: 13-bit square wave + 2-note arp (main/arp swap on arp_sel
 * = song_pos[2]) with per-note octave selected by a phase-accumulator
 * bit-pick (so the arp can cross octaves). 4-bit amp envelope; 15 = mute.
 */

`default_nettype none

module synth_melody (
    input  wire               clk,        // clk_sample domain
    input  wire               rst_n,
    input  wire               song_tick,
    input  wire               mel_trig_now,
    input  wire [2:0]         mel_idx_main_new,
    input  wire [2:0]         mel_idx_arp_new,
    input  wire               mel_ev_main_oct,
    input  wire               mel_ev_arp_oct,
    input  wire [1:0]         song_pos_lo,        // song_pos[1:0]
    input  wire               arp_sel,            // song_pos[2]
    output wire signed [4:0]  melody_sample
);

    // Decay step every 8 song_ticks (song_pos[2:0] == 0).
    wire mel_decay_en = (song_pos_lo == 2'd0) && (arp_sel == 1'b0);

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

    logic [12:0] mel_phase;
    logic [2:0]  mel_idx_main, mel_idx_arp;
    logic        mel_main_oct, mel_arp_oct;
    logic [3:0]  mel_vol;

    wire [6:0]  mel_inc_sel    = note_inc7(arp_sel ? mel_idx_arp : mel_idx_main);
    wire [12:0] mel_phase_next = mel_phase + {6'd0, mel_inc_sel};

    // Read registered phase to keep the 13-bit adder off the inc→mixer path.
    wire cur_oct    = arp_sel ? mel_arp_oct : mel_main_oct;
    wire pulse_high = cur_oct ? mel_phase[11] : mel_phase[12];

    // Mute at vol>=4: arith-shift floor of -16 sticks at -1 forever and
    // buzzes between notes; only vol 0..3 are audible envelope steps.
    wire signed [4:0]  mel_amp_signed = pulse_high ? 5'sh0F : 5'sh10;
    assign melody_sample = (mel_vol[3:2] != 2'b00) ? 5'sd0
                                                   : (mel_amp_signed >>> mel_vol);

    // Only mel_vol is reset (15 = muted until first trigger). phase/note/
    // oct don't need reset pins — they're overwritten on trig and don't
    // matter while muted.
`ifdef __ICARUS__
    initial begin
        mel_phase    = 13'd0;
        mel_idx_main = 3'd0;
        mel_idx_arp  = 3'd0;
        mel_main_oct = 1'b0;
        mel_arp_oct  = 1'b0;
    end
`endif
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) mel_vol <= 4'd15;
        else begin
            mel_phase <= mel_phase_next;
            if (song_tick) begin
                if (mel_decay_en && mel_vol < 4'd15)
                    mel_vol <= mel_vol + 4'd1;
                if (mel_trig_now) begin
                    mel_idx_main <= mel_idx_main_new;
                    mel_idx_arp  <= mel_idx_arp_new;
                    mel_main_oct <= mel_ev_main_oct;
                    mel_arp_oct  <= mel_ev_arp_oct;
                    mel_vol      <= 4'd0;
                end
            end
        end
    end

endmodule
