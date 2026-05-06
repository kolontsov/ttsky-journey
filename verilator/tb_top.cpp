// Journey — Verilator + SDL2 testbench
// VGA video: cycle-accurate from Verilator simulation.
// Audio: comment out ENABLE_AUDIO below to build video-only.
#define ENABLE_AUDIO

#include <SDL.h>
#include <verilated.h>
#include "Vtop.h"
#include "Vtop___024root.h"
#include "Vtop_tt_um_kolontsov_journey.h"
#ifdef ENABLE_AUDIO
#include "Vtop_clk_gen.h"
#include "Vtop_synth_engine.h"
#endif

#include <cstdint>
#include <cstdio>
#include <cstring>

// VGA geometry
static constexpr int H_VISIBLE = 640;
static constexpr int V_VISIBLE = 480;
static constexpr int SCALE     = 1;
static constexpr int WIN_W     = H_VISIBLE * SCALE;
static constexpr int WIN_H     = V_VISIBLE * SCALE;

#ifdef ENABLE_AUDIO
static constexpr int SYNTH_RATE = 36621;
static constexpr int SDL_RATE   = 48000;
static Vtop* audio_top = nullptr;
static int64_t frac_err = 0;

static void audio_callback(void*, Uint8* stream, int len) {
    auto* out = reinterpret_cast<int16_t*>(stream);
    int samples = len / static_cast<int>(sizeof(int16_t));
    for (int i = 0; i < samples; i++) {
        frac_err += SYNTH_RATE;
        if (frac_err >= SDL_RATE) {
            frac_err -= SDL_RATE;
            // Force one clk_sample rising edge — see audio_tb.cpp::advance_tick.
            auto* g = audio_top->rootp->tt_um_kolontsov_journey->u_clk_gen;
            g->clk_sample_div = 0x3FF;
            audio_top->clk = 0; audio_top->eval();
            audio_top->clk = 1; audio_top->eval();
            g->clk_sample_div = 0x400;
            audio_top->clk = 0; audio_top->eval();
            audio_top->clk = 1; audio_top->eval();
        }
        // `mixed` is 7-bit unsigned; MSB-align then center. See audio_tb.cpp.
        uint16_t s = audio_top->rootp->tt_um_kolontsov_journey->synth->mixed;
        out[i] = static_cast<int16_t>((s << 9) - 32768);
    }
}
#endif

// Tiny 4x5 digit font for FPS overlay (digits 0-9)
static constexpr uint8_t DIGIT_FONT[10][5] = {
    {0xF,0x9,0x9,0x9,0xF}, // 0
    {0x2,0x6,0x2,0x2,0x7}, // 1
    {0xF,0x1,0xF,0x8,0xF}, // 2
    {0xF,0x1,0xF,0x1,0xF}, // 3
    {0x9,0x9,0xF,0x1,0x1}, // 4
    {0xF,0x8,0xF,0x1,0xF}, // 5
    {0xF,0x8,0xF,0x9,0xF}, // 6
    {0xF,0x1,0x2,0x4,0x4}, // 7
    {0xF,0x9,0xF,0x9,0xF}, // 8
    {0xF,0x9,0xF,0x1,0xF}, // 9
};

static void draw_digit2x(uint32_t* fb, int ox, int oy, int digit, uint32_t color) {
    for (int y = 0; y < 5; y++)
        for (int x = 0; x < 4; x++)
            if (DIGIT_FONT[digit][y] & (0x8 >> x))
                for (int dy = 0; dy < 2; dy++)
                    for (int dx = 0; dx < 2; dx++)
                        fb[(oy + y*2 + dy) * H_VISIBLE + ox + x*2 + dx] = color;
}

