#!/usr/bin/env python3
# /// script
# dependencies = []
# ///
"""Convert between scripts/data/song.json and the narrow Furnace .fur edit format.

Export is intentionally conservative: PCM DAC rhythm + NES chip, one pattern
index per JSON section, one row per JSON sixteenth note.
"""

import argparse
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

from engine_song import (
    BAR_TICKS,
    CHANNEL_BITS,
    NOTE_INC_A3,
    SAMPLE_HZ,
    SONG_TICK_SAMPLES,
    SIXTEENTH_TICKS,
    TRACK_BASE_OCT,
    _letter_base_oct,
    _parse_bass_bar,
    _parse_drum_bars,
    _parse_melody_bar,
    _tile_to_four,
    bass_raw,
    kick_raw,
    load_song,
    noise_raw,
    parse_note,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SONG = ROOT / "scripts" / "data" / "song.json"
DEFAULT_OUT = ROOT / "scripts" / "data" / "journey.fur"
DEFAULT_IMPORT_OUT = ROOT / "scripts" / "data" / "song.imported.json"

FUR_VERSION = 245
SYSTEM_NES = 0x06
SYSTEM_PCM_DAC = 0xC0
INS_NES = 34
INS_AMIGA = 4
NOTE_OFF = 180
SAMPLE_DEPTH_16BIT = 16
METADATA_PREFIX = "journey-song-meta "
METADATA_FORMAT = "journey-song"
METADATA_VERSION = 1

CHIP_SPECS = (
    (SYSTEM_PCM_DAC, 4, 0.70),
    (SYSTEM_NES, 5, 1.00),
)
ACTIVE_CHANNELS = 6

PATTERN_ROWS = 64
ORDER_ROWS = 8
CHANNELS = (
    "Kick",
    "Snare",
    "Hat",
    "Bass",
    "Melody",
    "Arp",
    "NES Triangle",
    "NES Noise",
    "NES DPCM",
)
CHANNEL_SHORTS = ("KCK", "SNR", "HAT", "BAS", "MEL", "ARP", "TR", "NO", "DMC")

INS_KICK = 0
INS_BASS = 1
INS_MELODY = 2
INS_ARP = 3
INS_SNARE = 4
INS_HAT = 5

SAMPLE_KICK = 0
SAMPLE_SNARE = 1
SAMPLE_HAT = 2
SAMPLE_BASS_BASE = 3
SAMPLE_PLAY_NOTE = "C4"
KICK_VOLUME = 205
SNARE_VOLUME = 170
HAT_VOLUME = 135
BASS_VOLUME = 155
NES_FULL_VOLUME = 15
PCM_VOLUME_MACRO_MAX = 64
BASS_SAMPLE_TICKS = SIXTEENTH_TICKS * 2
MELODY_VOLUME_STEPS = (15, 8, 4, 2, 1, 0)
MELODY_VOLUME_STEP_TICKS = 8

NOTE_NAMES = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)
NOTE_TO_SEMITONE = {name: idx for idx, name in enumerate(NOTE_NAMES)}


class Writer:
    def __init__(self):
        self.buf = bytearray()

    def tell(self):
        return len(self.buf)

    def patch_i(self, pos, value):
        self.buf[pos:pos + 4] = struct.pack("<I", value)

    def b(self, value):
        self.buf.append(value & 0xFF)

    def s(self, value):
        self.buf += struct.pack("<H", value & 0xFFFF)

    def i(self, value):
        self.buf += struct.pack("<I", value & 0xFFFFFFFF)

    def f(self, value):
        self.buf += struct.pack("<f", float(value))

    def raw(self, data):
        self.buf += data

    def zstr(self, text):
        self.raw(text.encode("utf-8"))
        self.b(0)


class Reader:
    def __init__(self, data, label):
        self.data = data
        self.pos = 0
        self.label = label

    def _need(self, size):
        if self.pos + size > len(self.data):
            raise ValueError(f"{self.label}: unexpected end of data at offset {self.pos}")

    def tell(self):
        return self.pos

    def remaining(self):
        return len(self.data) - self.pos

    def b(self):
        self._need(1)
        value = self.data[self.pos]
        self.pos += 1
        return value

    def s(self):
        self._need(2)
        value = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def i(self):
        self._need(4)
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def f(self):
        self._need(4)
        value = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return value

    def raw(self, size):
        self._need(size)
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def zstr(self):
        end = self.data.find(b"\0", self.pos)
        if end < 0:
            raise ValueError(f"{self.label}: unterminated string at offset {self.pos}")
        raw = self.data[self.pos:end]
        self.pos = end + 1
        return raw.decode("utf-8")


def block(block_id, payload):
    return block_id + struct.pack("<I", len(payload)) + payload


def zstr_bytes(text):
    return text.encode("utf-8") + b"\0"


def note_number(name):
    # Furnace PATN encoding: 0 = C-(-5), 179 = B-9.
    letter = name[:-1] if name[-2] == "#" else name[0]
    octave = int(name[len(letter):])
    semitone = NOTE_TO_SEMITONE[letter]
    value = (octave + 5) * 12 + semitone
    if not 0 <= value < 180:
        raise ValueError(f"note {name!r} is outside Furnace's PATN note range")
    return value


def note_name_from_number(value):
    if not 0 <= value < 180:
        raise ValueError(f"Furnace note value {value} is not a playable note")
    octave = value // 12 - 5
    letter = NOTE_NAMES[value % 12]
    return f"{letter}{octave}"


def sample_map_note_number(name):
    # Instrument sample maps use Furnace's internal note scale: C0 = 0, C4 = 48.
    letter = name[:-1] if name[-2] == "#" else name[0]
    octave = int(name[len(letter):])
    semitone = NOTE_TO_SEMITONE[letter]
    value = octave * 12 + semitone
    if not 0 <= value < 120:
        raise ValueError(f"note {name!r} is outside Furnace's sample-map note range")
    return value


