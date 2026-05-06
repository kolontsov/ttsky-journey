/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Combinational CORDIC vectoring, 11-bit datapath. Maps centered (px, py)
 * to magnitude vx ≈ K·sqrt(px²+py²) (K ≈ 1.65) and 8-bit angle ≈ atan2.
 * Pre-rotate + iteration 0 are folded to closed form, then 5 shift iters.
 *
 * Inputs are pre-quantised >>>1 (drops 1 LSB) and the output is <<1 to
 * restore range. Bus guard ratio matches the 12-bit sweet spot so ABC
 * still pattern-matches the XOR+carry abs template.
 */

`default_nettype none

module cordic (
    input  wire signed [9:0]  px,   // centered x, [-320, 319]
    input  wire signed [9:0]  py,   // centered y, [-240, 239]
    output wire [9:0]         vx,     // magnitude (0..~660, LSB = 0)
    output wire [7:0]         angle   // angle, unsigned, 256 = 2π
);

    localparam signed [10:0] ATAN1 = 11'sd76;
    localparam signed [10:0] ATAN2 = 11'sd40;
    localparam signed [10:0] ATAN3 = 11'sd20;
    localparam signed [10:0] ATAN4 = 11'sd10;
    localparam signed [10:0] ATAN5 = 11'sd5;

    // Pre-quantise px/2, py/2.
    wire sx = px[9];
    wire sy = py[9];
    wire s  = sx ^ sy;
    wire signed [10:0] px_q = {{2{sx}}, px[9:1]};
    wire signed [10:0] py_q = {{2{sy}}, py[9:1]};

    // Right-half-plane pre-rotate + iter 0 (ATAN0=128) folded:
    //   vx1 = |px| + |py|
    //   vy1 = ±(|py| - |px|), sign = sx^sy
    //   a1  ∈ {±128, ±384} from (sx, sy) — pure wiring.
    wire signed [10:0] ax = (px_q ^ {11{sx}}) + {{10{1'b0}}, sx};
    wire signed [10:0] ay = (py_q ^ {11{sy}}) + {{10{1'b0}}, sy};

    wire signed [10:0] vx1  = ax + ay;
    wire signed [10:0] diff = ay - ax;
    wire signed [10:0] vy1  = (diff ^ {11{s}}) + {{10{1'b0}}, s};
    wire signed [10:0] a1   = {{2{sy}}, s, 1'b1, 7'b0};

    // Iter 1 (shift 1)
    wire signed [10:0] dy1 = vy1 >>> 1;
    wire signed [10:0] dx1 = vx1 >>> 1;
    wire signed [10:0] vx2 = vx1 + (dy1 ^ {11{vy1[10]}}) + {{10{1'b0}}, vy1[10]};
    wire signed [10:0] vy2 = vy1 - (dx1 ^ {11{vy1[10]}}) - {{10{1'b0}}, vy1[10]};
    wire signed [10:0] a2  = vy1[10] ? (a1 - ATAN1) : (a1 + ATAN1);

    // Iter 2 (shift 2)
    wire signed [10:0] dy2 = vy2 >>> 2;
    wire signed [10:0] dx2 = vx2 >>> 2;
    wire signed [10:0] vx3 = vx2 + (dy2 ^ {11{vy2[10]}}) + {{10{1'b0}}, vy2[10]};
    wire signed [10:0] vy3 = vy2 - (dx2 ^ {11{vy2[10]}}) - {{10{1'b0}}, vy2[10]};
    wire signed [10:0] a3  = vy2[10] ? (a2 - ATAN2) : (a2 + ATAN2);

    // Iter 3 (shift 3)
    wire signed [10:0] dy3 = vy3 >>> 3;
    wire signed [10:0] dx3 = vx3 >>> 3;
    wire signed [10:0] vx4 = vx3 + (dy3 ^ {11{vy3[10]}}) + {{10{1'b0}}, vy3[10]};
    wire signed [10:0] vy4 = vy3 - (dx3 ^ {11{vy3[10]}}) - {{10{1'b0}}, vy3[10]};
    wire signed [10:0] a4  = vy3[10] ? (a3 - ATAN3) : (a3 + ATAN3);

    // Iter 4 (shift 4)
    wire signed [10:0] dy4 = vy4 >>> 4;
    wire signed [10:0] dx4 = vx4 >>> 4;
    wire signed [10:0] vx5 = vx4 + (dy4 ^ {11{vy4[10]}}) + {{10{1'b0}}, vy4[10]};
    wire signed [10:0] vy5 = vy4 - (dx4 ^ {11{vy4[10]}}) - {{10{1'b0}}, vy4[10]};
    wire signed [10:0] a5  = vy4[10] ? (a4 - ATAN4) : (a4 + ATAN4);

    // Iter 5 (shift 5) — last stage, vy dropped.
    wire signed [10:0] dy5 = vy5 >>> 5;
    wire signed [10:0] vx6 = vx5 + (dy5 ^ {11{vy5[10]}}) + {{10{1'b0}}, vy5[10]};
    wire signed [10:0] a6  = vy5[10] ? (a5 - ATAN5) : (a5 + ATAN5);

    assign angle = a6[9:2];
    // Scale back ×2: vx6 max ~330, output max ~660 with LSB=0.
    assign vx  = {vx6[8:0], 1'b0};

    wire _unused = &{1'b0, vx6[10:9], a6[10], a6[1:0], px[0], py[0]};

endmodule
