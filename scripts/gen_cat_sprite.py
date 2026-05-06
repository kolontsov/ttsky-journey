#!/usr/bin/env python3
"""Generate src/cat_sprite.sv — signature-mask body + sparse accent overlay.

The 26×51×6-frame sprite is two compact bitplanes packed by signature mask:
each row's pixels sharing the same per-frame on/off pattern collapse into
one mask gated by a Boolean predicate over cat_frame. A sparse pv=3 plane
overlays highlights/cheeks. Frame encoding (logical→3-bit) is read from
scripts/search/cat_sprite_best.json (autotuner output)."""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations, product
from pathlib import Path
import sys

from sv_template import render_sv

ROOT = Path(__file__).resolve().parent.parent
OUT_DEFAULT = ROOT / "src" / "cat_sprite.sv"
JSON_PATH = ROOT / "scripts" / "data" / "cat.json"
BEST_PATH = ROOT / "scripts" / "search" / "cat_sprite_best.json"

FRAMES = 6
SW = 26
SH = 51
BODY_W = SW
BODY_H = SH

LEGEND = {".": 0, "#": 1, ":": 2, "@": 2, "+": 3, "*": 3}

# 6 logical frames in a 3-bit code; 2 unused codes are don't-cares for
# predicate minimization. Hand-chosen baseline; autotuner overrides via
# cat_sprite_best.json.
FRAME_ENC_DEFAULT = {0: 0b000, 1: 0b111, 2: 0b011, 3: 0b001, 4: 0b100, 5: 0b110}
FRAME_ENC: dict[int, int] = dict(FRAME_ENC_DEFAULT)
FRAME_ENC_USED: set[int] = set(FRAME_ENC.values())


def set_encoding(enc: dict[int, int]) -> None:
    global FRAME_ENC, FRAME_ENC_USED
    FRAME_ENC = dict(enc)
    FRAME_ENC_USED = set(FRAME_ENC.values())


def load_frame_enc() -> dict[int, int]:
    """Read encoding from cat_sprite_best.json, fall back to default if absent/bad."""
    if not BEST_PATH.exists():
        return dict(FRAME_ENC_DEFAULT)
    try:
        raw = json.loads(BEST_PATH.read_text()).get("frame_enc", {})
        enc = {int(k): int(v) for k, v in raw.items()}
    except (ValueError, TypeError):
        return dict(FRAME_ENC_DEFAULT)
    if set(enc.keys()) != set(range(FRAMES)) or len(set(enc.values())) != FRAMES:
        return dict(FRAME_ENC_DEFAULT)
    if any(v < 0 or v > 7 for v in enc.values()):
        return dict(FRAME_ENC_DEFAULT)
    return enc


def rows_to_pv(rows: list[str]) -> list[list[int]]:
    return [[LEGEND[c] for c in row] for row in rows]


def load_cat_frames() -> list[list[list[int]]]:
    d = json.loads(JSON_PATH.read_text())
    return [rows_to_pv(f) for f in d["frames"]]


def remap_accents_to_fill(frames: list[list[list[int]]]) -> list[list[list[int]]]:
    # pv=3 → pv=2 in body planes; the sparse overlay restores it at sample time.
    return [
        [[2 if px == 3 else px for px in row] for row in frame]
        for frame in frames
    ]


def compute_body_residues(
    frames: list[list[list[int]]],
) -> list[list[list[int]]]:
    return [
        [[frames[fi][y][x] for x in range(BODY_W)] for y in range(BODY_H)]
        for fi in range(FRAMES)
    ]


CUBES = []
for patt in product([-1, 0, 1], repeat=3):
    covered = []
    lits = sum(v != -1 for v in patt)
    for state in range(8):
        bits = ((state >> 2) & 1, (state >> 1) & 1, state & 1)
        if all(p == -1 or p == b for p, b in zip(patt, bits)):
            covered.append(state)
    CUBES.append((patt, tuple(covered), lits))


