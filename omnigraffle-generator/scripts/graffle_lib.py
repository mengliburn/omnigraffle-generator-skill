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
         # bounds are exactly the text width, so forbid wrapping outright
         'Wrap': 'NO',
         'Text': {'Text': rtf(text), 'TextAlongPathGlyphAnchor': 'center',
                  'Pad': 0, 'VerticalPad': 0}}
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
    # Flexible canvas that grows on every side, rather than a fixed sheet.
    # CanvasSizingMode 1 selects "Flexible"; AutoAdjust is a per-side bitmask
    # (top/left/bottom/right), so 15 turns all four sides on. 1 would be top only.
    sheet['CanvasSizingMode'] = 1
    sheet['AutoAdjust'] = 15
    sheet['PrintOnePage'] = False
    sheet['HPages'] = 1
    sheet['VPages'] = 1
    doc['PageBreaks'] = 'NO'          # no page-break rules drawn across the canvas
    doc['UseEntirePage'] = False
    doc['Sheets'] = [sheet]
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('data.plist', plistlib.dumps(doc, fmt=plistlib.FMT_BINARY))


def simplify_points(pts, tol=2.0):
    """Drop interior points that lie (near enough) on the line between their
    neighbours, so a straight connector is two points rather than three.

    Mermaid's routed polyline always carries a midpoint even for a dead-straight
    edge, which shows up in OmniGraffle as a redundant handle. Genuine bends —
    self-loops, dog-legs — exceed the tolerance and are kept.
    """
    if len(pts) <= 2:
        return list(pts)
    out = [pts[0]]
    for prev, cur, nxt in zip(pts, pts[1:], pts[2:]):
        ax, ay = prev
        bx, by = nxt
        px, py = cur
        dx, dy = bx - ax, by - ay
        seg = (dx * dx + dy * dy) ** 0.5
        if seg == 0:
            dist = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        else:
            dist = abs(dy * px - dx * py + bx * ay - by * ax) / seg
        if dist > tol:
            out.append(cur)
    out.append(pts[-1])
    return out


def _inside(p, r, eps=0.01):
    x, y, w, h = r
    return (x - eps) <= p[0] <= (x + w + eps) and (y - eps) <= p[1] <= (y + h + eps)


