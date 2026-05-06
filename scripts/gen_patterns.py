#!/usr/bin/env python3
"""Emit src/synth_patterns.sv from scripts/data/song.json.

engine_song.load_song() parses/validates the song; this script translates
the compiled variant tables into combinational SV (Quine-McCluskey + cube
sharing for the drum/melody decoders).
"""

import argparse, sys
from pathlib import Path

from engine_song import load_song, NOTE_INC_A3
from sv_template import render_sv


def _minimize_sop(ones, n_vars, dont_cares=()):
    # Quine-McCluskey for small boolean functions.
    # Returns list of (value, care): care bit=1 means var appears, polarity
    # from value. [] = const 0; [(0,0)] = const 1.
    ones = frozenset(ones)
    dcs = frozenset(dont_cares) - ones
    allowed = ones | dcs
    N = 1 << n_vars
    if not ones:
        return []
    if allowed == frozenset(range(N)):
        return [(0, 0)]

    # Every cube (value, care) whose coverage is a subset of `allowed`.
    cubes = {}           # (canon_val, care) -> allowed_minterms covered
    ones_cov = {}        # same key -> ones covered
    for care in range(N):
        seen = set()
        for value in range(N):
            canon = value & care
            if canon in seen:
                continue
            seen.add(canon)
            covered = frozenset(x for x in range(N) if (x & care) == canon)
            if covered.issubset(allowed):
                cubes[(canon, care)] = covered
                ones_cov[(canon, care)] = covered & ones

    # Prime implicants: cube whose allowed-coverage is not a strict subset
    # of another cube's allowed-coverage.
    items = sorted(cubes.items(), key=lambda it: -len(it[1]))
    primes = []
    for key, cov in items:
        if not any(cov < pcov for _, pcov in primes):
            primes.append((key, cov))

    # Greedy set-cover on the ones only (DCs don't need covering).
    uncovered = set(ones)
    chosen = []
    while uncovered:
        key, _ = max(primes, key=lambda p: len(ones_cov[p[0]] & uncovered))
        chosen.append(key)
        uncovered -= ones_cov[key]
    return chosen


def _cube_to_sv(cube, var_exprs):
    val, care = cube
    if care == 0:
        return "1'b1"
    parts = []
    for i, name in enumerate(var_exprs):
        if (care >> i) & 1:
            parts.append(name if (val >> i) & 1 else f'~{name}')
    return ' & '.join(parts)


def _cubes_to_sv(cubes, var_exprs):
    if not cubes:
        return "1'b0"
    if cubes == [(0, 0)]:
        return "1'b1"
    terms = [_cube_to_sv(c, var_exprs) for c in cubes]
    return ' | '.join(f'({t})' if len(cubes) > 1 and '&' in t else t
                      for t in terms)


def _try_reduction(cubes, bus_name, n_vars):
    # Cubes that are single positive literals on contiguous bits → reduction-OR.
    bits = []
    for val, care in cubes:
        if bin(care).count('1') != 1:
            return None
        b = care.bit_length() - 1
        if not ((val >> b) & 1):
            return None
        bits.append(b)
    bits = sorted(set(bits))
    if len(bits) < 2 or bits != list(range(bits[0], bits[-1] + 1)):
        return None
    return f'|{bus_name}[{bits[-1]}:{bits[0]}]'


