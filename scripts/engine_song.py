#!/usr/bin/env python3
"""Audio engine reference + JSON song loader.

Bit-accurate Python mirror of synth_engine.sv (same widths/shifts) — used
by play_song.py for preview and gen_patterns.py for HW pattern generation.
"""

import json, re
from pathlib import Path

CLK_HZ              = 25_000_000
SAMPLE_DIV          = 2048
SAMPLE_INC          = 3
SAMPLE_HZ           = CLK_HZ * SAMPLE_INC // SAMPLE_DIV   # 36621
SONG_TICK_SAMPLES   = 256
SIXTEENTH_TICKS     = 16
BEAT_TICKS          = 64
BAR_TICKS           = 256
SONG_TICKS          = 8192                         # 32 bars

# A3 reference, 16-bit phase increments at SAMPLE_HZ.
# Bass scales by >>2 (A1 base). Melody scales by >>3 (A3 base, 13-bit phase).
NOTE_INC_A3 = [0x0188, 0x01B7, 0x01D3, 0x0208, 0x0249, 0x0270, 0x0295, 0x02E8]

# Scientific octave of A at oct_bit=0, per track. Bass: A1..G#2 / A2..G#3.
# Melody: A3..G#4 / A4..G#5. (Octave number changes at C, so C..G# sit at base+1.)
TRACK_BASE_OCT = {
    'bass':   1,
    'melody': 3,
}

NOTE_RE = re.compile(r'^([A-G]#?)(-?\d+)$')


def _letter_base_oct(letter, track_base):
    return track_base if letter[0] in ('A', 'B') else track_base + 1


def parse_note(name, gamut, track):
    m = NOTE_RE.match(name)
    if not m:
        raise ValueError(f"bad note {name!r} in track {track!r}")
    letter, octave = m.group(1), int(m.group(2))
    if letter not in gamut:
        raise ValueError(f"note {name!r} not in gamut {gamut}")
    base = _letter_base_oct(letter, TRACK_BASE_OCT[track])
    if   octave == base:     oct_bit = 0
    elif octave == base + 1: oct_bit = 1
    else:
        raise ValueError(f"{track} note {name!r}: octave {octave} unreachable "
                         f"(valid: {letter}{base} or {letter}{base+1})")
    return gamut.index(letter), oct_bit


