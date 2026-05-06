// Gate-level offline recorder.
//
// Drives the post-PnR netlist (tt_um_kolontsov_journey as cell instances) with
// 25 MHz clk, proper rst_n pulse, then captures:
//   frames.bin  — RGB24 raw, 640x480 per frame, packed scanline order
//   audio.bin   — u8 raw, one byte per master clk (0x00 or 0xFF, σΔ output)
//
// Plusargs:
//   +frames=N     stop after N frames captured (default 2)
//   +out_dir=DIR  output directory (default ".")
//
// Mirrors verilator/tb_record.cpp's pixel/scanline timing. Audio diverges:
// no internal `mixed` access, so we dump raw σΔ bitstream and downsample in
// post-process (sox/ffmpeg LPF + decimate). 1 byte/clk @ 25 MHz = ~25 MB/s
// of audio data; ~2 sec is reasonable.

`default_nettype none
`timescale 1ns / 1ps

module tb_record_gl ();

    // Pixel/timing constants — match VGA mode at 25 MHz pix_clk.
    localparam integer H_VISIBLE       = 640;
    localparam integer V_VISIBLE       = 480;
    localparam integer H_BACK_PORCH    = 48;
    localparam integer V_OFFSET        = 35;
    localparam integer FRAME_BYTES     = H_VISIBLE * V_VISIBLE * 3;

    reg         clk = 1'b0;
    // Hold rst_n=0 from t=0: keeps dfstp/dfrtp SET_B/RESET_B at a defined
    // level so X from un-clocked rst_sync1/2 doesn't poison internal latches.
    reg         rst_n = 1'b0;
    reg         ena = 1'b1;
    reg  [7:0]  ui_in = 8'd0;
    reg  [7:0]  uio_in = 8'd0;
    wire [7:0]  uo_out;
    wire [7:0]  uio_out;
    wire [7:0]  uio_oe;
    wire        VPWR = 1'b1;
    wire        VGND = 1'b0;

    tt_um_kolontsov_journey dut (
        .VPWR   (VPWR),
        .VGND   (VGND),
        .ui_in  (ui_in),
        .uo_out (uo_out),
        .uio_in (uio_in),
        .uio_out(uio_out),
        .uio_oe (uio_oe),
        .ena    (ena),
        .clk    (clk),
        .rst_n  (rst_n)
    );

    // 25 MHz clock — period 40 ns, half-period 20 ns.
    always #20 clk = ~clk;

    integer max_frames, log_every;
    integer fd_frames, fd_audio;
    reg [1023:0] out_dir, frames_path, audio_path;

    // VGA decode signals
    wire hsync = uo_out[7];
    wire vsync = uo_out[3];
    wire [1:0] r = {uo_out[0], uo_out[4]};
    wire [1:0] g = {uo_out[1], uo_out[5]};
    wire [1:0] b = {uo_out[2], uo_out[6]};

    // Frame-buffer + scan tracking
    reg [7:0] fb [0:FRAME_BYTES-1];
    integer h_clk, scan_line, frame_count;
    reg prev_hsync, prev_vsync;

    // Buffer σΔ bits in memory, flush at vsync — per-clk $fwrite is the
    // dominant cost in Icarus. Sized > 1 frame (25 MHz / 60 Hz ≈ 416,667).
    localparam integer AUDIO_BUF = 500_000;
    reg [7:0] audio_buf [0:AUDIO_BUF-1];
    integer audio_idx;

    integer i, idx;

    // Diagnostic: classify uio_out[7] as 1 / 0 / X across the run.
    integer aud_ones, aud_zeros, aud_x;
    integer total_clks;

    initial begin
        // Force Q=0 on un-reset dfxtp_* cells. The SKY130 model's Q is a
        // UDP-driven wire — `force` is the only override. After `release`,
        // Q reflects the UDP's state, which only updates on its own clock
        // edge (hence the clk_sample wiggle below).