def _seg_rect_hit(a, b, r):
    """First intersection of segment a->b with rect r, or None (Liang-Barsky)."""
    x, y, w, h = r
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x), (dx, x + w - a[0]), (-dy, a[1] - y), (dy, y + h - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    t = t1 if _inside(a, r) else t0
    if not (0.0 <= t <= 1.0):
        return None
    return (a[0] + dx * t, a[1] + dy * t)


def clip_to_boxes(points, src_rect, tgt_rect):
    """Trim/extend a routed polyline so it starts and ends exactly on the box edges.

    Mermaid routes edges against its own generously padded containers. Once the
    shapes are tightened to their text the original endpoints sit well outside
    them, leaving a visible gap. Anchoring the path at the box centres and then
    clipping to each rect puts the ends back on the borders.
    """
    pts = [tuple(p) for p in points]
    if src_rect:
        c = (src_rect[0] + src_rect[2] / 2, src_rect[1] + src_rect[3] / 2)
        while len(pts) > 1 and _inside(pts[0], src_rect):
            pts.pop(0)
        pts.insert(0, c)
        hit = _seg_rect_hit(pts[0], pts[1], src_rect) if len(pts) > 1 else None
        if hit:
            pts[0] = hit
    if tgt_rect:
        c = (tgt_rect[0] + tgt_rect[2] / 2, tgt_rect[1] + tgt_rect[3] / 2)
        while len(pts) > 1 and _inside(pts[-1], tgt_rect):
            pts.pop()
        pts.append(c)
        hit = _seg_rect_hit(pts[-1], pts[-2], tgt_rect) if len(pts) > 1 else None
        if hit:
            pts[-1] = hit
    return pts


def _half_extent(r, ux, uy):
    return (r[2] / 2) * abs(ux) + (r[3] / 2) * abs(uy)


def compaction_scale(rects, edges, edge_gap=24.0, label_extent=None, pair_margin=16.0):
    """Smallest uniform scale for node *positions* that still leaves room.

    Shapes are tightened to their text but Mermaid positioned them for its own
    padded boxes, so every connector is left far longer than it needs to be.
    Scaling the centres (never the sizes) about the origin keeps the layout's
    relative arrangement exactly while pulling everything together.

    The scale is the tightest that satisfies, for every connected pair, a clear
    run of `edge_gap` (plus that edge's label, if any), and for every pair of
    boxes, non-overlap on at least one axis.
    """
    import math
    label_extent = label_extent or {}
    need = 0.0
    keys = list(rects)

    for e in edges:
        a, b = rects.get(e.get('src')), rects.get(e.get('tgt'))
        if not a or not b or e.get('src') == e.get('tgt'):
            continue
        ca = (a[0] + a[2] / 2, a[1] + a[3] / 2)
        cb = (b[0] + b[2] / 2, b[1] + b[3] / 2)
        dx, dy = cb[0] - ca[0], cb[1] - ca[1]
        d = math.hypot(dx, dy)
        if d < 1e-6:
            continue
        ux, uy = dx / d, dy / d
        clear = edge_gap + label_extent.get(id(e), 0.0)
        need = max(need, (_half_extent(a, ux, uy) + _half_extent(b, ux, uy) + clear) / d)

    for i, ka in enumerate(keys):
        for kb in keys[i + 1:]:
            a, b = rects[ka], rects[kb]
            ca = (a[0] + a[2] / 2, a[1] + a[3] / 2)
            cb = (b[0] + b[2] / 2, b[1] + b[3] / 2)
            dx, dy = abs(cb[0] - ca[0]), abs(cb[1] - ca[1])
            sx = ((a[2] + b[2]) / 2 + pair_margin) / dx if dx > 1e-6 else float('inf')
            sy = ((a[3] + b[3]) / 2 + pair_margin) / dy if dy > 1e-6 else float('inf')
            axis = min(sx, sy)          # separation on either axis suffices
            if axis != float('inf'):
                need = max(need, axis) if axis < 1.0 else need
    return min(1.0, need) if need > 0 else 1.0


def compact_ranks(centres, sizes, edges, label_extent, edge_gap=16.0,
                  node_gap=16.0, tol=8.0):
    """Squeeze the spacing between layout ranks, one gap at a time.

    A single uniform scale is dominated by the worst edge in the diagram, so one
    wide label keeps every other connector long. Dagre lays nodes out in ranks
    along one axis, so instead each gap between consecutive ranks is closed
    independently, down to what the widest label crossing *that* gap needs.

    Returns new centres; cross-axis positions and rank order are untouched.
    """
    if not centres:
        return centres, 'x'
    xs = [c[0] for c in centres.values()]
    ys = [c[1] for c in centres.values()]
    axis = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
    half = {k: (sizes[k][axis] / 2) for k in centres}

    order = sorted(centres, key=lambda k: centres[k][axis])
    ranks, cur = [], [order[0]]
    for k in order[1:]:
        if abs(centres[k][axis] - centres[cur[-1]][axis]) <= tol:
            cur.append(k)
        else:
            ranks.append(cur)
            cur = [k]
    ranks.append(cur)
    if len(ranks) < 2:
        return centres, 'x' if axis == 0 else 'y'

    rank_of = {k: i for i, r in enumerate(ranks) for k in r}
    shift = 0.0
    new = dict(centres)
    for i in range(1, len(ranks)):
        prev_edge = max(new[k][axis] + half[k] for k in ranks[i - 1])
        this_edge = min(centres[k][axis] + shift - half[k] for k in ranks[i])
        need = edge_gap
        for e in edges:
            s, t = e.get('src'), e.get('tgt')
            if s not in rank_of or t not in rank_of or s == t:
                continue
            lo, hi = sorted((rank_of[s], rank_of[t]))
            if lo < i <= hi:                     # this edge crosses the gap
                need = max(need, edge_gap + label_extent.get(id(e), 0.0))
        delta = (prev_edge + need) - this_edge
        shift += delta
        for k in ranks[i]:
            c = centres[k]
            new[k] = (c[0] + shift, c[1]) if axis == 0 else (c[0], c[1] + shift)

    # Close the cross-axis gaps inside each rank too, otherwise diagonal edges
    # stay long even though the flow axis is tight.
    cross = 1 - axis
    for r in ranks:
        if len(r) < 2:
            continue
        seq = sorted(r, key=lambda k: new[k][cross])
        run = 0.0
        for j in range(1, len(seq)):
            prev_hi = new[seq[j - 1]][cross] + sizes[seq[j - 1]][cross] / 2
            cur_lo = new[seq[j]][cross] + run - sizes[seq[j]][cross] / 2
            run += (prev_hi + node_gap) - cur_lo
            c = new[seq[j]]
            new[seq[j]] = (c[0], c[1] + run) if cross == 1 else (c[0] + run, c[1])
    return new, 'x' if axis == 0 else 'y'
