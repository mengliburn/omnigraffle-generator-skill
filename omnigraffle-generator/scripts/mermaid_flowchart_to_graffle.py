#!/usr/bin/env python3
"""PROTOTYPE: build a NATIVE OmniGraffle document from a Mermaid flowchart SVG.

    extract_flowchart_layout.mjs IN.svg > layout.json
    mermaid_flowchart_to_graffle.py layout.json OUT.graffle [--title "Canvas name"]

Unlike the SVG-import path, this emits OmniGraffle's own object model directly:

  * every node becomes one flat ShapedGraphic  -> no groups at all
  * every edge becomes one LineGraphic whose arrowhead is a *property*
    (Style.stroke.HeadArrow) -> line and arrow are a single object
  * each LineGraphic carries Head/Tail {ID: n} -> lines are really connected to
    the boxes, so they re-route when a box is moved

Input must be a Mermaid *flowchart* rendered with htmlLabels:false, before
og_fix_svg.mjs runs (this reads Mermaid's semantic markup, which that step
intentionally destroys).
"""
import argparse
import base64
import html
import json
import pathlib
import plistlib
import re
import sys
import zipfile

from graffle_lib import (WRAP_SLACK, clip_to_boxes, colour, compact_ranks,
                         compaction_scale, rtf, simplify_points)

TEMPLATE = pathlib.Path(__file__).with_name('graffle_template.plist')
SHAPES = {'rect': 'Rectangle', 'path': 'Cylinder', 'polygon': 'Rectangle',
          'circle': 'Circle', 'ellipse': 'Circle'}


def strip_tags(frag):
    # tspan rows are separate lines in the rendered label
    frag = re.sub(r'</tspan>\s*<tspan[^>]*class="text-outer-tspan[^"]*"', '\n<tspan', frag)
    txt = re.sub(r'<[^>]+>', '', frag)
    return re.sub(r'[ \t]+', ' ', html.unescape(txt)).strip()


def parse_nodes(svg):
    """id -> {key, x, y, w, h, label}"""
    nodes = {}
    for m in re.finditer(r'<g class="node[^"]*"[^>]*id="([^"]+)"[^>]*'
                         r'transform="translate\(([-\d.eE]+),\s*([-\d.eE]+)\)"[^>]*>', svg):
        gid, cx, cy = m.group(1), float(m.group(2)), float(m.group(3))
        # slice this node's subtree: up to the next node group or end of the nodes layer
        rest = svg[m.end():]
        nxt = re.search(r'<g class="node', rest)
        frag = rest[:nxt.start()] if nxt else rest
        r = re.search(r'<rect[^>]*class="[^"]*label-container[^"]*"[^>]*>', frag)
        if not r:
            continue
        def attr(name, default=0.0):
            a = re.search(rf'\s{name}="([-\d.eE]+)"', r.group(0))
            return float(a.group(1)) if a else default
        x, y, w, h = attr('x'), attr('y'), attr('width'), attr('height')
        texts = re.findall(r'<text[^>]*>(.*?)</text>', frag, flags=re.S)
        label = '\n'.join(filter(None, (strip_tags(t) for t in texts)))
        key = re.sub(r'^.*?flowchart-', '', gid)
        key = re.sub(r'-\d+$', '', key)
        nodes[key] = dict(key=key, x=cx + x, y=cy + y, w=w, h=h, label=label)
    return nodes


def split_edge_id(data_id, keys):
    m = re.match(r'^L_(.*)_\d+$', data_id)
    if not m:
        return None, None
    mid = m.group(1)
    # node keys may themselves contain underscores; match against known keys
    cands = [(s, mid[len(s) + 1:]) for s in keys
             if mid.startswith(s + '_') and mid[len(s) + 1:] in keys]
    if len(cands) == 1:
        return cands[0]
    if cands:
        cands.sort(key=lambda p: -len(p[0]))
        return cands[0]
    return None, None


def parse_edges(svg, keys):
    edges = []
    for m in re.finditer(r'<path[^>]*class="([^"]*flowchart-link[^"]*)"[^>]*>', svg):
        tag, cls = m.group(0), m.group(1)
        did = re.search(r'data-id="([^"]+)"', tag)
        pts = re.search(r'data-points="([^"]+)"', tag)
        if not (did and pts):
            continue
        try:
            pl = json.loads(base64.b64decode(pts.group(1)))
        except Exception:
            continue
        src, tgt = split_edge_id(did.group(1), keys)
        edges.append(dict(src=src, tgt=tgt,
                          points=[(float(p['x']), float(p['y'])) for p in pl],
                          dashed='edge-pattern-dotted' in cls))
    return edges