static void draw_label(uint32_t* fb, int ox, int oy,
                       const char* text, uint32_t fg, uint32_t bg) {
    constexpr int PAD = 2;
    int n = static_cast<int>(strlen(text));
    int w = n * 10 + PAD * 2;
    int h = 10 + PAD * 2;
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++)
            fb[(oy + y) * H_VISIBLE + ox + x] = bg;
    for (int i = 0; i < n; i++)
        if (text[i] >= '0' && text[i] <= '9')
            draw_digit2x(fb, ox + PAD + i * 10, oy + PAD, text[i] - '0', fg);
}

static inline uint32_t rgb222_to_argb(uint8_t r2, uint8_t g2, uint8_t b2) {
    return 0xFF000000u
        | (static_cast<uint32_t>(r2 * 85) << 16)
        | (static_cast<uint32_t>(g2 * 85) << 8)
        |  static_cast<uint32_t>(b2 * 85);
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    auto* top = new Vtop;
#ifdef ENABLE_AUDIO
    audio_top  = new Vtop;
#endif

    printf("Keybindings:\n");
    printf("  1   — toggle kick            (channel 0, ducks bass on on-beat)\n");
    printf("  2   — toggle noise/hat+snare (channel 1)\n");
    printf("  3   — toggle bass            (channel 2)\n");
    printf("  4   — toggle melody          (channel 3)\n");
    printf("  0   — all channels ON\n");
    printf("  Esc — quit\n");
    printf("  (all channels ON by default)\n\n");

    SDL_SetHint(SDL_HINT_NO_SIGNAL_HANDLERS, "1");

    if (SDL_Init(SDL_INIT_VIDEO
#ifdef ENABLE_AUDIO
        | SDL_INIT_AUDIO
#endif
    ) < 0) {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return 1;
    }

    SDL_Window* window = SDL_CreateWindow("Journey",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, WIN_W, WIN_H, 0);
    SDL_Renderer* renderer = SDL_CreateRenderer(window, -1,
        SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    SDL_Texture* texture = SDL_CreateTexture(renderer,
        SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING,
        H_VISIBLE, V_VISIBLE);

    // See audio_tb.cpp::reset_top() for why rst_n=1 must clock first.
    auto reset = [](Vtop* t) {
        t->ena = 1; t->ui_in = 0; t->uio_in = 0;
        t->rst_n = 1;
        for (int i = 0; i < 4; i++) {  // propagate rst_n=1 through 2-FF sync
            t->clk = 0; t->eval();
            t->clk = 1; t->eval();
        }
        t->rst_n = 0; t->eval();
        for (int i = 0; i < 20; i++) {
            t->clk = 0; t->eval();
            t->clk = 1; t->eval();
        }
        t->rst_n = 1;
    };
    reset(top);

#ifdef ENABLE_AUDIO
    reset(audio_top);
    SDL_AudioSpec want{}, have;
    want.freq     = SDL_RATE;
    want.format   = AUDIO_S16SYS;
    want.channels = 1;
    want.samples  = 4096;
    want.callback = audio_callback;
    SDL_AudioDeviceID audio_dev = SDL_OpenAudioDevice(nullptr, 0, &want, &have, 0);
    SDL_PauseAudioDevice(audio_dev, 0);
#endif

    // --- VGA frame loop ---
    uint32_t fb[H_VISIBLE * V_VISIBLE];
    memset(fb, 0, sizeof(fb));

    bool prev_hsync = true, prev_vsync = true;
    int h_clk = 0;
    int scan_line = 0;
    int frame_count = 0;

    static constexpr int H_BACK_PORCH_CLKS = 48;   // pix == master at 25 MHz
    static constexpr int H_VISIBLE_CLKS    = 640;
    static constexpr int V_OFFSET          = 35;

    Uint32 fps_last_tick = SDL_GetTicks();
    int fps_frame_count = 0;
    int fps_display = 0;

    bool running = true;
    while (running) {
        bool frame_done = false;
        while (!frame_done) {
            top->clk = 0; top->eval();
            top->clk = 1; top->eval();

            uint8_t uo = top->uo_out;
            bool hsync = (uo >> 7) & 1;
            bool vsync = (uo >> 3) & 1;

            if (prev_vsync && !vsync) {
                if (frame_count > 0) frame_done = true;
                frame_count++;
                scan_line = -V_OFFSET;
            }

            if (!prev_hsync && hsync) {
                h_clk = 0;
                scan_line++;
            } else {
                h_clk++;
            }

            int pixel_offset = h_clk - H_BACK_PORCH_CLKS;
            if (scan_line >= 0 && scan_line < V_VISIBLE
                && pixel_offset >= 0 && pixel_offset < H_VISIBLE_CLKS) {
                int px = pixel_offset;
                uint8_t r = ((uo >> 0) & 1) << 1 | ((uo >> 4) & 1);
                uint8_t g = ((uo >> 1) & 1) << 1 | ((uo >> 5) & 1);
                uint8_t b = ((uo >> 2) & 1) << 1 | ((uo >> 6) & 1);
                fb[scan_line * H_VISIBLE + px] = rgb222_to_argb(r, g, b);
            }

            prev_hsync = hsync;
            prev_vsync = vsync;
        }

        fps_frame_count++;
        Uint32 now = SDL_GetTicks();
        if (now - fps_last_tick >= 1000) {
            fps_display = fps_frame_count * 1000 / (now - fps_last_tick);
            fps_frame_count = 0;
            fps_last_tick = now;
        }
        char fps_buf[8];
        snprintf(fps_buf, sizeof(fps_buf), "%02d", fps_display);
        constexpr uint32_t BG = 0xFF333333u;
        int fps_w = static_cast<int>(strlen(fps_buf)) * 10 + 4;
        draw_label(fb, H_VISIBLE - fps_w - 2, 2, fps_buf, 0xFFFFFFFFu, BG);

        SDL_UpdateTexture(texture, nullptr, fb, H_VISIBLE * sizeof(uint32_t));
        SDL_RenderClear(renderer);
        SDL_RenderCopy(renderer, texture, nullptr, nullptr);
        SDL_RenderPresent(renderer);

        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            if (ev.type == SDL_QUIT)
                running = false;
            if (ev.type == SDL_KEYDOWN) {
#ifdef ENABLE_AUDIO
                static const char* names_up[4]  = {"KICK",  "NOISE", "BASS",  "MELODY"};
                static const char* names_low[4] = {"kick",  "noise", "bass",  "melody"};
                auto print_status = []() {
                    auto* s = audio_top->rootp->tt_um_kolontsov_journey->synth;
                    fprintf(stderr, "%s %s %s %s  (mute=0x%02x)\n",
                        (s->ch_mute >> 0) & 1 ? names_low[0] : names_up[0],
                        (s->ch_mute >> 1) & 1 ? names_low[1] : names_up[1],
                        (s->ch_mute >> 2) & 1 ? names_low[2] : names_up[2],
                        (s->ch_mute >> 3) & 1 ? names_low[3] : names_up[3],
                        s->ch_mute);
                };
                auto toggle_ch = [&](int bit) {
                    auto* s = audio_top->rootp->tt_um_kolontsov_journey->synth;
                    s->ch_mute ^= (1u << bit);
                    print_status();
                };
#else
                auto toggle_ch = [](int) {};
#endif
                switch (ev.key.keysym.sym) {
                case SDLK_ESCAPE: running = false; break;
                case SDLK_1: toggle_ch(0); break;
                case SDLK_2: toggle_ch(1); break;
                case SDLK_3: toggle_ch(2); break;
                case SDLK_4: toggle_ch(3); break;
                case SDLK_0:
#ifdef ENABLE_AUDIO
                    audio_top->rootp->tt_um_kolontsov_journey->synth->ch_mute = 0;
                    print_status();
#endif
                    break;
                default: break;
                }
            }
        }
    }

#ifdef ENABLE_AUDIO
    SDL_CloseAudioDevice(audio_dev);
    delete audio_top;
#endif
    SDL_DestroyTexture(texture);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    delete top;
    return 0;
}
