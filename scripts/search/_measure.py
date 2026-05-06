"""Shared measurement primitives for search scripts."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
STATS_PATH = Path("/tmp/journey_stats.txt")


def _parse_module_stat(text: str, module: str) -> tuple[int, int]:
    current = None
    wire_bits: int | None = None
    cells: int | None = None
    for line in text.splitlines():
        m = re.match(r"^===\s+([^= ]+)\s+===$", line)
        if m:
            current = m.group(1)
            continue
        if current != module:
            continue
        if wire_bits is None:
            m = re.match(r"\s*(\d+)\s+wire bits$", line)
            if m:
                wire_bits = int(m.group(1))
                continue
        if cells is None:
            m = re.match(r"\s*(\d+)\s+cells$", line)
            if m:
                cells = int(m.group(1))
        if wire_bits is not None and cells is not None:
            return wire_bits, cells
    raise RuntimeError(f"could not parse module {module!r} from stats")


def measure_cells(modules: list[str] | None = None) -> dict:
    """Run `make cells`. Returns {cells, wires, modules: {name: {wires, cells}}}.
    Pass `modules` to include per-module breakdown."""
    out = subprocess.run(
        ["make", "cells"], cwd=REPO, capture_output=True, text=True, timeout=90
    )
    if out.returncode != 0:
        raise RuntimeError(out.stdout + out.stderr)

    flat_cells: int | None = None
    flat_wires: int | None = None
    for line in out.stdout.splitlines():
        m = re.match(r"\s*(\d+)\s+TOTAL\s+\(flat\)", line)
        if m:
            flat_cells = int(m.group(1))
            continue
        m = re.match(r"\s*(\d+)\s+WIRES\s+\(flat\)", line)
        if m:
            flat_wires = int(m.group(1))
    if flat_cells is None or flat_wires is None:
        raise RuntimeError(f"could not parse flat stats:\n{out.stdout}\n{out.stderr}")

    result: dict = {"cells": flat_cells, "wires": flat_wires, "modules": {}}
    if modules:
        stats_text = STATS_PATH.read_text()
        for name in modules:
            wires, cells = _parse_module_stat(stats_text, name)
            result["modules"][name] = {"wires": wires, "cells": cells}
    return result


def measure_gpl_util() -> float:
    proc = subprocess.run(
        ["make", "sky-gpl"], cwd=REPO, capture_output=True, text=True, timeout=600
    )
    try:
        util = json.loads(proc.stdout).get("util")
    except json.JSONDecodeError:
        util = None
    if util is None:
        raise RuntimeError(f"gpl produced no util:\n{proc.stdout}\n{proc.stderr}")
    return float(util)
