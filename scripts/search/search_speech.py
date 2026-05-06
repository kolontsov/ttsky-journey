#!/usr/bin/env python3
"""Search for a glyph_idx assignment that minimizes cat_speech.

9 glyphs spread across idx 1..9 (idx 0 pinned to blank/default). Three stages:
  A. Prefix-cost rank over all 9!=362,880 perms (free, weak proxy at high GPL).
  B. cells+wires on top prescreen-n; rank by (wires, cells) — wire bits is the
     GPL pin-density proxy that matters at ≥99% util.
  C. gpl_util on top-n by wires, early-out on streak of worse-than-baseline.

Leaves src/cat_speech.sv restored to baseline at the end.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "search"))  # _measure (sibling)
sys.path.insert(0, str(ROOT / "scripts"))  # gen_speech

import gen_speech  # noqa: E402
from _measure import measure_cells, measure_gpl_util  # noqa: E402

CHAR_BITS = 4  # glyph_idx width
BEST_PATH = ROOT / "scripts" / "search" / "speech_best.json"


def write_best_json(order: list[str], stats: dict, metric: str) -> None:
    import datetime
    import json
    payload = {
        "glyph_chars": list(order),
        "metric": metric,
        "value": stats.get("gpl_util") if metric == "gpl_util" else stats["cells"],
        "yosys_cells": stats["cells"],
        "updated": datetime.date.today().isoformat(),
        "note": "Read by gen_speech.py; updated by search_speech.py.",
    }
    BEST_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def glyph_rows_42(ch: str, font: dict) -> int:
    # Pack 7 rows of 6-bit glyph into a 42-bit word.
    rows = font.get(ch, [0] * gen_speech.CHAR_H)
    w = 0
    for gy in range(7):
        r = rows[gy] & ((1 << gen_speech.CHAR_W) - 1)
        w |= r << (gy * 6)
    return w


def prefix_cost(assignment: dict[str, int], glyph_words: dict[str, int]) -> int:
    # Pair cost: hamming(glyphs) * 2^shared_idx_prefix.
    items = list(assignment.items())
    total = 0
    for a in range(len(items)):
        ca, ia = items[a]
        wa = glyph_words[ca]
        for b in range(a + 1, len(items)):
            cb, ib = items[b]
            x = ia ^ ib
            shared = CHAR_BITS - x.bit_length()
            diff = bin(wa ^ glyph_words[cb]).count("1")
            total += diff * (1 << shared)
    return total


def regenerate(order: list[str]) -> None:
    gen_speech.GLYPH_CHARS = list(order)
    gen_speech.GLYPH_IDX = {ch: i + 1 for i, ch in enumerate(order)}
    gen_speech.GLYPH_IDX[' '] = 0
    font = gen_speech.load_bitmap_font(
        gen_speech.FONT_OTB, gen_speech.CHAR_W, gen_speech.CHAR_H
    )
    gen_speech.build_frame()  # sanity
    with contextlib.redirect_stdout(io.StringIO()):
        gen_speech.write_sv(font)


def measure(order: list[str], with_wires: bool = False, with_gpl: bool = False) -> dict:
    regenerate(order)
    modules = ["cat_speech"] if with_wires else None
    cells = measure_cells(modules=modules)
    result: dict = {"cells": cells["cells"], "wires": None, "gpl_util": None}
    if with_wires:
        result["wires"] = cells["modules"]["cat_speech"]["wires"]
    if with_gpl:
        result["gpl_util"] = measure_gpl_util()
    return result


def fmt_metric(stats: dict) -> str:
    # "yosys" = post-flatten synth count, distinct from SKY130 cells / GPL util.
    parts = [f"{stats['cells']} yosys"]
    if stats.get("wires") is not None:
        parts.append(f"{stats['wires']} wires")
    if stats.get("gpl_util") is not None:
        parts.append(f"util {stats['gpl_util']:.3f}%")
    return ", ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metric", choices=("cells", "gpl_util"), default="cells")
    ap.add_argument("--prescreen-n", type=int, default=100,
                    help="how many top prefix-cost candidates to measure "
                    "cells+wires for (Stage B; default 100, ~5 s each)")
    ap.add_argument("--top-n", type=int, default=None,
                    help="how many wire-bits-ranked candidates to send to "
                    "Stage C (default: 30 for cells, 10 for gpl_util)")
    ap.add_argument("--early-out-k", type=int, default=5,
                    help="abort gpl_util stage after K consecutive "
                    "worse-than-baseline measurements (default 5)")
    args = ap.parse_args()
    with_gpl = args.metric == "gpl_util"
    top_n = args.top_n if args.top_n is not None else (10 if with_gpl else 30)
    prescreen_n = max(args.prescreen_n, top_n)

    sys.stdout.reconfigure(line_buffering=True)
    t_start = time.time()

    def ts() -> str:
        s = int(time.time() - t_start)
        return f"[{s // 60:02d}:{s % 60:02d}]"

    chars = list(gen_speech.GLYPH_CHARS)  # baseline order
    print(f"Baseline GLYPH_CHARS: {chars}")
    print(f"Metric: {args.metric}, prescreen-N: {prescreen_n}, top-N: {top_n}, "
          f"early-out-K: {args.early_out_k}")

    font = gen_speech.load_bitmap_font(
        gen_speech.FONT_OTB, gen_speech.CHAR_W, gen_speech.CHAR_H
    )
    glyph_words = {c: glyph_rows_42(c, font) for c in chars}

    base = measure(chars, with_wires=True, with_gpl=with_gpl)
    print(f"baseline: {fmt_metric(base)}\n")

    # ── Stage A: algorithmic prefix-cost rank ─────────────────────────────
    print(f"=== Stage A: enumerate {len(chars)}! = 362,880 perms by prefix cost ===")
    scored = []
    for perm in itertools.permutations(chars):
        assignment = {ch: i + 1 for i, ch in enumerate(perm)}
        cost = prefix_cost(assignment, glyph_words)
        scored.append((cost, perm))
    scored.sort(key=lambda t: t[0])

    base_cost = prefix_cost(
        {c: i + 1 for i, c in enumerate(chars)}, glyph_words,
    )
    print(f"baseline prefix cost: {base_cost}")
    print(f"best prefix cost:     {scored[0][0]}\n")

    # ── Stage B: cells+wires on top prescreen_n distinct-cost perms ───────
    print(f"=== Stage B: cells+wires for top {prescreen_n} perms (~5 s each) ===")
    stage_b: list[tuple[dict, list[str], int]] = []
    seen_costs: set[int] = set()
    for cost, perm in scored:
        if cost in seen_costs:
            continue
        seen_costs.add(cost)
        stats = measure(list(perm), with_wires=True, with_gpl=False)
        d_cells = stats["cells"] - base["cells"]
        d_wires = stats["wires"] - base["wires"]
        marker = ""
        if stats["wires"] < base["wires"] or (
            stats["wires"] == base["wires"] and stats["cells"] < base["cells"]
        ):
            marker = "  *"
        print(f"{ts()} [B {len(stage_b)+1:3d}/{prescreen_n}] cost={cost} "
              f"{stats['wires']} wires ({d_wires:+d}), "
              f"{stats['cells']} yosys ({d_cells:+d}){marker}")
        stage_b.append((stats, list(perm), cost))
        if len(stage_b) >= prescreen_n:
            break

    # Rank by (wires, cells). Wire bits is the GPL pin-density proxy; cells tiebreak.
    stage_b.sort(key=lambda r: (r[0]["wires"], r[0]["cells"]))
    print(f"\nStage B top {min(top_n, 5)} by (wires, cells):")
    for stats, perm, cost in stage_b[:min(top_n, 5)]:
        d_w = stats["wires"] - base["wires"]
        d_c = stats["cells"] - base["cells"]
        print(f"  {stats['wires']} wires ({d_w:+d}), "
              f"{stats['cells']} yosys ({d_c:+d})  cost={cost}  {perm}")
    print()

    # ── Stage C: gpl_util on top_n by wires (only when --metric gpl_util) ─
    if with_gpl:
        print(f"=== Stage C: gpl_util for top {top_n} by wires "
              f"(early-out after {args.early_out_k} worse-than-baseline) ===")
        results: list[tuple[dict, list[str], int]] = []
        worse_streak = 0
        for stats, perm, cost in stage_b[:top_n]:
            full = measure(perm, with_wires=True, with_gpl=True)
            d_util = full["gpl_util"] - base["gpl_util"]
            d_cells = full["cells"] - base["cells"]
            mark = " *" if full["gpl_util"] < base["gpl_util"] else ""
            print(f"{ts()} [C {len(results)+1:2d}/{top_n}] cost={cost} {perm}: "
                  f"util {full['gpl_util']:6.3f}% ({d_util:+.3f}), "
                  f"{full['wires']} wires, {full['cells']} yosys ({d_cells:+d}){mark}")
            results.append((full, list(perm), cost))
            if full["gpl_util"] >= base["gpl_util"]:
                worse_streak += 1
                if worse_streak >= args.early_out_k:
                    print(f"\n{ts()} early-out: {worse_streak} consecutive "
                          f"worse-than-baseline measurements; baseline is best here.")
                    break
            else:
                worse_streak = 0
        results.sort(key=lambda r: (r[0]["gpl_util"], r[0]["cells"]))
        title = "best by GPL util"
    else:
        results = [(s, p, c) for s, p, c in stage_b[:top_n]]
        results.sort(key=lambda r: (r[0]["cells"], r[0]["wires"]))
        title = "best by yosys-flat cells"

    print(f"\n=== {title} ===")
    for stats, perm, cost in results[:5]:
        d_cells = stats["cells"] - base["cells"]
        if with_gpl and stats.get("gpl_util") is not None:
            d_util = stats["gpl_util"] - base["gpl_util"]
            print(
                f"  util {stats['gpl_util']:6.3f}% ({d_util:+.3f}), "
                f"{stats['cells']} yosys ({d_cells:+d})  cost={cost}  {perm}"
            )
        else:
            print(f"  {stats['cells']} yosys ({d_cells:+d})  cost={cost}  {perm}")

    # Persist the winner so `make gen` reproduces it. Only update if strictly
    # better than the existing baseline on the active metric — never regress.
    best_stats, best_order, _ = results[0]
    base_metric = base["gpl_util"] if with_gpl else base["cells"]
    new_metric = best_stats["gpl_util"] if with_gpl else best_stats["cells"]
    if new_metric is not None and new_metric < base_metric:
        write_best_json(best_order, best_stats, args.metric)
        regenerate(best_order)
        print(f"\nWinner locked into {BEST_PATH.name}: {best_order}")
        print(f"src/cat_speech.sv regenerated with the winning order.")
    else:
        regenerate(chars)
        print(f"\nNo improvement over baseline; "
              f"{BEST_PATH.name} unchanged, src/cat_speech.sv restored.")


if __name__ == "__main__":
    main()
