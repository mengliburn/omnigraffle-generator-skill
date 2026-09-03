#!/usr/bin/env python3
"""Combine several OmniGraffle-safe SVGs into one stacked SVG.

    combine_svgs.py -o OUT.svg IN.svg[=Title] [IN.svg[=Title] ...]

Two things make this more than concatenation, both required by OmniGraffle:

  * ID namespacing. Mermaid names every diagram's root "my-svg", so ids and
    url(#...) references collide across files and arrowheads/gradients break.

  * Transform baking. Wrapping a diagram in <g transform="translate(...)"> is
    valid SVG and renders correctly in a browser, but OmniGraffle ignores
    ancestor transforms for some elements, scattering them at raw coordinates.
    Every transform is therefore folded into the coordinates themselves, so
    the output contains no transform attributes outside <defs> at all.

Only translate() is folded; a non-translate transform is left in place and its
subtree is not shifted (Mermaid only emits translate outside <defs>).
"""
import argparse
import html
import re
import sys
import pathlib
import xml.etree.ElementTree as ET

SVG = 'http://www.w3.org/2000/svg'
SKIP = {'defs', 'marker', 'symbol', 'clipPath', 'linearGradient', 'radialGradient',
        'filter', 'pattern', 'style'}
# absolute path command -> (arity, x-indices, y-indices) within each argument group
ARITY = {'M': (2, [0], [1]), 'L': (2, [0], [1]), 'T': (2, [0], [1]),
         'H': (1, [0], []), 'V': (1, [], [0]),
         'C': (6, [0, 2, 4], [1, 3, 5]), 'S': (4, [0, 2], [1, 3]),
         'Q': (4, [0, 2], [1, 3]), 'A': (7, [5], [6]), 'Z': (0, [], [])}
TOKEN = re.compile(r'[A-Za-z]|[-+]?(?:[0-9]*\.[0-9]+|[0-9]+)(?:[eE][-+]?[0-9]+)?')


def fmt(v):
    s = f'{v:.4f}'.rstrip('0').rstrip('.')
    return '0' if s in ('', '-0') else s


def translate_d(d, tx, ty):
    toks = TOKEN.findall(d)
    out, i, cmd, first = [], 0, None, True
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            out.append(t)
            i += 1
            if cmd in 'Zz':
                first = False
            continue
        if cmd is None:
            return d
        up = cmd.upper()
        if up not in ARITY:
            return d
        n, xi, yi = ARITY[up]
        if n == 0:
            return d
        grp = toks[i:i + n]
        if len(grp) < n:
            return d
        vals = [float(v) for v in grp]
        # relative commands need no shift; a leading 'm' is absolute
        if cmd.isupper() or (first and cmd == 'm'):
            for k in xi:
                vals[k] += tx
            for k in yi:
                vals[k] += ty
        out.extend(fmt(v) for v in vals)
        i += n
        first = False
        cmd = 'L' if cmd == 'M' else ('l' if cmd == 'm' else cmd)
    return ' '.join(out)


def parse_translate(t):
    tx = ty = 0.0
    for fn, args in re.findall(r'([a-zA-Z]+)\s*\(([^)]*)\)', t or ''):
        if fn != 'translate':
            return None
        v = [float(x) for x in re.split(r'[,\s]+', args.strip()) if x]
        tx += v[0]
        ty += v[1] if len(v) > 1 else 0.0
    return tx, ty


def shift(el, tx, ty):
    tag = el.tag.split('}')[-1]

    def add(attr, delta):
        if attr in el.attrib:
            try:
                el.set(attr, fmt(float(el.get(attr)) + delta))
            except ValueError:
                pass

    if tag in ('rect', 'image', 'use', 'foreignObject', 'text', 'tspan', 'svg'):
        add('x', tx); add('y', ty)
    elif tag in ('circle', 'ellipse'):
        add('cx', tx); add('cy', ty)
    elif tag == 'line':
        add('x1', tx); add('y1', ty); add('x2', tx); add('y2', ty)
    elif tag == 'path' and 'd' in el.attrib:
        el.set('d', translate_d(el.get('d'), tx, ty))
    elif tag in ('polygon', 'polyline') and 'points' in el.attrib:
        nums = [float(v) for v in re.split(r'[,\s]+', el.get('points').strip()) if v]
        el.set('points', ' '.join(
            fmt(nums[i] + (tx if i % 2 == 0 else ty)) for i in range(len(nums))))


