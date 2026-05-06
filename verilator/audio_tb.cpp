// Journey — audio-only testbench
// Plays synth output via SDL. Supports --wav for pre-rendering.
// Fast-forward trick: skips clocks between sample_ticks.

#include <SDL.h>
#include <verilated.h>
#include "Vaud.h"
#include "Vaud___024root.h"
#include "Vaud_tt_um_kolontsov_journey.h"
#include "Vaud_clk_gen.h"
#include "Vaud_synth_engine.h"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <unistd.h>

static constexpr int SYNTH_RATE = 36621;   // 25M * 3 / 2048 (phase-accum +3)
static constexpr int SDL_RATE   = 48000;
static constexpr int WAV_SECS   = 30;

static Vaud* top;
static int64_t frac_err = 0;
static uint64_t samples_out = 0;

static inline int16_t read_mixed() {
    // `mixed` is 7-bit unsigned (mid=64); MSB-align into int16 then center.
    uint16_t s = top->rootp->tt_um_kolontsov_journey->synth->mixed;
    return static_cast<int16_t>((s << 9) - 32768);
}

static inline void advance_tick() {
    // Force one clk_sample rising edge. clk_sample is registered from
    // clk_sample_div[10]; bounce between 0x3FF and 0x400 across two posedges.
    auto* g = top->rootp->tt_um_kolontsov_journey->u_clk_gen;
    g->clk_sample_div = 0x3FF;
    top->clk = 0; top->eval();
    top->clk = 1; top->eval();   // bit10=0 → clk_sample low
    g->clk_sample_div = 0x400;
    top->clk = 0; top->eval();
    top->clk = 1; top->eval();   // bit10=1 → clk_sample rising edge
}

static int16_t produce_sample_resampled() {
    frac_err += SYNTH_RATE;
    if (frac_err >= SDL_RATE) {
        frac_err -= SDL_RATE;
        advance_tick();
    }
    return read_mixed();
}

static void audio_callback(void*, Uint8* stream, int len) {
    auto* out = reinterpret_cast<int16_t*>(stream);
    int n = len / sizeof(int16_t);
    for (int i = 0; i < n; i++)
        out[i] = produce_sample_resampled();
    samples_out += n;
}

static void reset_top() {
    // rst_n_sync zero-inits in Verilator, so a naked rst_n=1→0 on the port
    // produces no negedge and submodule async-resets (e.g. synth_noise LFSR
    // seed 0x1CAF, otherwise stuck at 0 → silent noise channel) never fire.
    // Clock rst_n=1 first to push rst_n_sync→1, then drop to create a negedge.
    top->rst_n = 1; top->ena = 1;
    top->ui_in = 0; top->uio_in = 0;
    for (int i = 0; i < 4; i++) {  // propagate rst_n=1 through 2-FF sync
        top->clk = 0; top->eval();
        top->clk = 1; top->eval();
    }
    top->rst_n = 0; top->eval();   // negedge → submodule async resets fire
    for (int i = 0; i < 20; i++) {
        top->clk = 0; top->eval();
        top->clk = 1; top->eval();
    }
    top->rst_n = 1;
    top->clk = 0; top->eval();
    top->clk = 1; top->eval();
}

static void write_wav(const char* path, const int16_t* data, int n, int rate) {
    FILE* f = fopen(path, "wb");
    if (!f) { perror(path); return; }
    uint32_t dsz = n * 2, fsz = 36 + dsz;
    uint32_t br = rate * 2, fmt = 16;
    uint16_t pcm = 1, ch = 1, ba = 2, bits = 16;
    fwrite("RIFF", 1, 4, f); fwrite(&fsz, 4, 1, f);
    fwrite("WAVEfmt ", 1, 8, f); fwrite(&fmt, 4, 1, f);
    fwrite(&pcm, 2, 1, f); fwrite(&ch, 2, 1, f);
    uint32_t r32 = rate;
    fwrite(&r32, 4, 1, f); fwrite(&br, 4, 1, f);
    fwrite(&ba, 2, 1, f); fwrite(&bits, 2, 1, f);
    fwrite("data", 1, 4, f); fwrite(&dsz, 4, 1, f);
    fwrite(data, 2, n, f); fclose(f);
    fprintf(stderr, "Wrote %s (%d samples, %.1f sec)\n", path, n, n / (float)rate);
}

int main(int argc, char** argv) {
    bool wav_mode = false;
    uint32_t mute = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--wav") == 0) wav_mode = true;
        else if (strncmp(argv[i], "--mute=", 7) == 0)
            mute = strtoul(argv[i] + 7, nullptr, 0);
    }

    Verilated::commandArgs(argc, argv);
    top = new Vaud;
    reset_top();
    top->rootp->tt_um_kolontsov_journey->synth->ch_mute = mute;
    if (mute) fprintf(stderr, "ch_mute = 0x%02x\n", mute);

    SDL_SetHint(SDL_HINT_NO_SIGNAL_HANDLERS, "1");

    if (wav_mode) {
        int total = SYNTH_RATE * WAV_SECS;
        auto* buf = new int16_t[total];
        fprintf(stderr, "Pre-rendering %d sec at %d Hz...\n", WAV_SECS, SYNTH_RATE);
        for (int i = 0; i < total; i++) {
            advance_tick();
            buf[i] = read_mixed();
            if (i % SYNTH_RATE == 0)
                fprintf(stderr, "\r  %d/%d sec", i / SYNTH_RATE, WAV_SECS);
        }
        fprintf(stderr, "\n");
        write_wav("journey.wav", buf, total, SYNTH_RATE);
        delete[] buf;

        if (SDL_Init(SDL_INIT_AUDIO) == 0) {
            SDL_AudioSpec spec{}; uint8_t* wb; uint32_t wl;
            if (SDL_LoadWAV("journey.wav", &spec, &wb, &wl)) {
                SDL_AudioDeviceID d = SDL_OpenAudioDevice(nullptr, 0, &spec, nullptr, 0);
                if (d) {
                    SDL_QueueAudio(d, wb, wl);
                    SDL_PauseAudioDevice(d, 0);
                    fprintf(stderr, "Playing... (Ctrl+C to stop)\n");
                    SDL_Delay(WAV_SECS * 1000 + 500);
                    SDL_CloseAudioDevice(d);
                }
                SDL_FreeWAV(wb);
            }
            SDL_Quit();
        }
    } else {
        if (SDL_Init(SDL_INIT_AUDIO) < 0) {
            fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
            return 1;
        }
        SDL_AudioSpec want{}, have;
        want.freq = SDL_RATE; want.format = AUDIO_S16SYS;
        want.channels = 1; want.samples = 1024;
        want.callback = audio_callback;
        SDL_AudioDeviceID dev = SDL_OpenAudioDevice(nullptr, 0, &want, &have, 0);
        if (!dev) { fprintf(stderr, "SDL audio: %s\n", SDL_GetError()); return 1; }
        fprintf(stderr, "Playing synth (Ctrl+C to stop)...\n");
        SDL_PauseAudioDevice(dev, 0);
        for (;;) {
            usleep(500000);
            fprintf(stderr, "\rsamples: %llu (%.1f sec)\033[K",
                    (unsigned long long)samples_out, samples_out / (double)SDL_RATE);
        }
    }

    delete top;
    return 0;
}
