#!/usr/bin/env python3
"""Per-module pin attribution from the pre-ABC flat netlist.

Yosys flattens before ABC, so post-place cells are anonymous `_NNNN_` —
but ~230 hierarchical wire names survive (flop outputs + module ports).
We attribute each cell via the hierarchical prefix of wires it touches,
then BFS-propagate labels to neighbours sharing a net to cover deep
combinational cones. Reports per-module pin density and top pin-heavy
cells — answers "which cells are the pin-surge culprits in <module>?"
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path


DEFAULT_NL = "runs/wokwi/06-yosys-synthesis/tt_um_kolontsov_journey.nl.v"


def parse_netlist(path: Path):
    text = path.read_text()

    # Cell: <type>  <name> (\n  .pin(net),\n  ... );
    cell_re = re.compile(
        r"^\s*(sky130_fd_sc_hd__\S+)\s+(\S+)\s*\(\s*\n"
        r"((?:\s*\.\S+\([^)]*\),?\s*\n)+)"
        r"\s*\);",
        re.MULTILINE,
    )
    pin_re = re.compile(r"\.(\S+)\(\s*([^)]*?)\s*\)")

    cells = []
    for m in cell_re.finditer(text):
        ctype, cname, body = m.group(1), m.group(2), m.group(3)
        pins = []
        for pm in pin_re.finditer(body):
            pin, net = pm.group(1), pm.group(2)
            net = net.strip()
            # Strip Verilog escaped-id backslash + trailing space.
            if net.startswith("\\"):
                net = net[1:].rstrip()
            pins.append((pin, net))
        cells.append((cname, ctype, pins))
    return cells


# Nets that connect to most flops in the design — too broad to attribute.
LOW_INFO_NETS = {"clk", "clk_pix", "clk_sample", "rst_n", "rst_n_sync",
                 "ena", "_0_", "_1_"}


def net_module(net: str) -> str | None:
    # 'synth.u_kick.kick_inc[0]' → 'synth.u_kick';  'pixel_x' → '(top)';
    # '_1234_' / 'clk' / 'rst_n_sync' → None.
    if not net or net.startswith("_") and net.endswith("_") and net[1:-1].isdigit():
        return None
    base = net.split("[", 1)[0]
    if base in LOW_INFO_NETS:
        return None
    if "." in base:
        parts = base.split(".")
        return ".".join(parts[:-1])
    return "(top)"


def attribute(cells):
    attrib = {}
    for cname, _ctype, pins in cells:
        votes = Counter()
        for _pin, net in pins:
            m = net_module(net)
            if m is None:
                continue
            # Dotted wires (specific submodule internals) outweigh flat ones
            # like pixel_x that may have been pulled up across boundaries.
            weight = 10 if m != "(top)" else 1
            votes[m] += weight
        if votes:
            # Most votes wins; deeper path tiebreaks.
            best = max(votes.items(),
                       key=lambda kv: (kv[1], kv[0].count(".")))[0]
            attrib[cname] = best
        else:
            attrib[cname] = None
    return attrib


def propagate(cells, attrib, max_hops=4):
    # BFS-propagate hierarchical labels along anonymous nets, bounded by
    # max_hops so a deep CORDIC cone doesn't leak labels across the design.
    # (top) seeds don't propagate — only dotted labels spread.
    net_cells = defaultdict(list)
    for cname, _ctype, pins in cells:
        for _pin, net in pins:
            if net and not (net.startswith("_") and net.endswith("_")
                            and net[1:-1].isdigit()):
                continue
            net_cells[net].append(cname)

    neighbours = defaultdict(set)
    for _net, clist in net_cells.items():
        for i, a in enumerate(clist):
            for b in clist[i+1:]:
                neighbours[a].add(b)
                neighbours[b].add(a)

    incoming = defaultdict(Counter)
    frontier = deque()
    for cname, mod in attrib.items():
        if mod is not None:
            incoming[cname][mod] += 10
            if mod != "(top)":
                frontier.append((cname, mod, 0))

    visited_from = defaultdict(set)  # cell → set of (mod, hop)
    while frontier:
        cur, mod, hop = frontier.popleft()
        if hop >= max_hops:
            continue
        for nb in neighbours.get(cur, ()):
            key = (mod, hop + 1)
            if key in visited_from[nb]:
                continue
            visited_from[nb].add(key)
            incoming[nb][mod] += max(1, max_hops - hop)
            if attrib.get(nb) is None:
                frontier.append((nb, mod, hop + 1))

    for cname, mod in list(attrib.items()):
        if mod is None and cname in incoming and incoming[cname]:
            attrib[cname] = incoming[cname].most_common(1)[0][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("netlist", nargs="?", default=DEFAULT_NL)
    ap.add_argument("--top", type=int, default=5,
                    help="top-N pin-heavy cells per module (default 5)")
    ap.add_argument("--module", help="drill into a single module only")
    ap.add_argument("--no-propagate", action="store_true",
                    help="skip BFS pass (show direct-pass coverage only)")
    args = ap.parse_args()

    path = Path(args.netlist)
    if not path.exists():
        sys.exit(f"netlist not found: {path}\n"
                 f"Run 'make harden' first.")

    cells = parse_netlist(path)
    attrib = attribute(cells)

    direct_n = sum(1 for v in attrib.values() if v is not None)
    print(f"Netlist: {path}")
    print(f"Cells: {len(cells)}   Direct attribution: {direct_n} "
          f"({100*direct_n/len(cells):.1f}%)")

    if not args.no_propagate:
        propagate(cells, attrib, max_hops=4)
        final_n = sum(1 for v in attrib.values() if v is not None)
        print(f"After BFS propagation: {final_n} "
              f"({100*final_n/len(cells):.1f}%)")
    print()

    mod_cells = defaultdict(list)  # mod → [(pins, cname, ctype)]
    for cname, ctype, pins in cells:
        mod = attrib.get(cname) or "?"
        mod_cells[mod].append((len(pins), cname, ctype))

    rows = []
    for mod, clist in mod_cells.items():
        n = len(clist)
        total_p = sum(p for p, _, _ in clist)
        rows.append((total_p, n, total_p / n, mod, clist))
    rows.sort(reverse=True)

    if args.module:
        rows = [r for r in rows if args.module in r[3]]
        if not rows:
            sys.exit(f"module not found: {args.module}\n"
                     f"Available: {sorted(mod_cells)}")

    print(f"{'cells':>5} {'pins':>5} {'p/c':>5}  module")
    for total_p, n, pc, mod, _clist in rows:
        print(f"{n:>5} {total_p:>5} {pc:>5.2f}  {mod}")
    print()

    for _total_p, _n, _pc, mod, clist in rows:
        clist.sort(reverse=True)
        if clist[0][0] < 4:
            continue
        print(f"── {mod} — top {args.top} pin-heavy cells:")
        for pins, cname, ctype in clist[:args.top]:
            short = ctype.replace("sky130_fd_sc_hd__", "")
            print(f"    {pins:>2} pins  {cname:<8}  {short}")


if __name__ == "__main__":
    main()