`include "gl_init_force.vh"

        // Plusargs
        if (!$value$plusargs("frames=%d", max_frames))   max_frames = 2;
        if (!$value$plusargs("log_every=%d", log_every)) log_every = 1;
        if (!$value$plusargs("out_dir=%s", out_dir))     out_dir = "./gl_capture";

        $sformat(frames_path, "%0s/frames.bin", out_dir);
        $sformat(audio_path,  "%0s/audio.bin",  out_dir);

        fd_frames = $fopen(frames_path, "wb");
        fd_audio  = $fopen(audio_path,  "wb");
        if (fd_frames == 0 || fd_audio == 0) begin
            $display("ERROR: could not open output files in %0s", out_dir);
            $finish;
        end

        // Zero framebuffer
        for (i = 0; i < FRAME_BYTES; i = i + 1) fb[i] = 8'd0;
        h_clk = 0; scan_line = 0; frame_count = 0;
        audio_idx = 0;
        prev_hsync = 1'b1; prev_vsync = 1'b1;
        aud_ones = 0; aud_zeros = 0; aud_x = 0; total_clks = 0;

        // Hold rst_n=0 + force for several clks so clk-domain UDPs (e.g.
        // sigma_delta accum) capture defined D from forced upstream Qs.
        // Diverges from RTL test.py / tb_record.cpp which start rst_n=1.
        repeat (8) @(posedge clk);

        // Inject one fake clk_sample posedge so audio-domain UDPs capture
        // defined D. Without this, clk_sample stays 0 throughout force-hold
        // (driver Q forced=0), audio UDP internals stay X, and Q reverts
        // to X on release → σΔ output stuck at X.
        force dut.clk_sample = 1'b1;
        repeat (2) @(posedge clk);
        force dut.clk_sample = 1'b0;
        repeat (2) @(posedge clk);
        release dut.clk_sample;

        // Continue + complete reset cycle.
        repeat (16) @(posedge clk);
        rst_n = 1'b1;
        repeat (4)  @(posedge clk);

`include "gl_init_release.vh"

        $display("[gl-record] capturing %0d frames -> %0s", max_frames, out_dir);
    end

    // Main capture loop — fires every clk after reset release.
    always @(posedge clk) begin
        if (rst_n) begin
            // Audio: buffer σΔ bit (uio_out[7]) as one byte per clk; flush
            // at vsync. Per-clk $fwrite was the dominant cost in Icarus.
            if (audio_idx < AUDIO_BUF) begin
                audio_buf[audio_idx] = uio_out[7] ? 8'hFF : 8'h00;
                audio_idx = audio_idx + 1;
            end

            // Classify σΔ bit. `===` distinguishes X from 0/1 (4-state).
            total_clks = total_clks + 1;
            if      (uio_out[7] === 1'b1) aud_ones  = aud_ones  + 1;
            else if (uio_out[7] === 1'b0) aud_zeros = aud_zeros + 1;
            else                          aud_x     = aud_x     + 1;
            // Snapshot at a few late points: 100k, 1M, 10M clks after reset.
            if (total_clks == 100_000 || total_clks == 1_000_000
                || total_clks == 10_000_000)
                $display("[gl-audio] @%0d clks: ones=%0d zeros=%0d X=%0d  bit=%b",
                         total_clks, aud_ones, aud_zeros, aud_x, uio_out[7]);

            // Vsync falling → realign scan tracking. First vsync after reset
            // arms `frame_count`; subsequent frame boundaries are detected at
            // end-of-visible (below) so we can dump+finish without burning
            // another vertical blanking interval.
            if (prev_vsync && !vsync) begin
                scan_line = -V_OFFSET;
                if (frame_count == 0) frame_count = 1;
            end

            // Hsync rising → new scanline
            if (!prev_hsync && hsync) begin
                h_clk = 0;
                scan_line = scan_line + 1;
                // Heartbeat every 64 lines so progress shows long before the
                // first frame; skip pre-vsync warmup (those pixels aren't kept).
                if (frame_count > 0 && scan_line >= 0
                    && (scan_line & 'h3F) == 0)
                    $display("[gl-record]   line %0d / %0d (frame %0d)  sim=%0t",
                             scan_line, V_VISIBLE, frame_count, $time);

                // End-of-visible region → fb is fully written for this frame.
                // Dump immediately (don't wait for next vsync fall).
                if (frame_count > 0 && scan_line == V_VISIBLE) begin
                    for (i = 0; i < FRAME_BYTES; i = i + 1)
                        $fwrite(fd_frames, "%c", fb[i]);
                    for (i = 0; i < audio_idx; i = i + 1)
                        $fwrite(fd_audio, "%c", audio_buf[i]);
                    audio_idx = 0;
                    if (log_every > 0 && frame_count % log_every == 0)
                        $display("[gl-record]   frame %0d / %0d  sim=%0t",
                                 frame_count, max_frames, $time);
                    if (frame_count >= max_frames) begin
                        $display("[gl-record] done");
                        $display("[gl-audio] FINAL: total=%0d ones=%0d zeros=%0d X=%0d",
                                 total_clks, aud_ones, aud_zeros, aud_x);
                        $fclose(fd_frames);
                        $fclose(fd_audio);
                        $finish;
                    end
                    frame_count = frame_count + 1;
                end
            end else begin
                h_clk = h_clk + 1;
            end

            // Pixel sample (one pixel per clk in visible region)
            if (scan_line >= 0 && scan_line < V_VISIBLE
                && (h_clk - H_BACK_PORCH) >= 0
                && (h_clk - H_BACK_PORCH) < H_VISIBLE) begin
                idx = (scan_line * H_VISIBLE + (h_clk - H_BACK_PORCH)) * 3;
                fb[idx]     = r * 8'd85;
                fb[idx + 1] = g * 8'd85;
                fb[idx + 2] = b * 8'd85;
            end

            prev_hsync <= hsync;
            prev_vsync <= vsync;
        end
    end

    // Watchdog: 50M clocks max (= 2 sec @ 25 MHz) so a stuck sim doesn't hang.
    initial begin
        #(50_000_000 * 40);
        $display("[gl-record] WATCHDOG: 2 sec elapsed, frame_count=%0d", frame_count);
        $fclose(fd_frames);
        $fclose(fd_audio);
        $finish;
    end

endmodule
