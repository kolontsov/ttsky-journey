/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * 5-channel chiptune engine — top-level wiring. scripts/engine_song.py is
 * the bit-accurate reference on any divergence.
 *
 *   clk (25 MHz) -x3/2048-> clk_sample (36621 Hz) -/256-> song_tick (143 Hz)
 *   song_pos[12:0] -> 32 bars -> ~57.3 s loop
 *
 * Channels run on clk_sample (~27 us per cycle, ample for adders + mixer);
 * sigma_delta runs on clk_sd (25 MHz, OSR=683, ~86 dB SNR). Channel state
 * lives in synth_{kick,bass,melody,noise}; patterns in synth_patterns.
 * This file owns only timing, structural decode, mixer, and σΔ.
 */

`default_nettype none

module synth_engine (
    input  wire        clk_sample,   // 36.6 kHz audio-tick clock (top gen)
    input  wire        clk_sd,       // sigma-delta clock (25 MHz master)
    input  wire        rst_n,        // 36.6 kHz synth/channel reset
    input  wire        rst_n_sd,     // 25 MHz sigma-delta output reset
    output wire        audio_out,
    // High while kick envelope is alive (~84 ms). Consumed by pixel_shader
    // for beat-synced radial zoom in the BW outro phase.
    output wire        kick_active_o   // alive while kick env decays (~84 ms)
    // Pre-σΔ sample for the Verilator audio sim only.
`ifdef VERILATOR
   ,output wire [15:0] sample_out
`endif
);

    // 256 samples per song step → song_tick high for one clk_sample/step.
    logic [7:0] sample_in_tick;
    wire        song_tick = (sample_in_tick == 8'd0);
`ifdef __ICARUS__
    initial sample_in_tick = 8'd0;