def note_name(letter, oct_bit, track):
    octave = _letter_base_oct(letter, TRACK_BASE_OCT[track]) + oct_bit
    return f"{letter}{octave}"


def song_tick_hz():
    return SAMPLE_HZ / SONG_TICK_SAMPLES


def song_bpm():
    seconds_per_beat = (BAR_TICKS / 4) * SONG_TICK_SAMPLES / SAMPLE_HZ
    return 60.0 / seconds_per_beat


def load_furnace_source(path):
    # engine_song.load_song() compiles only sections referenced by the
    # arrangement; Furnace is the editor, so surface every section regardless.
    raw = json.loads(Path(path).read_text())
    compiled = load_song(path)

    sections_by_name = {}
    for name, section in raw["sections"].items():
        tracks = section["tracks"]
        sections_by_name[name] = {
            "name": name,
            "kick": _parse_drum_bars(tracks.get("kick", []), "kick"),
            "snare": _parse_drum_bars(tracks.get("snare", []), "snare"),
            "hat": _parse_drum_bars(tracks.get("hat", []), "hat"),
            "bass": [
                _parse_bass_bar(bar, raw["gamut"])
                for bar in _tile_to_four(tracks["bass"], "bass")
            ],
            "melody": [
                _parse_melody_bar(bar, raw["gamut"])
                for bar in _tile_to_four(tracks["melody"], "melody")
            ],
        }

    section_names = list(raw["sections"].keys())
    compiled["description"] = raw.get("description", "")
    compiled["key"] = raw.get("key", "")
    compiled["sections_by_name"] = sections_by_name
    compiled["section_names"] = section_names
    compiled["section_index"] = {name: i for i, name in enumerate(section_names)}
    return compiled


@dataclass
class Row:
    note: int | None = None
    ins: int | None = None
    vol: int | None = None
    fx: list[tuple[int | None, int | None]] = field(default_factory=list)

    def merge(self, other):
        if other.note is not None:
            self.note = other.note
        if other.ins is not None:
            self.ins = other.ins
        if other.vol is not None:
            self.vol = other.vol
        if other.fx:
            self.fx.extend(other.fx)


def add_note(rows, row, name, ins, vol=None, gate=None, fx=()):
    if not 0 <= row < len(rows):
        return
    rows[row].merge(Row(note=note_number(name), ins=ins, vol=vol, fx=list(fx)))
    if gate is not None:
        off_row = row + gate
        if off_row < len(rows):
            rows[off_row].merge(Row(note=NOTE_OFF))


def section_rows(compiled, section_name, channel):
    section = compiled["sections_by_name"][section_name]
    rows = [Row() for _ in range(PATTERN_ROWS)]
    gamut = compiled["gamut"]

    if channel == 0:  # kick
        for bar in range(4):
            for sixt, hit in enumerate(section["kick"][bar]):
                if hit:
                    add_note(rows, bar * 16 + sixt, "C2", INS_KICK)

    elif channel == 1:  # snare one-shot generated from the reference LFSR
        for bar in range(4):
            for sixt, hit in enumerate(section["snare"][bar]):
                if hit:
                    add_note(
                        rows,
                        bar * 16 + sixt,
                        "G4",
                        INS_SNARE,
                    )

    elif channel == 2:  # hat one-shot generated from the reference LFSR
        for bar in range(4):
            for sixt, hit in enumerate(section["hat"][bar]):
                if hit and not section["snare"][bar][sixt]:
                    add_note(
                        rows,
                        bar * 16 + sixt,
                        "A7",
                        INS_HAT,
                    )

    elif channel == 3:  # bass
        for bar in range(4):
            for eighth, (idx, oct_bit) in enumerate(section["bass"][bar]):
                row = bar * 16 + eighth * 2
                add_note(
                    rows,
                    row,
                    note_name(gamut[idx], oct_bit, "bass"),
                    INS_BASS,
                )

    elif channel in (4, 5):  # melody main/arp split to two Furnace channels
        for bar in range(4):
            for sixt, event in enumerate(section["melody"][bar]):
                if event is None:
                    continue
                main_idx, main_oct, arp_idx, arp_oct = event
                if channel == 4:
                    name = note_name(gamut[main_idx], main_oct, "melody")
                    add_note(rows, bar * 16 + sixt, name, INS_MELODY)
                else:
                    name = note_name(gamut[arp_idx], arp_oct, "melody")
                    add_note(rows, bar * 16 + sixt, name, INS_ARP)

    return rows


def encode_pattern_rows(rows):
    out = bytearray()
    empty = 0

    def flush_empty():
        nonlocal empty
        while empty > 0:
            if empty == 1:
                out.append(0)
                empty = 0
            else:
                n = min(empty, 129)
                out.append(0x80 | (n - 2))
                empty -= n

    for row in rows:
        fx = row.fx[:8]
        mask = 0
        effect_mask = 0

        if row.note is not None:
            mask |= 0x01
        if row.ins is not None:
            mask |= 0x02
        if row.vol is not None:
            mask |= 0x04

        for idx, (cmd, val) in enumerate(fx):
            if cmd is not None:
                if idx == 0:
                    mask |= 0x08
                elif idx < 4:
                    mask |= 0x20
                    effect_mask |= 1 << (idx * 2)
                else:
                    mask |= 0x40
                    effect_mask |= 1 << (idx * 2)
            if val is not None:
                if idx == 0:
                    mask |= 0x10
                elif idx < 4:
                    mask |= 0x20
                    effect_mask |= 1 << (idx * 2 + 1)
                else:
                    mask |= 0x40
                    effect_mask |= 1 << (idx * 2 + 1)

        if mask == 0:
            empty += 1
            continue

        flush_empty()
        out.append(mask)
        if mask & 0x20:
            out.append(effect_mask & 0xFF)
        if mask & 0x40:
            out.append((effect_mask >> 8) & 0xFF)
        if mask & 0x01:
            out.append(row.note)
        if mask & 0x02:
            out.append(row.ins)
        if mask & 0x04:
            out.append(row.vol)
        if mask & 0x08:
            out.append(fx[0][0] if len(fx) > 0 and fx[0][0] is not None else 0)
        if mask & 0x10:
            out.append(fx[0][1] if len(fx) > 0 and fx[0][1] is not None else 0)
        if mask & 0x20:
            for idx in range(1, min(4, len(fx))):
                cmd, val = fx[idx]
                if effect_mask & (1 << (idx * 2)):
                    out.append(cmd)
                if effect_mask & (1 << (idx * 2 + 1)):
                    out.append(val)
        if mask & 0x40:
            for idx in range(4, min(8, len(fx))):
                cmd, val = fx[idx]
                if effect_mask & (1 << (idx * 2)):
                    out.append(cmd)
                if effect_mask & (1 << (idx * 2 + 1)):
                    out.append(val)

    out.append(0xFF)
    return bytes(out)


