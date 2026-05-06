#!/usr/bin/env python3
# Emit 256-entry palette case data for src/palette.sv.
# Word layout: [7:6]=gray, [5:4]=R, [3:2]=G, [1:0]=B.
# Gray uses 3 sine cycles (not 4) to avoid resonance with the tunnel's
# 4-fold angular symmetry — 4 cycles puts gray peaks on cardinals.

import argparse
import math
import sys
from typing import TextIO


def palette_rgb222(i: int) -> tuple[int, int, int]:
    a = i * math.pi / 128
    r = max(0, min(15, round(8 + 7 * math.sin(a)))) >> 2
    g = max(0, min(15, round(8 + 7 * math.sin(a + 2)))) >> 2
    b = max(0, min(15, round(8 + 7 * math.sin(a + 4)))) >> 2
    return r, g, b


def gray_level(i: int) -> int:
    a = i * 3 * math.pi / 128
    return max(0, min(3, round(1.5 + 1.5 * math.sin(a))))


def palette_word(i: int) -> int:
    r, g, b = palette_rgb222(i)
    gr = gray_level(i)
    return (gr << 6) | (r << 4) | (g << 2) | b


def emit_case(out: TextIO) -> None:
    for i in range(256):
        print(f"            8'd{i}: data = 8'b{palette_word(i):08b};", file=out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emit 256-entry RGB222 palette case data for src/palette.sv."
    )
    parser.add_argument(
        "-o", "--output",
        help="Write the generated case entries to this file instead of stdout"
    )
    args = parser.parse_args()

    if args.output:
        with open(args.output, "w") as f:
            emit_case(f)
    else:
        emit_case(sys.stdout)


if __name__ == "__main__":
    main()
