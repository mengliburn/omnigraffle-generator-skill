#!/usr/bin/env python3
"""Shared helpers for emitting native OmniGraffle documents.

Facts about the .graffle format that these helpers encode, all established by
drawing the equivalent objects in OmniGraffle and reading the plist back:

  * a .graffle is a ZIP whose data.plist holds a "Sheets" array (one per canvas)
  * shape text is RTF, not plain text
  * GraphicsList is FRONT-to-back: the first entry draws on top
  * a LineGraphic without "LogicalPath" is silently discarded on load
  * arrowheads are a property of the line (Style.stroke.HeadArrow), not a
    separate object
  * connections are Head/Tail {"ID": n}, and the target may be a ShapedGraphic
    *or* another LineGraphic (line-to-line connections are supported)
"""
import pathlib
import plistlib
import zipfile

TEMPLATE = pathlib.Path(__file__).with_name('graffle_template.plist')


def _rtf_escape(s):
    """RTF is cp1252; non-ASCII must use \\uN? escapes or it arrives as mojibake."""
    out = []
    for ch in s:
        if ch in '\\{}':
            out.append('\\' + ch)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            o = ord(ch)
            if o > 0xFFFF:                      # emit a surrogate pair
                o -= 0x10000
                for u in (0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)):
                    out.append(f'\\u{u - 65536 if u > 32767 else u}?')
            else:
                out.append(f'\\u{o - 65536 if o > 32767 else o}?')
    return ''.join(out)


def rtf(text):
    """OmniGraffle stores shape text as RTF."""
    body = '\\\n'.join(_rtf_escape(l) for l in (text or '').split('\n'))
    return (r'{\rtf1\ansi\ansicpg1252\cocoartf2870'
            '\n' r'{\fonttbl\f0\fswiss\fcharset0 Helvetica;}'
            '\n' r'{\colortbl;\red255\green255\blue255;}'
            '\n' r'\pard\qc\partightenfactor0' '\n\n'
            r'\f0\fs24 \cf0 ' + body + '}')


def colour(r, g, b):
    return {'r': f'{r:.5f}', 'g': f'{g:.5f}', 'b': f'{b:.5f}'}


def bounds(x, y, w, h):
    return f'{{{{{x:.2f}, {y:.2f}}}, {{{w:.2f}, {h:.2f}}}}}'


def point(x, y):
    return f'{{{x:.2f}, {y:.2f}}}'


def shape(gid, x, y, w, h, text='', fill=None, stroke=None, shape_name='Rectangle',
          font_size=None):
    style = {'shadow': {'Draws': 'NO'}}
    style['fill'] = {'Color': fill} if fill else {'Draws': 'NO'}
    style['stroke'] = {'Color': stroke, 'Width': 1.0} if stroke else {'Draws': 'NO'}
    g = {'Class': 'ShapedGraphic', 'ID': gid, 'Shape': shape_name,
         'Bounds': bounds(x, y, w, h), 'Style': style,
         'Text': {'Text': rtf(text), 'TextAlongPathGlyphAnchor': 'center'}}
    if font_size:
        g['FontInfo'] = {'Size': font_size}
    return g


def line(gid, pts, stroke=None, width=1.0, arrow=True, dashed=False,
         head_id=None, tail_id=None):
    """pts: [(x, y), ...] in canvas coordinates."""
    p = [point(x, y) for x, y in pts]
    st = {'Color': stroke or colour(0.2, 0.2, 0.2), 'Width': width, 'Legacy': False}
    if arrow:
        st['HeadArrow'] = 'FilledArrow'
        st['TailArrow'] = 'None'
    if dashed:
        st['Pattern'] = 2
    g = {'Class': 'LineGraphic', 'ID': gid, 'Points': p,
         # a LineGraphic without LogicalPath is dropped on load
         'LogicalPath': {'elements': [
             {'element': 'MOVETO' if i == 0 else 'LINETO', 'point': q}
             for i, q in enumerate(p)]},
         'AllowLabelDrop': False,
         'Style': {'fill': {'Draws': 'NO'}, 'shadow': {'Draws': 'NO'}, 'stroke': st}}
    if head_id is not None:
        g['Head'] = {'ID': head_id}
    if tail_id is not None:
        g['Tail'] = {'ID': tail_id}
    return g


def write_graffle(path, graphics, title, canvas_w, canvas_h):
    """graphics must already be ordered FRONT to back."""
    doc = plistlib.loads(TEMPLATE.read_bytes())
    sheet = doc['Sheets'][0]
    sheet['GraphicsList'] = graphics
    sheet['SheetTitle'] = title
    sheet['CanvasSize'] = f'{{{canvas_w:.2f}, {canvas_h:.2f}}}'
    doc['Sheets'] = [sheet]
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('data.plist', plistlib.dumps(doc, fmt=plistlib.FMT_BINARY))
