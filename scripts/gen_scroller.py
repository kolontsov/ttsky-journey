#!/usr/bin/env python3
# Generate src/scroller_rom.sv: text indirection + font ROM.
# Layouts: rows ({idx,row}->byte), cols ({idx,col}->byte, default — best
# cell/wire tradeoff), packed (idx->64-bit). char_idx 0 = most common char
# so case defaults collapse.

import json
import os
import sys
from collections import Counter
from pathlib import Path

from sv_template import render_sv

BEST_JSON = Path(__file__).parent / "search" / "scroller_best.json"


def load_committed_order(msg, text_len=128, lead_in_chars=20):
    # Returns autotuner's best char_order if compatible with msg's alphabet,
    # else None (caller falls back to natural frequency order).
    if not BEST_JSON.exists():
        return None
    try:
        candidate = list(json.loads(BEST_JSON.read_text())["char_order"])
    except (json.JSONDecodeError, KeyError, OSError):
        return None
    expected = set(((" " * lead_in_chars) + msg).ljust(text_len))
    if set(candidate) != expected:
        sys.stderr.write(
            f"WARNING: {BEST_JSON.name} alphabet "
            f"{sorted(set(candidate))!r} ≠ message {sorted(expected)!r}; "
            "regenerating with natural order. Re-run `make scroller-search`.\n"
        )
        return None
    return candidate

