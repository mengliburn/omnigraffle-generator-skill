# omnigraffle-generator-skill

An agent skill (Claude Code / GitHub Copilot CLI) that turns **Mermaid diagrams into
OmniGraffle-editable vector art** — and assembles them into a single multi-canvas
`.graffle` document, one diagram per canvas.

Not screenshots. Real shapes, real text, editable in OmniGraffle.

## The problem

A stock `mmdc` SVG looks perfect in a browser and imports into OmniGraffle almost entirely
broken:

- every flowchart shape imports **blank** (Mermaid uses `<foreignObject>`; OmniGraffle ignores it)
- multi-line labels **collapse** and stop being centred (OmniGraffle merges `<tspan>`s)
- **black boxes** appear behind edge labels (OmniGraffle can't parse `rgba()`)
- **arrowheads vanish**, and a pile of junk shapes lands at the origin (OmniGraffle renders
  `<marker>` *definitions* as objects, and doesn't apply them to paths)
- long identifiers **split mid-word** (`requeueRequestsPCollectio` / `n`)

None of this is visible in a browser, which is why it's so easy to ship broken. This skill
encodes the fixes, plus the verification that proves they worked.

## Install

```bash
git clone https://github.com/mengliburn/omnigraffle-generator-skill.git
cp -r omnigraffle-generator-skill/omnigraffle-generator ~/.claude/skills/
```

Then ask your agent for *"mermaid to omnigraffle"* or *"multi-canvas graffle"*.

The scripts also run standalone — see [`omnigraffle-generator/SKILL.md`](omnigraffle-generator/SKILL.md).

## Quick start

```bash
S=~/.claude/skills/omnigraffle-generator/scripts

python3 $S/extract_mermaid.py DOC.md out/mmd      # markdown -> .mmd (optional)
$S/render_mermaid.sh out/svg out/mmd/*.mmd        # .mmd -> .svg
node $S/og_fix_svg.mjs out/svg/*.svg              # make OmniGraffle-safe (in place)

for f in out/svg/*.svg; do                        # verify — never skip this
  python3 $S/verify_svg.py "$f" "out/mmd/$(basename "$f" .svg).mmd"
done

# optional: one flat SVG with every diagram stacked
python3 $S/combine_svgs.py -o out/all.svg "out/svg/01-a.svg=First" "out/svg/02-b.svg=Second"

# optional: native multi-canvas OmniGraffle document
$S/make_multicanvas.sh out/diagrams.graffle "out/svg/01-a.svg=01 · First" "out/svg/02-b.svg=02 · Second"
```

The fixed SVGs stay valid for browsers and GitHub, so they remain usable inline in docs.

## Scripts

| Script | Purpose |
|---|---|
| `extract_mermaid.py` | Pull ```` ```mermaid ```` blocks out of Markdown, naming each from its nearest heading |
| `render_mermaid.sh` | Render `.mmd` → SVG with OmniGraffle-safe Mermaid settings; provisions the toolchain; patches Mermaid's edge-label wrapping bug |
| `og_fix_svg.mjs` | **The core.** Rewrites an SVG so OmniGraffle imports it faithfully |
| `verify_svg.py` | Structural + text-completeness checks; catches losses invisible in a browser |
| `combine_svgs.py` | Merge SVGs into one stacked SVG (ID namespacing + transform baking) |
| `svg_to_graffle.sh` | Import one SVG and save a single-canvas `.graffle` |
| `merge_graffle.py` | Merge single-canvas `.graffle` files into one multi-canvas document |
| `make_multicanvas.sh` | Orchestrates the two above |
| `dump_graffle_text.applescript` | Read text back **out of OmniGraffle** — the only real verification |

## How multi-canvas works

OmniGraffle's automation can't do it: clipboard copy/paste is silently ignored, and
`duplicate` fails across documents (`Can't make ... into type reference`).

So it happens at the **file level**. A `.graffle` is a ZIP whose `data.plist` holds a
`Sheets` array — one entry per canvas. Each SVG is imported separately (which gives it
natural near-origin coordinates and an auto-sized canvas), then the sheets are merged,
offsetting graphic `ID`s per sheet since they restart near 0 in every file.

## Requirements

- `node` + `npm` — the Mermaid toolchain is provisioned automatically on first run
- `python3` — stdlib only
- macOS + OmniGraffle — only for the `.graffle` steps; SVG generation is cross-platform

## Verification stance

Structural checks on a file do not prove OmniGraffle parsed it, and a browser screenshot
proves nothing about OmniGraffle at all. `dump_graffle_text.applescript` reads the text back
out of the application so a claim of "it renders correctly" is actually checked.

## License

MIT
