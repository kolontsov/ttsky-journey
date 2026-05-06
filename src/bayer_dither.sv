/*
 * Copyright (c) 2026 Vadim Kolontsov
 * SPDX-License-Identifier: Apache-2.0
 *
 * 8x8 Bayer matrix, 6-bit output (0..63), pure combinational.
 */

`default_nettype none

module bayer_dither (
    input  wire [2:0] bx,
    input  wire [2:0] by,
    output logic [5:0] bayer_value
);

    always_comb begin
        case ({by, bx})
            6'd0:  bayer_value = 6'd0;  6'd1:  bayer_value = 6'd32;
            6'd2:  bayer_value = 6'd8;  6'd3:  bayer_value = 6'd40;
            6'd4:  bayer_value = 6'd2;  6'd5:  bayer_value = 6'd34;
            6'd6:  bayer_value = 6'd10; 6'd7:  bayer_value = 6'd42;

            6'd8:  bayer_value = 6'd48; 6'd9:  bayer_value = 6'd16;
            6'd10: bayer_value = 6'd56; 6'd11: bayer_value = 6'd24;
            6'd12: bayer_value = 6'd50; 6'd13: bayer_value = 6'd18;
            6'd14: bayer_value = 6'd58; 6'd15: bayer_value = 6'd26;

            6'd16: bayer_value = 6'd12; 6'd17: bayer_value = 6'd44;
            6'd18: bayer_value = 6'd4;  6'd19: bayer_value = 6'd36;
            6'd20: bayer_value = 6'd14; 6'd21: bayer_value = 6'd46;
            6'd22: bayer_value = 6'd6;  6'd23: bayer_value = 6'd38;

            6'd24: bayer_value = 6'd60; 6'd25: bayer_value = 6'd28;
            6'd26: bayer_value = 6'd52; 6'd27: bayer_value = 6'd20;
            6'd28: bayer_value = 6'd62; 6'd29: bayer_value = 6'd30;
            6'd30: bayer_value = 6'd54; 6'd31: bayer_value = 6'd22;

            6'd32: bayer_value = 6'd3;  6'd33: bayer_value = 6'd35;
            6'd34: bayer_value = 6'd11; 6'd35: bayer_value = 6'd43;
            6'd36: bayer_value = 6'd1;  6'd37: bayer_value = 6'd33;
            6'd38: bayer_value = 6'd9;  6'd39: bayer_value = 6'd41;

            6'd40: bayer_value = 6'd51; 6'd41: bayer_value = 6'd19;
            6'd42: bayer_value = 6'd59; 6'd43: bayer_value = 6'd27;
            6'd44: bayer_value = 6'd49; 6'd45: bayer_value = 6'd17;
            6'd46: bayer_value = 6'd57; 6'd47: bayer_value = 6'd25;

            6'd48: bayer_value = 6'd15; 6'd49: bayer_value = 6'd47;
            6'd50: bayer_value = 6'd7;  6'd51: bayer_value = 6'd39;
            6'd52: bayer_value = 6'd13; 6'd53: bayer_value = 6'd45;
            6'd54: bayer_value = 6'd5;  6'd55: bayer_value = 6'd37;

            6'd56: bayer_value = 6'd63; 6'd57: bayer_value = 6'd31;
            6'd58: bayer_value = 6'd55; 6'd59: bayer_value = 6'd23;
            6'd60: bayer_value = 6'd61; 6'd61: bayer_value = 6'd29;
            6'd62: bayer_value = 6'd53; 6'd63: bayer_value = 6'd21;
        endcase
    end

endmodule