def minimize_frame_subset(active_frames: tuple[int, ...]) -> str:
    active = {FRAME_ENC[i] for i in active_frames}
    dontcare = set(range(8)) - FRAME_ENC_USED
    valid = [cube for cube in CUBES if set(cube[1]) <= (active | dontcare)]
    best = None
    for n_terms in range(1, 6):
        for combo in combinations(valid, n_terms):
            covered: set[int] = set()
            lits = 0
            for _, states, lit_count in combo:
                covered |= set(states) & FRAME_ENC_USED
                lits += lit_count
            if active <= covered:
                cost = (n_terms, lits)
                if best is None or cost < best[0]:
                    best = (cost, combo)
        if best:
            break
    if best is None:
        raise RuntimeError(f"Cannot minimize {sorted(active)}")
    names = ["frame[2]", "frame[1]", "frame[0]"]
    terms = []
    for patt, _, _ in best[1]:
        parts = []
        for name, val in zip(names, patt):
            if val == 1:
                parts.append(name)
            elif val == 0:
                parts.append("~" + name)
        if not parts:
            terms.append("1'b1")
        elif len(parts) == 1:
            terms.append(parts[0])
        else:
            terms.append("(" + " & ".join(parts) + ")")
    return terms[0] if len(terms) == 1 else "(" + " | ".join(terms) + ")"


def build_body_signatures(
    bodies: list[list[list[int]]],
) -> dict[int, dict[tuple[int, ...], list[int]]]:
    rowsig: dict[int, dict[tuple[int, ...], list[int]]] = {
        0: defaultdict(lambda: [0] * BODY_H),
        1: defaultdict(lambda: [0] * BODY_H),
    }
    for bit in (0, 1):
        for y in range(BODY_H):
            row_masks: dict[tuple[int, ...], int] = defaultdict(int)
            for x in range(BODY_W):
                sig = tuple((bodies[fi][y][x] >> bit) & 1 for fi in range(FRAMES))
                if any(sig):
                    row_masks[sig] |= 1 << x
            for sig, mask in row_masks.items():
                rowsig[bit][sig][y] = mask
    return rowsig


def build_accent_signatures(
    frames: list[list[list[int]]],
) -> dict[tuple[int, ...], list[int]]:
    rowsig: dict[tuple[int, ...], list[int]] = defaultdict(lambda: [0] * BODY_H)
    for y in range(BODY_H):
        row_masks: dict[tuple[int, ...], int] = defaultdict(int)
        for x in range(BODY_W):
            sig = tuple(1 if frames[fi][y][x] == 3 else 0 for fi in range(FRAMES))
            if any(sig):
                row_masks[sig] |= 1 << x
        for sig, mask in row_masks.items():
            rowsig[sig][y] = mask
    return rowsig


def verify_overlay(
    frames: list[list[list[int]]],
    bodies_for_rom: list[list[list[int]]],
) -> None:
    for fi in range(FRAMES):
        for y in range(BODY_H):
            for x in range(BODY_W):
                rom_v = bodies_for_rom[fi][y][x]
                lo = rom_v & 1
                hi = ((rom_v >> 1) & 1) & (0 if lo else 1)
                recon = 3 if frames[fi][y][x] == 3 else ((hi << 1) | lo)
                if recon != frames[fi][y][x]:
                    raise RuntimeError(
                        f"Mismatch frame={fi} y={y} x={x}: "
                        f"recon={recon} json={frames[fi][y][x]}"
                    )


def _build_body_block(
    rowsig: dict[int, dict[tuple[int, ...], list[int]]],
    ordered_sigs: dict[int, list[tuple[int, ...]]],
) -> str:
    L: list[str] = []
    L.append("    // ---- Body (per-frame residue, signature-mask delta) ----")
    for bit in (0, 1):
        bit_name = "lo" if bit == 0 else "hi"
        L.append(f"    // Signature predicates: body bitplane {bit_name}")
        for idx, sig in enumerate(ordered_sigs[bit]):
            active = tuple(i for i, bitv in enumerate(sig) if bitv)
            expr = minimize_frame_subset(active)
            L.append(f"    wire body_sig_{bit_name}_{idx} = {expr};  // frames {list(active)}")
        L.append("")

    for bit in (0, 1):
        bit_name = "lo" if bit == 0 else "hi"
        L.append(f"    logic [{BODY_W - 1}:0] body_{bit_name}_row;")
        L.append("    always_comb begin")
        L.append(f"        body_{bit_name}_row = {BODY_W}'d0;")
        L.append("        case (sy)")
        for y in range(BODY_H):
            terms = []
            for idx, sig in enumerate(ordered_sigs[bit]):
                mask = rowsig[bit][sig][y]
                if mask:
                    terms.append(
                        f"({{{BODY_W}{{body_sig_{bit_name}_{idx}}}}} & "
                        f"{BODY_W}'h{mask:07x})"
                    )
            if terms:
                L.append(f"            6'd{y}: body_{bit_name}_row = {' | '.join(terms)};")
        L.append("            default: begin end")
        L.append("        endcase")
        L.append("    end")
        if bit == 0:
            L.append("")
    return '\n'.join(L)


