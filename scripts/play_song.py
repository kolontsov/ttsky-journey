#!/usr/bin/env python3
# /// script
# dependencies = ["numpy", "sounddevice"]
# ///
"""Play / export the song defined in scripts/data/song.json.

Usage:
    uv run scripts/play_song.py                # live playback (~57s)
    uv run scripts/play_song.py --wav out.wav  # export WAV instead
    uv run scripts/play_song.py --solo bass    # start with one or more channels solo'd
    uv run scripts/play_song.py --bars 4       # render only the first 4 bars
    uv run scripts/play_song.py --gain bass=1 melody=2   # per-channel volume
        # gain N = right-shift by N (0=full, 1=−6 dB, 2=−12 dB).
        # Channels: kick, bass, melody, noise. Preview-only (not in HW).

During live playback (matches `make sim` keys):
    1 2 3 4    toggle kick / noise / bass / melody
    0          un-mute all
    q / Ctrl+C quit
"""

import argparse, select, struct, sys, termios, time, tty
from pathlib import Path

from engine_song import (
    Engine, load_song, render, SAMPLE_HZ, SONG_TICK_SAMPLES, BAR_TICKS,
)

BARS_PER_SECTION = 4
SAMPLES_PER_BAR = BAR_TICKS * SONG_TICK_SAMPLES
DEFAULT_SONG = Path(__file__).parent / 'data' / 'song.json'

# Match `make sim` (tb_top.cpp) ordering. Key '2' toggles hat+snare together
# (shared HW noise channel).
CHANNEL_KEYS = {
    '1': ('kick',),
    '2': ('hat', 'snare'),
    '3': ('bass',),
    '4': ('melody',),
}
DISPLAY_NAMES = {'1': 'kick', '2': 'noise', '3': 'bass', '4': 'melody'}


def bar_schedule(song, n_bars):
    arrangement = song['arrangement']
    out = []
    for b in range(n_bars):
        sec_idx = b // BARS_PER_SECTION
        bar_in_sec = b % BARS_PER_SECTION
        name = arrangement[sec_idx] if sec_idx < len(arrangement) else '?'
        t = b * SAMPLES_PER_BAR / SAMPLE_HZ
        out.append((t, b, sec_idx, bar_in_sec, name))
    return out


def fmt_bar(t, song_bar, sec_idx, bar_in_sec, name):
    return (f"  [{t:6.2f}s] bar {song_bar + 1:2d}/32  "
            f"section {sec_idx} {name!r:<6}  bar {bar_in_sec + 1}/{BARS_PER_SECTION}")


def fmt_channels(eng):
    # UPPER = on, lower = muted (matches `make sim` status print).
    out = []
    for key in ('1', '2', '3', '4'):
        name = DISPLAY_NAMES[key]
        on = any(ch in eng.active for ch in CHANNEL_KEYS[key])
        out.append(name.upper() if on else name)
    return ' '.join(out)


def write_wav(path, samples, rate=SAMPLE_HZ):
    data = struct.pack(f'<{len(samples)}h', *samples)
    with open(path, 'wb') as f:
        f.write(b'RIFF')
        f.write(struct.pack('<I', 36 + len(data)))
        f.write(b'WAVEfmt ')
        f.write(struct.pack('<IHHIIHH', 16, 1, 1, rate, rate * 2, 2, 16))
        f.write(b'data')
        f.write(struct.pack('<I', len(data)))
        f.write(data)


def live_play(song, ticks, schedule, solo, gains):
    import numpy as np
    import sounddevice as sd

    eng = Engine(song, solo=solo, gains=gains)
    eng._run_triggers()   # see engine_song.render() for the reset trick

    state = {'tick': 0, 'in_tick': 0, 'done': False}
    scale = 1.0 / 32768.0

    def callback(outdata, frames, _time_info, _status):
        buf = [0] * frames
        for i in range(frames):
            if state['done']:
                break
            buf[i] = eng.sample()
            state['in_tick'] += 1
            if state['in_tick'] >= SONG_TICK_SAMPLES:
                state['in_tick'] = 0
                eng.song_tick()
                state['tick'] += 1
                if state['tick'] >= ticks:
                    state['done'] = True
        outdata[:, 0] = np.asarray(buf, dtype=np.float32) * scale
        if state['done']:
            raise sd.CallbackStop

    print("Keys: 1=kick 2=noise 3=bass 4=melody  0=all  q=quit")
    print(f"  {fmt_channels(eng)}")

    fd = sys.stdin.fileno()
    old_term = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        with sd.OutputStream(samplerate=SAMPLE_HZ, channels=1,
                             dtype='float32', callback=callback):
            start = time.monotonic()
            sched_iter = iter(schedule)
            next_bar = next(sched_iter, None)
            while not state['done']:
                now = time.monotonic() - start
                while next_bar and now >= next_bar[0]:
                    print(fmt_bar(*next_bar), flush=True)
                    next_bar = next(sched_iter, None)
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    key = sys.stdin.read(1)
                    if key in ('q', '\x03', '\x1b'):
                        break
                    if key == '0':
                        eng.active = set(Engine.ALL)
                        print(f"  {fmt_channels(eng)}", flush=True)
                    elif key in CHANNEL_KEYS:
                        chs = CHANNEL_KEYS[key]
                        any_on = any(ch in eng.active for ch in chs)
                        for ch in chs:
                            if any_on:
                                eng.active.discard(ch)
                            else:
                                eng.active.add(ch)
                        print(f"  {fmt_channels(eng)}", flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_term)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--song', default=str(DEFAULT_SONG), help='song JSON path')
    ap.add_argument('--wav',  metavar='FILE', help='write WAV instead of playing')
    ap.add_argument('--solo', nargs='+', choices=list(Engine.ALL),
                    help='start with one or more channels solo\'d')
    ap.add_argument('--bars', type=int, default=32,
                    help='bars to render (default 32 = full song)')
    ap.add_argument('--gain', nargs='+', metavar='CH=N', default=[],
                    help='per-channel right-shift (kick/bass/melody/noise = 0/1/2)')
    ap.add_argument('--no-play', action='store_true',
                    help='print bar schedule, no audio')
    args = ap.parse_args()

    gains = {}
    for spec in args.gain:
        if '=' not in spec:
            ap.error(f"--gain expects CH=N, got {spec!r}")
        ch, n = spec.split('=', 1)
        if ch not in Engine.GAIN_CHANNELS:
            ap.error(f"--gain channel must be one of {Engine.GAIN_CHANNELS}, got {ch!r}")
        if not n.isdigit() or int(n) > 7:
            ap.error(f"--gain N must be a small non-negative int, got {n!r}")
        gains[ch] = int(n)

    song = load_song(args.song)
    bars = min(args.bars, 32)
    ticks = bars * BAR_TICKS
    dur = ticks * SONG_TICK_SAMPLES / SAMPLE_HZ
    print(f"Song: {bars} bars = {ticks} ticks = {dur:.1f}s @ {SAMPLE_HZ} Hz")
    eff_gains = {**Engine.DEFAULT_GAINS, **gains}
    print(f"Gains: {eff_gains}")

    schedule = bar_schedule(song, bars)

    if args.wav:
        samples = render(song, ticks, solo=args.solo, gains=gains)
        write_wav(args.wav, samples)
        print(f"Wrote {args.wav} ({len(samples)} samples)")
        for row in schedule:
            print(fmt_bar(*row))
        return 0

    if args.no_play:
        for row in schedule:
            print(fmt_bar(*row))
        return 0

    print(f"Playing {dur:.1f}s...")
    try:
        live_play(song, ticks, schedule, solo=args.solo, gains=gains)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