`endif
    always_ff @(posedge clk_sample) sample_in_tick <= sample_in_tick + 8'd1;

    // Reset to all-1s so the first song_tick wraps to 0 and fires the
    // pos=0 triggers (matches engine_song.py's initial _run_triggers()).
    logic [12:0] song_pos;
    wire  [12:0] next_pos = song_pos + 13'd1;
    always_ff @(posedge clk_sample or negedge rst_n) begin
        if (!rst_n)         song_pos <= 13'h1FFF;
        else if (song_tick) song_pos <= next_pos;
    end

    // Triggers / pattern lookups use next_pos (just-advanced); decay
    // gates use song_pos (pre-increment).
    wire [2:0] section_idx = next_pos[12:10];
    wire [1:0] bar_in_s    = next_pos[9:8];
    wire [3:0] sixt_in_b   = next_pos[7:4];
    wire [2:0] eighth_in_b = next_pos[7:5];
    wire       sixt_edge   = song_tick && (next_pos[3:0] == 4'd0);
    wire       eighth_edge = song_tick && (next_pos[4:0] == 5'd0);

    wire        kick_trig_now, noise_trig_now, noise_mode, mel_trig_now;
    wire [2:0]  mel_idx_main_new, mel_idx_arp_new;
    wire        mel_ev_main_oct, mel_ev_arp_oct;
    wire [7:0]  bass_inc;

    synth_patterns u_patterns (
        .section_idx      (section_idx),
        .bar_in_s         (bar_in_s),
        .sixt_in_b        (sixt_in_b),
        .eighth_in_b      (eighth_in_b),
        .sixt_edge        (sixt_edge),
        .kick_trig_now    (kick_trig_now),
        .noise_trig_now   (noise_trig_now),
        .noise_mode       (noise_mode),
        .mel_trig_now     (mel_trig_now),
        .mel_idx_main_new (mel_idx_main_new),
        .mel_idx_arp_new  (mel_idx_arp_new),
        .mel_ev_main_oct  (mel_ev_main_oct),
        .mel_ev_arp_oct   (mel_ev_arp_oct),
        .bass_inc         (bass_inc)
    );

    // Channels: kick is 6b signed (no envelope shifter, so LSB matters
    // for smoothness), bass/melody/noise are 5b signed (their envelopes
    // shift anyway, so -12 dB at the source is free). Mixer 6+5+5 → 7b
    // signed [-64..+61], ~1 LSB headroom. low_mix = kick or bass via
    // ducking mux below; noise_mix shares LFSR for hat+snare.
    wire signed [5:0] kick_sample;
    wire signed [4:0] bass_sample, melody_sample, noise_sample;
    wire              kick_active;
    assign kick_active_o = kick_active;

    synth_kick u_kick (
        .clk           (clk_sample),
        .rst_n         (rst_n),
        .song_tick     (song_tick),
        .kick_trig_now (kick_trig_now),
        .kick_sample   (kick_sample),
        .kick_active   (kick_active)
    );

    synth_bass u_bass (
        .clk           (clk_sample),
        .rst_n         (rst_n),
        .song_tick     (song_tick),
        .eighth_edge   (eighth_edge),
        .bass_inc      (bass_inc),
        .song_pos_lo   (song_pos[1:0]),
        .bass_sample   (bass_sample)
    );

    synth_melody u_melody (
        .clk              (clk_sample),
        .rst_n            (rst_n),
        .song_tick        (song_tick),
        .mel_trig_now     (mel_trig_now),
        .mel_idx_main_new (mel_idx_main_new),
        .mel_idx_arp_new  (mel_idx_arp_new),
        .mel_ev_main_oct  (mel_ev_main_oct),
        .mel_ev_arp_oct   (mel_ev_arp_oct),
        .song_pos_lo      (song_pos[1:0]),
        .arp_sel          (song_pos[2]),
        .melody_sample    (melody_sample)
    );

    synth_noise u_noise (
        .clk            (clk_sample),
        .rst_n          (rst_n),
        .song_tick      (song_tick),
        .noise_trig_now (noise_trig_now),
        .noise_mode     (noise_mode),
        .song_pos_lo    (song_pos[1:0]),
        .noise_sample   (noise_sample)
    );

    // Ducking: kick and bass share a slot. While kick_active, kick owns
    // the slot and bass is silenced — automatic sidechain pump. Bass
    // phase keeps running so it resumes at the right phase; bass_env
    // holds at /4 between retrigs so the release click is masked.
`ifdef VERILATOR
    // Per-channel mute mask for the testbench (kick / noise / bass / melody).
    // duck_en is gated by ~ch_mute[0] so muting kick also disables ducking.
    logic [3:0] ch_mute /* verilator public */ = 4'd0;
    wire              duck_en    = kick_active & ~ch_mute[0];
    wire signed [5:0] kick_gated = ch_mute[0] ? 6'sd0 : kick_sample;
    wire signed [4:0] bass_gated = ch_mute[2] ? 5'sd0 : bass_sample;
    // Bass sign-extended 5→6 to share low_mix width with kick.
    wire signed [5:0] low_mix    = duck_en ? kick_gated
                                           : {bass_gated[4], bass_gated};
    wire signed [4:0] noise_mix  = ch_mute[1] ? 5'sd0 : noise_sample;
    wire signed [4:0] melody_mix = ch_mute[3] ? 5'sd0 : melody_sample;
`else
    wire signed [5:0] low_mix    = kick_active ? kick_sample
                                               : {bass_sample[4], bass_sample};
    wire signed [4:0] noise_mix  = noise_sample;
    wire signed [4:0] melody_mix = melody_sample;
`endif

    wire signed [6:0] mix_signed =
          {low_mix[5],         low_mix}
        + {{2{melody_mix[4]}}, melody_mix}
        + {{2{noise_mix[4]}},  noise_mix};

    // No reset on `mixed`: σΔ `out` is reset and mixed converges in one
    // sample, so power-on pop is inaudible — drops a reset sink.
    logic [6:0] mixed /* verilator public */;
`ifdef __ICARUS__
    initial mixed = 7'd0;
`endif
    // MSB flip biases signed to unsigned for σΔ.
    always_ff @(posedge clk_sample) begin
        mixed <= {~mix_signed[6], mix_signed[5:0]};
    end

`ifdef VERILATOR
    assign sample_out = {mixed, 9'b0};
`endif

    sigma_delta sd (
        .clk       (clk_sd),
        .rst_n     (rst_n_sd),
        .sample_in (mixed),
        .out       (audio_out)
    );

endmodule
