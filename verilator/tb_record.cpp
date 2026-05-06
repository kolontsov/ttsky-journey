// Journey — offline MP4 recorder (no SDL, headless)
// Pipes raw RGB24 frames to ffmpeg, collects audio, muxes into MP4.
// Usage: journey_record [--duration SEC] [-o FILE]

// Set to 0 to produce a video-only MP4 (skip audio capture + WAV + ffmpeg mux).
#define RECORD_AUDIO 1

#include <verilated.h>
#include "Vrec.h"
#include "Vrec___024root.h"
#include "Vrec_tt_um_kolontsov_journey.h"
#include "Vrec_clk_gen.h"
#if RECORD_AUDIO
#include "Vrec_synth_engine.h"
#endif

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <vector>
#include <chrono>

static constexpr int H_VISIBLE = 640;
static constexpr int V_VISIBLE = 480;
static constexpr int FRAME_BYTES = H_VISIBLE * V_VISIBLE * 3;
static constexpr int AUDIO_RATE = 36621;  // 25 MHz * 3 / 2048 (phase-accum +3)

static constexpr int H_BACK_PORCH_CLKS = 48;   // pix == master at 25 MHz
static constexpr int H_VISIBLE_CLKS    = 640;
static constexpr int V_OFFSET          = 35;

#if RECORD_AUDIO
static void write_wav(const char* path, const int16_t* data, uint32_t n,
                      uint32_t rate) {
    FILE* f = fopen(path, "wb");
    if (!f) { perror(path); return; }
    uint32_t dsz = n * 2, fsz = 36 + dsz;
    uint32_t br = rate * 2, fmt_sz = 16;
    uint16_t pcm = 1, ch = 1, ba = 2, bits = 16;
    fwrite("RIFF", 1, 4, f); fwrite(&fsz, 4, 1, f);
    fwrite("WAVEfmt ", 1, 8, f); fwrite(&fmt_sz, 4, 1, f);
    fwrite(&pcm, 2, 1, f); fwrite(&ch, 2, 1, f);
    fwrite(&rate, 4, 1, f); fwrite(&br, 4, 1, f);
    fwrite(&ba, 2, 1, f); fwrite(&bits, 2, 1, f);
    fwrite("data", 1, 4, f); fwrite(&dsz, 4, 1, f);
    fwrite(data, 2, n, f); fclose(f);
}
#endif