def _tile_to_four(bars, name):
    n = len(bars)
    if n == 0:
        return [[]] * 4
    if n > 4:
        raise ValueError(f"track {name!r}: {n} bars, max 4")
    if 4 % n != 0:
        raise ValueError(f"track {name!r}: {n} bars doesn't tile 4 evenly")
    return bars * (4 // n)


def _parse_drum_bars(bars, name):
    bars = _tile_to_four(bars, name)
    out = []
    for bar in bars:
        row = [False] * 16
        for pos in bar:
            if not 0 <= pos < 16:
                raise ValueError(f"{name}: pos {pos} out of range 0..15")
            row[pos] = True
        out.append(row)
    return out


def _parse_bass_bar(bar, gamut):
    # Bass fires every eighth (sixt 0,2,…,14); each must carry an event.
    ev_by_eighth = [None] * 8
    for ev in bar:
        pos, note = ev
        if pos % 2 != 0 or not 0 <= pos < 16:
            raise ValueError(f"bass pos {pos}: must be even in 0..14")
        e = pos >> 1
        if ev_by_eighth[e] is not None:
            raise ValueError(f"bass: duplicate event at pos {pos}")
        ev_by_eighth[e] = parse_note(note, gamut, 'bass')
    for i, ev in enumerate(ev_by_eighth):
        if ev is None:
            raise ValueError(f"bass: missing event at eighth {i} (sixt {i*2})")
    return ev_by_eighth


def _parse_melody_bar(bar, gamut):
    row = [None] * 16
    for ev in bar:
        pos, notes = ev
        if not 0 <= pos < 16:
            raise ValueError(f"melody pos {pos}: out of range 0..15")
        if row[pos] is not None:
            raise ValueError(f"melody: duplicate event at pos {pos}")
        if isinstance(notes, str):
            main_s = arp_s = notes
        else:
            main_s, arp_s = notes
        mi, mo = parse_note(main_s, gamut, 'melody')
        ai, ao = parse_note(arp_s,  gamut, 'melody')
        row[pos] = (mi, mo, ai, ao)
    return row


def load_song(path):
    """Parse song.json → compiled dict (gamut, arrangement, section_variants,
    n_variants, variants). All tracks tiled to 4 bars; see code for shapes."""
    raw = json.loads(Path(path).read_text())
    gamut = raw['gamut']
    if len(gamut) != 8 or len(set(gamut)) != 8:
        raise ValueError(f"gamut must be 8 unique notes, got {gamut}")
    arrangement = raw['arrangement']
    if len(arrangement) != 8:
        raise ValueError(f"arrangement must have 8 slots, got {len(arrangement)}")
    sections = raw['sections']

    # Variant indices assigned in order of first appearance in arrangement.
    variant_of = {}
    for name in arrangement:
        if name not in sections:
            raise ValueError(f"arrangement references undefined section {name!r}")
        if name not in variant_of:
            variant_of[name] = len(variant_of)

    section_variants = [variant_of[n] for n in arrangement]
    variants = {}
    for name, v in variant_of.items():
        tracks = sections[name]['tracks']
        variants[v] = {
            'name':   name,
            'kick':   _parse_drum_bars(tracks.get('kick',  []),  'kick'),
            'snare':  _parse_drum_bars(tracks.get('snare', []), 'snare'),
            'hat':    _parse_drum_bars(tracks.get('hat',   []),   'hat'),
            'bass':   [_parse_bass_bar(b, gamut)
                       for b in _tile_to_four(tracks['bass'],   'bass')],
            'melody': [_parse_melody_bar(b, gamut)
                       for b in _tile_to_four(tracks['melody'], 'melody')],
        }

    return {
        'gamut':            gamut,
        'arrangement':      arrangement,
        'section_variants': section_variants,
        'n_variants':       len(variant_of),
        'variants':         variants,
    }


# Channel sample widths matching synth_*.sv. Kick keeps an extra bit for
# triangle smoothness; bass/melody/noise narrowed to 5-bit (their envelopes
# shift further down). Sum fits 7-bit signed.
CHANNEL_BITS = {'kick': 6, 'bass': 5, 'melody': 5, 'noise': 5}
MIX_TO_INT16_SHIFT = 9   # MSB-align 7-bit mixer to int16, mirrors HW sample_out


def kick_raw(phase, frames):
    if not frames:
        return 0
    fold = (~(phase >> 5) & 0x3F) if (phase & 0x800) else ((phase >> 5) & 0x3F)
    return fold - 32


def bass_raw(phase, env):
    if env == 3:
        return 0
    return (((phase >> 10) & 0x1F) - 16) >> env


def melody_raw(phase, vol, oct_bit):
    # vol≥4 mutes (not vol=15) — arith-shift of -16 sticks at -1 for vol≥4,
    # producing audible 0/-1 buzz between notes.
    if vol >= 4:
        return 0
    pulse_high = (phase >> (11 if oct_bit else 12)) & 1
    amp = 0x0F if pulse_high else -0x10
    return amp >> vol


def noise_raw(lfsr, vol, mode):
    if vol == 7:
        return 0
    nb = (lfsr & 0x1F) - 16
    shifted = nb if mode else (nb >> 1)
    return shifted >> vol


class Engine:
    """Bit-accurate mirror of synth_engine.sv."""

    # 'hat'/'snare' both map to the shared noise channel; soloing one blocks
    # the other's triggers.
    ALL = ('kick', 'bass', 'melody', 'hat', 'snare')

    # Preview-only per-channel right-shift. HW has no gain knob — the default
    # −6 dB balance is baked into CHANNEL_BITS.
    GAIN_CHANNELS = ('kick', 'bass', 'melody', 'noise')
    DEFAULT_GAINS = {ch: 0 for ch in GAIN_CHANNELS}

    def __init__(self, song, solo=None, gains=None):
        self.song = song
        self.active = set(solo) if solo else set(self.ALL)
        g = {**self.DEFAULT_GAINS, **(gains or {})}
        self.gains = {ch: int(g[ch]) for ch in self.GAIN_CHANNELS}

        self.song_pos = 0

        self.kick_phase = 0
        self.kick_inc   = 0
        self.kick_frames = 0

        self.bass_phase = 0
        self.bass_inc   = 0
        self.bass_env   = 3

        self.mel_phase    = 0
        self.mel_inc_main = 0
        self.mel_inc_arp  = 0
        self.mel_main_oct = 0
        self.mel_arp_oct  = 0
        self.mel_vol      = 15

        self.lfsr       = 0x1CAF
        self.noise_vol  = 7
        self.noise_mode = 0   # 0=hat, 1=snare

    def song_tick(self):
        self.song_pos = (self.song_pos + 1) % SONG_TICKS

        # Kick pitch sweep: inc *= 7/8 per tick (HW: inc - inc>>3).
        if self.kick_frames:
            self.kick_inc -= self.kick_inc >> 3
            self.kick_frames -= 1

        # Envelope decay paces: melody/8, bass/4 (cap at 2 = sustain),
        # hat/1, snare/4.
        if (self.song_pos & 7) == 0 and self.mel_vol < 15:
            self.mel_vol += 1
        if (self.song_pos & 3) == 0 and self.bass_env < 2:
            self.bass_env += 1
        noise_decay = (self.song_pos & 3) == 0 if self.noise_mode else True
        if noise_decay and self.noise_vol < 7:
            self.noise_vol += 1

        self._run_triggers()

    def _run_triggers(self):
        pos = self.song_pos
        section_idx = pos >> 10
        variant = self.song['section_variants'][section_idx]
        bar_in_s  = (pos >> 8) & 3
        sixt_in_b = (pos >> 4) & 0xF
        sec = self.song['variants'][variant]

        if (pos & 0xF) == 0:
            if sec['kick'][bar_in_s][sixt_in_b] and 'kick' in self.active:
                self._trig_kick()
            # Snare wins on overlap (matches synth_patterns noise_mode=drum_snare).
            snare = sec['snare'][bar_in_s][sixt_in_b] and 'snare' in self.active
            hat   = sec['hat'  ][bar_in_s][sixt_in_b] and 'hat'   in self.active
            if snare or hat:
                self._trig_noise(mode=1 if snare else 0)
            mel = sec['melody'][bar_in_s][sixt_in_b]
            if mel is not None and 'melody' in self.active:
                self._trig_melody(*mel)

        if (pos & 0x1F) == 0 and 'bass' in self.active:
            eighth = sixt_in_b >> 1
            note_idx, oct_bit = sec['bass'][bar_in_s][eighth]
            self.bass_inc = (NOTE_INC_A3[note_idx] >> 3) << oct_bit
            self.bass_env = 0

    def _trig_kick(self):
        self.kick_phase  = 0x400
        self.kick_inc    = 28
        self.kick_frames = 12

    def _trig_noise(self, mode):
        self.noise_vol  = 0
        self.noise_mode = mode

    def _trig_melody(self, main_idx, main_oct, arp_idx, arp_oct):
        self.mel_inc_main = NOTE_INC_A3[main_idx] >> 3
        self.mel_inc_arp  = NOTE_INC_A3[arp_idx]  >> 3
        self.mel_main_oct = main_oct
        self.mel_arp_oct  = arp_oct
        self.mel_vol      = 0

    def sample(self):
        # Sample from registered state (HW reads phase, not phase_next), then
        # advance accumulators + LFSR.
        kr = kick_raw(self.kick_phase, self.kick_frames)
        br = bass_raw(self.bass_phase, self.bass_env)
        cur_oct = self.mel_arp_oct if (self.song_pos & 4) else self.mel_main_oct
        mr = melody_raw(self.mel_phase, self.mel_vol, cur_oct)
        nr = noise_raw(self.lfsr, self.noise_vol, self.noise_mode)

        if self.kick_frames:
            self.kick_phase = (self.kick_phase + self.kick_inc) & 0xFFF
        self.bass_phase = (self.bass_phase + self.bass_inc) & 0x7FFF
        mel_inc = self.mel_inc_arp if (self.song_pos & 4) else self.mel_inc_main
        self.mel_phase = (self.mel_phase + mel_inc) & 0x1FFF
        # 15-bit Galois LFSR, x^15 + x^14 + 1.
        self.lfsr = ((self.lfsr >> 1) ^ 0x6000) & 0x7FFF if (self.lfsr & 1) \
                    else (self.lfsr >> 1) & 0x7FFF

        # Mixer: low slot = kick_active ? kick : bass (synthwave pump duck).
        kick_gated = (kr >> self.gains['kick']) if 'kick' in self.active else 0
        bass_gated = (br >> self.gains['bass']) if 'bass' in self.active else 0
        duck = self.kick_frames > 0 and 'kick' in self.active
        low  = kick_gated if duck else bass_gated
        noise_gated = (nr >> self.gains['noise']) \
            if ('hat' in self.active or 'snare' in self.active) else 0
        mel_gated   = (mr >> self.gains['melody']) if 'melody' in self.active else 0
        return (low + mel_gated + noise_gated) << MIX_TO_INT16_SHIFT


def render(song, ticks, solo=None, gains=None):
    eng = Engine(song, solo=solo, gains=gains)
    out = []
    # HW resets song_pos to 0x1FFF so the first tick wraps to 0 and fires the
    # pos=0 triggers. Python inits 0 and fires once up-front for the same effect.
    eng._run_triggers()
    for _ in range(ticks):
        for _ in range(SONG_TICK_SAMPLES):
            out.append(eng.sample())
        eng.song_tick()
    return out
