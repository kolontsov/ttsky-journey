#!/usr/bin/env python3
"""Generate src/cat_speech.sv.

Bubble frame is procedural (no ROM) — rectangle body + beveled corners +
staircase tail. Text is inline case logic over a 6×8 ATI font with only
the 9 glyphs we actually use. 2-bit frame palette: 0=trans, 1=fill (yellow),
2=border (black). Text pixels override fill at sample time.
sel=0 "LUMOS!", sel=1 "MEEOW!".
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from sv_template import render_sv

ROOT = Path(__file__).resolve().parent.parent
OUT_SV = ROOT / "src" / "cat_speech.sv"
FONT_OTB = ROOT / "scripts" / "data" / "Bm437_ATI_SmallW_6x8.otb"

CHAR_W = 6
CHAR_H = 8
N_CHARS = 6
PAD_L = 5
PAD_R = 3
PAD_T = 3
PAD_B = 2
BORDER = 1

SW = BORDER + PAD_L + CHAR_W * N_CHARS + PAD_R + BORDER   # 1+5+36+3+1 = 46
BODY_H = BORDER + PAD_T + CHAR_H + PAD_B + BORDER         # 1+3+8+2+1  = 15

TAIL_STEPS = [
    (0, 6, 13),
    (1, 7, 12),
    (2, 8, 11),
    (3, 9, 10),
]

# Beveled chamfer per corner: 3 cells transparent + 1 stair (border).
CORNER_W = 3
CORNER_H = 2
CORNER_CUT = [(0, 0), (0, 1), (1, 0)]
CORNER_STAIR = [(1, 1)]
TAIL_H = max(dy for dy, _, _ in TAIL_STEPS) + 1            # 4
SH = BODY_H + TAIL_H                                       # 19

TEXT_SX0 = BORDER + PAD_L                                  # 6
TEXT_SY0 = BORDER + PAD_T                                  # 4

# Per-variant texts. Length == N_CHARS; space = blank (idx 0).
TEXTS = ["LUMOS!", "MEEOW!"]

# Glyph indices 1.. in insertion order; 0 = blank. Order is autotuned —
# scripts/search/speech_best.json overrides this default if present.
_DEFAULT_GLYPH_CHARS = ['L', 'U', 'M', 'O', 'S', '!', 'E', 'W']


def _load_glyph_chars() -> list[str]:
    import json
    path = Path(__file__).parent / "search" / "speech_best.json"
    if not path.exists():
        return list(_DEFAULT_GLYPH_CHARS)
    try:
        loaded = list(json.loads(path.read_text())["glyph_chars"])
    except (json.JSONDecodeError, KeyError, OSError):
        return list(_DEFAULT_GLYPH_CHARS)
    if sorted(loaded) != sorted(_DEFAULT_GLYPH_CHARS):
        import sys
        sys.stderr.write(
            f"WARNING: speech_best.json glyphs {sorted(loaded)!r} ≠ "
            f"expected {sorted(_DEFAULT_GLYPH_CHARS)!r}; using default order. "
            "Re-run `make speech-search`.\n"
        )
        return list(_DEFAULT_GLYPH_CHARS)
    return loaded


GLYPH_CHARS = _load_glyph_chars()
GLYPH_IDX = {ch: i + 1 for i, ch in enumerate(GLYPH_CHARS)}
GLYPH_IDX[' '] = 0


def load_bitmap_font(path: Path, char_w: int, char_h: int) -> dict[str, list[int]]:
    font = ImageFont.truetype(str(path), size=char_h)
    glyphs: dict[str, list[int]] = {}
    canvas_w = char_w + 4
    canvas_h = char_h + 4
    for ch in GLYPH_CHARS:
        img = Image.new("L", (canvas_w, canvas_h), 0)
        ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=255)
        rows = []
        for y in range(char_h):
            byte = 0
            for x in range(char_w):
                if img.getpixel((x, y)) > 128:
                    byte |= 1 << x
            rows.append(byte)
        glyphs[ch] = rows
    return glyphs


def build_frame() -> list[list[int]]:
    border = 2
    grid = [[0] * SW for _ in range(SH)]

    for y in range(BODY_H):
        for x in range(SW):
            grid[y][x] = 1
    for x in range(SW):
        grid[0][x] = border
        grid[BODY_H - 1][x] = border
    for y in range(BODY_H):
        grid[y][0] = border
        grid[y][SW - 1] = border

    def place(pattern, value):
        for ry, rx in pattern:
            grid[ry][rx] = value
            grid[ry][SW - 1 - rx] = value
            grid[BODY_H - 1 - ry][rx] = value
            grid[BODY_H - 1 - ry][SW - 1 - rx] = value
    place(CORNER_CUT, 0)
    place(CORNER_STAIR, border)

    for i, (dy, left, right) in enumerate(TAIL_STEPS):
        y = BODY_H + dy
        if right - left >= 2:
            grid[y][left] = border
            grid[y][right] = border
            for x in range(left + 1, right):
                grid[y][x] = 1
            if i == 0:
                for x in range(left, right + 1):
                    grid[BODY_H - 1][x] = 1
        else:
            for x in range(left, right + 1):
                grid[y][x] = border

    return grid


def proc_pixel(sx: int, sy: int) -> int:
    # Python mirror of the SV frame logic — for self-check vs build_frame().
    BH1 = BODY_H - 1
    SW1 = SW - 1
    body_y = sy <= BH1
    body_edge = body_y and (sy == 0 or sy == BH1 or sx == 0 or sx == SW1)

    near_l = sx < CORNER_W
    near_r = sx > SW - 1 - CORNER_W
    near_t = sy < CORNER_H
    near_b = (sy > BH1 - CORNER_H) and body_y
    in_corner = (near_l or near_r) and (near_t or near_b)

    rx = sx if near_l else (SW1 - sx)
    ry = sy if near_t else (BH1 - sy)

    corner_cut = in_corner and (ry, rx) in CORNER_CUT
    corner_stair = in_corner and (ry, rx) in CORNER_STAIR

    in_tail = BODY_H <= sy <= BODY_H + 3
    tdelta = (sy - BODY_H) & 0b11
    tl = 6 + tdelta
    tr = 13 - tdelta
    tail_edge = in_tail and (sx == tl or sx == tr)
    tail_fill = in_tail and tl < sx < tr

    tail_joint = sy == BH1 and 6 <= sx <= 13

    if corner_cut:
        return 0
    if body_y:
        if tail_joint:
            return 1
        if corner_stair or body_edge:
            return 2
        return 1
    if tail_edge:
        return 2
    if tail_fill:
        return 1
    return 0


def check_frame_proc(grid: list[list[int]]) -> None:
    for sy in range(SH):
        for sx in range(SW):
            want = grid[sy][sx]
            got = proc_pixel(sx, sy)
            if want != got:
                raise AssertionError(
                    f"frame mismatch at ({sx},{sy}): grid={want} proc={got}"
                )


def emit_tx_case() -> list[str]:
    L = []
    L.append("    // Divide-by-6: tx -> (char_pos, gx). Outside [0..35] forced blank.")
    L.append("    logic [2:0] char_pos;")
    L.append("    logic [2:0] gx;")
    L.append("    always_comb begin")
    L.append("        case (tx)")
    for tx in range(CHAR_W * N_CHARS):
        cp = tx // CHAR_W
        gxv = tx % CHAR_W
        L.append(f"            6'd{tx}: begin char_pos = 3'd{cp}; gx = 3'd{gxv}; end")
    L.append("            default: begin char_pos = 3'd0; gx = 3'd0; end")
    L.append("        endcase")
    L.append("    end")
    return L


def emit_text_case() -> list[str]:
    L = []
    L.append("    // Text table: {sel, char_pos[2:0]} -> glyph idx (0 = blank)")
    L.append("    logic [3:0] glyph_idx;")
    L.append("    always_comb begin")
    L.append("        case ({sel, char_pos})")
    for si, text in enumerate(TEXTS):
        assert len(text) == N_CHARS, f"{text!r} must be {N_CHARS} chars"
        for cp, ch in enumerate(text):
            idx = GLYPH_IDX[ch]
            if idx == 0:
                continue  # blank slot -> covered by case default
            L.append(f"            4'b{si}_{cp:03b}: glyph_idx = 4'd{idx};  // {ch}")
    L.append("            default: glyph_idx = 4'd0;")
    L.append("        endcase")
    L.append("    end")
    return L


def emit_font_case(font: dict[str, list[int]]) -> list[str]:
    L = []
    L.append("    // Embedded 6x8 font — only the 9 glyphs we actually use.")
    L.append("    // Row LSB = leftmost pixel. Default row = 0 (blank glyph + OOB).")
    L.append("    logic [5:0] glyph_row;")
    L.append("    always_comb begin")
    L.append("        case ({glyph_idx, gy})")
    for ch in GLYPH_CHARS:
        idx = GLYPH_IDX[ch]
        rows = font[ch]
        for gy in range(CHAR_H):
            row = rows[gy] & 0x3F
            if row == 0:
                continue
            addr = (idx << 3) | gy
            L.append(f"            7'd{addr}: glyph_row = 6'b{row:06b};  // {ch} row {gy}")
    L.append("            default: glyph_row = 6'd0;")
    L.append("        endcase")
    L.append("    end")
    return L


def _emit_corner_pattern(name: str, pattern: list[tuple[int, int]]) -> list[str]:
    if not pattern:
        return [f"    wire {name} = 1'b0;"]
    rx_bits = max(1, (CORNER_W - 1).bit_length())
    ry_bits = max(1, (CORNER_H - 1).bit_length())
    terms = [
        f"((ry == {ry_bits}'d{ry}) & (rx == {rx_bits}'d{rx}))"
        for ry, rx in pattern
    ]
    L = [f"    wire {name} = in_corner & ("]
    for i, t in enumerate(terms):
        sep = "  " if i == 0 else "| "
        L.append(f"        {sep}{t}")
    L[-1] = L[-1] + ");"
    return L


def emit_frame_proc() -> list[str]:
    rx_bits = max(1, (CORNER_W - 1).bit_length())
    ry_bits = max(1, (CORNER_H - 1).bit_length())
    L = []
    L.append("    // Procedural bubble frame — rectangle body + beveled corners")
    L.append("    // + staircase tail. No ROM. 2-bit palette: 0=trans,1=fill,2=border.")
    L.append(f"    wire body_y = (sy <= 5'd{BODY_H - 1});")
    L.append(f"    wire body_edge = body_y & ((sy == 5'd0) | (sy == 5'd{BODY_H - 1})")
    L.append(f"                              | (sx == 6'd0) | (sx == 6'd{SW - 1}));")
    L.append("")
    L.append(f"    // Corner region: {CORNER_W}-wide × {CORNER_H}-tall near each corner of body box.")
    L.append(f"    // rx/ry = distance from the nearest outer edge (0..{CORNER_W-1} / 0..{CORNER_H-1}).")
    L.append(f"    wire near_l = (sx < 6'd{CORNER_W});")
    L.append(f"    wire near_r = (sx > 6'd{SW - 1 - CORNER_W});")
    L.append(f"    wire near_t = (sy < 5'd{CORNER_H});")
    L.append(f"    wire near_b = (sy > 5'd{BODY_H - 1 - CORNER_H}) & body_y;")
    L.append("    wire in_corner = (near_l | near_r) & (near_t | near_b);")
    L.append("")
    L.append("    /* verilator lint_off UNUSEDSIGNAL */")
    L.append(f"    wire [5:0] rx_r_full = 6'd{SW - 1} - sx;")
    L.append(f"    wire [4:0] ry_b_full = 5'd{BODY_H - 1} - sy;")
    L.append("    /* verilator lint_on UNUSEDSIGNAL */")
    if rx_bits > 1:
        L.append(f"    wire [{rx_bits-1}:0] rx = near_l ? sx[{rx_bits-1}:0] : rx_r_full[{rx_bits-1}:0];")
    else:
        L.append("    wire rx = near_l ? sx[0] : rx_r_full[0];")
    if ry_bits > 1:
        L.append(f"    wire [{ry_bits-1}:0] ry = near_t ? sy[{ry_bits-1}:0] : ry_b_full[{ry_bits-1}:0];")
    else:
        L.append("    wire ry = near_t ? sy[0] : ry_b_full[0];")
    L.append("")
    L.extend(_emit_corner_pattern("corner_cut", CORNER_CUT))
    L.extend(_emit_corner_pattern("corner_stair", CORNER_STAIR))
    L.append("")
    L.append("    // Tail (rows BODY_H..BODY_H+3, delta = sy - BODY_H).")
    L.append("    // Per row: left = 6+delta, right = 13-delta. Last row (delta=3)")
    L.append("    // collapses to 2 cells with both as border (tail tip).")
    L.append(f"    wire in_tail = (sy >= 5'd{BODY_H}) & (sy <= 5'd{BODY_H + 3});")
    L.append(f"    wire [1:0] tdelta = sy[1:0] - 2'd{BODY_H & 3};  // delta 0..3")
    L.append("    wire [3:0] tl = 4'd6  + {2'b0, tdelta};")
    L.append("    wire [3:0] tr = 4'd13 - {2'b0, tdelta};")
    L.append("    wire tail_edge = in_tail & ((sx == {2'b0, tl}) | (sx == {2'b0, tr}));")
    L.append("    wire tail_fill = in_tail & (sx > {2'b0, tl}) & (sx < {2'b0, tr});")
    L.append("")
    L.append("    // Tail joint: bottom body row at tail x-range becomes fill (not border).")
    L.append(f"    wire tail_joint = (sy == 5'd{BODY_H - 1})")
    L.append("                    & (sx >= 6'd6) & (sx <= 6'd13);")
    L.append("")
    L.append("    logic [1:0] frame_pv;")
    L.append("    always_comb begin")
    L.append("        if (corner_cut)                     frame_pv = 2'd0;  // trans")
    L.append("        else if (body_y) begin")
    L.append("            if (tail_joint)                 frame_pv = 2'd1;  // fill")
    L.append("            else if (corner_stair | body_edge) frame_pv = 2'd2;  // border")
    L.append("            else                            frame_pv = 2'd1;  // fill")
    L.append("        end else if (tail_edge)             frame_pv = 2'd2;  // border")
    L.append("        else if (tail_fill)                 frame_pv = 2'd1;  // fill")
    L.append("        else                                frame_pv = 2'd0;  // trans")
    L.append("    end")
    return L


def write_sv(font: dict[str, list[int]]) -> None:
    tx_lines = emit_tx_case()
    text_lines = emit_text_case()
    font_lines = emit_font_case(font)
    frame_lines = emit_frame_proc()

    TEXT_SX1 = TEXT_SX0 + CHAR_W * N_CHARS - 1
    TEXT_SY1 = TEXT_SY0 + CHAR_H - 1

    render_sv(
        'src/cat_speech.sv.j2',
        OUT_SV,
        texts_0_repr=repr(TEXTS[0]),
        texts_1_repr=repr(TEXTS[1]),
        SW=SW,
        SH=SH,
        TEXT_SX0=TEXT_SX0,
        TEXT_SX1=TEXT_SX1,
        TEXT_SY0=TEXT_SY0,
        TEXT_SY1=TEXT_SY1,
        TEXT_WIDTH=CHAR_W * N_CHARS,
        CHAR_H=CHAR_H,
        n_glyphs=len(GLYPH_CHARS),
        frame_block='\n'.join(frame_lines),
        tx_block='\n'.join(tx_lines),
        text_block='\n'.join(text_lines),
        font_block='\n'.join(font_lines),
    )


def main() -> None:
    font = load_bitmap_font(FONT_OTB, CHAR_W, CHAR_H)
    grid = build_frame()
    check_frame_proc(grid)
    write_sv(font)
    print(f"Wrote {OUT_SV}")
    print(f"  Frame: proc ({SW}x{SH}), self-check passed")
    print(f"  Glyphs: {len(GLYPH_CHARS)}  Texts: {TEXTS}")


if __name__ == "__main__":
    main()
