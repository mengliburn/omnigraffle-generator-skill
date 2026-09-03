#!/usr/bin/env python3
"""Extract ```mermaid fenced blocks from a Markdown file into individual .mmd files.

Usage:
    extract_mermaid.py DOC.md OUTDIR

Files are named NN-<slug>.mmd where <slug> comes from the nearest preceding
Markdown heading (or bold lead-in line), so the output is self-describing.
Prints one "NN-slug<TAB>title" line per diagram so callers can reuse the titles.
"""
import re
import sys
import pathlib


def slugify(text: str) -> str:
    text = re.sub(r'`[^`]*`', '', text)
    text = re.sub(r'[*_#]+', '', text)
    text = re.sub(r'[^A-Za-z0-9]+', '-', text).strip('-').lower()
    return re.sub(r'-{2,}', '-', text)[:48] or 'diagram'


def nearest_title(lines, idx):
    """Nearest preceding heading or bold lead-in, e.g. '**Before**'."""
    for k in range(idx - 1, max(-1, idx - 40), -1):
        s = lines[k].strip()
        m = re.match(r'^#{1,6}\s+(.*)$', s) or re.match(r'^\*\*(.+?)\*\*$', s)
        if m:
            return re.sub(r'\s+', ' ', m.group(1)).strip()
    return ''


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    doc, outdir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)

    lines = doc.read_text().split('\n')
    i = n = 0
    seen = {}
    while i < len(lines):
        if lines[i].strip() == '```mermaid':
            j = i + 1
            while j < len(lines) and lines[j].strip() != '```':
                j += 1
            if j >= len(lines):
                print(f'error: unterminated ```mermaid block at line {i + 1}', file=sys.stderr)
                return 1
            n += 1
            title = nearest_title(lines, i)
            base = slugify(title)
            # a heading covering two diagrams (Before/After) would collide; disambiguate
            seen[base] = seen.get(base, 0) + 1
            if seen[base] > 1:
                base = f'{base}-{seen[base]}'
            name = f'{n:02d}-{base}'
            (outdir / f'{name}.mmd').write_text('\n'.join(lines[i + 1:j]) + '\n')
            print(f'{name}\t{title}')
            i = j
        i += 1

    if n == 0:
        print('error: no ```mermaid blocks found', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