def parse_edge_labels(svg):
    out = []
    for m in re.finditer(r'<g class="edgeLabel"[^>]*transform="translate\(([-\d.eE]+),\s*'
                         r'([-\d.eE]+)\)"[^>]*>(.*?)</g></g></g>', svg, flags=re.S):
        x, y, frag = float(m.group(1)), float(m.group(2)), m.group(3)
        texts = re.findall(r'<text[^>]*>(.*?)</text>', frag, flags=re.S)
        label = '\n'.join(filter(None, (strip_tags(t) for t in texts)))
        if label:
            out.append(dict(x=x, y=y, label=label))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('layout', help='layout.json from extract_flowchart_layout.mjs')
    ap.add_argument('out')
    ap.add_argument('--title', default=None)
    ap.add_argument('--pad-x', type=float, default=0.0,
                    help='horizontal padding around node text (default 0 = tight)')
    ap.add_argument('--pad-y', type=float, default=0.0,
                    help='vertical padding around node text (default 0 = tight)')
    ap.add_argument('--edge-gap', type=float, default=16.0,
                    help='clear run to keep on each connector beyond its label (default 16)')
    ap.add_argument('--node-gap', type=float, default=16.0,
                    help='gap between neighbouring nodes within a rank (default 16)')
    ap.add_argument('--keep-routing', action='store_true',
                    help='keep Mermaid\'s routed polylines instead of straight connectors')
    ap.add_argument('--no-compact', action='store_true',
                    help='keep Mermaid spacing instead of pulling the tightened shapes together')
    ap.add_argument('--simplify-tol', type=float, default=6.0,
                    help='drop interior line points within this distance of the '
                         'straight chord (default 6; larger straightens more)')
    a = ap.parse_args()

    layout = json.loads(pathlib.Path(a.layout).read_text())
    minx, miny, vw, vh = layout['viewBox']
    nodes = {n['key']: n for n in layout['nodes']}
    if not nodes:
        sys.exit('error: no flowchart nodes in layout')
    keys = set(nodes)
    edges = []
    for e in layout['edges']:
        src, tgt = split_edge_id(e['id'] or '', keys)
        edges.append(dict(src=src, tgt=tgt,
                          points=[(float(x), float(y)) for x, y in e['points']],
                          dashed=bool(e['dashed'])))
    elabels = [dict(x=l['x'] + l['w'] / 2, y=l['y'] + l['h'] / 2,
                    w=l['w'], h=l['h'], label=l['label'],
                    textW=l.get('textW'), textH=l.get('textH'))
               for l in layout['edgeLabels']]

    # --- tighten shapes, then pull the layout together -----------------------
    import math
    sizes, centres = {}, {}
    for key, n in nodes.items():
        w, h = n['w'], n['h']
        # Mermaid pads its containers generously. Shrink plain rectangles to their
        # measured text; leave cylinders/stadiums alone, their caps need the room.
        if n.get('shape') == 'rect' and n.get('textW'):
            w = min(w, n['textW'] + a.pad_x + WRAP_SLACK)
            h = min(h, n['textH'] + a.pad_y)
        sizes[key] = (w, h)
        centres[key] = (n['x'] + n['w'] / 2, n['y'] + n['h'] / 2)

    # tie each edge label to the edge it belongs to, so it can ride along
    label_of = {}
    for l in elabels:
        best = None
        for e in edges:
            if e['src'] not in centres or e['tgt'] not in centres:
                continue
            ca, cb = centres[e['src']], centres[e['tgt']]
            mid = ((ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2)
            d = math.hypot(l['x'] - mid[0], l['y'] - mid[1])
            if best is None or d < best[0]:
                best = (d, e)
        if best and best[0] < 260 and id(best[1]) not in label_of:
            label_of[id(best[1])] = l

    scale = 1.0
    if not a.no_compact:
        xs = [c[0] for c in centres.values()]
        ys = [c[1] for c in centres.values()]
        axis_x = (max(xs) - min(xs)) >= (max(ys) - min(ys))
        extent = {}
        for e in edges:
            l = label_of.get(id(e))
            if l:
                extent[id(e)] = (l.get('textW') or l['w']) if axis_x else (l.get('textH') or l['h'])
        before = dict(centres)
        centres, _ = compact_ranks(centres, sizes, edges, extent,
                                   edge_gap=a.edge_gap, node_gap=a.node_gap)
        deltas = {k: (centres[k][0] - before[k][0], centres[k][1] - before[k][1]) for k in centres}
        for e in edges:
            ds = deltas.get(e['src'], (0, 0))
            dt = deltas.get(e['tgt'], (0, 0))
            dx, dy = (ds[0] + dt[0]) / 2, (ds[1] + dt[1]) / 2
            e['points'] = [(x + dx, y + dy) for x, y in e['points']]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1
        moved = max((abs(d[0]) + abs(d[1]) for d in deltas.values()), default=0)
        scale = 1.0 - moved / span

        # rebuild the extents from the compacted geometry
        allx = [centres[k][0] - sizes[k][0] / 2 for k in nodes]
        ally = [centres[k][1] - sizes[k][1] / 2 for k in nodes]
        allx2 = [centres[k][0] + sizes[k][0] / 2 for k in nodes]
        ally2 = [centres[k][1] + sizes[k][1] / 2 for k in nodes]
        for c in layout.get('clusters', []):
            mk = [k for k, n in nodes.items()
                  if n['x'] >= c['x'] - 1 and n['y'] >= c['y'] - 1
                  and n['x'] + n['w'] <= c['x'] + c['w'] + 1
                  and n['y'] + n['h'] <= c['y'] + c['h'] + 1]
            if not mk:
                continue
            padl = min(nodes[k]['x'] for k in mk) - c['x']
            padt = min(nodes[k]['y'] for k in mk) - c['y']
            padr = c['x'] + c['w'] - max(nodes[k]['x'] + nodes[k]['w'] for k in mk)
            padb = c['y'] + c['h'] - max(nodes[k]['y'] + nodes[k]['h'] for k in mk)
            x0 = min(centres[k][0] - sizes[k][0] / 2 for k in mk) - padl
            y0 = min(centres[k][1] - sizes[k][1] / 2 for k in mk) - padt
            x1 = max(centres[k][0] + sizes[k][0] / 2 for k in mk) + padr
            y1 = max(centres[k][1] + sizes[k][1] / 2 for k in mk) + padb
            c['x'], c['y'], c['w'], c['h'] = x0, y0, x1 - x0, y1 - y0
            allx.append(x0); ally.append(y0); allx2.append(x1); ally2.append(y1)
        minx, miny = min(allx), min(ally)
        vw, vh = max(allx2) - minx, max(ally2) - miny

    PAD = 30.0
    ox, oy = PAD - minx, PAD - miny
    gid = 2
    node_gfx, line_gfx, label_gfx, cluster_gfx = [], [], [], []
    rects = {}
    idmap = {}

    for key, n in nodes.items():
        idmap[key] = gid
        shape_name = SHAPES.get(n.get('shape'), 'Rectangle')
        w, h = sizes[key]
        cx, cy = centres[key]
        rects[key] = (cx - w / 2, cy - h / 2, w, h)
        node_gfx.append({
            'Class': 'ShapedGraphic', 'ID': gid,
            'Shape': shape_name,
            'Bounds': f'{{{{{cx - w / 2 + ox:.2f}, {cy - h / 2 + oy:.2f}}}, {{{w:.2f}, {h:.2f}}}}}',
            'Style': {
                'fill': {'Color': colour(0.925, 0.925, 1.0)},
                'stroke': {'Color': colour(0.576, 0.439, 0.859), 'Width': 1.0},
                'shadow': {'Draws': 'NO'},
            },
            'Text': {'Text': rtf(n['label']), 'TextAlongPathGlyphAnchor': 'center',
                     'Pad': 0, 'VerticalPad': 0},
        })
        gid += 1

    # Subgraph containers sit at the very back. Sort smallest-first so a nested
    # subgraph stays in front of the one enclosing it (GraphicsList is front-to-back);
    # otherwise the outer container paints over the inner one.
    for c in sorted(layout.get('clusters', []), key=lambda c: c['w'] * c['h']):
        cluster_gfx.append({
            'Class': 'ShapedGraphic', 'ID': gid, 'Shape': 'Rectangle',
            'Bounds': f'{{{{{c["x"] + ox:.2f}, {c["y"] + oy:.2f}}}, {{{c["w"]:.2f}, {c["h"]:.2f}}}}}',
            'Style': {'fill': {'Color': colour(0.98, 0.98, 0.90)},
                      'stroke': {'Color': colour(0.66, 0.66, 0.66), 'Width': 1.0, 'Pattern': 2},
                      'shadow': {'Draws': 'NO'}},
            'Text': {'Text': rtf(c.get('label', '')), 'TextAlongPathGlyphAnchor': 'center',
                     'VerticalPad': 4},
            'TextPlacement': 0,
        })
        gid += 1

    connected = 0
    for e in edges:
        ra, rb = rects.get(e['src']), rects.get(e['tgt'])
        if not a.keep_routing and ra and rb and e['src'] != e['tgt']:
            # a plain two-point connector: no routed midpoints at all
            seg = [(ra[0] + ra[2] / 2, ra[1] + ra[3] / 2), (rb[0] + rb[2] / 2, rb[1] + rb[3] / 2)]
            routed = clip_to_boxes(seg, ra, rb)
        else:
            routed = clip_to_boxes(e['points'], ra, rb)
        routed = simplify_points(routed, a.simplify_tol)
        lab = label_of.get(id(e))
        if lab is not None:
            lab['x'] = sum(p[0] for p in routed) / len(routed)
            lab['y'] = sum(p[1] for p in routed) / len(routed)
        pts = [f'{{{x + ox:.2f}, {y + oy:.2f}}}' for x, y in routed]
        if len(pts) < 2:
            continue
        stroke = {'Color': colour(0.2, 0.2, 0.2), 'Width': 1.0,
                  'HeadArrow': 'FilledArrow', 'TailArrow': 'None', 'Legacy': False}
        if e['dashed']:
            stroke['Pattern'] = 2
        # OmniGraffle drops a LineGraphic that has no LogicalPath
        elements = [{'element': 'MOVETO' if i == 0 else 'LINETO', 'point': pt}
                    for i, pt in enumerate(pts)]
        g = {'Class': 'LineGraphic', 'ID': gid, 'Points': pts,
             'LogicalPath': {'elements': elements},
             'AllowLabelDrop': False,
             'Style': {'fill': {'Draws': 'NO'}, 'shadow': {'Draws': 'NO'}, 'stroke': stroke}}
        if e['src'] in idmap and e['tgt'] in idmap:
            g['Tail'] = {'ID': idmap[e['src']]}
            g['Head'] = {'ID': idmap[e['tgt']]}
            connected += 1
        line_gfx.append(g)
        gid += 1

    for lb in elabels:
        tw = lb.get('textW') or lb['w']
        th = lb.get('textH') or lb['h']
        w, h = max(tw, 20.0) + a.pad_x + WRAP_SLACK, max(th, 14.0) + a.pad_y
        label_gfx.append({
            'Class': 'ShapedGraphic', 'ID': gid, 'Shape': 'Rectangle',
            'Bounds': f'{{{{{lb["x"] + ox - w / 2:.2f}, {lb["y"] + oy - h / 2:.2f}}}, {{{w:.2f}, {h:.2f}}}}}',
            # opaque fill so the label masks the connector underneath, as Mermaid does
            'Style': {'fill': {'Color': colour(1.0, 1.0, 1.0)},
                      'stroke': {'Draws': 'NO'}, 'shadow': {'Draws': 'NO'}},
            'Text': {'Text': rtf(lb['label']), 'TextAlongPathGlyphAnchor': 'center',
                     'Pad': 0, 'VerticalPad': 0},
        })
        gid += 1

    # GraphicsList is FRONT-to-back: labels must precede lines to mask them
    graphics = label_gfx + node_gfx + line_gfx + cluster_gfx

    doc = plistlib.loads(TEMPLATE.read_bytes())
    sheet = doc['Sheets'][0]
    sheet['GraphicsList'] = graphics
    sheet['SheetTitle'] = a.title or pathlib.Path(a.layout).stem
    sheet['CanvasSize'] = f'{{{vw + 2 * PAD:.2f}, {vh + 2 * PAD:.2f}}}'
    doc['Sheets'] = [sheet]

    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('data.plist', plistlib.dumps(doc, fmt=plistlib.FMT_BINARY))

    print(f'{a.out}: {len(nodes)} nodes, {len(cluster_gfx)} subgraphs, {len(edges)} edges '
          f'({connected} connected), {len(elabels)} edge labels, 0 groups, '
          f'layout scale {scale:.3f}')
    unresolved = [e for e in edges if e['src'] not in idmap or e['tgt'] not in idmap]
    if unresolved:
        print(f'WARNING: {len(unresolved)} edge(s) could not be resolved to nodes',
              file=sys.stderr)


if __name__ == '__main__':
    main()
