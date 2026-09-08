#!/usr/bin/env python3
"""Build a NATIVE OmniGraffle document from a Mermaid sequence diagram.

    extract_sequence_layout.mjs IN.svg > layout.json
    mermaid_sequence_to_graffle.py layout.json OUT.graffle [--title "Canvas name"]

Mapping, chosen so the result behaves like a hand-drawn sequence diagram:

  participant box  -> ShapedGraphic (flat, no groups)
  lifeline         -> LineGraphic, Tail = top box, Head = bottom box
  message          -> LineGraphic with an arrowhead property,
                      Tail = source lifeline, Head = target lifeline
  activation bar   -> ShapedGraphic
  note             -> ShapedGraphic
  message label    -> opaque ShapedGraphic, drawn in front so it masks the line
  sequence number  -> small Circle ShapedGraphic

Messages attach to *lifelines*, not to participant boxes. Attaching them to the
boxes would be wrong: moving a participant would drag the message off its
y-position, whereas a message belongs at a fixed point in time on the lifeline.
OmniGraffle supports line-to-line connections, which makes this possible.
"""
import argparse
import json
import pathlib
import sys

from graffle_lib import (WRAP_SLACK, clip_to_boxes, colour, line, shape,
                         simplify_points, write_graffle)

ACTOR_FILL = colour(0.918, 0.918, 0.918)     # #eaeaea
ACTOR_STROKE = colour(0.4, 0.4, 0.4)         # #666
NOTE_FILL = colour(0.929, 0.949, 0.682)      # #EDF2AE
LINE_COLOUR = colour(0.2, 0.2, 0.2)
LIFELINE_COLOUR = colour(0.6, 0.6, 0.6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('layout')
    ap.add_argument('out')
    ap.add_argument('--title', default=None)
    ap.add_argument('--pad-x', type=float, default=0.0,
                    help='horizontal padding around participant text (default 0 = tight)')
    ap.add_argument('--pad-y', type=float, default=0.0,
                    help='vertical padding around participant text (default 0 = tight)')
    ap.add_argument('--connect-messages', action='store_true',
                    help='attach messages to lifelines (WARNING: OmniGraffle '
                         're-routes them and flattens the timeline)')
    a = ap.parse_args()

    L = json.loads(pathlib.Path(a.layout).read_text())
    minx, miny, vw, vh = L['viewBox']
    PAD = 30.0
    ox, oy = PAD - minx, PAD - miny

    gid = 2
    boxes, lifelines, messages, notes, acts, labels, seqs = [], [], [], [], [], [], []
    top_id, bottom_id, lifeline_id = {}, {}, {}
    top_rect, bottom_rect = {}, {}

    for act in L['actors']:
        # tighten to the caption, keeping the centre so lifelines stay aligned
        w, h = act['w'], act['h']
        if act.get('textW'):
            w = min(w, act['textW'] + a.pad_x + WRAP_SLACK)
            h = min(h, act['textH'] + a.pad_y)
        cx, cy = act['x'] + act['w'] / 2, act['y'] + act['h'] / 2
        g = shape(gid, cx - w / 2 + ox, cy - h / 2 + oy, w, h,
                  text=act['label'], fill=ACTOR_FILL, stroke=ACTOR_STROKE)
        boxes.append(g)
        if act['which'] == 'top':
            top_id[act['name']] = gid
            top_rect[act['name']] = (cx - w / 2, cy - h / 2, w, h)
        else:
            bottom_id[act['name']] = gid
            bottom_rect[act['name']] = (cx - w / 2, cy - h / 2, w, h)
        gid += 1

    for lf in L['lifelines']:
        # the participant boxes were tightened, so the lifeline must be re-clipped
        # to their new borders or it starts short of them
        # clipping leaves the old endpoints behind as collinear leftovers
        seg = simplify_points(clip_to_boxes([(lf['x1'], lf['y1']), (lf['x2'], lf['y2'])],
                                            top_rect.get(lf['id']), bottom_rect.get(lf['id'])))
        g = line(gid, [(x + ox, y + oy) for x, y in seg],
                 stroke=LIFELINE_COLOUR, width=0.75, arrow=False,
                 tail_id=top_id.get(lf['id']), head_id=bottom_id.get(lf['id']))
        lifelines.append(g)
        lifeline_id[lf['id']] = gid
        gid += 1

    connected = 0
    for m in L['messages']:
        src = dst = None
        # Messages are deliberately NOT connected by default. OmniGraffle
        # re-routes a connected line to its target's connection point as soon as
        # the document loads, which collapses every message onto one y and
        # destroys the timeline (observed: all 11 messages snapped to y=72.5).
        # A message's meaning is "at this point in time", so position wins.
        if a.connect_messages and m['from'] != m['to']:
            src, dst = lifeline_id.get(m['from']), lifeline_id.get(m['to'])
            if src is not None and dst is not None:
                connected += 1
            else:
                src = dst = None
        g = line(gid, [(m['x1'] + ox, m['y1'] + oy), (m['x2'] + ox, m['y2'] + oy)],
                 stroke=LINE_COLOUR, width=1.5, arrow=m.get('arrow', True),
                 dashed=m['dashed'], tail_id=src, head_id=dst)
        messages.append(g)
        gid += 1

    for n in L['notes']:
        notes.append(shape(gid, n['x'] + ox, n['y'] + oy, n['w'], n['h'],
                           text=n['text'], fill=NOTE_FILL, stroke=ACTOR_STROKE))
        gid += 1

    for c in L['activations']:
        acts.append(shape(gid, c['x'] + ox, c['y'] + oy, max(c['w'], 8), c['h'],
                          fill=NOTE_FILL, stroke=ACTOR_STROKE))
        gid += 1

    for lb in L['labels']:
        w, h = lb['w'] + 12, lb['h'] + 6
        labels.append(shape(gid, lb['x'] + ox - 6, lb['y'] + oy - 3, w, h,
                            text=lb['text'], fill=colour(1.0, 1.0, 1.0)))
        gid += 1

    for s in L['seqNumbers']:
        d = max(s['w'], s['h'], 16.0) + 4
        cx, cy = s['x'] + s['w'] / 2 + ox, s['y'] + s['h'] / 2 + oy
        seqs.append(shape(gid, cx - d / 2, cy - d / 2, d, d, text=s['text'],
                          fill=colour(0.2, 0.2, 0.2), shape_name='Circle', font_size=9))
        gid += 1

    # FRONT to back: labels and numbers on top, then boxes/notes/activations,
    # then messages, with the lifelines furthest back
    graphics = seqs + labels + notes + acts + boxes + messages + lifelines

    write_graffle(a.out, graphics, a.title or pathlib.Path(a.layout).stem,
                  vw + 2 * PAD, vh + 2 * PAD)

    print(f'{a.out}: {len(boxes)} participant boxes, {len(lifelines)} lifelines, '
          f'{len(messages)} messages ({connected} connected), '
          f'{len(notes)} notes, {len(acts)} activations, {len(labels)} labels, '
          f'{len(seqs)} numbers, 0 groups')
    missing = [m for m in L['messages'] if m['from'] not in lifeline_id
               or m['to'] not in lifeline_id]
    if missing:
        print(f'WARNING: {len(missing)} message(s) reference unknown participants',
              file=sys.stderr)


if __name__ == '__main__':
    main()
