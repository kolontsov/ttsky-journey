/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Reciprocal: leading-zero count + 16-entry LUT + right barrel shift.
 * depth ≈ 4096/vx, 8-bit saturating, with a fixed central-disc clamp.
 *
 * No left-shift path: smallest LUT entry is 132, and 132<<1=264 > 255,
 * so v<16 always saturates — m=0,k=0 → LUT[0]=255 covers it.
 */

`default_nettype none

module reciprocal (
    input  wire [9:0] v_in,
    output wire [7:0] depth
);

    logic [3:0] m;
    logic [2:0] k;       // right-shift amount, 0..5

    always_comb begin
        if      (v_in[9]) begin m = v_in[8:5]; k = 3'd5; end
        else if (v_in[8]) begin m = v_in[7:4]; k = 3'd4; end
        else if (v_in[7]) begin m = v_in[6:3]; k = 3'd3; end
        else if (v_in[6]) begin m = v_in[5:2]; k = 3'd2; end
        else if (v_in[5]) begin m = v_in[4:1]; k = 3'd1; end
        else if (v_in[4]) begin m = v_in[3:0]; k = 3'd0; end
        else             begin m = 4'd0;       k = 3'd0; end
    end

    // LUT[i] = min(255, 4096 / (16 + i))
    logic [7:0] lut_val;
    always_comb begin
        case (m)
            4'd0:  lut_val = 8'd255;
            4'd1:  lut_val = 8'd240;
            4'd2:  lut_val = 8'd227;
            4'd3:  lut_val = 8'd215;
            4'd4:  lut_val = 8'd204;
            4'd5:  lut_val = 8'd195;
            4'd6:  lut_val = 8'd186;
            4'd7:  lut_val = 8'd178;
            4'd8:  lut_val = 8'd170;
            4'd9:  lut_val = 8'd163;
            4'd10: lut_val = 8'd157;
            4'd11: lut_val = 8'd151;
            4'd12: lut_val = 8'd146;
            4'd13: lut_val = 8'd141;
            4'd14: lut_val = 8'd136;
            default: lut_val = 8'd132;
        endcase
    end

    wire [7:0] recip_raw = lut_val >> k;

    // Central-disc clamp at 230 — gives the "approaching wall" effect.
    // recip_raw > 230 only for v_in < 18, so a range check beats a comparator.
    wire clamp_230 = ~|v_in[9:5] & (~v_in[4] | ~|v_in[3:1]);  // v_in < 18
    assign depth = clamp_230 ? 8'd230 : recip_raw;

endmodule