def make_patn(subsong, channel, pattern_index, name, rows):
    payload = bytearray()
    payload.append(subsong)
    payload.append(channel)
    payload += struct.pack("<H", pattern_index)
    payload += zstr_bytes(name)
    payload += encode_pattern_rows(rows)
    return block(b"PATN", payload)


def song_metadata(compiled):
    return {
        "format": METADATA_FORMAT,
        "version": METADATA_VERSION,
        "key": compiled.get("key", ""),
        "gamut": compiled["gamut"],
    }


def song_comment(compiled):
    key = compiled.get("key", "")
    gamut = " ".join(compiled["gamut"])
    meta_json = json.dumps(song_metadata(compiled), separators=(",", ":"))
    lines = [
        f"Generated from scripts/data/song.json. Row = sixteenth; tempo ~= {song_bpm():.2f} BPM.",
        f"Key: {key or 'unspecified'}; gamut: {gamut}",
        f"{METADATA_PREFIX}{meta_json}",
    ]
    return "\n".join(lines)


def make_sng2(compiled):
    payload = bytearray()
    payload += struct.pack("<f", song_tick_hz())
    payload += bytes([1, 1])  # initial arp speed, effect speed divider
    payload += struct.pack("<HH", PATTERN_ROWS, ORDER_ROWS)
    payload += bytes([4, 16])  # row highlight: beat, bar
    payload += struct.pack("<HH", 1, 1)  # virtual tempo
    payload.append(1)  # speed pattern length
    payload += struct.pack("<16H", *([SIXTEENTH_TICKS] * 16))
    payload += zstr_bytes("Journey")
    payload += zstr_bytes(song_comment(compiled))

    for _channel in CHANNELS:
        for section_name in compiled["arrangement"]:
            payload.append(compiled["section_index"][section_name])

    payload += bytes([1] * len(CHANNELS))  # one effect column per channel
    payload += bytes([3 if idx < ACTIVE_CHANNELS else 0 for idx in range(len(CHANNELS))])
    payload += bytes([0 if idx < ACTIVE_CHANNELS else 3 for idx in range(len(CHANNELS))])

    for name in CHANNELS:
        payload += zstr_bytes(name)
    for name in CHANNEL_SHORTS:
        payload += zstr_bytes(name)

    payload += struct.pack("<6I", 0, 0, 0, 0, 0, 0)  # default colors
    return block(b"SNG2", payload)


def sample16(name, values, channel, *, center_rate=SAMPLE_HZ):
    payload = bytearray()
    payload += zstr_bytes(name)
    payload += struct.pack("<III", len(values), center_rate, center_rate)
    payload += bytes([SAMPLE_DEPTH_16BIT, 0, 0, 0])
    payload += struct.pack("<ii", -1, -1)
    payload += struct.pack("<4I", 0, 0, 0, 0)
    shift = 16 - CHANNEL_BITS[channel]
    payload += struct.pack(
        f"<{len(values)}h",
        *[max(-32768, min(32767, v << shift)) for v in values],
    )
    return block(b"SMP2", payload)


def advance_lfsr(lfsr):
    if lfsr & 1:
        return ((lfsr >> 1) ^ 0x6000) & 0x7FFF
    return (lfsr >> 1) & 0x7FFF


def kick_sample():
    phase = 0x400
    inc = 28
    frames = 12
    out = []
    for _tick in range(14):
        for _ in range(SONG_TICK_SAMPLES):
            out.append(kick_raw(phase, frames))
            if frames:
                phase = (phase + inc) & 0xFFF
        if frames:
            inc -= inc >> 3
            frames -= 1
    return out


def noise_sample(mode):
    lfsr = 0x1CAF
    vol = 0
    out = []
    ticks = 30 if mode else 9
    for tick in range(ticks):
        for _ in range(SONG_TICK_SAMPLES):
            out.append(noise_raw(lfsr, vol, mode))
            lfsr = advance_lfsr(lfsr)
        if mode:
            if (tick + 1) % 4 == 0 and vol < 7:
                vol += 1
        elif vol < 7:
            vol += 1
    return out


def bass_note_specs(compiled):
    specs = []
    seen = set()
    for oct_bit in (0, 1):
        for idx, letter in enumerate(compiled["gamut"]):
            name = note_name(letter, oct_bit, "bass")
            if name in seen:
                continue
            seen.add(name)
            specs.append((name, idx, oct_bit, SAMPLE_BASS_BASE + len(specs)))
    return specs


def bass_sample(note_idx, oct_bit):
    phase = 0
    inc = (NOTE_INC_A3[note_idx] >> 3) << oct_bit
    env = 0
    out = []
    for tick in range(BASS_SAMPLE_TICKS):
        for _ in range(SONG_TICK_SAMPLES):
            out.append(bass_raw(phase, env))
            phase = (phase + inc) & 0x7FFF
        if (tick + 1) % 4 == 0 and env < 2:
            env += 1
    return out