int main(int argc, char** argv) {
    int duration_sec = 60;
    const char* output = "journey.mp4";
    bool upscale = false;

    for (int i = 1; i < argc; i++) {
        if ((strcmp(argv[i], "--duration") == 0 || strcmp(argv[i], "-d") == 0)
            && i + 1 < argc)
            duration_sec = atoi(argv[++i]);
        else if (strcmp(argv[i], "-o") == 0 && i + 1 < argc)
            output = argv[++i];
        else if (strcmp(argv[i], "--upscale") == 0)
            upscale = true;
        else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            fprintf(stderr,
                "Usage: %s [--duration SEC] [-o FILE] [--upscale]\n"
                "  --duration, -d  Recording length in seconds (default 60)\n"
                "  -o              Output filename (default journey.mp4)\n"
                "  --upscale       4× nearest-neighbor + pillarbox to 3840x2160\n"
                "                  (single encode pass; for YouTube uploads)\n",
                argv[0]);
            return 0;
        }
    }

    Verilated::commandArgs(argc, argv);
    auto* top = new Vrec;

    // Reset — see audio_tb.cpp::reset_top() for why we clock rst_n=1 first
    // (push 2-FF synchronizer high, then drop rst_n to create a real negedge
    // on rst_n_sync so submodule async resets fire, e.g. synth_noise LFSR seed).
    top->ena = 1; top->ui_in = 0; top->uio_in = 0;
    top->rst_n = 1;
    for (int i = 0; i < 4; i++) {
        top->clk = 0; top->eval();
        top->clk = 1; top->eval();
    }
    top->rst_n = 0; top->eval();
    for (int i = 0; i < 20; i++) {
        top->clk = 0; top->eval();
        top->clk = 1; top->eval();
    }
    top->rst_n = 1;

    // Exact VGA rate: 25 MHz / (800 × 525) = 1250/21 ≈ 59.524 fps
    int total_frames = duration_sec * 1250 / 21 + 1;

    // Step 1: pipe raw frames to ffmpeg (video-only H.264).
    //
    // --upscale: 4× nearest-neighbor → 2560×1920, pillarboxed to 3840×2160
    // (4K), single encode pass. YT locks ≤480p uploads to its worst
    // encoder; 2160p triggers AV1/VP9.
    //
    // tune animation: x264 mode for cartoon/cel content (flat regions +
    // sharp edges) — much closer to pixel art than default film tune.
    //
    // Bitrate-capped (not CRF) on the upscale path: this content (scrolling
    // text + swirling tunnel + sharp nearest-neighbor block edges) defeats
    // CRF's quality target and produces enormous files. Bitrate cap gives
    // predictable size; YT re-encodes anyway.
    //
    // QuickTime compatibility: bf 3 (cap B-frames), g 120 / keyint_min 60
    // (2 s GOP), bufsize 50M (1 s at 50 Mbps — tight enough to keep
    // hardware decoders happy), profile high + level 5.2 (explicit 4K60),
    // movflags +faststart (moov atom at file head for seek-friendly play).
    const char* vf = upscale
        ? "-vf 'scale=2560:1920:flags=neighbor,pad=3840:2160:(ow-iw)/2:(oh-ih)/2:black' "
        : "";
    const char* rate_mode = upscale
        ? "-b:v 50M -maxrate 50M -bufsize 50M "
          "-g 120 -keyint_min 60 -bf 3 "
          "-profile:v high -level 5.2 -movflags +faststart"
        : "-crf 18";
    const char* tune = upscale ? "-tune animation " : "";
    char vid_cmd[1024];
    snprintf(vid_cmd, sizeof(vid_cmd),
        "ffmpeg -y -loglevel warning "
        "-f rawvideo -pixel_format rgb24 -video_size %dx%d -framerate 1250/21 "
        "-i pipe:0 "
        "%s"
        "-c:v libx264 -preset slow %s%s -pix_fmt yuv420p "
        "/tmp/_nh_vid.mp4",
        H_VISIBLE, V_VISIBLE, vf, tune, rate_mode);
    FILE* vpipe = popen(vid_cmd, "w");
    if (!vpipe) {
        fprintf(stderr, "Failed to launch ffmpeg\n");
        return 1;
    }
    setvbuf(vpipe, nullptr, _IOFBF, 1 << 20);

#if RECORD_AUDIO
    std::vector<int16_t> audio_buf;
    audio_buf.reserve(AUDIO_RATE * duration_sec);
#endif

    static uint8_t fb[FRAME_BYTES];
    memset(fb, 0, FRAME_BYTES);

    bool prev_hsync = true, prev_vsync = true;
#if RECORD_AUDIO
    bool prev_sample_msb = false;