def _emit_sop_factored(cubes, var_exprs, bus_name='sixt_in_b'):
    # Factor most-shared literal recursively; recognizes contiguous reduction-OR.
    if not cubes:
        return "1'b0"
    if cubes == [(0, 0)]:
        return "1'b1"
    if len(cubes) == 1:
        return _cube_to_sv(cubes[0], var_exprs)

    red = _try_reduction(cubes, bus_name, len(var_exprs))
    if red is not None:
        return red

    # Literal → count across cubes that actually reference it.
    n_vars = len(var_exprs)
    counts = {}
    for val, care in cubes:
        for b in range(n_vars):
            if (care >> b) & 1:
                lit = (b, (val >> b) & 1)
                counts[lit] = counts.get(lit, 0) + 1
    best_lit, best_cnt = (max(counts.items(), key=lambda kv: kv[1])
                          if counts else (None, 0))
    if best_cnt < 2:
        terms = [_cube_to_sv(c, var_exprs) for c in cubes]
        return ' | '.join(f'({t})' if '&' in t else t for t in terms)

    b, pol = best_lit
    factored, rest = [], []
    for val, care in cubes:
        if (care >> b) & 1 and ((val >> b) & 1) == pol:
            factored.append((val & ~(1 << b), care & ~(1 << b)))
        else:
            rest.append((val, care))
    lit_sv = var_exprs[b] if pol else f'~{var_exprs[b]}'
    inner = _emit_sop_factored(factored, var_exprs, bus_name)
    if any(op in inner for op in ('|', '&')) and not inner.startswith('|'):
        factored_expr = f'{lit_sv} & ({inner})'
    else:
        factored_expr = f'{lit_sv} & {inner}'
    if not rest:
        return factored_expr
    rest_expr = _emit_sop_factored(rest, var_exprs, bus_name)
    return f'{factored_expr} | {rest_expr}'


def _cube_name(cube, n_vars):
    val, care = cube
    mins = sorted(x for x in range(1 << n_vars) if (x & care) == (val & care))
    return 'sixt_' + '_'.join(str(m) for m in mins)

ROOT    = Path(__file__).resolve().parent.parent
SONG    = ROOT / 'scripts' / 'data' / 'song.json'
OUT     = ROOT / 'src'     / 'synth_patterns.sv'


