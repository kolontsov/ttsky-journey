#!/usr/bin/env python3
"""Summarize the last `make harden` run from runs/wokwi/final/metrics.json + GPL log.

Pure read — does not re-synthesize. Run after `make harden`.
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
METRICS = REPO / "runs/wokwi/final/metrics.json"
GPL_LOGS = "runs/wokwi/*-openroad-globalplacement/openroad-globalplacement.log"


def fmt(x: float | None) -> str:
    return f"{x:+6.2f} ns" if x is not None else "      n/a"


def fail(*xs: float | None) -> str:
    return "  FAIL" if any(x is not None and x < 0 for x in xs) else ""


def ss_note(x: float | None) -> str:
    return f", SS visibility {fmt(x).strip()}" if x is not None else ", SS visibility n/a"


def read_gpl_util() -> float | None:
    util = None
    for path in sorted(glob.glob(str(REPO / GPL_LOGS))):
        match = re.search(r"GPL-0019.*?(\d+\.\d+)", Path(path).read_text())
        if match:
            util = float(match.group(1))
    return util


def main() -> int:
    if not METRICS.exists():
        print(f"no metrics at {METRICS} — run 'make harden' first", file=sys.stderr)
        return 1
    m = json.loads(METRICS.read_text())

    comb = m.get("design__instance__count__class:multi_input_combinational_cell", 0)
    seq = m.get("design__instance__count__class:sequential_cell", 0)
    logic = comb + seq

    hold_b = m.get("design__instance__count__hold_buffer", 0)
    setup_b = m.get("design__instance__count__setup_buffer", 0)
    clk_b = m.get("design__instance__count__class:clock_buffer", 0)
    buf = hold_b + setup_b + clk_b

    post_util = m.get("design__instance__utilization__stdcell", 0) * 100
    gpl_util = read_gpl_util()

    s_tt = m.get("timing__setup__ws__corner:nom_tt_025C_1v80")
    s_ff = m.get("timing__setup__ws__corner:nom_ff_n40C_1v95")
    s_ss = m.get("timing__setup__ws__corner:nom_ss_100C_1v60")
    h_tt = m.get("timing__hold__ws__corner:nom_tt_025C_1v80")
    h_ff = m.get("timing__hold__ws__corner:nom_ff_n40C_1v95")
    h_ss = m.get("timing__hold__ws__corner:nom_ss_100C_1v60")

    drc = sorted(
        (int(k.split(":")[1]), v) for k, v in m.items() if k.startswith("route__drc_errors__iter:")
    )
    iters = len(drc)
    trail = ",".join(str(v) for _, v in drc)

    gpl_val = f"{gpl_util:>5.1f}%" if gpl_util else "     ?"
    gpl_info = "pin-padded, true ceiling ~100%" if gpl_util else "log not found"

    print(f"  logic     {logic:>6d}  (comb {comb} + seq {seq})")
    print(f"  buffers   {buf:>6d}  (hold {hold_b} + setup {setup_b} + clk {clk_b})")
    print(f"  util      {post_util:>5.1f}%  (post-place stdcell / core)")
    print(f"  GPL       {gpl_val}  ({gpl_info})")
    print(f"  setup  {fmt(s_tt)}  (FF {fmt(s_ff)}{ss_note(s_ss)}){fail(s_tt, s_ff)}")
    print(f"  hold   {fmt(h_tt)}  (FF {fmt(h_ff)}{ss_note(h_ss)}){fail(h_tt, h_ff)}")
    print(f"  routing   {iters:>6d}  (iterations, DRC {trail})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