# 8×8 font, ASCII 0x20..0x7E, LSB = leftmost pixel.
FONT = {
    0x20: [0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00],
    0x21: [0x18,0x3C,0x3C,0x18,0x18,0x00,0x18,0x00],
    0x22: [0x36,0x36,0x00,0x00,0x00,0x00,0x00,0x00],
    0x23: [0x36,0x36,0x7F,0x36,0x7F,0x36,0x36,0x00],
    0x24: [0x0C,0x3E,0x03,0x1E,0x30,0x1F,0x0C,0x00],
    0x25: [0x00,0x63,0x33,0x18,0x0C,0x66,0x63,0x00],
    0x26: [0x1C,0x36,0x1C,0x6E,0x3B,0x33,0x6E,0x00],
    0x27: [0x06,0x06,0x03,0x00,0x00,0x00,0x00,0x00],
    0x28: [0x18,0x0C,0x06,0x06,0x06,0x0C,0x18,0x00],
    0x29: [0x06,0x0C,0x18,0x18,0x18,0x0C,0x06,0x00],
    0x2A: [0x00,0x66,0x3C,0xFF,0x3C,0x66,0x00,0x00],
    0x2B: [0x00,0x0C,0x0C,0x3F,0x0C,0x0C,0x00,0x00],
    0x2C: [0x00,0x00,0x00,0x00,0x00,0x0C,0x0C,0x06],
    0x2D: [0x00,0x00,0x00,0x3F,0x00,0x00,0x00,0x00],
    0x2E: [0x00,0x00,0x00,0x00,0x00,0x0C,0x0C,0x00],
    0x2F: [0x60,0x30,0x18,0x0C,0x06,0x03,0x01,0x00],
    0x30: [0x3E,0x63,0x73,0x7B,0x6F,0x67,0x3E,0x00],
    0x31: [0x0C,0x0E,0x0C,0x0C,0x0C,0x0C,0x3F,0x00],
    0x32: [0x1E,0x33,0x30,0x1C,0x06,0x33,0x3F,0x00],
    0x33: [0x1E,0x33,0x30,0x1C,0x30,0x33,0x1E,0x00],
    0x34: [0x38,0x3C,0x36,0x33,0x7F,0x30,0x78,0x00],
    0x35: [0x3F,0x03,0x1F,0x30,0x30,0x33,0x1E,0x00],
    0x36: [0x1C,0x06,0x03,0x1F,0x33,0x33,0x1E,0x00],
    0x37: [0x3F,0x33,0x30,0x18,0x0C,0x0C,0x0C,0x00],
    0x38: [0x1E,0x33,0x33,0x1E,0x33,0x33,0x1E,0x00],
    0x39: [0x1E,0x33,0x33,0x3E,0x30,0x18,0x0E,0x00],
    0x3A: [0x00,0x0C,0x0C,0x00,0x00,0x0C,0x0C,0x00],
    0x3B: [0x00,0x0C,0x0C,0x00,0x00,0x0C,0x0C,0x06],
    0x3C: [0x18,0x0C,0x06,0x03,0x06,0x0C,0x18,0x00],
    0x3D: [0x00,0x00,0x3F,0x00,0x00,0x3F,0x00,0x00],
    0x3E: [0x06,0x0C,0x18,0x30,0x18,0x0C,0x06,0x00],
    0x3F: [0x1E,0x33,0x30,0x18,0x0C,0x00,0x0C,0x00],
    0x40: [0x3E,0x63,0x7B,0x7B,0x7B,0x03,0x1E,0x00],
    0x41: [0x0C,0x1E,0x33,0x33,0x3F,0x33,0x33,0x00],
    0x42: [0x3F,0x66,0x66,0x3E,0x66,0x66,0x3F,0x00],
    0x43: [0x3C,0x66,0x03,0x03,0x03,0x66,0x3C,0x00],
    0x44: [0x1F,0x36,0x66,0x66,0x66,0x36,0x1F,0x00],
    0x45: [0x7F,0x46,0x16,0x1E,0x16,0x46,0x7F,0x00],
    0x46: [0x7F,0x46,0x16,0x1E,0x16,0x06,0x0F,0x00],
    0x47: [0x3C,0x66,0x03,0x03,0x73,0x66,0x7C,0x00],
    0x48: [0x33,0x33,0x33,0x3F,0x33,0x33,0x33,0x00],
    0x49: [0x1E,0x0C,0x0C,0x0C,0x0C,0x0C,0x1E,0x00],
    0x4A: [0x78,0x30,0x30,0x30,0x33,0x33,0x1E,0x00],
    0x4B: [0x67,0x66,0x36,0x1E,0x36,0x66,0x67,0x00],
    0x4C: [0x0F,0x06,0x06,0x06,0x46,0x66,0x7F,0x00],
    0x4D: [0x63,0x77,0x7F,0x7F,0x6B,0x63,0x63,0x00],
    0x4E: [0x63,0x67,0x6F,0x7B,0x73,0x63,0x63,0x00],
    0x4F: [0x1C,0x36,0x63,0x63,0x63,0x36,0x1C,0x00],
    0x50: [0x3F,0x66,0x66,0x3E,0x06,0x06,0x0F,0x00],
    0x51: [0x1E,0x33,0x33,0x33,0x3B,0x1E,0x38,0x00],
    0x52: [0x3F,0x66,0x66,0x3E,0x36,0x66,0x67,0x00],
    0x53: [0x1E,0x33,0x07,0x0E,0x38,0x33,0x1E,0x00],
    0x54: [0x3F,0x2D,0x0C,0x0C,0x0C,0x0C,0x1E,0x00],
    0x55: [0x33,0x33,0x33,0x33,0x33,0x33,0x3F,0x00],
    0x56: [0x33,0x33,0x33,0x33,0x33,0x1E,0x0C,0x00],
    0x57: [0x63,0x63,0x63,0x6B,0x7F,0x77,0x63,0x00],
    0x58: [0x63,0x63,0x36,0x1C,0x1C,0x36,0x63,0x00],
    0x59: [0x33,0x33,0x33,0x1E,0x0C,0x0C,0x1E,0x00],
    0x5A: [0x7F,0x63,0x31,0x18,0x4C,0x66,0x7F,0x00],
    0x5B: [0x1E,0x06,0x06,0x06,0x06,0x06,0x1E,0x00],
    0x5C: [0x03,0x06,0x0C,0x18,0x30,0x60,0x40,0x00],
    0x5D: [0x1E,0x18,0x18,0x18,0x18,0x18,0x1E,0x00],
    0x5E: [0x08,0x1C,0x36,0x63,0x00,0x00,0x00,0x00],
    0x5F: [0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xFF],
    0x60: [0x0C,0x0C,0x18,0x00,0x00,0x00,0x00,0x00],
    0x61: [0x00,0x00,0x1E,0x30,0x3E,0x33,0x6E,0x00],
    0x62: [0x07,0x06,0x06,0x3E,0x66,0x66,0x3B,0x00],
    0x63: [0x00,0x00,0x1E,0x33,0x03,0x33,0x1E,0x00],
    0x64: [0x38,0x30,0x30,0x3E,0x33,0x33,0x6E,0x00],
    0x65: [0x00,0x00,0x1E,0x33,0x3F,0x03,0x1E,0x00],
    0x66: [0x1C,0x36,0x06,0x0F,0x06,0x06,0x0F,0x00],
    0x67: [0x00,0x00,0x6E,0x33,0x33,0x3E,0x30,0x1F],
    0x68: [0x07,0x06,0x36,0x6E,0x66,0x66,0x67,0x00],
    0x69: [0x0C,0x00,0x0E,0x0C,0x0C,0x0C,0x1E,0x00],
    0x6A: [0x30,0x00,0x30,0x30,0x30,0x33,0x33,0x1E],
    0x6B: [0x07,0x06,0x66,0x36,0x1E,0x36,0x67,0x00],
    0x6C: [0x0E,0x0C,0x0C,0x0C,0x0C,0x0C,0x1E,0x00],
    0x6D: [0x00,0x00,0x33,0x7F,0x7F,0x6B,0x63,0x00],
    0x6E: [0x00,0x00,0x1F,0x33,0x33,0x33,0x33,0x00],
    0x6F: [0x00,0x00,0x1E,0x33,0x33,0x33,0x1E,0x00],
    0x70: [0x00,0x00,0x3B,0x66,0x66,0x3E,0x06,0x0F],
    0x71: [0x00,0x00,0x6E,0x33,0x33,0x3E,0x30,0x78],
    0x72: [0x00,0x00,0x3B,0x6E,0x66,0x06,0x0F,0x00],
    0x73: [0x00,0x00,0x3E,0x03,0x1E,0x30,0x1F,0x00],
    0x74: [0x08,0x0C,0x3E,0x0C,0x0C,0x2C,0x18,0x00],
    0x75: [0x00,0x00,0x33,0x33,0x33,0x33,0x6E,0x00],
    0x76: [0x00,0x00,0x33,0x33,0x33,0x1E,0x0C,0x00],
    0x77: [0x00,0x00,0x63,0x6B,0x7F,0x7F,0x36,0x00],
    0x78: [0x00,0x00,0x63,0x36,0x1C,0x36,0x63,0x00],
    0x79: [0x00,0x00,0x33,0x33,0x33,0x3E,0x30,0x1F],
    0x7A: [0x00,0x00,0x3F,0x19,0x0C,0x26,0x3F,0x00],
    0x7B: [0x38,0x0C,0x0C,0x07,0x0C,0x0C,0x38,0x00],
    0x7C: [0x18,0x18,0x18,0x00,0x18,0x18,0x18,0x00],
    0x7D: [0x07,0x0C,0x0C,0x38,0x0C,0x0C,0x07,0x00],
    0x7E: [0x6E,0x3B,0x00,0x00,0x00,0x00,0x00,0x00],
}