def build_context(song):
    arrangement       = song['arrangement']
    section_variants  = song['section_variants']
    n_variants        = song['n_variants']
    variants          = song['variants']
    gamut             = song['gamut']

    # HW width guards: 7-bit note_inc7 / 8-bit bass_inc baked into ports.
    for i, raw in enumerate(NOTE_INC_A3):
        scaled = raw >> 3
        if scaled >= 128:
            raise ValueError(
                f"note_inc7 overflow: NOTE_INC_A3[{i}]={raw:#x} >> 3 = {scaled} "
                f"doesn't fit in synth_melody's 7-bit inc lookup. Widen the lookup or lower the note.")
        if (scaled << 1) >= 256:
            raise ValueError(
                f"bass_inc overflow: NOTE_INC_A3[{i}]={raw:#x} >> 3 << 1 = {scaled<<1} "
                f"doesn't fit in 8-bit bass_inc port. Widen the port or lower the note.")

    # ------------------------------------------------------------- note_inc
    note_inc_lines = [
        f"            3'd{i}: note_inc7 = 7'h{(NOTE_INC_A3[i] >> 3):02X};  // {name}"
        for i, name in enumerate(gamut)
    ]

    bits = max(1, (n_variants - 1).bit_length())
    vbits = bits
    variant_lines = [
        f"        3'd{i}: variant = {bits}'d{v};"
        for i, v in enumerate(section_variants)
    ]

    # Drums: per-(variant, track) truth table on sixt_in_b → minimized SOP,
    # with cubes shared across ≥2 (variant, track) pairs hoisted to wires.
    for track in ('kick', 'snare', 'hat'):
        if not all(variants[v][track][b] == variants[v][track][0]
                   for v in range(n_variants) for b in range(4)):
            raise ValueError(f"{track} rows must be section-cycle-only for "
                             "the shared drum decoder")

    def _mask_for(track, v):
        if track == 'kick':
            return variants[v]['kick'][0]
        if track == 'noise_trig':
            return [variants[v]['hat'][0][i] or variants[v]['snare'][0][i]
                    for i in range(16)]
        if track == 'noise_mode':
            return variants[v]['snare'][0]
        raise ValueError(track)

    def _ones(mask16):
        return [i for i in range(16) if mask16[i]]

    tracks = ('kick', 'noise_trig', 'noise_mode')
    sop = {(t, v): _minimize_sop(_ones(_mask_for(t, v)), 4)
           for t in tracks for v in range(n_variants)}

    # Hoist shared cubes only if ≥3 literals — 1-2 lit cubes factor better
    # in-expression (e.g. a&b|a&c|a&d → a&|b[3:1]) than as named helpers.
    sixt_bits = ['sixt_in_b[0]', 'sixt_in_b[1]', 'sixt_in_b[2]', 'sixt_in_b[3]']
    cube_uses = {}
    for cubes in sop.values():
        for c in cubes:
            cube_uses[c] = cube_uses.get(c, 0) + 1
    helpers = {c: _cube_name(c, 4) for c, n in cube_uses.items()
               if n >= 2 and bin(c[1]).count('1') >= 3}

    drum_helper_lines = [
        f"    wire {name} = {_cubes_to_sv([cube], sixt_bits)};"
        for cube, name in sorted(helpers.items(),
                                 key=lambda kv: (bin(kv[0][1]).count('1'), kv[0]))
    ]

    def _expr_for(cubes):
        if not cubes:
            return "1'b0"
        if cubes == [(0, 0)]:
            return "1'b1"
        inline_cubes = [c for c in cubes if c not in helpers]
        helper_refs = [helpers[c] for c in cubes if c in helpers]
        if not inline_cubes:
            return helper_refs[0] if len(helper_refs) == 1 else ' | '.join(helper_refs)
        inline_expr = _emit_sop_factored(inline_cubes, sixt_bits)
        if not helper_refs:
            return inline_expr
        if '|' in inline_expr and not inline_expr.startswith('|'):
            inline_expr = f'({inline_expr})'
        return ' | '.join(helper_refs + [inline_expr])

    sig_names = {'kick': 'drum_kick', 'noise_trig': 'drum_noise',
                 'noise_mode': 'drum_snare'}
    drum_case_lines = []
    # Last variant goes in `default` so unreachable higher codes collapse with it.
    for v in range(n_variants):
        tag = f"{vbits}'d{v}:" if v < n_variants - 1 else 'default:'
        drum_case_lines.append(f'            {tag} begin')
        for t in tracks:
            drum_case_lines.append(
                f'                {sig_names[t]:<10} = {_expr_for(sop[(t, v)])};'
            )
        drum_case_lines.append('            end')

    bass_roots = [variants[0]['bass'][b][0][0] for b in range(4)]
    for v in range(n_variants):
        for b in range(4):
            if variants[v]['bass'][b][0] != (bass_roots[b], 0):
                raise ValueError("bass compact decode expects every bar to start on the chord root")

    bass_root_lines = [
        f"        2'd{b}: bass_root = 3'd{root};" for b, root in enumerate(bass_roots)
    ]

    bass_key_w = vbits + 3
    bass_offset_lines = []
    for v in range(n_variants):
        for e in range(8):
            notes = [variants[v]['bass'][b][e] for b in range(4)]
            offsets = [((idx - bass_roots[b]) & 7) for b, (idx, _oct) in enumerate(notes)]
            oct_bits = [oct_bit for _idx, oct_bit in notes]
            if len(set(oct_bits)) != 1:
                raise ValueError("bass compact decode expects octave pattern to be bar-invariant")
            oct_bit = oct_bits[0]
            if len(set(offsets)) == 1:
                offset = offsets[0]
                if offset == 0 and oct_bit == 0:
                    continue
                bass_offset_lines.append(
                    f"            {bass_key_w}'b{v:0{vbits}b}_{e:03b}: "
                    f"begin bass_offset = 3'd{offset}; bass_oct_bit = 1'b{oct_bit}; end"
                )
            else:
                bass_offset_lines.append(
                    f"            {bass_key_w}'b{v:0{vbits}b}_{e:03b}: begin"
                )
                bass_offset_lines.append(f"                bass_oct_bit = 1'b{oct_bit};")
                bass_offset_lines.append('                case (bar_in_s)')
                for b, offset in enumerate(offsets):
                    bass_offset_lines.append(
                        f"                    2'd{b}: bass_offset = 3'd{offset};"
                    )
                bass_offset_lines.append("                    default: bass_offset = 3'd0;")
                bass_offset_lines.append('                endcase')
                bass_offset_lines.append('            end')

    # Melody: per-bit SOP over {variant, bar_in_s, eighth_in_b}. Invalid
    # positions are don't-cares (except `valid`). Storing cross_oct=main^arp
    # rather than arp_oct directly gives a sparser function (~15% vs ~45% ones).
    mel_key_w = vbits + 2 + 3
    mel_var_exprs = [f'mel_key[{i}]' for i in range(mel_key_w)]

    for v in range(n_variants):
        for b in range(4):
            for e in range(8):
                if variants[v]['melody'][b][2 * e + 1] is not None:
                    raise ValueError(
                        "melody event on odd sixteenth cannot use compact eighth decode")

    def _key(v, b, e):
        return (v << 5) | (b << 3) | e

    valid_set = set()
    main_idx_bits = [set() for _ in range(3)]
    main_oct_set  = set()
    arp_idx_bits  = [set() for _ in range(3)]
    cross_oct_set = set()
    for v in range(n_variants):
        for b in range(4):
            for e in range(8):
                ev = variants[v]['melody'][b][2 * e]
                if ev is None:
                    continue
                mi, mo, ai, ao = ev
                k = _key(v, b, e)
                valid_set.add(k)
                for i in range(3):
                    if (mi >> i) & 1: main_idx_bits[i].add(k)
                    if (ai >> i) & 1: arp_idx_bits[i].add(k)
                if mo: main_oct_set.add(k)
                if mo ^ ao: cross_oct_set.add(k)
    invalid_set = set(range(1 << mel_key_w)) - valid_set

    melody_lines = []
    def _emit_bit(name, ones, dcs):
        cubes = _minimize_sop(ones, mel_key_w, dont_cares=dcs)
        expr = _emit_sop_factored(cubes, mel_var_exprs, bus_name='mel_key')
        melody_lines.append(f'    wire {name} = {expr};')

    _emit_bit('mel_ev_valid', valid_set, set())
    for i in range(3):
        _emit_bit(f'mel_ev_main_idx_{i}', main_idx_bits[i], invalid_set)
    _emit_bit('mel_ev_main_oct_i', main_oct_set, invalid_set)
    for i in range(3):
        _emit_bit(f'mel_ev_arp_idx_{i}', arp_idx_bits[i], invalid_set)
    _emit_bit('mel_ev_cross_oct', cross_oct_set, invalid_set)

    return {
        'n_variants':         n_variants,
        'vbits':              vbits,
        'arrangement_str':    ' '.join(arrangement),
        'mel_key_w':          mel_key_w,
        'bass_root_default':  bass_roots[0],
        'note_inc_cases':     '\n'.join(note_inc_lines),
        'variant_cases':      '\n'.join(variant_lines),
        'drum_helpers':       '\n'.join(drum_helper_lines),
        'drum_variant_cases': '\n'.join(drum_case_lines),
        'bass_root_cases':    '\n'.join(bass_root_lines),
        'bass_offset_cases':  '\n'.join(bass_offset_lines),
        'melody_wires':       '\n'.join(melody_lines),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--song',     default=str(SONG))
    ap.add_argument('--out',      default=str(OUT))
    ap.add_argument('--dry-run',  action='store_true', help='print to stdout')
    args = ap.parse_args()

    song = load_song(args.song)
    ctx  = build_context(song)

    if args.dry_run:
        from sv_template import _ENV
        sys.stdout.write(_ENV.get_template('src/synth_patterns.sv.j2').render(**ctx))
        return 0

    text = render_sv('src/synth_patterns.sv.j2', args.out, **ctx)
    n = text.count('\n')
    print(f"Wrote {args.out} ({n} lines)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
