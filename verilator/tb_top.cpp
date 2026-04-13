/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 */

// Journey — Verilator + SDL2 testbench

#include <SDL.h>
#include <verilated.h>
#include "Vtop.h"

#include <cstdint>
#include <cstdio>
#include <cstring>

static constexpr int H_VISIBLE = 640;
static constexpr int V_VISIBLE = 480;
static constexpr int WIN_W     = H_VISIBLE;
static constexpr int WIN_H     = V_VISIBLE;

static inline uint32_t rgb222_to_argb(uint8_t r2, uint8_t g2, uint8_t b2) {
    return 0xFF000000u
        | (static_cast<uint32_t>(r2 * 85) << 16)
        | (static_cast<uint32_t>(g2 * 85) << 8)
        |  static_cast<uint32_t>(b2 * 85);
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    auto* top = new Vtop;

    SDL_SetHint(SDL_HINT_NO_SIGNAL_HANDLERS, "1");
    if (SDL_Init(SDL_INIT_VIDEO) < 0) {
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

    // Reset
    top->ena = 1; top->ui_in = 0; top->uio_in = 0; top->rst_n = 0;
    for (int i = 0; i < 20; i++) {
        top->clk = 0; top->eval();
        top->clk = 1; top->eval();
    }
    top->rst_n = 1;

    uint32_t fb[H_VISIBLE * V_VISIBLE];
    memset(fb, 0, sizeof(fb));

    bool prev_hsync = true, prev_vsync = true;
    int h_clk = 0, scan_line = 0, frame_count = 0;

    // 25.175 MHz pixel clock = 1:1 with master clock, no divider
    static constexpr int H_BACK_PORCH_CLKS = 48;
    static constexpr int H_VISIBLE_CLKS    = 640;
    static constexpr int V_OFFSET          = 35;

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

        SDL_UpdateTexture(texture, nullptr, fb, H_VISIBLE * sizeof(uint32_t));
        SDL_RenderClear(renderer);
        SDL_RenderCopy(renderer, texture, nullptr, nullptr);
        SDL_RenderPresent(renderer);

        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            if (ev.type == SDL_QUIT) running = false;
            if (ev.type == SDL_KEYDOWN && ev.key.keysym.sym == SDLK_ESCAPE)
                running = false;
        }
    }

    SDL_DestroyTexture(texture);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    delete top;
    return 0;
}