DEFAULT_MSG = "JOURNEY BY VADIM KOLONTSOV * JUST 2 ASIC TILES * NYAN CAT MAGIC * CORDIC * DITHER * CHIPTUNE *"


def load_font_png(path, cell_w=8, cell_h=8, first_char=0x20):
    # PNG bitmap grid (github.com/ianhan/BitmapFonts format).
    from PIL import Image
    img = Image.open(path).convert('L')
    cols = img.width // cell_w
    rows = img.height // cell_h
    font = {}
    for r in range(rows):
        for c in range(cols):
            code = first_char + r * cols + c
            if code > 0x7E:
                break
            glyph = []
            for y in range(cell_h):
                byte = 0
                for x in range(cell_w):
                    if img.getpixel((c * cell_w + x, r * cell_h + y)) > 0:
                        byte |= 1 << x
                glyph.append(byte)
            font[code] = glyph
    return font


def pack_glyph_rows(glyph):
    packed = 0
    for row, byte in enumerate(glyph):
        packed |= byte << (row * 8)
    return packed


def glyph_col(glyph, col):
    value = 0
    for row, byte in enumerate(glyph):
        if (byte >> col) & 1:
            value |= 1 << row
    return value


def generate_sv(msg, out_path, font=None, text_len=128, lead_in_chars=20,
                char_bits=5, scale_h=4, rom_style='case', font_layout='cols',
                char_order=None):
    if rom_style not in ('case', 'readmemh'):
        raise ValueError(f"rom_style must be 'case' or 'readmemh', got {rom_style!r}")
    if font_layout not in ('rows', 'cols', 'packed'):
        raise ValueError(
            f"font_layout must be 'rows', 'cols', or 'packed', got {font_layout!r}"
        )
    if font is None:
        font = FONT

    raw = (' ' * lead_in_chars) + msg
    if len(raw) > text_len:
        raise ValueError(
            f"Message ({len(msg)}) + lead-in ({lead_in_chars}) = {len(raw)} "
            f"exceeds text-len {text_len}"
        )
    padded = raw.ljust(text_len)

    freq = Counter(padded)
    default_order = [ch for ch, _ in freq.most_common()]
    if char_order is None:
        ordered_chars = default_order
    else:
        if sorted(char_order) != sorted(default_order):
            raise ValueError(
                f"char_order must be a permutation of {default_order!r}"
            )
        ordered_chars = list(char_order)
    max_glyphs = 1 << char_bits
    if len(ordered_chars) > max_glyphs:
        raise ValueError(
            f"Too many unique chars: {len(ordered_chars)} > {max_glyphs}. "
            f"Simplify message or increase --char-bits."
        )
    char_idx_map = {ch: i for i, ch in enumerate(ordered_chars)}

    text_rom = [char_idx_map[ch] for ch in padded]
    font_rom = {}   # (idx, row) -> 8-bit glyph row, bit 0 = leftmost pixel
    col_rom = {}    # (idx, col) -> 8-bit glyph column, bit 0 = top pixel
    glyph_rom = {}  # idx -> 64-bit row-major glyph
    for ch, idx in char_idx_map.items():
        glyph = font.get(ord(ch), font[0x3F])
        glyph_rom[idx] = pack_glyph_rows(glyph)
        for row in range(8):
            font_rom[(idx, row)] = glyph[row]
        for col in range(8):
            col_rom[(idx, col)] = glyph_col(glyph, col)

    char_addr_bits = (text_len - 1).bit_length()
    font_addr_bits = char_bits + 3  # {char_idx, text_y}
    scale_bits = (scale_h - 1).bit_length()
    if scale_h != 1 << scale_bits:
        raise ValueError(f"scale_h must be a power of 2, got {scale_h}")
    within_char_bits = 3 + scale_bits
    text_x_bits = char_addr_bits + within_char_bits

    px_per_char = 8 * scale_h
    total_px = text_len * px_per_char
    n_glyphs = len(ordered_chars)
    text_nondefault = sum(1 for i in text_rom if i != 0)
    font_nondefault = sum(1 for v in font_rom.values() if v != 0)
    col_nondefault = sum(1 for v in col_rom.values() if v != 0)
    glyph_nondefault = sum(1 for v in glyph_rom.values() if v != 0)

    # Build text-rom block.
    if rom_style == 'case':
        T = []
        T.append(f"    // Text ROM: char_addr -> char_idx (idx 0 = {ordered_chars[0]!r})")
        T.append(f"    logic [{char_bits-1}:0] char_idx;")
        T.append("    always_comb begin")
        T.append("        case (char_addr)")
        for addr, idx in enumerate(text_rom):
            if idx == 0:
                continue
            T.append(f"            {char_addr_bits}'d{addr}: char_idx = {char_bits}'d{idx};")
        T.append(f"            default: char_idx = {char_bits}'d0;")
        T.append("        endcase")
        T.append("    end")
    else:
        out_dir = os.path.dirname(os.path.abspath(out_path))
        text_hex = os.path.join(out_dir, 'scroller_text.hex')
        with open(text_hex, 'w') as f:
            for idx in text_rom:
                f.write(f"{idx:x}\n")
        T = [
            f"    // Text ROM: char_addr -> char_idx (loaded from {os.path.basename(text_hex)})",
            f"    reg [{char_bits-1}:0] text_mem [0:{text_len-1}];",
            f"    initial $readmemh(\"{text_hex}\", text_mem);",
            f"    wire [{char_bits-1}:0] char_idx = text_mem[char_addr];",
        ]
    text_rom_block = '\n'.join(T)

    # Build font/col/glyph ROM block.
    if rom_style == 'case':
        F = []
        if font_layout == 'rows':
            F.append("    // Font ROM: {char_idx, text_y} -> 8-bit glyph row (bit 0 = leftmost pixel)")
            F.append("    logic [7:0] font_byte;")
            F.append("    always_comb begin")
            F.append("        case ({char_idx, text_y})")
            for (idx, row), byte in sorted(font_rom.items()):
                if byte == 0:
                    continue
                full_addr = (idx << 3) | row
                F.append(f"            {font_addr_bits}'d{full_addr}: font_byte = 8'h{byte:02X};")
            F.append("            default: font_byte = 8'h00;")
            F.append("        endcase")
            F.append("    end")
        elif font_layout == 'cols':
            F.append("    // Column ROM: {char_idx, glyph_x} -> 8-bit glyph column (bit 0 = top pixel)")
            F.append(f"    wire [2:0] glyph_x = text_x[{within_char_bits-1}:{scale_bits}];")
            F.append("    logic [7:0] font_col;")
            F.append("    always_comb begin")
            F.append("        case ({char_idx, glyph_x})")
            for (idx, col), byte in sorted(col_rom.items()):
                if byte == 0:
                    continue
                full_addr = (idx << 3) | col
                F.append(f"            {font_addr_bits}'d{full_addr}: font_col = 8'h{byte:02X};")
            F.append("            default: font_col = 8'h00;")
            F.append("        endcase")
            F.append("    end")
        else:
            F.append("    // Packed glyph ROM: char_idx -> 64-bit row-major glyph bitmap")
            F.append("    logic [63:0] glyph_bits;")
            F.append("    always_comb begin")
            F.append("        case (char_idx)")
            for idx, bits in sorted(glyph_rom.items()):
                if bits == 0:
                    continue
                F.append(f"            {char_bits}'d{idx}: glyph_bits = 64'h{bits:016X};")
            F.append("            default: glyph_bits = 64'h0000000000000000;")
            F.append("        endcase")
            F.append("    end")
    else:
        out_dir = os.path.dirname(os.path.abspath(out_path))
        if font_layout == 'rows':
            font_hex = os.path.join(out_dir, 'scroller_font.hex')
            font_mem_size = (1 << char_bits) * 8
            with open(font_hex, 'w') as f:
                for addr in range(font_mem_size):
                    idx = addr >> 3
                    row = addr & 7
                    f.write(f"{font_rom.get((idx, row), 0):02x}\n")
            F = [
                f"    // Font ROM: {{char_idx, text_y}} -> 8-bit glyph row (loaded from {os.path.basename(font_hex)})",
                f"    reg [7:0] font_mem [0:{font_mem_size-1}];",
                f"    initial $readmemh(\"{font_hex}\", font_mem);",
                f"    wire [7:0] font_byte = font_mem[{{char_idx, text_y}}];",
            ]
        elif font_layout == 'cols':
            font_hex = os.path.join(out_dir, 'scroller_font_cols.hex')
            font_mem_size = (1 << char_bits) * 8
            with open(font_hex, 'w') as f:
                for addr in range(font_mem_size):
                    idx = addr >> 3
                    col = addr & 7
                    f.write(f"{col_rom.get((idx, col), 0):02x}\n")
            F = [
                f"    // Column ROM: {{char_idx, glyph_x}} -> 8-bit glyph column (loaded from {os.path.basename(font_hex)})",
                f"    wire [2:0] glyph_x = text_x[{within_char_bits-1}:{scale_bits}];",
                f"    reg [7:0] font_mem [0:{font_mem_size-1}];",
                f"    initial $readmemh(\"{font_hex}\", font_mem);",
                "    wire [7:0] font_col = font_mem[{char_idx, glyph_x}];",
            ]
        else:
            glyph_hex = os.path.join(out_dir, 'scroller_glyph.hex')
            glyph_mem_size = 1 << char_bits
            with open(glyph_hex, 'w') as f:
                for idx in range(glyph_mem_size):
                    f.write(f"{glyph_rom.get(idx, 0):016x}\n")
            F = [
                f"    // Packed glyph ROM: char_idx -> 64-bit bitmap (loaded from {os.path.basename(glyph_hex)})",
                f"    reg [63:0] glyph_mem [0:{glyph_mem_size-1}];",
                f"    initial $readmemh(\"{glyph_hex}\", glyph_mem);",
                "    wire [63:0] glyph_bits = glyph_mem[char_idx];",
            ]
    font_rom_block = '\n'.join(F)

    # Build pixel-assign + optional unused tail.
    Tl = []
    if font_layout == 'rows':
        Tl.append(f"    // {scale_h}x horizontal scale: font bit = text_x[{within_char_bits-1}:{scale_bits}]")
        Tl.append(f"    assign pixel = font_byte[text_x[{within_char_bits-1}:{scale_bits}]];")
    elif font_layout == 'cols':
        Tl.append("    // Column bit: font_col[text_y]")
        Tl.append("    assign pixel = font_col[text_y];")
    else:
        Tl.append(f"    // Packed glyph bit = glyph_bits[{{text_y, text_x[{within_char_bits-1}:{scale_bits}]}}]")
        Tl.append(f"    wire [5:0] bit_addr = {{text_y, text_x[{within_char_bits-1}:{scale_bits}]}};")
        Tl.append("    assign pixel = glyph_bits[bit_addr];")
    if scale_bits > 0:
        Tl.append("")
        Tl.append(f"    wire _unused = &{{text_x[{scale_bits-1}:0], 1'b0}};")
    tail_block = '\n'.join(Tl)

    render_sv(
        'src/scroller_rom.sv.j2',
        out_path,
        msg=msg,
        text_len=text_len,
        lead_in_chars=lead_in_chars,
        n_glyphs=n_glyphs,
        n_glyphs_x8=n_glyphs * 8,
        max_glyphs=max_glyphs,
        total_px=total_px,
        px_per_char=px_per_char,
        scale_h=scale_h,
        text_nondefault=text_nondefault,
        font_nondefault=font_nondefault,
        col_nondefault=col_nondefault,
        glyph_nondefault=glyph_nondefault,
        font_layout=font_layout,
        rom_style=rom_style,
        text_x_bits_m1=text_x_bits - 1,
        char_addr_bits_m1=char_addr_bits - 1,
        within_char_bits=within_char_bits,
        text_rom_block=text_rom_block,
        font_rom_block=font_rom_block,
        tail_block=tail_block,
    )

    print(f"Generated: {out_path} (rom_style={rom_style}, font_layout={font_layout})")
    print(f'Message: "{msg}" ({len(msg)} chars)')
    print(f"Text buffer: {text_len} chars, {total_px} px wide, {n_glyphs} unique glyphs")
    print(f"Text ROM: {text_nondefault}/{text_len} non-default entries")
    if font_layout == 'rows':
        print(f"Font ROM: {font_nondefault}/{n_glyphs * 8} non-default entries")
    elif font_layout == 'cols':
        print(f"Column ROM: {col_nondefault}/{n_glyphs * 8} non-default entries")
    else:
        print(f"Glyph ROM: {glyph_nondefault}/{n_glyphs} non-default entries")


if __name__ == "__main__":
    args = sys.argv[1:]
    font_path = None
    text_len = 128
    lead_in = 20
    rom_style = 'case'
    font_layout = 'cols'
    char_order = None

    while args and args[0].startswith('--'):
        flag = args.pop(0)
        if flag == '--font':
            font_path = args.pop(0)
        elif flag == '--text-len':
            text_len = int(args.pop(0))
        elif flag == '--lead-in':
            lead_in = int(args.pop(0))
        elif flag == '--rom-style':
            rom_style = args.pop(0)
        elif flag == '--font-layout':
            font_layout = args.pop(0)
        elif flag == '--char-order':
            char_order = list(args.pop(0))
        else:
            sys.stderr.write(f"Unknown flag: {flag}\n")
            sys.exit(1)

    msg = args[0] if args else DEFAULT_MSG
    out_path = args[1] if len(args) > 1 else "src/scroller_rom.sv"
    font = load_font_png(font_path) if font_path else None
    if char_order is None:
        char_order = load_committed_order(msg, text_len=text_len, lead_in_chars=lead_in)
    generate_sv(msg, out_path, font, text_len=text_len, lead_in_chars=lead_in,
                rom_style=rom_style, font_layout=font_layout,
                char_order=char_order)
