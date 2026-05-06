/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Noise: hat + snare on a shared 15-bit Galois LFSR (x^15+x^14+1).
 * mode latches at trigger to choose hat (decay/tick) vs snare
 * (decay/4 ticks, +6 dB). synth_patterns resolves overlap upstream so
 * snare wins.
 */

`default_nettype none

module synth_noise (
    input  wire               clk,        // clk_sample domain
    input  wire               rst_n,
    input  wire               song_tick,
    input  wire               noise_trig_now,
    input  wire               noise_mode,    // 0=hat, 1=snare
    input  wire [1:0]         song_pos_lo,   // song_pos[1:0]
    output wire signed [4:0]  noise_sample
);

    logic [14:0] lfsr;
    logic [2:0]  vol;
    logic        mode;    // latched at trigger time

    wire [14:0] lfsr_next = lfsr[0] ? ((lfsr >> 1) ^ 15'h6000) : (lfsr >> 1);

    // Read registered LFSR to keep XOR off the mixer critical path.
    wire signed [4:0]  noise_byte = $signed({~lfsr[4], lfsr[3:0]});
    // hat is -6 dB vs snare via the >>>1.
    wire signed [4:0]  noise_shl  = mode ? noise_byte : (noise_byte >>> 1);

    assign noise_sample = (vol == 3'd7) ? 5'sd0 : (noise_shl >>> vol);

    wire decay_en = mode ? (song_pos_lo == 2'd0) : 1'b1;

`ifdef __ICARUS__
    initial mode = 1'b0;
`endif
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lfsr <= 15'h1CAF;
            vol  <= 3'd7;
        end else begin
            lfsr <= lfsr_next;
            if (song_tick) begin
                if (decay_en && vol < 3'd7)
                    vol <= vol + 3'd1;
                if (noise_trig_now) begin
                    vol  <= 3'd0;
                    mode <= noise_mode;
                end
            end
        end
    end

endmodule