def furnace_samples(compiled):
    samples = [
        sample16("hw kick", kick_sample(), "kick"),
        sample16("hw snare", noise_sample(mode=1), "noise"),
        sample16("hw hat", noise_sample(mode=0), "noise"),
    ]
    for name, note_idx, oct_bit, sample_index in bass_note_specs(compiled):
        if sample_index != len(samples):
            raise ValueError("bass sample index allocation drifted")
        samples.append(sample16(f"hw bass {name}", bass_sample(note_idx, oct_bit), "bass"))
    return samples


def feature(code, payload):
    return code + struct.pack("<H", len(payload)) + payload


def macro(code, values, *, loop=255, rel=255, mode=0, open_=0, delay=0, speed=1):
    if len(values) > 255:
        raise ValueError("Furnace macro length must fit in one byte")
    min_v = min(values)
    max_v = max(values)

    if min_v >= 0 and max_v <= 255:
        word_size = 0
        fmt = f"<{len(values)}B"
    elif min_v >= -128 and max_v <= 127:
        word_size = 64
        fmt = f"<{len(values)}b"
    elif min_v >= -32768 and max_v <= 32767:
        word_size = 128
        fmt = f"<{len(values)}h"
    else:
        word_size = 192
        fmt = f"<{len(values)}i"

    data = bytearray()
    data += bytes(
        [code, len(values), loop, rel, mode, (open_ & 0x3F) | word_size, delay, speed]
    )
    data += struct.pack(fmt, *values)
    return data


def melody_decay():
    # Approximates synth_melody's shift envelope in NES linear volume steps.
    env = []
    for volume in MELODY_VOLUME_STEPS:
        env.extend([volume] * MELODY_VOLUME_STEP_TICKS)
    return env


