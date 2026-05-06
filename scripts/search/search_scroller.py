#!/usr/bin/env python3
"""Search for char_idx permutations that minimize scroller ROM cells/wires.

Keeps idx 0 = space to preserve default-case collapse in the text ROM.
Metrics: cells (default), pins (rom wire bits), score (cells + W*wires), gpl_util.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))  # scripts/ for gen_scroller
from _measure import measure_cells, measure_gpl_util
from gen_scroller import DEFAULT_MSG, generate_sv, load_font_png

REPO = Path(__file__).resolve().parent.parent.parent
SV_PATH = REPO / "src" / "scroller_rom.sv"
FONT_PNG = REPO / "scripts" / "data" / "08X08-F5.png"
FONT = load_font_png(FONT_PNG)
TOPK_PATH = REPO / "scripts" / "search" / "scroller_topk.json"
BEST_PATH = REPO / "scripts" / "search" / "scroller_best.json"
TOPK = 10

_USE_COLOR = sys.stdout.isatty()
CYAN = "\033[36m" if _USE_COLOR else ""
GREEN = "\033[32m" if _USE_COLOR else ""
RESET = "\033[0m" if _USE_COLOR else ""


def write_best_json(order: list[str], stats: dict, metric: str) -> None:
    import datetime
    payload = {
        "char_order": "".join(order),
        "metric": metric,
        "value": stats.get("gpl_util") if metric == "gpl_util" else stats["cells"],
        "yosys_cells": stats["cells"],
        "flat_wires": stats.get("flat_wires"),
        "scroller_rom_wires": stats["rom_wires"],
        "updated": datetime.date.today().isoformat(),
        "note": "Read by gen_scroller.py; updated by search_scroller.py.",
    }
    BEST_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def padded_text() -> str:
    return ((" " * 20) + DEFAULT_MSG).ljust(128)


def parse_current_order() -> list[str]:
    text = SV_PATH.read_text()
    mapping: dict[int, int] = {}
    for addr, idx in re.findall(r"\s*7'd(\d+):\s*char_idx\s*=\s*5'd(\d+);", text):
        mapping[int(addr)] = int(idx)

    padded = padded_text()
    idx_to_char: dict[int, str] = {0: " "}
    for addr, idx in sorted(mapping.items()):
        if addr < len(padded):
            idx_to_char[idx] = padded[addr]

    # Fill slots for chars whose only appearances were collapsed into default.
    all_chars = list(dict.fromkeys(ch for ch, _ in Counter(padded).most_common()))
    for ch in all_chars:
        if ch in idx_to_char.values():
            continue
        for idx in range(32):
            if idx not in idx_to_char:
                idx_to_char[idx] = ch
                break

    return [idx_to_char[i] for i in range(max(idx_to_char) + 1)]


def run_make_stats(with_gpl: bool = False) -> dict[str, float]:
    cells = measure_cells(modules=["scroller_rom"])
    rom = cells["modules"]["scroller_rom"]
    stats: dict[str, float] = {
        "cells": cells["cells"],
        "flat_wires": cells["wires"],
        "rom_wires": rom["wires"],
        "rom_cells": rom["cells"],
    }
    if with_gpl:
        stats["gpl_util"] = measure_gpl_util()
    return stats


def load_topk() -> dict[str, Any]:
    if not TOPK_PATH.exists():
        raise SystemExit(f"{TOPK_PATH} not found; run `make scroller-search` first.")
    return json.loads(TOPK_PATH.read_text())


def fmt_entry(entry: dict[str, Any], baseline: dict[str, Any] | int) -> str:
    if isinstance(baseline, int):
        base_cells = baseline
        base_flat = entry.get("flat_wires", 0)
        base_rom = entry.get("rom_wires", 0)
        base_util = entry.get("gpl_util")
    else:
        base_cells = baseline["cells"]
        base_flat = baseline.get("flat_wires", entry.get("flat_wires", 0))
        base_rom = baseline.get("rom_wires", entry.get("rom_wires", 0))
        base_util = baseline.get("gpl_util")
    cells = entry["cells"]
    flat = entry.get("flat_wires", 0)
    rom = entry.get("rom_wires", 0)
    parts = [
        f"{cells:4d} yosys ({cells - base_cells:+d})",
        f"{flat:4d} flat ({flat - base_flat:+d})",
        f"{rom:4d} rom ({rom - base_rom:+d})",
    ]
    util = entry.get("gpl_util")
    if util is not None and base_util is not None:
        parts.insert(0, f"util {util:6.3f}% ({util - base_util:+.3f})")
    return ", ".join(parts)


def cmd_list() -> None:
    data = load_topk()
    baseline = data.get("baseline", 0)
    print(f"Metric: {data.get('metric', 'cells')}")
    if isinstance(baseline, dict):
        print(
            "Baseline: "
            f"{baseline['cells']} cells, {baseline.get('rom_wires', '?')} scroller wires"
        )
    else:
        print(f"Baseline: {baseline} cells")

    for key, title in (
        ("top", "Top metric candidates"),
        ("top_cells", "Top cells"),
        ("top_pins", "Top scroller wire bits"),
        ("pareto", "Pareto front"),
    ):
        rows = data.get(key, [])
        if not rows:
            continue
        print(f"\n{title}:")
        for i, entry in enumerate(rows, 1):
            print(f"  #{i:2d}  {fmt_entry(entry, baseline)}  {''.join(entry['order'])!r}")


def cmd_pick(n: int) -> None:
    data = load_topk()
    top = data.get("top", [])
    if n < 1 or n > len(top):
        raise SystemExit(f"--pick must be 1..{len(top)}, got {n}")
    entry = top[n - 1]
    generate_sv(DEFAULT_MSG, SV_PATH, font=FONT, char_order=entry["order"])
    print(f"Wrote candidate #{n}: {fmt_entry(entry, data.get('baseline', 0))}")
    print(f"Order: {''.join(entry['order'])!r}")
    print("If you keep it, update SCROLLER_CHAR_ORDER in Makefile.")


def parse_args(argv: list[str]) -> tuple[str, float, int, int]:
    metric = "cells"
    pin_weight = 0.25
    nums: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--metric":
            i += 1
            metric = argv[i]
        elif arg == "--pin-weight":
            i += 1
            pin_weight = float(argv[i])
        else:
            nums.append(arg)
        i += 1
    if metric not in ("cells", "pins", "score", "gpl_util"):
        raise SystemExit(f"--metric must be cells, pins, score, or gpl_util; got {metric!r}")
    n_random = int(nums[0]) if len(nums) > 0 else 100
    n_local = int(nums[1]) if len(nums) > 1 else 50
    return metric, pin_weight, n_random, n_local


def metric_key(entry: dict[str, Any], metric: str, pin_weight: float) -> tuple[float, ...]:
    # flat_wires tracks cells closely enough here that it is redundant for
    # ranking; rom_wires is the useful pin-density proxy.
    if metric == "pins":
        return (entry["rom_wires"], entry["cells"], entry["rom_cells"])
    if metric == "score":
        score = entry["cells"] + pin_weight * entry["rom_wires"]
        return (score, entry["cells"], entry["rom_wires"])
    if metric == "gpl_util":
        return (entry["gpl_util"], entry["cells"], entry["rom_wires"])
    return (entry["cells"], entry["rom_wires"], entry["rom_cells"])


def pareto_front(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    front = []
    for entry in sorted(entries, key=lambda e: (e["cells"], e["rom_wires"])):
        dominated = False
        for other in entries:
            if other is entry:
                continue
            if (
                other["cells"] <= entry["cells"]
                and other["rom_wires"] <= entry["rom_wires"]
                and (
                    other["cells"] < entry["cells"]
                    or other["rom_wires"] < entry["rom_wires"]
                )
            ):
                dominated = True
                break
        if not dominated:
            front.append(entry)
    return front[:TOPK]


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        cmd_list()
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--pick":
        cmd_pick(int(sys.argv[2]))
        return

    metric, pin_weight, n_random, n_local = parse_args(sys.argv[1:])
    seed = random.randrange(2**32)
    random.seed(seed)
    print(f"Random seed: {seed}")
    sys.stdout.reconfigure(line_buffering=True)
    t_start = time.time()
    def ts() -> str:
        s = int(time.time() - t_start)
        return f"[{s // 60:02d}:{s % 60:02d}]"

    current_order = parse_current_order()
    print(f"Current order: {current_order!r}")
    print(f"Metric: {metric}" + (f" (pin_weight={pin_weight})" if metric == "score" else ""))

    head = current_order[0]
    tail = current_order[1:]

    with_gpl = metric == "gpl_util"
    generate_sv(DEFAULT_MSG, SV_PATH, font=FONT, char_order=current_order)
    baseline = run_make_stats(with_gpl=with_gpl)
    base_lead = (
        f"util {CYAN}{baseline['gpl_util']:.3f}%{RESET}, "
        if with_gpl
        else ""
    )
    print(
        "baseline: "
        f"{base_lead}"
        f"{baseline['cells']} yosys cells (post-flatten synth), "
        f"{baseline['flat_wires']} flat wires, "
        f"{baseline['rom_wires']} scroller_rom wires, "
        f"{baseline['rom_cells']} scroller_rom cells\n"
    )

    # "yosys" = post-flatten synth count, distinct from SKY130 cells / GPL util.
    def fmt_trial(stats: dict[str, float]) -> str:
        if with_gpl:
            return (f"util {CYAN}{stats['gpl_util']:.3f}%{RESET}, "
                    f"{stats['cells']} yosys, {stats['rom_wires']} rom wires")
        return f"{stats['cells']} yosys, {stats['rom_wires']} rom wires"

    def fmt_best(entry: dict[str, Any]) -> str:
        if with_gpl:
            return f"best util {CYAN}{entry['gpl_util']:.3f}%{RESET} / {entry['cells']} yosys"
        return f"best {entry['cells']} yosys / {entry['rom_wires']} rom wires"

    results: list[dict[str, Any]] = []
    seen_orders: set[tuple[str, ...]] = set()
    best_entry: dict[str, Any] | None = None
    best_order = current_order[:]
    t0 = time.time()

    def consider(order: list[str], stats: dict[str, int]) -> dict[str, Any] | None:
        nonlocal best_entry, best_order
        key = tuple(order)
        if key in seen_orders:
            return None
        seen_orders.add(key)
        entry = {**stats, "order": order[:]}
        results.append(entry)
        if best_entry is None or metric_key(entry, metric, pin_weight) < metric_key(
            best_entry, metric, pin_weight
        ):
            best_entry = entry
            best_order = order[:]
        return entry

    consider(current_order, baseline)

    try:
        total = n_random + n_local
        print(f"=== Phase 1: {n_random} random permutations ===")
        for i in range(n_random):
            perm = tail[:]
            random.shuffle(perm)
            order = [head] + perm
            generate_sv(DEFAULT_MSG, SV_PATH, font=FONT, char_order=order)
            stats = run_make_stats(with_gpl=with_gpl)
            entry = consider(order, stats)
            if entry is None:
                continue
            marker = f"  {GREEN}* NEW BEST{RESET}" if entry is best_entry else ""
            dt = time.time() - t0
            eta = dt / max(1, len(results) - 1) * max(0, total - i - 1)
            print(
                f"{ts()} [R {i+1:3d}/{n_random}] "
                f"{fmt_trial(stats)} "
                f"({fmt_best(best_entry)}, ETA {eta:.0f}s)"
                f"{marker}"
            )

        print(f"\n=== Phase 2: {n_local} swap-2 neighbours of best ===")
        for j in range(n_local):
            perm = best_order[1:][:]
            a, b = random.sample(range(len(perm)), 2)
            perm[a], perm[b] = perm[b], perm[a]
            order = [head] + perm
            generate_sv(DEFAULT_MSG, SV_PATH, font=FONT, char_order=order)
            stats = run_make_stats(with_gpl=with_gpl)
            entry = consider(order, stats)
            if entry is None:
                continue
            marker = f"  {GREEN}* NEW BEST{RESET}" if entry is best_entry else ""
            print(
                f"{ts()} [S {j+1:3d}/{n_local}] swap({a},{b}) -> "
                f"{fmt_trial(stats)} "
                f"({fmt_best(best_entry)})"
                f"{marker}"
            )
    finally:
        assert best_entry is not None
        generate_sv(DEFAULT_MSG, SV_PATH, font=FONT, char_order=best_order)
        # Only lock in a new best if it strictly beats baseline on the active
        # metric — avoids regressing scroller_best.json on a fruitless run.
        base_key = metric_key(results[0], metric, pin_weight)
        new_key = metric_key(best_entry, metric, pin_weight)
        if new_key < base_key:
            write_best_json(best_order, best_entry, metric)
            print(f"\nBest candidate written to {SV_PATH}")
            print(f"Best order locked into {BEST_PATH.name} (used by `make gen`)")
        else:
            print(f"\nNo improvement over baseline; "
                  f"{BEST_PATH.name} unchanged, {SV_PATH.name} restored.")

        top = sorted(results, key=lambda e: metric_key(e, metric, pin_weight))[:TOPK]
        top_cells = sorted(results, key=lambda e: (e["cells"], e["rom_wires"]))[:TOPK]
        top_pins = sorted(results, key=lambda e: (e["rom_wires"], e["cells"]))[:TOPK]
        pareto = pareto_front(results)
        payload = {
            "metric": metric,
            "pin_weight": pin_weight,
            "baseline": baseline,
            "top": top,
            "top_cells": top_cells,
            "top_pins": top_pins,
            "pareto": pareto,
        }
        TOPK_PATH.write_text(json.dumps(payload, indent=2))
        print(f"Top candidates saved to {TOPK_PATH}")
        for i, entry in enumerate(top, 1):
            print(f"  #{i:2d}  {fmt_entry(entry, baseline)}  {''.join(entry['order'])!r}")

    print(
        "\nBaseline: "
        f"{baseline['cells']} cells, {baseline['rom_wires']} rom wires"
        + (f", util {baseline['gpl_util']:.3f}%" if with_gpl else "")
    )
    best_line = (
        f"{best_entry['cells']} cells ({best_entry['cells'] - baseline['cells']:+d}), "
        f"{best_entry['rom_wires']} rom ({best_entry['rom_wires'] - baseline['rom_wires']:+d})"
    )
    if with_gpl:
        d_util = best_entry["gpl_util"] - baseline["gpl_util"]
        best_line = f"util {best_entry['gpl_util']:.3f}% ({d_util:+.3f}), " + best_line
    print(f"Best:     {best_line}")


if __name__ == "__main__":
    main()