#endif
    int h_clk = 0, scan_line = 0, frame_count = 0;

    fprintf(stderr, "Recording %d sec (~%d frames) → %s\n",
            duration_sec, total_frames, output);

    auto t0 = std::chrono::steady_clock::now();

    while (frame_count <= total_frames) {
        bool frame_done = false;
        while (!frame_done) {
            top->clk = 0; top->eval();
            top->clk = 1; top->eval();

            uint8_t uo = top->uo_out;
            bool hsync = (uo >> 7) & 1;
            bool vsync = (uo >> 3) & 1;

#if RECORD_AUDIO
            // Audio: grab one sample per clk_sample_div MSB rising edge.
            // With +3 phase-accum step, MSB toggles 6 times per 2048 master
            // clocks → 3 rising edges → 25M * 3 / 2048 = 36621 Hz exactly.
            uint16_t sd = top->rootp->tt_um_kolontsov_journey->u_clk_gen->clk_sample_div;
            bool curr_msb = (sd >> 10) & 1;
            if (curr_msb && !prev_sample_msb) {
                // `mixed` is 7-bit unsigned (mid = 64). MSB-align to 16-bit
                // before centering — see audio_tb.cpp::read_mixed().
                uint16_t s = top->rootp->tt_um_kolontsov_journey->synth->mixed;
                audio_buf.push_back(static_cast<int16_t>((s << 9) - 32768));
            }
            prev_sample_msb = curr_msb;
#endif

            // Vsync falling edge → frame boundary
            if (prev_vsync && !vsync) {
                if (frame_count > 0) frame_done = true;
                frame_count++;
                scan_line = -V_OFFSET;
            }

            // Hsync rising edge → new scanline
            if (!prev_hsync && hsync) {
                h_clk = 0;
                scan_line++;
            } else {
                h_clk++;
            }

            // Pixel sampling (one pixel per master clock; pix_clk == clk @ 25 MHz)
            int pixel_offset = h_clk - H_BACK_PORCH_CLKS;
            if (scan_line >= 0 && scan_line < V_VISIBLE
                && pixel_offset >= 0 && pixel_offset < H_VISIBLE_CLKS) {
                int px = pixel_offset;
                uint8_t r = ((uo >> 0) & 1) << 1 | ((uo >> 4) & 1);
                uint8_t g = ((uo >> 1) & 1) << 1 | ((uo >> 5) & 1);
                uint8_t b = ((uo >> 2) & 1) << 1 | ((uo >> 6) & 1);
                int idx = (scan_line * H_VISIBLE + px) * 3;
                fb[idx]     = r * 85;
                fb[idx + 1] = g * 85;
                fb[idx + 2] = b * 85;
            }

            prev_hsync = hsync;
            prev_vsync = vsync;
        }

        fwrite(fb, 1, FRAME_BYTES, vpipe);

        if (frame_count % 60 == 0) {
            auto now = std::chrono::steady_clock::now();
            double elapsed = std::chrono::duration<double>(now - t0).count();
            double fps = frame_count / elapsed;
            double eta = (total_frames - frame_count) / fps;
            fprintf(stderr, "\r  %d/%d frames  %.1f sim-fps  ETA %.0fs  ",
                    frame_count, total_frames, fps, eta);
        }
    }

    auto t1 = std::chrono::steady_clock::now();
    double wall = std::chrono::duration<double>(t1 - t0).count();
    fprintf(stderr, "\n  Sim done: %d frames in %.1fs (%.1f sim-fps)\n",
            frame_count, wall, frame_count / wall);

    pclose(vpipe);

#if RECORD_AUDIO
    // Step 2: write audio WAV
    const char* wav_path = "/tmp/_nh_aud.wav";
    write_wav(wav_path, audio_buf.data(), audio_buf.size(), AUDIO_RATE);
    fprintf(stderr, "  Audio: %zu samples (%.1f sec)\n",
            audio_buf.size(), audio_buf.size() / (double)AUDIO_RATE);

    // Step 3: mux video + audio into final MP4
    char mux_cmd[1024];
    snprintf(mux_cmd, sizeof(mux_cmd),
        "ffmpeg -y -loglevel warning "
        "-i /tmp/_nh_vid.mp4 -i %s "
        "-c:v copy -c:a aac -b:a 192k -shortest "
        "\"%s\"",
        wav_path, output);
    fprintf(stderr, "  Muxing → %s\n", output);
    int rc = system(mux_cmd);

    remove("/tmp/_nh_vid.mp4");
    remove(wav_path);
#else
    // Video-only: move intermediate to final output
    remove(output);
    int rc = rename("/tmp/_nh_vid.mp4", output);
#endif
    delete top;

    if (rc == 0)
        fprintf(stderr, "Done: %s\n", output);
    else {
#if RECORD_AUDIO
        fprintf(stderr, "Mux failed (exit %d)\n", rc);
#else
        fprintf(stderr, "Failed to write %s\n", output);
#endif
        return 1;
    }
    return 0;
}
