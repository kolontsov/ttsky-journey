#!/usr/bin/env python3
"""Search for the best cat_frame encoding (logical 0..5 → 3-bit code).

Phase 1 (~seconds): score all 8P6=20160 injective encodings by SOP literal
cost (body+accent predicates + FSM next-state); bit-perm×xor-mask symmetry
folds to 420 orbits. Keep top-K.

Phase 2 (~17 s/candidate): for each top-K candidate, regenerate cat_sprite.sv
and run `make sky-gpl` for the full-design util — needed because cat-only
metrics don't predict how everything packs together.

Winner persists to cat_sprite_best.json + src/cat_sprite.sv; top-K rankings
to cat_sprite_topk.json (use --list / --pick N).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import itertools
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))  # scripts/ for gen_cat_sprite

import gen_cat_sprite as gen  # noqa: E402
from _measure import measure_gpl_util  # noqa: E402

SV_PATH = ROOT / "src" / "cat_sprite.sv"
BEST_PATH = ROOT / "scripts" / "search" / "cat_sprite_best.json"
TOPK_PATH = ROOT / "scripts" / "search" / "cat_sprite_topk.json"
DEFAULT_TOPK = 10


def _cube_set_for(active: set[int], dontcare: set[int]) -> list[tuple]:
    return [c for c in gen.CUBES if set(c[1]) <= (active | dontcare)]


def _sop_cost(active: set[int], used: set[int]) -> tuple[int, int] | None:
    # Min (terms, lits) SOP covering `active`, with codes outside `used` as DCs.
    if not active:
        return (0, 0)
    dontcare = set(range(8)) - used
    valid = _cube_set_for(active, dontcare)
    best: tuple[int, int] | None = None
    for n_terms in range(1, 6):
        for combo in itertools.combinations(valid, n_terms):
            covered: set[int] = set()
            lits = 0
            for _, states, lit_count in combo:
                covered |= set(states) & used
                lits += lit_count
            if active <= covered:
                cost = (n_terms, lits)
                if best is None or cost < best:
                    best = cost
        if best:
            break
    return best


def collect_subsets(bodies: list[list[list[int]]],
                    width: int,
                    height: int) -> list[tuple[int, ...]]:
    seen: set[tuple[int, ...]] = set()
    out: list[tuple[int, ...]] = []
    for bit in (0, 1):
        for y in range(height):
            for x in range(width):
                sig = tuple((bodies[fi][y][x] >> bit) & 1
                            for fi in range(gen.FRAMES))
                if any(sig):
                    active = tuple(i for i, v in enumerate(sig) if v)
                    if active not in seen:
                        seen.add(active)
                        out.append(active)
    return out


def collect_accent_subsets(frames: list[list[list[int]]],
                           width: int,
                           height: int) -> list[tuple[int, ...]]:
    seen: set[tuple[int, ...]] = set()
    out: list[tuple[int, ...]] = []
    for y in range(height):
        for x in range(width):
            sig = tuple(1 if frames[fi][y][x] == 3 else 0
                        for fi in range(gen.FRAMES))
            if any(sig):
                active = tuple(i for i, v in enumerate(sig) if v)
                if active not in seen:
                    seen.add(active)
                    out.append(active)
    return out


def fsm_cost(enc: tuple[int, ...], used: set[int]) -> tuple[int, int]:
    nxt = {enc[i]: enc[(i + 1) % gen.FRAMES] for i in range(gen.FRAMES)}
    total_terms = 0
    total_lits = 0
    for bit in range(3):
        active = {code for code in used if (nxt[code] >> bit) & 1}
        if not active or active == used:
            continue
        c = _sop_cost(active, used)
        if c:
            total_terms += c[0]
            total_lits += c[1]
    return total_terms, total_lits


def encoding_cost(enc: tuple[int, ...],
                  body_subsets: list[tuple[int, ...]],
                  accent_subsets: list[tuple[int, ...]]) -> tuple[int, int]:
    used = set(enc)
    terms = 0
    lits = 0
    for active in body_subsets:
        coded = {enc[i] for i in active}
        c = _sop_cost(coded, used)
        if c:
            terms += c[0]
            lits += c[1]
    for active in accent_subsets:
        coded = {enc[i] for i in active}
        c = _sop_cost(coded, used)
        if c:
            terms += c[0]
            lits += c[1]
    t_fsm, l_fsm = fsm_cost(enc, used)
    terms += t_fsm
    lits += l_fsm
    return (lits, terms)


def canonical_orbit(enc: tuple[int, ...]) -> tuple[int, ...]:
    # Lex-smallest under bit-perm × xor-mask. Same orbit ⇒ same SOP cost
    # and same post-flatten netlist.
    best = enc
    for perm in itertools.permutations(range(3)):
        for mask in range(8):
            transformed = tuple(
                ((((c >> perm[0]) & 1) << 0)
                 | (((c >> perm[1]) & 1) << 1)
                 | (((c >> perm[2]) & 1) << 2)) ^ mask
                for c in enc
            )
            if transformed < best:
                best = transformed
    return best


def enumerate_encodings(body_subsets: list[tuple[int, ...]],
                        accent_subsets: list[tuple[int, ...]]) -> list[dict]:
    by_orbit: dict[tuple[int, ...], dict] = {}
    for codes in itertools.permutations(range(8), gen.FRAMES):
        orbit = canonical_orbit(codes)
        if orbit in by_orbit:
            continue
        cost = encoding_cost(codes, body_subsets, accent_subsets)
        by_orbit[orbit] = {
            "enc": list(codes),
            "lits": cost[0],
            "terms": cost[1],
        }
    return sorted(by_orbit.values(), key=lambda r: (r["lits"], r["terms"]))


def write_best_json(enc: list[int], metric: str, value: float | None,
                    note: str = "") -> None:
    payload = {
        "frame_enc": {str(i): int(enc[i]) for i in range(gen.FRAMES)},
        "metric": metric,
        "value": value,
        "updated": datetime.date.today().isoformat(),
        "note": note or "Read by gen_cat_sprite.py; updated by search_cat_sprite.py.",
    }
    BEST_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def regen_cat_sprite() -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        gen.emit_sv(SV_PATH)


def measure_enc(enc: list[int]) -> float:
    write_best_json(enc, "search_in_progress", None,
                    note="Transient — search_cat_sprite.py mid-run.")
    regen_cat_sprite()
    return measure_gpl_util()


def load_topk() -> dict[str, Any]:
    if not TOPK_PATH.exists():
        raise SystemExit(f"{TOPK_PATH} not found; run `make cat-sprite-search` first.")
    return json.loads(TOPK_PATH.read_text())


def fmt_enc(enc: list[int]) -> str:
    return "{" + ", ".join(f"{i}:{enc[i]}" for i in range(gen.FRAMES)) + "}"


def cmd_list() -> None:
    data = load_topk()
    base = data.get("baseline", {})
    print(f"Baseline: util {base.get('util'):.3f}%  enc={fmt_enc(base['enc'])}")
    print()
    print("Top candidates (by full-design GPL util):")
    for i, e in enumerate(data["top"], 1):
        delta = e["util"] - base["util"]
        print(
            f"  #{i:2d}  util {e['util']:6.3f}% ({delta:+.3f})  "
            f"sop=({e['lits']} lits, {e['terms']} terms)  enc={fmt_enc(e['enc'])}"
        )


def cmd_pick(n: int) -> None:
    data = load_topk()
    top = data["top"]
    if n < 1 or n > len(top):
        raise SystemExit(f"--pick must be 1..{len(top)}, got {n}")
    e = top[n - 1]
    write_best_json(
        e["enc"], "manual_pick", e["util"],
        note=f"Manually picked candidate #{n} via cat-sprite-pick.",
    )
    regen_cat_sprite()
    print(f"Picked #{n}: util {e['util']:.3f}%  enc={fmt_enc(e['enc'])}")
    print(f"Wrote {BEST_PATH.name} and regenerated {SV_PATH.relative_to(ROOT)}.")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        cmd_list()
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--pick":
        cmd_pick(int(sys.argv[2]))
        return

    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=DEFAULT_TOPK,
                    help=f"how many top SOP-cost candidates to evaluate via "
                    f"`make sky-gpl` (default {DEFAULT_TOPK})")
    args = ap.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    t_start = time.time()

    def ts() -> str:
        s = int(time.time() - t_start)
        return f"[{s // 60:02d}:{s % 60:02d}]"

    # Stash baseline so we can restore on early exit.
    baseline_enc_dict = gen.load_frame_enc()
    baseline_enc = [baseline_enc_dict[i] for i in range(gen.FRAMES)]
    print(f"{ts()} baseline enc: {fmt_enc(baseline_enc)}")

    frames = gen.load_cat_frames()
    body_frames = gen.remap_accents_to_fill(frames)
    bodies = gen.compute_body_residues(body_frames)
    bodies_for_rom = [
        [[(3 if v == 1 else v) for v in row] for row in frame]
        for frame in bodies
    ]
    body_subsets = collect_subsets(bodies_for_rom, gen.BODY_W, gen.BODY_H)
    accent_subsets = collect_accent_subsets(frames, gen.BODY_W, gen.BODY_H)
    print(f"{ts()} subsets: {len(body_subsets)} body, {len(accent_subsets)} accent")

    print(f"{ts()} === Phase 1: scoring all 20160 encodings (SOP cost) ===")
    ranked = enumerate_encodings(body_subsets, accent_subsets)
    print(
        f"{ts()} {len(ranked)} orbit classes; "
        f"best SOP=({ranked[0]['lits']} lits, {ranked[0]['terms']} terms), "
        f"worst=({ranked[-1]['lits']}, {ranked[-1]['terms']})"
    )

    # Always include baseline as the reference, even if SOP-suboptimal.
    baseline_orbit = canonical_orbit(tuple(baseline_enc))
    candidates = list(ranked[: args.topk])
    if not any(canonical_orbit(tuple(c["enc"])) == baseline_orbit for c in candidates):
        for r in ranked:
            if canonical_orbit(tuple(r["enc"])) == baseline_orbit:
                candidates.append(r)
                break

    print(f"{ts()} top {len(candidates)} by SOP cost:")
    for i, c in enumerate(candidates, 1):
        tag = " (baseline)" if canonical_orbit(tuple(c["enc"])) == baseline_orbit else ""
        print(
            f"{ts()}   #{i:2d}  sop=({c['lits']:3d} lits, {c['terms']:2d} terms)  "
            f"enc={fmt_enc(c['enc'])}{tag}"
        )

    print(f"\n{ts()} === Phase 2: full-design `make sky-gpl` for {len(candidates)} candidates ===")

    util_base = measure_enc(baseline_enc)
    baseline_record = {"enc": baseline_enc, "util": util_base}
    print(f"{ts()} baseline util {util_base:.3f}%  enc={fmt_enc(baseline_enc)}")

    results: list[dict] = []
    best_util = util_base
    best_record: dict | None = None
    t_phase2 = time.time()

    try:
        for i, c in enumerate(candidates):
            enc = c["enc"]
            if canonical_orbit(tuple(enc)) == baseline_orbit:
                util = util_base
            else:
                util = measure_enc(enc)
            record = {
                "enc": enc,
                "util": util,
                "lits": c["lits"],
                "terms": c["terms"],
            }
            results.append(record)

            new_best = util < best_util
            if new_best:
                best_util = util
                best_record = record
            marker = "  * NEW BEST" if new_best else ""

            dt = time.time() - t_phase2
            done = i + 1
            eta = dt / max(1, done) * max(0, len(candidates) - done)
            print(
                f"{ts()} [G {done:2d}/{len(candidates)}] "
                f"util {util:6.3f}%  sop=({c['lits']:3d}, {c['terms']:2d})  "
                f"(best {best_util:.3f}%, ETA {eta:.0f}s){marker}"
            )
    finally:
        # On exit: install winner if any, else restore baseline (don't leave
        # the tree mid-search).
        if best_record is not None and best_record["util"] < util_base:
            write_best_json(
                best_record["enc"], "gpl_util", best_record["util"],
                note=f"search_cat_sprite.py winner ({len(candidates)} candidates evaluated).",
            )
            regen_cat_sprite()
            print(
                f"\n{ts()} Winner: util {best_record['util']:.3f}% "
                f"({best_record['util'] - util_base:+.3f})  enc={fmt_enc(best_record['enc'])}"
            )
            print(f"{ts()} Locked into {BEST_PATH.name} and {SV_PATH.relative_to(ROOT)}.")
        else:
            write_best_json(
                baseline_enc, "manual", None,
                note="Restored baseline — no improvement found.",
            )
            regen_cat_sprite()
            print(f"\n{ts()} No improvement over baseline ({util_base:.3f}%); "
                  f"{BEST_PATH.name} restored.")

        ranked_results = sorted(results,
                                key=lambda r: (r["util"], r["lits"], r["terms"]))
        TOPK_PATH.write_text(json.dumps({
            "baseline": baseline_record,
            "top": ranked_results,
            "updated": datetime.date.today().isoformat(),
        }, indent=2) + "\n")
        print(f"{ts()} Top candidates saved to {TOPK_PATH.name}")


if __name__ == "__main__":
    main()
