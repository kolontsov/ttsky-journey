/*
 * Tang Primer 20K + Dock — top-level wrapper for Journey.
 *
 * Drives the official Tiny VGA PMOD (https://github.com/mole99/tiny-vga,
 * 2-bit/channel resistor ladder, single 12-pin PMOD) on dock PMOD3 and the
 * tt-audio-pmod (https://github.com/MichaelBell/tt-audio-pmod, low-pass
 * filter expecting a 1-bit PWM/ΣΔ signal) on dock PMOD1.
 *
 * Same PMOD layout the judges' Tiny Tapeout demoboard uses, preserving the
 * chip's exact uo_out byte packing and uio_out[7] sigma-delta path. Audio
 * goes straight from uio_out[7] to the audio PMOD's filter input.
 *
 * Pin map and PMOD back-view conventions: docs/tangprimer20k.md.
 */

`default_nettype none

module tangprimer20k_top (
    input  wire       clk_27m,    // 27 MHz onboard oscillator (H11)
    input  wire       btn_s0_n,   // S0 user button (T10), active low → reset

    // Tiny VGA PMOD on dock PMOD3 — 8 data pins in chip uo_out order
    output wire [7:0] vga_pmod,

    // tt-audio-pmod on dock PMOD1 — 1-bit ΣΔ on PMOD pin 10 (= chip bit 7)
    output wire       audio_pin,

    // Onboard LEDs (active low, drive 1 = off)
    output wire [5:0] led_n
);

    // ---- 27 MHz → 25.2 MHz pixel clock (via 75.6 MHz CLKOUT + /3 tap) ----
    // 25.2 MHz can't come from CLKOUT directly: the 3 MHz PFD floor caps
    // IDIV at 9, but 25.2 = 27 * FBDIV/IDIV requires IDIV=15. So we run
    // CLKOUT at 75.6 MHz and use the rPLL's hard-wired /3 tap CLKOUTD3 for
    // the pixel clock.
    //
    // 25.2 MHz is +0.10% from VESA 640×480@60 spec (25.175 MHz), keeping
    // cheap VGA-to-HDMI converters inside their tighter lock windows.
    //
    // CLKOUT   = FCLKIN * FBDIV / IDIV = 27 * 14 / 5 = 75.6 MHz
    // CLKOUTD3 = CLKOUT / 3                          = 25.2 MHz
    // PFD      = FCLKIN / IDIV         = 27 / 5      = 5.4 MHz  (≥ 3 MHz min)
    // VCO      = CLKOUT * ODIV         = 75.6 * 8    = 604.8 MHz (range 400-1200)
    wire clk_25m;
    wire pll_lock;

    rPLL #(
        .FCLKIN       ("27"),
        .IDIV_SEL     (4),       // IDIV = IDIV_SEL + 1 = 5
        .FBDIV_SEL    (13),      // FBDIV = FBDIV_SEL + 1 = 14 → 75.6 MHz
        .ODIV_SEL     (8),
        .DYN_SDIV_SEL (2),
        .DEVICE       ("GW2A-18C")
    ) pll (
        .CLKIN    (clk_27m),
        .CLKOUT   (),
        .LOCK     (pll_lock),
        .CLKOUTP  (),
        .CLKOUTD  (),
        .CLKOUTD3 (clk_25m),
        .RESET    (1'b0),
        .RESET_P  (1'b0),
        .CLKFB    (1'b0),
        .FBDSEL   (6'b0),
        .IDSEL    (6'b0),
        .ODSEL    (6'b0),
        .PSDA     (4'b0),
        .DUTYDA   (4'b0),
        .FDLY     (4'b0)
    );

    // ---- Reset: hold until PLL locks; S0 forces reset ----
    reg [3:0] rst_cnt = 4'd0;
    wire rst_n = rst_cnt[3] & btn_s0_n;

    always @(posedge clk_25m) begin
        if (!pll_lock)
            rst_cnt <= 4'd0;
        else if (!rst_cnt[3])
            rst_cnt <= rst_cnt + 4'd1;
    end

    // ---- Journey core ----
    wire [7:0] uo_out;
    wire [7:0] uio_out;

    tt_um_kolontsov_journey core (
        .ui_in   (8'd0),
        .uo_out  (uo_out),
        .uio_in  (8'd0),
        .uio_out (uio_out),
        .uio_oe  (),
        .ena     (1'b1),
        .clk     (clk_25m),
        .rst_n   (rst_n)
    );

    // VGA: chip already packs uo_out in Tiny VGA order
    //   uo[0]=R1  uo[1]=G1  uo[2]=B1  uo[3]=vsync
    //   uo[4]=R0  uo[5]=G0  uo[6]=B0  uo[7]=hsync
    // Dock PMOD pin order matches chip bit order (.cst takes care of routing).
    assign vga_pmod = uo_out;

    // Audio: chip's 1-bit ΣΔ output drives the PMOD's filter input directly.
    assign audio_pin = uio_out[7];

    // ---- LED diagnostics (active low) ----
    // LED0: heartbeat from clk_25m (proves system clock alive after reset)
    // LED1: PLL lock indicator (steady on once locked)
    reg [24:0] led_cnt;
    always @(posedge clk_25m) begin
        if (!rst_n)
            led_cnt <= 25'd0;
        else
            led_cnt <= led_cnt + 25'd1;
    end

    assign led_n = {4'b1111, ~pll_lock, ~led_cnt[24]};

    // uio_out[0..6] unused on this board.
    wire _unused = &{uio_out[6:0], 1'b0};

endmodule