def alternating_melody_decay(*, phase):
    env = melody_decay()
    return [vol if ((idx // 4) & 1) == phase else 0 for idx, vol in enumerate(env)]


def pcm_volume_macro(pattern_volume):
    return max(0, min(PCM_VOLUME_MACRO_MAX, round(pattern_volume * PCM_VOLUME_MACRO_MAX / 255)))


def feature_ma(macros):
    payload = bytearray()
    payload += struct.pack("<H", 8)
    for item in macros:
        payload += item
    payload.append(255)
    return feature(b"MA", payload)


def fixed_sample_map(sample_index, *, play_note=SAMPLE_PLAY_NOTE):
    play_note_number = sample_map_note_number(play_note)
    return [(play_note_number, sample_index) for _note in range(120)]


def bass_sample_map(compiled):
    entries = fixed_sample_map(SAMPLE_BASS_BASE)
    play_note_number = sample_map_note_number(SAMPLE_PLAY_NOTE)
    for name, _note_idx, _oct_bit, sample_index in bass_note_specs(compiled):
        entries[sample_map_note_number(name)] = (play_note_number, sample_index)
    return entries


def feature_sm(sample_index, *, play_note=SAMPLE_PLAY_NOTE, note_map=None):
    if note_map is None:
        note_map = fixed_sample_map(sample_index, play_note=play_note)
    if len(note_map) != 120:
        raise ValueError("Furnace sample maps must have exactly 120 entries")

    payload = bytearray()
    payload += struct.pack("<HBB", sample_index, 0x03, 0)
    for freq_note, mapped_sample in note_map:
        payload += struct.pack("<HH", freq_note, mapped_sample)
    return feature(b"SM", payload)


def make_ins(name, macros, *, sample_index=None, ins_type=INS_NES, sample_map=None):
    payload = bytearray()
    payload += struct.pack("<HBB", FUR_VERSION, ins_type, 0)
    payload += feature(b"NA", zstr_bytes(name))
    if macros:
        payload += feature_ma(macros)
    if sample_index is not None:
        payload += feature_sm(sample_index, note_map=sample_map)
    payload += b"EN"
    return block(b"INS2", payload)


def furnace_instruments(compiled):
    return [
        make_ins(
            "kick sample",
            [macro(0, [pcm_volume_macro(KICK_VOLUME)], loop=0)],
            sample_index=SAMPLE_KICK,
            ins_type=INS_AMIGA,
        ),
        make_ins(
            "bass saw sample",
            [macro(0, [pcm_volume_macro(BASS_VOLUME)], loop=0)],
            sample_index=SAMPLE_BASS_BASE,
            ins_type=INS_AMIGA,
            sample_map=bass_sample_map(compiled),
        ),
        make_ins(
            "melody pulse",
            [
                macro(2, [2]),
                macro(0, alternating_melody_decay(phase=0)),
            ],
        ),
        make_ins(
            "arp pulse",
            [
                macro(2, [2]),
                macro(0, alternating_melody_decay(phase=1)),
            ],
        ),
        make_ins(
            "snare sample",
            [macro(0, [pcm_volume_macro(SNARE_VOLUME)], loop=0)],
            sample_index=SAMPLE_SNARE,
            ins_type=INS_AMIGA,
        ),
        make_ins(
            "hat sample",
            [macro(0, [pcm_volume_macro(HAT_VOLUME)], loop=0)],
            sample_index=SAMPLE_HAT,
            ins_type=INS_AMIGA,
        ),
    ]


def make_info(compiled, element_specs):
    payload = bytearray()
    payload += zstr_bytes("Journey")
    payload += zstr_bytes("Vadim Kolontsov")
    payload += zstr_bytes("Generic PCM DAC rhythm + NES (Ricoh 2A03)")
    payload += zstr_bytes("Tiny Tapeout SKY130")
    payload += zstr_bytes("")
    payload += zstr_bytes("")
    payload += zstr_bytes("")
    payload += zstr_bytes("")
    payload += struct.pack("<f", 440.0)
    payload.append(0)  # automatic system name

    payload += struct.pack("<fHH", 1.0, len(CHANNELS), len(CHIP_SPECS))
    for system_id, channel_count, volume in CHIP_SPECS:
        payload += struct.pack("<HHfff", system_id, channel_count, volume, 0.0, 0.0)

    payload += struct.pack("<I", 0)  # patchbay connections
    payload.append(1)  # automatic patchbay

    pointer_positions = []
    for element_type, count in element_specs:
        payload.append(element_type)
        payload += struct.pack("<I", count)
        positions = []
        for _ in range(count):
            positions.append(len(payload))
            payload += b"\0\0\0\0"
        pointer_positions.append(positions)
    payload.append(0)

    return block(b"INF2", payload), pointer_positions


def build_fur(song_path):
    compiled = load_furnace_source(song_path)
    chip_channels = sum(channel_count for _system_id, channel_count, _volume in CHIP_SPECS)
    if chip_channels != len(CHANNELS):
        raise ValueError(f"chip/channel mismatch: chips expose {chip_channels}, names cover {len(CHANNELS)}")
    if ACTIVE_CHANNELS > len(CHANNELS):
        raise ValueError("active channel count exceeds total channel count")

    instruments = furnace_instruments(compiled)
    waves = []
    samples = furnace_samples(compiled)

    patterns = []
    for channel, channel_name in enumerate(CHANNELS):
        for section_name in compiled["section_names"]:
            pattern_index = compiled["section_index"][section_name]
            rows = section_rows(compiled, section_name, channel)
            patterns.append(
                make_patn(
                    0,
                    channel,
                    pattern_index,
                    f"{section_name} {channel_name}",
                    rows,
                )
            )

    element_specs = [
        (0x01, 1),                  # SNG2
        (0x04, len(instruments)),   # INS2
        (0x05, len(waves)),         # WAVE
        (0x06, len(samples)),       # SMP2
        (0x07, len(patterns)),      # PATN
    ]
    info, pointer_positions = make_info(compiled, element_specs)

    w = Writer()
    w.raw(b"-Furnace module-")
    w.s(FUR_VERSION)
    w.s(0)
    w.i(32)
    w.i(0)
    w.i(0)
    w.raw(info)

    blocks = [[make_sng2(compiled)], instruments, waves, samples, patterns]
    for positions, block_list in zip(pointer_positions, blocks):
        for pos, item in zip(positions, block_list):
            w.patch_i(32 + 8 + pos, w.tell())
            w.raw(item)

    return bytes(w.buf)


@dataclass
class ParsedPattern:
    subsong: int
    channel: int
    index: int
    name: str
    rows: list[Row]


def iter_fur_blocks(data):
    if not data.startswith(b"-Furnace module-"):
        raise ValueError("not a Furnace module: missing file header")
    if len(data) < 32:
        raise ValueError("truncated Furnace module header")

    version = struct.unpack_from("<H", data, 16)[0]
    info_ptr = struct.unpack_from("<I", data, 20)[0]
    if info_ptr >= len(data):
        raise ValueError(f"INF2 pointer {info_ptr} is outside the file")

    pos = info_ptr
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError(f"truncated block header at offset {pos}")
        block_id = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        start = pos + 8
        end = start + size
        if end > len(data):
            raise ValueError(f"{block_id!r} block at offset {pos} exceeds file length")
        yield version, block_id, data[start:end], pos
        pos = end


def parse_inf2(payload):
    r = Reader(payload, "INF2")
    strings = [r.zstr() for _ in range(8)]
    tuning = r.f()
    auto_system_name = r.b()
    master_volume = r.f()
    channel_count = r.s()
    chip_count = r.s()

    chips = []
    for _ in range(chip_count):
        chips.append(
            {
                "system": r.s(),
                "channels": r.s(),
                "volume": r.f(),
                "pan": r.f(),
                "front_back": r.f(),
            }
        )

    patchbay_connections = r.i()
    if patchbay_connections != 0:
        raise ValueError("Furnace patchbay connections are not supported by this importer")
    auto_patchbay = r.b()

    elements = []
    while r.remaining():
        element_type = r.b()
        if element_type == 0:
            break
        count = r.i()
        pointers = [r.i() for _ in range(count)]
        elements.append((element_type, count, pointers))

    return {
        "name": strings[0],
        "author": strings[1],
        "system": strings[2],
        "strings": strings,
        "tuning": tuning,
        "auto_system_name": auto_system_name,
        "master_volume": master_volume,
        "channel_count": channel_count,
        "chips": chips,
        "auto_patchbay": auto_patchbay,
        "elements": elements,
    }


def parse_sng2(payload, channel_count):
    r = Reader(payload, "SNG2")
    hz = r.f()
    arp_speed = r.b()
    effect_speed_divider = r.b()
    pattern_rows = r.s()
    order_rows = r.s()
    row_highlight = (r.b(), r.b())
    virtual_tempo = (r.s(), r.s())
    speed_pattern_len = r.b()
    speed_pattern = [r.s() for _ in range(16)]
    name = r.zstr()
    comment = r.zstr()

    orders = [
        [r.b() for _ in range(order_rows)]
        for _channel in range(channel_count)
    ]
    effect_columns = [r.b() for _channel in range(channel_count)]
    channel_visibility = [r.b() for _channel in range(channel_count)]
    channel_collapse = [r.b() for _channel in range(channel_count)]
    channel_names = [r.zstr() for _channel in range(channel_count)]
    channel_shorts = [r.zstr() for _channel in range(channel_count)]

    return {
        "hz": hz,
        "arp_speed": arp_speed,
        "effect_speed_divider": effect_speed_divider,
        "pattern_rows": pattern_rows,
        "order_rows": order_rows,
        "row_highlight": row_highlight,
        "virtual_tempo": virtual_tempo,
        "speed_pattern_len": speed_pattern_len,
        "speed_pattern": speed_pattern,
        "name": name,
        "comment": comment,
        "orders": orders,
        "effect_columns": effect_columns,
        "channel_visibility": channel_visibility,
        "channel_collapse": channel_collapse,
        "channel_names": channel_names,
        "channel_shorts": channel_shorts,
    }


def decode_pattern_rows(encoded, pattern_rows, label):
    r = Reader(encoded, label)
    rows = [Row() for _ in range(pattern_rows)]
    row_idx = 0

    while True:
        token = r.b()
        if token == 0xFF:
            break
        if token == 0:
            row_idx += 1
            if row_idx > pattern_rows:
                raise ValueError(f"{label}: empty row run exceeds {pattern_rows} rows")
            continue
        if token & 0x80:
            row_idx += (token & 0x7F) + 2
            if row_idx > pattern_rows:
                raise ValueError(f"{label}: empty row run exceeds {pattern_rows} rows")
            continue

        if row_idx >= pattern_rows:
            raise ValueError(f"{label}: pattern cell exceeds {pattern_rows} rows")

        mask = token
        effect_mask = 0
        if mask & 0x20:
            effect_mask |= r.b()
        if mask & 0x40:
            effect_mask |= r.b() << 8

        row = Row()
        if mask & 0x01:
            row.note = r.b()
        if mask & 0x02:
            row.ins = r.b()
        if mask & 0x04:
            row.vol = r.b()

        fx = [(None, None) for _ in range(8)]
        if mask & 0x08:
            fx[0] = (r.b(), fx[0][1])
        if mask & 0x10:
            fx[0] = (fx[0][0], r.b())
        if mask & 0x20:
            for idx in range(1, 4):
                cmd, val = fx[idx]
                if effect_mask & (1 << (idx * 2)):
                    cmd = r.b()
                if effect_mask & (1 << (idx * 2 + 1)):
                    val = r.b()
                fx[idx] = (cmd, val)
        if mask & 0x40:
            for idx in range(4, 8):
                cmd, val = fx[idx]
                if effect_mask & (1 << (idx * 2)):
                    cmd = r.b()
                if effect_mask & (1 << (idx * 2 + 1)):
                    val = r.b()
                fx[idx] = (cmd, val)
        row.fx = [item for item in fx if item != (None, None)]
        rows[row_idx] = row
        row_idx += 1

    if r.remaining():
        raise ValueError(f"{label}: unexpected trailing PATN data after row terminator")
    return rows


def parse_patn(payload, pattern_rows, offset):
    r = Reader(payload, f"PATN@{offset}")
    subsong = r.b()
    channel = r.b()
    index = r.s()
    name = r.zstr()
    rows = decode_pattern_rows(
        payload[r.tell():],
        pattern_rows,
        f"PATN {name!r} ch{channel} idx{index}",
    )
    return ParsedPattern(subsong, channel, index, name, rows)


def extract_song_metadata(comment):
    for line in comment.splitlines():
        line = line.strip()
        if not line.startswith(METADATA_PREFIX):
            continue
        meta = json.loads(line[len(METADATA_PREFIX):])
        if meta.get("format") != METADATA_FORMAT:
            raise ValueError(f"unsupported song metadata format {meta.get('format')!r}")
        if meta.get("version") != METADATA_VERSION:
            raise ValueError(f"unsupported song metadata version {meta.get('version')!r}")
        return meta
    return None


def metadata_from_song_json(path):
    raw = json.loads(Path(path).read_text())
    return {
        "key": raw.get("key", ""),
        "gamut": raw.get("gamut"),
        "description": raw.get("description", ""),
        "section_names": list(raw.get("sections", {}).keys()),
    }


def parse_fur(path):
    data = Path(path).read_bytes()
    blocks = list(iter_fur_blocks(data))
    if not blocks:
        raise ValueError("Furnace module contains no blocks")

    version = blocks[0][0]
    inf2_blocks = [payload for _version, block_id, payload, _offset in blocks if block_id == b"INF2"]
    if len(inf2_blocks) != 1:
        raise ValueError(f"expected exactly one INF2 block, found {len(inf2_blocks)}")
    info = parse_inf2(inf2_blocks[0])

    sng2_blocks = [payload for _version, block_id, payload, _offset in blocks if block_id == b"SNG2"]
    if len(sng2_blocks) != 1:
        raise ValueError(f"expected exactly one SNG2 block, found {len(sng2_blocks)}")
    sng = parse_sng2(sng2_blocks[0], info["channel_count"])

    patterns = {}
    for _version, block_id, payload, offset in blocks:
        if block_id != b"PATN":
            continue
        pat = parse_patn(payload, sng["pattern_rows"], offset)
        if pat.subsong != 0:
            raise ValueError(f"PATN {pat.name!r}: only subsong 0 is supported")
        key = (pat.channel, pat.index)
        if key in patterns:
            raise ValueError(f"duplicate pattern for channel {pat.channel}, index {pat.index}")
        patterns[key] = pat

    return version, info, sng, patterns


def validate_import_contract(version, info, sng):
    if version != FUR_VERSION:
        raise ValueError(f"expected Furnace module version {FUR_VERSION}, got {version}")
    if info["channel_count"] != len(CHANNELS):
        raise ValueError(f"expected {len(CHANNELS)} channels, got {info['channel_count']}")

    chip_layout = [(chip["system"], chip["channels"]) for chip in info["chips"]]
    expected_layout = [(system_id, channel_count) for system_id, channel_count, _volume in CHIP_SPECS]
    if chip_layout != expected_layout:
        raise ValueError(f"unexpected chip layout {chip_layout}, expected {expected_layout}")

    if sng["pattern_rows"] != PATTERN_ROWS:
        raise ValueError(f"expected {PATTERN_ROWS} pattern rows, got {sng['pattern_rows']}")
    if sng["order_rows"] != ORDER_ROWS:
        raise ValueError(f"expected {ORDER_ROWS} order rows, got {sng['order_rows']}")
    if sng["speed_pattern_len"] != 1 or sng["speed_pattern"] != [SIXTEENTH_TICKS] * 16:
        raise ValueError("unsupported speed pattern; song.json has fixed sixteenth-note rows")
    if abs(sng["hz"] - song_tick_hz()) > 0.001:
        raise ValueError(f"unsupported tick rate {sng['hz']:.6f}; expected {song_tick_hz():.6f}")
    if sng["channel_names"] != list(CHANNELS):
        raise ValueError(f"unexpected channel names {sng['channel_names']!r}")
    if sng["effect_columns"] != [1] * len(CHANNELS):
        raise ValueError("edited effect-column counts are not supported")

    first_order = sng["orders"][0]
    for channel in range(1, ACTIVE_CHANNELS):
        if sng["orders"][channel] != first_order:
            raise ValueError("active channels must share the same order table")


def derive_section_names(patterns):
    by_index = {}
    for (channel, index), pat in sorted(patterns.items()):
        if channel >= ACTIVE_CHANNELS:
            continue
        suffix = f" {CHANNELS[channel]}"
        if not pat.name.endswith(suffix):
            continue
        section_name = pat.name[:-len(suffix)]
        if not section_name:
            continue
        if index in by_index and by_index[index] != section_name:
            raise ValueError(
                f"pattern index {index} has conflicting section names "
                f"{by_index[index]!r} and {section_name!r}"
            )
        by_index[index] = section_name

    if not by_index:
        raise ValueError("cannot derive section names from PATN names")
    max_index = max(by_index)
    missing = [idx for idx in range(max_index + 1) if idx not in by_index]
    if missing:
        raise ValueError(f"missing section names for pattern indices {missing}")
    return [by_index[idx] for idx in range(max_index + 1)]


def validate_gamut(gamut):
    if not isinstance(gamut, list) or len(gamut) != 8 or len(set(gamut)) != 8:
        raise ValueError(f"gamut must be 8 unique note names, got {gamut!r}")
    for note in gamut:
        if note not in NOTE_TO_SEMITONE:
            raise ValueError(f"unsupported gamut note {note!r}")


def cell_context(section_name, channel, row_idx):
    return f"{section_name}/{CHANNELS[channel]} row {row_idx:02d}"


def checked_note_event(row, section_name, channel, pattern_index, row_idx, expected_ins):
    ctx = cell_context(section_name, channel, row_idx)
    if row.note is None:
        if row.ins is not None:
            raise ValueError(f"{ctx}: standalone instrument {row.ins:02X} is not representable")
        return None
    if row.note == NOTE_OFF:
        raise ValueError(f"{ctx}: note-off is not representable in song.json")
    if row.note > NOTE_OFF:
        raise ValueError(f"{ctx}: special Furnace note value {row.note} is not supported")
    if row.ins is None:
        raise ValueError(f"{ctx}: note is missing instrument {expected_ins:02X}")
    if row.ins != expected_ins:
        raise ValueError(
            f"{ctx}: instrument {row.ins:02X} does not match expected {expected_ins:02X} "
            f"for pattern {pattern_index}"
        )
    return note_name_from_number(row.note)


def parse_song_note(name, gamut, track, ctx):
    try:
        parse_note(name, gamut, track)
    except ValueError as exc:
        raise ValueError(f"{ctx}: {exc}") from exc


def get_pattern_rows(patterns, section_name, channel, pattern_index):
    key = (channel, pattern_index)
    if key not in patterns:
        raise ValueError(f"missing pattern for section {section_name!r}, channel {CHANNELS[channel]!r}")
    return patterns[key].rows


def compact_tiled_bars(bars):
    for count in (1, 2, 4):
        unit = bars[:count]
        if unit * (4 // count) == bars:
            return [list(bar) for bar in unit]
    return [list(bar) for bar in bars]


def decode_drum_track(patterns, section_name, pattern_index, channel, expected_note, expected_ins):
    rows = get_pattern_rows(patterns, section_name, channel, pattern_index)
    bars = [[] for _ in range(4)]
    for row_idx, row in enumerate(rows):
        name = checked_note_event(row, section_name, channel, pattern_index, row_idx, expected_ins)
        if name is None:
            continue
        if name != expected_note:
            raise ValueError(
                f"{cell_context(section_name, channel, row_idx)}: expected {expected_note}, got {name}"
            )
        bars[row_idx // 16].append(row_idx % 16)
    return compact_tiled_bars(bars)


def decode_bass_track(patterns, section_name, pattern_index, gamut):
    rows = get_pattern_rows(patterns, section_name, 3, pattern_index)
    note_by_row = {}
    for row_idx, row in enumerate(rows):
        name = checked_note_event(row, section_name, 3, pattern_index, row_idx, INS_BASS)
        if name is None:
            continue
        if row_idx & 1:
            raise ValueError(f"{cell_context(section_name, 3, row_idx)}: bass notes must be on even sixteenths")
        parse_song_note(name, gamut, "bass", cell_context(section_name, 3, row_idx))
        note_by_row[row_idx] = name

    bars = []
    for bar in range(4):
        events = []
        for eighth in range(8):
            row_idx = bar * 16 + eighth * 2
            if row_idx not in note_by_row:
                raise ValueError(f"{cell_context(section_name, 3, row_idx)}: missing required bass note")
            events.append([eighth * 2, note_by_row[row_idx]])
        bars.append(events)
    return bars


def decode_melody_track(patterns, section_name, pattern_index, gamut):
    main_rows = get_pattern_rows(patterns, section_name, 4, pattern_index)
    arp_rows = get_pattern_rows(patterns, section_name, 5, pattern_index)
    bars = [[] for _ in range(4)]

    for row_idx, (main_row, arp_row) in enumerate(zip(main_rows, arp_rows)):
        main_name = checked_note_event(main_row, section_name, 4, pattern_index, row_idx, INS_MELODY)
        arp_name = checked_note_event(arp_row, section_name, 5, pattern_index, row_idx, INS_ARP)
        if main_name is None and arp_name is None:
            continue
        if main_name is None or arp_name is None:
            raise ValueError(
                f"{section_name}/Melody+Arp row {row_idx:02d}: main and arp notes must start together"
            )
        if row_idx & 1:
            raise ValueError(
                f"{section_name}/Melody+Arp row {row_idx:02d}: melody events must be on even sixteenths"
            )
        parse_song_note(main_name, gamut, "melody", cell_context(section_name, 4, row_idx))
        parse_song_note(arp_name, gamut, "melody", cell_context(section_name, 5, row_idx))
        pos = row_idx % 16
        notes = main_name if main_name == arp_name else [main_name, arp_name]
        bars[row_idx // 16].append([pos, notes])

    return bars


def validate_inactive_channels(patterns, section_names):
    for (channel, index), pat in patterns.items():
        if channel < ACTIVE_CHANNELS:
            continue
        section_name = section_names[index] if index < len(section_names) else f"pattern {index}"
        for row_idx, row in enumerate(pat.rows):
            if row.note is not None:
                raise ValueError(f"{section_name}/{CHANNELS[channel]} row {row_idx:02d}: inactive channel has a note")
            if row.ins is not None:
                raise ValueError(
                    f"{section_name}/{CHANNELS[channel]} row {row_idx:02d}: inactive channel has an instrument"
                )


def build_song_from_fur(fur_path, base_path=None):
    version, info, sng, patterns = parse_fur(fur_path)
    validate_import_contract(version, info, sng)

    base_meta = metadata_from_song_json(base_path) if base_path is not None else {}
    meta = extract_song_metadata(sng["comment"])
    if meta is None:
        if base_path is None:
            raise ValueError(
                "Furnace file has no embedded journey-song metadata block "
                "(comment field cleared, or pre-metadata export); "
                "pass --base PATH to a song.json to source gamut/key/description from"
            )
        meta = {}

    gamut = meta.get("gamut") or base_meta.get("gamut")
    validate_gamut(gamut)
    section_names = derive_section_names(patterns)
    if len(set(section_names)) != len(section_names):
        raise ValueError(f"section names must be unique, got {section_names!r}")

    order_indices = sng["orders"][0]
    for index in order_indices:
        if index >= len(section_names):
            raise ValueError(
                f"order table references pattern index {index}, "
                f"but only {len(section_names)} section patterns were found"
            )
    arrangement = [section_names[index] for index in order_indices]

    validate_inactive_channels(patterns, section_names)

    sections = {}
    for pattern_index, section_name in enumerate(section_names):
        sections[section_name] = {
            "tracks": {
                "kick": decode_drum_track(patterns, section_name, pattern_index, 0, "C2", INS_KICK),
                "snare": decode_drum_track(patterns, section_name, pattern_index, 1, "G4", INS_SNARE),
                "hat": decode_drum_track(patterns, section_name, pattern_index, 2, "A7", INS_HAT),
                "bass": decode_bass_track(patterns, section_name, pattern_index, gamut),
                "melody": decode_melody_track(patterns, section_name, pattern_index, gamut),
            }
        }

    song = {
        "description": base_meta.get("description", ""),
        "key": meta.get("key") or base_meta.get("key", ""),
        "gamut": gamut,
        "arrangement": arrangement,
        "sections": sections,
    }
    return song


def inline_json(value):
    return json.dumps(value, separators=(", ", ": "))


def song_json_text(song):
    lines = ["{"]
    lines.append(f'  "description": {inline_json(song["description"])},')
    lines.append(f'  "key": {inline_json(song.get("key", ""))},')
    lines.append(f'  "gamut": {inline_json(song["gamut"])},')
    lines.append(f'  "arrangement": {inline_json(song["arrangement"])},')
    lines.append('  "sections": {')

    section_items = list(song["sections"].items())
    for section_idx, (section_name, section) in enumerate(section_items):
        section_comma = "," if section_idx + 1 < len(section_items) else ""
        tracks = section["tracks"]
        lines.append(f"    {inline_json(section_name)}: {{")
        lines.append('      "tracks": {')
        lines.append(f'        "kick":   {inline_json(tracks["kick"])},')
        lines.append(f'        "snare":  {inline_json(tracks["snare"])},')
        lines.append(f'        "hat":    {inline_json(tracks["hat"])},')

        for track_name in ("bass", "melody"):
            track_comma = "," if track_name == "bass" else ""
            lines.append(f'        "{track_name}": [')
            bars = tracks[track_name]
            for bar_idx, bar in enumerate(bars):
                bar_comma = "," if bar_idx + 1 < len(bars) else ""
                lines.append(f"          {inline_json(bar)}{bar_comma}")
            lines.append(f"        ]{track_comma}")

        lines.append("      }")
        lines.append(f"    }}{section_comma}")

    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def export(args):
    out = Path(args.out)
    data = build_fur(Path(args.song))
    out.write_bytes(data)
    print(f"Wrote {out} ({len(data)} bytes)")
    print(f"Tempo: {song_bpm():.2f} BPM, {PATTERN_ROWS} rows/section, {ORDER_ROWS} orders")
    return 0


def import_cmd(args):
    song = build_song_from_fur(
        Path(args.fur),
        base_path=Path(args.base) if args.base else None,
    )
    out = Path(args.out)
    out.write_text(song_json_text(song))
    print(f"Wrote {out}")
    print(f"Imported {len(song['sections'])} sections, arrangement: {' '.join(song['arrangement'])}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    exp = sub.add_parser("export", help="write a Furnace .fur module")
    exp.add_argument("--song", default=str(DEFAULT_SONG), help="input song.json")
    exp.add_argument("--out", default=str(DEFAULT_OUT), help="output .fur path")
    exp.set_defaults(func=export)

    imp = sub.add_parser("import", help="read the narrow Furnace .fur edit format")
    imp.add_argument("--fur", default=str(DEFAULT_OUT), help="input .fur path")
    imp.add_argument("--out", default=str(DEFAULT_IMPORT_OUT), help="output song.json path")
    imp.add_argument(
        "--base",
        default=str(DEFAULT_SONG),
        help="fallback song.json metadata for older exports without embedded metadata",
    )
    imp.set_defaults(func=import_cmd)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
