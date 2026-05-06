/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Bass: single 15-bit sawtooth + amp-envelope shift. Retriggered every
 * eighth_edge. Envelope decays 6 dB every 4 song_ticks while env<2, then
 * sustains at -12 dB so bass holds between retrigs instead of plucking.
 */

`default_nettype none

module synth_bass (
    input  wire               clk,        // clk_sample domain
    input  wire               rst_n,
    input  wire               song_tick,
    input  wire               eighth_edge,
    input  wire [7:0]         bass_inc,
    input  wire [1:0]         song_pos_lo,  // song_pos[1:0]
    output wire signed [4:0]  bass_sample
);

    // Decay step every 4 song_ticks (= -6 dB).
    wire bass_decay_en = (song_pos_lo == 2'd0);

    logic [14:0] bass_phase;
    logic [1:0]  bass_env;

    wire [14:0]        bass_phase_next = bass_phase + {7'd0, bass_inc};
    // Read registered phase to keep the inc adder off the inc→mixer path.
    wire signed [4:0]  saw = $signed({~bass_phase[14], bass_phase[13:10]});
    assign bass_sample = (bass_env == 2'd3) ? 5'sd0 : (saw >>> bass_env);

    // Only bass_env is reset (3 = muted until first retrig). Phase needs
    // no reset pin — inaudible while muted, settles after first sample.
`ifdef __ICARUS__
    initial bass_phase = 15'd0;
`endif
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) bass_env <= 2'd3;
        else begin
            bass_phase <= bass_phase_next;
            if (song_tick) begin
                if (bass_decay_en && bass_env < 2'd2)
                    bass_env <= bass_env + 2'd1;
                if (eighth_edge)
                    bass_env <= 2'd0;
            end
        end
    end

endmodule
