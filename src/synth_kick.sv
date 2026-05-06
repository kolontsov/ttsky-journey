/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Kick: triangle osc with exponential pitch sweep, 12 song_ticks
 * (~84 ms). Output gated by kick_frames != 0; small click at cutoff is
 * accepted (no zero-cross mute).
 */

`default_nettype none

module synth_kick (
    input  wire               clk,        // clk_sample domain
    input  wire               rst_n,
    input  wire               song_tick,
    input  wire               kick_trig_now,
    output wire signed [5:0]  kick_sample,
    // Mixer ducks bass under kick on this signal — exporting it saves
    // one 13-bit adder column in the mixer.
    output wire               kick_active
);

    logic [11:0] kick_phase;
    logic [4:0]  kick_inc;
    logic [3:0]  kick_frames;

    wire [11:0] kick_phase_next = kick_phase + {7'd0, kick_inc};

    // Read the registered phase, not phase_next, to keep the inc adder
    // off the inc→mixer critical path. 27 us latency is inaudible.
    wire [5:0] kick_tri_fold = kick_phase[11] ? ~kick_phase[10:5]
                                              :  kick_phase[10:5];
    wire signed [5:0]  kick_sample_raw =
        $signed({~kick_tri_fold[5], kick_tri_fold[4:0]});
    assign kick_active = (kick_frames != 4'd0);
    assign kick_sample = kick_active ? kick_sample_raw : 6'sd0;

    // Only kick_frames is reset — it gates audibility, so a random init
    // would burst on power-up. phase/inc are overwritten on the next
    // trigger so they need no reset pin.
`ifdef __ICARUS__
    initial begin
        kick_phase = 12'd0;
        kick_inc   = 5'd0;
    end
`endif
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) kick_frames <= 4'd0;
        else begin
            kick_phase <= kick_phase_next;
            if (song_tick && kick_frames != 4'd0) begin
                kick_inc    <= kick_inc - (kick_inc >> 3);
                kick_frames <= kick_frames - 4'd1;
            end
            // kick_trig_now is already a single-cycle pulse upstream, so
            // no extra song_tick gate is needed.
            if (kick_trig_now) begin
                kick_phase  <= 12'h400;  // quarter-range start
                kick_inc    <= 5'd28;    // ~250 Hz initial
                kick_frames <= 4'd12;
            end
        end
    end

endmodule
