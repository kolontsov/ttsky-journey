#!/usr/bin/env python3
"""Spatial pin-density heatmap from the post-place OpenROAD DEF.

Bins cells into an NxM grid; reports pin/cell counts per bin to expose
hotspots that the core-wide average hides.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_DEF = "runs/wokwi/final/def/tt_um_kolontsov_journey.def"

# Filler/tap/decap cells: no signal pins, skip.
SKIP_PREFIXES = ("FILLER_", "PHY_EDGE_", "TAP_", "sky130_fd_sc_hd__tap",
                 "sky130_fd_sc_hd__decap", "sky130_fd_sc_hd__fill")


def parse_def(path: Path):
    text = path.read_text()

    m = re.search(r"DIEAREA\s*\(\s*(\d+)\s+(\d+)\s*\)\s*\(\s*(\d+)\s+(\d+)\s*\)",
                  text)
    die = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))

    comp_block = re.search(
        r"^COMPONENTS\s+\d+\s*;\s*\n(.*?)^END COMPONENTS",
        text, re.DOTALL | re.MULTILINE).group(1)

    comp_re = re.compile(
        r"^\s*-\s+(\S+)\s+(\S+).*?PLACED\s*\(\s*(\d+)\s+(\d+)\s*\)",
        re.MULTILINE | re.DOTALL)

    components = {}
    for m in comp_re.finditer(comp_block):
        name, cell_type, x, y = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        components[name] = (cell_type, x, y)

    nets_block = re.search(
        r"^NETS\s+\d+\s*;\s*\n(.*?)^END NETS",
        text, re.DOTALL | re.MULTILINE).group(1)

    # Per net: "    - <name>" then "( inst pin )"... up to ';'.
    pin_count = Counter()
    for chunk in re.split(r"^\s*-\s+\S+", nets_block, flags=re.MULTILINE)[1:]:
        chunk = chunk.split(";", 1)[0]
        for m in re.finditer(r"\(\s*(\S+)\s+\S+\s*\)", chunk):
            inst = m.group(1)
            if inst == "PIN":
                continue
            pin_count[inst] += 1

    return die, components, pin_count


def is_real(name: str, cell_type: str) -> bool:
    if name.startswith(SKIP_PREFIXES):
        return False
    if cell_type.startswith(SKIP_PREFIXES):
        return False
    return True


def render_heatmap(grid, nbx, nby, vmax):
    # Y flipped so (0,0) is bottom-left.
    ramp = " .:-=+*#%@"
    for by in range(nby - 1, -1, -1):
        row = []
        for bx in range(nbx):
            v = grid[by][bx]
            if vmax == 0:
                row.append(" ")
            else:
                idx = min(len(ramp) - 1, int(v / vmax * (len(ramp) - 1)))
                row.append(ramp[idx])
        print("  " + "".join(row))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("def_path", nargs="?", default=DEFAULT_DEF)
    ap.add_argument("--bins", default="20x14",
                    help="grid NxM (default 20x14 ≈ 16.5×15.7 µm on 2x2)")
    ap.add_argument("--top", type=int, default=10, help="top-N hot bins to list")
    args = ap.parse_args()

    path = Path(args.def_path)
    if not path.exists():
        sys.exit(f"DEF not found: {path}")

    die, components, pin_count = parse_def(path)
    x0, y0, x1, y1 = die
    die_w_um = (x1 - x0) / 1000.0
    die_h_um = (y1 - y0) / 1000.0

    nbx, nby = [int(x) for x in args.bins.split("x")]
    bin_w = (x1 - x0) / nbx
    bin_h = (y1 - y0) / nby

    bin_pins = [[0] * nbx for _ in range(nby)]
    bin_cells = [[0] * nbx for _ in range(nby)]
    bin_types = defaultdict(Counter)
    bin_insts = defaultdict(list)

    total_real = 0
    total_pins = 0
    for name, (ctype, x, y) in components.items():
        if not is_real(name, ctype):
            continue
        total_real += 1
        bx = min(nbx - 1, int((x - x0) / bin_w))
        by = min(nby - 1, int((y - y0) / bin_h))
        p = pin_count.get(name, 0)
        bin_pins[by][bx] += p
        bin_cells[by][bx] += 1
        bin_types[(by, bx)][ctype] += 1
        bin_insts[(by, bx)].append((p, name, ctype))
        total_pins += p

    bin_area_um2 = (bin_w * bin_h) / 1e6
    pins_per_um2 = [[bin_pins[y][x] / bin_area_um2 for x in range(nbx)]
                    for y in range(nby)]
    pcmax = max(max(r) for r in pins_per_um2)
    cmax = max(max(r) for r in bin_cells)

    print(f"DEF: {path}")
    print(f"Die: {die_w_um:.1f} × {die_h_um:.1f} µm ({die_w_um*die_h_um:.0f} µm²)")
    print(f"Real cells: {total_real}   Total signal pins: {total_pins}")
    print(f"Mean pins/cell: {total_pins/total_real:.2f}")
    print(f"Mean pins/µm²: {total_pins/(die_w_um*die_h_um):.3f}")
    print()
    print(f"Grid: {nbx} × {nby}  (bin = {bin_w/1000:.1f} × {bin_h/1000:.1f} µm "
          f"= {bin_area_um2:.1f} µm²)")
    print()

    print("Pin density heatmap (pins/µm², lighter=sparser, darker=denser):")
    render_heatmap(pins_per_um2, nbx, nby, pcmax)
    print(f"  scale: 0 → {pcmax:.3f} pins/µm²")
    print()

    print("Cell density heatmap (cells per bin):")
    render_heatmap(bin_cells, nbx, nby, cmax)
    print(f"  scale: 0 → {cmax} cells/bin")
    print()

    flat = [(pins_per_um2[y][x], bin_pins[y][x], bin_cells[y][x], x, y)
            for y in range(nby) for x in range(nbx)]
    flat.sort(reverse=True)

    print(f"Top {args.top} bins by pins/µm²:")
    print(f"  {'rank':>4} {'x_um':>7} {'y_um':>7} {'pins':>5} {'cells':>5} "
          f"{'p/c':>5} {'p/µm²':>7}  top cell types")
    for i, (dens, pins, cells, bx, by) in enumerate(flat[:args.top]):
        cx = (x0 + (bx + 0.5) * bin_w) / 1000.0
        cy = (y0 + (by + 0.5) * bin_h) / 1000.0
        pc = pins / cells if cells else 0
        top3 = bin_types[(by, bx)].most_common(3)
        types_s = "  ".join(f"{t.replace('sky130_fd_sc_hd__', '')}×{n}"
                            for t, n in top3)
        print(f"  {i+1:>4} {cx:>7.1f} {cy:>7.1f} {pins:>5} {cells:>5} "
              f"{pc:>5.2f} {dens:>7.3f}  {types_s}")

    # Mean pins/cell finds bins dominated by inherently pin-heavy types
    # (muxes/AOIs/FFs) — the real problem, distinct from raw cell density.
    print()
    print(f"Top {args.top} bins by mean pins/cell (≥20 cells):")
    heavy = [(bin_pins[y][x] / bin_cells[y][x] if bin_cells[y][x] else 0,
              bin_cells[y][x], bin_pins[y][x], x, y)
             for y in range(nby) for x in range(nbx) if bin_cells[y][x] >= 20]
    heavy.sort(reverse=True)
    print(f"  {'rank':>4} {'x_um':>7} {'y_um':>7} {'p/c':>5} {'cells':>5} "
          f"{'pins':>5}  top cell types")
    for i, (pc, cells, pins, bx, by) in enumerate(heavy[:args.top]):
        cx = (x0 + (bx + 0.5) * bin_w) / 1000.0
        cy = (y0 + (by + 0.5) * bin_h) / 1000.0
        top3 = bin_types[(by, bx)].most_common(3)
        types_s = "  ".join(f"{t.replace('sky130_fd_sc_hd__', '')}×{n}"
                            for t, n in top3)
        print(f"  {i+1:>4} {cx:>7.1f} {cy:>7.1f} {pc:>5.2f} {cells:>5} "
              f"{pins:>5}  {types_s}")


if __name__ == "__main__":
    main()
