#!/usr/bin/env python3
"""Merge single-canvas .graffle files into one multi-canvas .graffle.

    merge_graffle.py -o OUT.graffle IN.graffle[=Canvas Title] [...]

A .graffle is a ZIP whose data.plist holds a "Sheets" array, one entry per
canvas, so merging is a plist operation rather than a GUI one. This matters:
OmniGraffle's automation cannot do it. Clipboard copy/paste is ignored, and
`duplicate` fails across documents ("Can't make ... into type reference").

Graphic "ID" values restart near 0 in every file, so each sheet's ids are
offset before merging. Connection references (Head/Tail) are nested dicts that
also carry "ID", so a uniform per-sheet offset keeps them consistent.

Because each input is imported on its own, every diagram already sits at its
natural near-origin coordinates with a correctly auto-sized canvas — no
repositioning is needed.
"""
import argparse
import os
import plistlib
import sys
import zipfile


def offset_ids(o, off):
    if isinstance(o, dict):
        return {k: (v + off if k == 'ID' and isinstance(v, int) and not isinstance(v, bool)
                    else offset_ids(v, off))
                for k, v in o.items()}
    if isinstance(o, list):
        return [offset_ids(v, off) for v in o]
    return o


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('inputs', nargs='+', help='FILE.graffle or FILE.graffle=Canvas Title')
    ap.add_argument('--id-stride', type=int, default=10000,
                    help='id offset applied per sheet (default 10000)')
    a = ap.parse_args()

    specs = []
    for spec in a.inputs:
        path, sep, title = spec.partition('=')
        if not os.path.exists(path):
            sys.exit(f'error: {path} not found')
        specs.append((path, title if sep else os.path.splitext(os.path.basename(path))[0]))

    first = zipfile.ZipFile(specs[0][0])
    raw0 = first.read('data.plist')
    fmt = plistlib.FMT_BINARY if raw0[:8] == b'bplist00' else plistlib.FMT_XML
    doc = plistlib.loads(raw0)

    sheets = []
    for i, (path, title) in enumerate(specs):
        d = plistlib.loads(zipfile.ZipFile(path).read('data.plist'))
        src = d.get('Sheets') or []
        if not src:
            sys.exit(f'error: {path} has no Sheets')
        if len(src) > 1:
            print(f'note: {path} has {len(src)} canvases; taking the first', file=sys.stderr)
        s = offset_ids(src[0], i * a.id_stride)
        s['SheetTitle'] = title
        s['UniqueID'] = i + 1
        s['CanvasSizingMode'] = 1      # flexible canvas, not a fixed sheet
        s['AutoAdjust'] = 1
        s['HPages'] = 1
        s['VPages'] = 1
        sheets.append(s)
        print(f'  canvas {i + 1}: {title!r} '
              f'objects={len(s.get("GraphicsList", []))} size={s.get("CanvasSize")}')

    doc['Sheets'] = sheets
    doc['PageBreaks'] = 'NO'          # don't draw page-break rules
    doc['UseEntirePage'] = False
    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_DEFLATED) as z:
        for item in first.namelist():
            z.writestr(item, plistlib.dumps(doc, fmt=fmt) if item == 'data.plist'
                       else first.read(item))

    chk = plistlib.loads(zipfile.ZipFile(a.out).read('data.plist'))['Sheets']
    titles = [s['SheetTitle'] for s in chk]
    if len(chk) != len(specs):
        print(f'ERROR: wrote {len(chk)} canvases, expected {len(specs)}', file=sys.stderr)
        return 1
    print(f'==> {a.out}: {len(chk)} canvases {titles}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