def _build_accent_block(
    accent_rowsig: dict[tuple[int, ...], list[int]],
    ordered_accent_sigs: list[tuple[int, ...]],
) -> str:
    L: list[str] = []
    L.append("    // ---- Accent overlay (pv=3 highlights/cheeks, sparse exact plane) ----")
    for idx, sig in enumerate(ordered_accent_sigs):
        active = tuple(i for i, bitv in enumerate(sig) if bitv)
        expr = minimize_frame_subset(active)
        L.append(f"    wire accent_sig_{idx} = {expr};  // frames {list(active)}")
    L.append("")
    L.append(f"    logic [{BODY_W - 1}:0] accent_row;")
    L.append("    always_comb begin")
    L.append(f"        accent_row = {BODY_W}'d0;")
    L.append("        case (sy)")
    for y in range(BODY_H):
        terms = []
        for idx, sig in enumerate(ordered_accent_sigs):
            mask = accent_rowsig[sig][y]
            if mask:
                terms.append(
                    f"({{{BODY_W}{{accent_sig_{idx}}}}} & "
                    f"{BODY_W}'h{mask:07x})"
                )
        if terms:
            L.append(f"            6'd{y}: accent_row = {' | '.join(terms)};")
    L.append("            default: begin end")
    L.append("        endcase")
    L.append("    end")
    L.append("")
    L.append("    wire accent_bit = accent_row[sx];")
    return '\n'.join(L)


def emit_sv(out_path: Path) -> None:
    frames = load_cat_frames()
    body_frames = remap_accents_to_fill(frames)
    bodies = compute_body_residues(body_frames)

    set_encoding(load_frame_enc())
    print(f"  cat_frame encoding: {FRAME_ENC}")

    # Encode pv=1 outline as internal pv=3 so the hi plane is one compact
    # silhouette; `hi & ~lo` recovers pv=1 / pv=2 at sample time.
    bodies_for_rom = [
        [[(3 if v == 1 else v) for v in row] for row in frame]
        for frame in bodies
    ]
    verify_overlay(frames, bodies_for_rom)

    rowsig = build_body_signatures(bodies_for_rom)
    ordered_sigs = {bit: list(rowsig[bit].keys()) for bit in (0, 1)}
    accent_rowsig = build_accent_signatures(frames)
    ordered_accent_sigs = list(accent_rowsig.keys())

    reset_code = FRAME_ENC[0]
    frame_lines = []
    for i in range(FRAMES):
        cur = FRAME_ENC[i]
        nxt = FRAME_ENC[(i + 1) % FRAMES]
        frame_lines.append(f"                    3'd{cur}:    cat_frame <= 3'd{nxt};")

    body_block = _build_body_block(rowsig, ordered_sigs)
    accent_block = _build_accent_block(accent_rowsig, ordered_accent_sigs)

    render_sv(
        'src/cat_sprite.sv.j2',
        out_path,
        reset_code=reset_code,
        frame_transitions='\n'.join(frame_lines),
        body_block=body_block,
        accent_block=accent_block,
    )
    print(f"Wrote {out_path}")
    print(f"  body signatures: lo={len(ordered_sigs[0])}, hi={len(ordered_sigs[1])}")
    print(f"  accent signatures: {len(ordered_accent_sigs)}")


def main() -> None:
    args = sys.argv[1:]
    out_path = Path(args[0]) if args else OUT_DEFAULT
    emit_sv(out_path)


if __name__ == "__main__":
    main()
