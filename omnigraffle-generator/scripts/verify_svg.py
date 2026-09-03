#!/usr/bin/env python3
"""Verify an OmniGraffle-safe SVG really is safe, and that no label text was lost.

    verify_svg.py FILE.svg [FILE.mmd]

Structural checks (each maps to a known OmniGraffle failure mode):
  * no <foreignObject>      -> otherwise every flowchart shape imports blank
  * no nested <tspan>       -> otherwise OmniGraffle drops the text
  * no rgba() paint         -> otherwise OmniGraffle renders it black
  * no <marker>             -> otherwise marker defs are dumped as stray objects

Content check (only when the .mmd is given): every quoted flowchart label and
every sequence-diagram participant/message string must appear in the SVG's
text, with rows joined by spaces. This is what catches silent mid-word
splitting, which looks fine structurally but corrupts identifiers.
"""
import html
import re
import sys
import pathlib


def svg_text(svg):
    s = re.sub(r'<style.*?</style>', '', svg, flags=re.S)
    rows = []
    for t in re.findall(r'<text[^>]*>(.*?)</text>', s, flags=re.S):
        rows.append(html.unescape(re.sub('<[^>]+>', ' ', t)))
    return re.sub(r'[ \t]+', ' ', ' '.join(rows))


def mermaid_fragments(src):
    frags = []
    if 'sequenceDiagram' in src:
        for ln in src.splitlines():
            ln = ln.strip()
            m = (re.match(r'participant \w+ as (.+)$', ln)
                 or re.match(r'(?:Note over [^:]+|[\w]+\s*-?-?>>?[-x]?\s*[\w]+)\s*:\s*(.+)$', ln))
            if m:
                frags += [x.strip() for x in re.split(r'<br\s*/?>', m.group(1)) if x.strip()]
    else:
        for lab in re.findall(r'"([^"]+)"', src):
            frags += [x.strip() for x in re.split(r'<br\s*/?>', lab) if x.strip()]
    return [re.sub(r'\s+', ' ', html.unescape(x)) for x in frags]


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    svg_path = pathlib.Path(sys.argv[1])
    svg = svg_path.read_text()
    body = re.sub(r'<defs.*?</defs>', '', re.sub(r'<style.*?</style>', '', svg, flags=re.S), flags=re.S)

    problems = []
    checks = {
        'foreignObject': svg.count('<foreignObject'),
        'nested_tspan': len(re.findall(r'<tspan[^>]*>(?:(?!</tspan>).)*<tspan', svg, flags=re.S)),
        'rgba_paint': len(re.findall(r'rgba\(', body)),
        'marker_defs': svg.count('<marker'),
    }
    for k, v in checks.items():
        if v:
            problems.append(f'{k}={v}')

    missing = []
    if len(sys.argv) == 3:
        frags = mermaid_fragments(pathlib.Path(sys.argv[2]).read_text())
        text = svg_text(svg)
        missing = [f for f in frags if f not in text]
        print(f'{svg_path.name}: {checks} label_fragments={len(frags)} missing={len(missing)}')
        for m in missing[:8]:
            print(f'    MISSING: {m!r}')
    else:
        print(f'{svg_path.name}: {checks}')

    if problems or missing:
        print(f'FAIL: {" ".join(problems)}{" missing_text" if missing else ""}', file=sys.stderr)
        return 1
    print('OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