def walk(el, tx, ty):
    if el.tag.split('}')[-1] in SKIP:
        return
    t = el.get('transform')
    if t:
        r = parse_translate(t)
        if r is None:
            for c in list(el):
                walk(c, 0.0, 0.0)
            return
        tx += r[0]
        ty += r[1]
        del el.attrib['transform']
    shift(el, tx, ty)
    for c in list(el):
        walk(c, tx, ty)


def flatten_fragment(inner, tx, ty):
    ET.register_namespace('', SVG)
    ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
    root = ET.fromstring(
        f'<svg xmlns="{SVG}" xmlns:xlink="http://www.w3.org/1999/xlink">{inner}</svg>')
    for c in list(root):
        walk(c, tx, ty)
    body = ''.join(ET.tostring(c, encoding='unicode') for c in root)
    return body.replace('ns0:', '').replace(':ns0', '')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('inputs', nargs='+', help='FILE.svg or FILE.svg=Title')
    ap.add_argument('--gap', type=float, default=110.0)
    ap.add_argument('--title-height', type=float, default=58.0)
    ap.add_argument('--pad', type=float, default=40.0)
    ap.add_argument('--no-titles', action='store_true')
    a = ap.parse_args()

    blocks = []
    for i, spec in enumerate(a.inputs, 1):
        path, _, title = spec.partition('=')
        p = pathlib.Path(path)
        if not p.exists():
            sys.exit(f'error: {p} not found')
        s = p.read_text()
        m = re.match(r'<svg[^>]*>', s)
        if not m:
            sys.exit(f'error: {p} has no <svg> root')
        head = m.group(0)
        vb = re.search(r'viewBox="([^"]+)"', head)
        if not vb:
            sys.exit(f'error: {p} has no viewBox')
        minx, miny, w, h = (float(x) for x in vb.group(1).split())
        inner = s[len(head):].rsplit('</svg>', 1)[0]

        pref = f'd{i:02d}-'
        for old in sorted(set(re.findall(r'\sid="([^"]+)"', inner)), key=len, reverse=True):
            new = pref + old
            inner = (inner.replace(f'id="{old}"', f'id="{new}"')
                          .replace(f'url(#{old})', f'url(#{new})')
                          .replace(f'href="#{old}"', f'href="#{new}"'))
        blocks.append(dict(name=p.stem, title=title or p.stem, inner=inner,
                           minx=minx, miny=miny, w=w, h=h))

    th = 0.0 if a.no_titles else a.title_height
    maxw = max(b['w'] for b in blocks)
    total_w = maxw + 2 * a.pad
    y = a.pad
    parts = []
    for b in blocks:
        x = a.pad + (maxw - b['w']) / 2
        baked = flatten_fragment(b['inner'], x - b['minx'], y + th - b['miny'])
        title = ''
        if not a.no_titles:
            title = (f'<text x="{x:.2f}" y="{y + th - 18:.2f}" text-anchor="start" '
                     f'style="font-family:Helvetica,Arial,sans-serif;font-size:30px;'
                     f'font-weight:700;fill:rgb(30,30,40);text-anchor:start;'
                     f'dominant-baseline:auto">{html.escape(b["title"])}</text>')
        # title lives inside the group so each diagram is a self-contained unit
        parts.append(f'<g id="{b["name"]}">{title}{baked}</g>')
        y += th + b['h'] + a.gap
    total_h = y - a.gap + a.pad

    out = (f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{total_w:.2f}" height="{total_h:.2f}" '
           f'viewBox="0 0 {total_w:.2f} {total_h:.2f}">'
           f'<rect x="0" y="0" width="{total_w:.2f}" height="{total_h:.2f}" '
           f'style="fill:rgb(255,255,255)"/>' + ''.join(parts) + '</svg>')
    pathlib.Path(a.out).write_text(out)

    ids = re.findall(r'\sid="([^"]+)"', out)
    refs = set(re.findall(r'url\(#([^)]+)\)', out))
    body = re.sub(r'<defs.*?</defs>', '', out, flags=re.S)
    dupes = len(ids) - len(set(ids))
    unresolved = sorted(refs - set(ids))
    leftover = len(re.findall(r'transform="', body))
    print(f'{a.out}: {total_w:.0f}x{total_h:.0f}, {len(blocks)} diagrams, '
          f'dup_ids={dupes}, unresolved_refs={len(unresolved)}, leftover_transforms={leftover}')
    if dupes or unresolved or leftover:
        print(f'WARNING: dupes={dupes} unresolved={unresolved[:5]} transforms={leftover}',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
