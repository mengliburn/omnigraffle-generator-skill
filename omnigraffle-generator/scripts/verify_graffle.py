#!/usr/bin/env python3
"""Check a generated .graffle against every invariant this skill promises.

    verify_graffle.py FILE.graffle [MMD_DIR]

Reads the plist directly, so it needs no OmniGraffle. Pass the directory of
.mmd sources to also confirm no label text was lost (files are matched to
canvases in sorted order).

Each check corresponds to a defect that actually shipped at some point:

  groups            OmniGraffle's SVG importer nests everything; native output
                    must be flat
  midpoints         Mermaid's routed polyline leaves stray handles on connectors
  endpoint gaps     shapes tightened to their text leave the old endpoints short
                    of the new borders
  hidden lines      an opaque label must not blanket the connector it names
  overlaps          compaction must never push two shapes into each other
  canvas            flexible on all four sides, page-break rules off
  wrap              word wrap left enabled on every text shape
"""
import math
import pathlib
import plistlib
import re
import sys
import zipfile


def nums(s):
    return [float(x) for x in re.findall(r'[-\d.]+', s)]


def dist_to_rect(p, r):
    x, y, w, h = r[:4]
    return math.hypot(max(x - p[0], 0, p[0] - (x + w)), max(y - p[1], 0, p[1] - (y + h)))


def seg_in_rect(a, b, r):
    """Length of segment a-b lying inside rect r (Liang-Barsky)."""
    x, y, w, h = r[:4]
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x), (dx, x + w - a[0]), (-dy, a[1] - y), (dy, y + h - a[1])):
        if p == 0:
            if q < 0:
                return 0.0
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return 0.0
            t0 = max(t0, t)
        else:
            if t < t0:
                return 0.0
            t1 = min(t1, t)
    return max(0.0, t1 - t0) * math.hypot(dx, dy)


def canvas_text(sheet):
    out = []
    for g in sheet['GraphicsList']:
        rtf = g.get('Text', {}).get('Text', '')
        if not rtf:
            continue
        body = rtf.split('\\cf0 ', 1)[-1].rstrip('}')
        body = re.sub(r'\\u(-?\d+)\?', lambda m: chr(int(m.group(1)) % 65536), body)
        body = body.replace('\\\n', '\n').replace('\\{', '{').replace('\\}', '}')
        out.append(re.sub(r'\\[a-zA-Z]+\d*\s?', '', body))
    return re.sub(r'[ \t]+', ' ', '\n'.join(out))


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    doc = plistlib.loads(zipfile.ZipFile(path).read('data.plist'))
    sheets = doc['Sheets']

    groups = midpoints = gaps_bad = hidden = overlaps = nowrap = 0
    lines = shapes = 0
    worst_gap = 0.0
    problems = []

    if doc.get('PageBreaks') != 'NO':
        problems.append(f"PageBreaks={doc.get('PageBreaks')!r} (want 'NO')")

    for sh in sheets:
        gl = sh['GraphicsList']
        if sh.get('CanvasSizingMode') != 1:
            problems.append(f"{sh['SheetTitle']!r}: CanvasSizingMode="
                            f"{sh.get('CanvasSizingMode')} (want 1 = Flexible)")
        if sh.get('AutoAdjust') != 15:
            problems.append(f"{sh['SheetTitle']!r}: AutoAdjust={sh.get('AutoAdjust')} "
                            f"(want 15 = all four sides)")

        rects = {g['ID']: nums(g['Bounds']) for g in gl if g['Class'] == 'ShapedGraphic'}
        labels = [nums(g['Bounds']) for g in gl if g['Class'] == 'ShapedGraphic'
                  and g.get('Style', {}).get('stroke', {}).get('Draws') == 'NO']
        solid = [nums(g['Bounds']) for g in gl if g['Class'] == 'ShapedGraphic'
                 and g.get('Style', {}).get('stroke', {}).get('Draws') != 'NO'
                 and g.get('Shape') != 'Rectangle' or
                 (g['Class'] == 'ShapedGraphic'
                  and g.get('Style', {}).get('fill', {}).get('Color'))]

        for g in gl:
            if 'Graphics' in g:
                groups += 1
            if g['Class'] == 'ShapedGraphic':
                shapes += 1
                if g.get('Wrap') == 'NO':
                    nowrap += 1
                continue
            if g['Class'] != 'LineGraphic':
                continue
            lines += 1
            pts = [nums(p) for p in g['Points']]
            selfloop = ('Head' in g and 'Tail' in g and g['Head']['ID'] == g['Tail']['ID'])
            if len(pts) > 2 and not selfloop:
                midpoints += 1
            if 'Head' in g:
                for end, key in ((pts[0], 'Tail'), (pts[-1], 'Head')):
                    r = rects.get(g[key]['ID'])
                    if r:
                        d = dist_to_rect(end, r)
                        worst_gap = max(worst_gap, d)
                        if d > 0.5:
                            gaps_bad += 1
            L = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                    for i in range(len(pts) - 1))
            cov = max((sum(seg_in_rect(pts[i], pts[i + 1], lr) for i in range(len(pts) - 1))
                       for lr in labels), default=0.0)
            if L > 0 and cov >= L - 1:
                hidden += 1

        boxes = [nums(g['Bounds']) for g in gl if g['Class'] == 'ShapedGraphic'
                 and g.get('Style', {}).get('stroke', {}).get('Draws') != 'NO'
                 and g.get('TextPlacement') is None]
        for i, x in enumerate(boxes):
            for y in boxes[i + 1:]:
                if (x[0] < y[0] + y[2] and y[0] < x[0] + x[2]
                        and x[1] < y[1] + y[3] and y[1] < x[1] + x[3]):
                    overlaps += 1

    print(f'{path.name}: {len(sheets)} canvases, {shapes} shapes, {lines} lines')
    checks = [
        ('nested groups', groups, 0),
        ('connectors with midpoints', midpoints, 0),
        ('endpoints off their box border', gaps_bad, 0),
        ('lines fully hidden by a label', hidden, 0),
        ('overlapping shapes', overlaps, 0),
        ('shapes with word wrap off', nowrap, 0),
    ]
    for name, got, want in checks:
        print(f'  {name:34} {got}   (want {want})')
        if got != want:
            problems.append(f'{name}={got}')
    print(f'  {"worst endpoint gap":34} {worst_gap:.3f}')

    if len(sys.argv) == 3:
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from verify_svg import mermaid_fragments
        mmds = sorted(pathlib.Path(sys.argv[2]).glob('*.mmd'))
        total = missing = 0
        for sh, m in zip(sheets, mmds):
            blob = canvas_text(sh)
            frags = mermaid_fragments(m.read_text())
            miss = [f for f in frags if f not in blob]
            total += len(frags)
            missing += len(miss)
            print(f"  {sh['SheetTitle'][:32]:32} {len(frags) - len(miss)}/{len(frags)} fragments")
            for x in miss[:3]:
                print(f'      MISSING: {x!r}')
        print(f'  {"label fragments":34} {total - missing}/{total}')
        if missing:
            problems.append(f'{missing} missing label fragments')

    if problems:
        print('\nFAIL: ' + '; '.join(problems), file=sys.stderr)
        return 1
    print('\nOK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
