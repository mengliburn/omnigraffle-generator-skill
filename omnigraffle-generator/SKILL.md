---
name: omnigraffle-generator
description: |
  Convert Mermaid diagrams into SVGs that OmniGraffle imports faithfully, and assemble
  them into a single multi-canvas .graffle document (one diagram per canvas). Handles the
  OmniGraffle SVG-importer limitations that silently destroy text, colour and layout.

  Trigger: "mermaid to omnigraffle", "omnigraffle svg", "open diagram in omnigraffle",
  "multi-canvas graffle", "omnigraffle-generator"
user-invocable: true
allowed-tools: ["Bash", "Read", "Write", "Edit", "Grep", "Glob"]
---

# OmniGraffle Generator

Turn Mermaid diagrams into **editable OmniGraffle vector art**, not screenshots.

A stock `mmdc` SVG *looks* correct in a browser and imports into OmniGraffle almost
entirely broken. Every transform in this skill exists because of a specific, observed
OmniGraffle importer limitation — see [Why each step exists](#why-each-step-exists).
Do not skip steps because the SVG "looks fine"; a browser will not show you any of these
failures.

`$SKILL` below is this skill's directory.

---

## Workflow

### Step 1 — Get the Mermaid sources

From a Markdown file:

```bash
python3 $SKILL/scripts/extract_mermaid.py DOC.md OUTDIR/mmd
```

It writes `NN-<slug>.mmd` per ```` ```mermaid ```` block, naming each from the nearest
preceding heading, and prints `name<TAB>title` lines. **Keep those titles** — reuse them
as diagram titles in Step 4 and canvas names in Step 5.

If the user already has `.mmd` files, skip this.

### Step 2 — Render to SVG

```bash
$SKILL/scripts/render_mermaid.sh OUTDIR/svg OUTDIR/mmd/*.mmd
```

Provisions `@mermaid-js/mermaid-cli` into `~/.cache/omnigraffle-generator/toolchain` on
first run (one time, ~20 s), renders with `htmlLabels:false`, and patches Mermaid's
edge-label wrapping bug.

### Step 3 — Make the SVGs OmniGraffle-safe

```bash
node $SKILL/scripts/og_fix_svg.mjs OUTDIR/svg/*.svg     # edits in place
```

This is the core of the skill. It reports what it changed per file.

**Verify before continuing** — this catches the failures that are invisible in a browser:

```bash
for f in OUTDIR/svg/*.svg; do
  n=$(basename "$f" .svg)
  python3 $SKILL/scripts/verify_svg.py "$f" "OUTDIR/mmd/$n.mmd"
done
```

Every file must print `OK`. `missing=N` means label text was lost or split mid-word — stop
and investigate rather than shipping it.

At this point the individual SVGs are usable: they open correctly in OmniGraffle **and**
still render normally in a browser / on GitHub.

### Step 4 — (optional) One combined SVG

For a single flat file containing every diagram stacked vertically with titles:

```bash
python3 $SKILL/scripts/combine_svgs.py -o OUTDIR/all-diagrams.svg \
  "OUTDIR/svg/01-foo.svg=1. First diagram" \
  "OUTDIR/svg/02-bar.svg=2. Second diagram"
```

Must report `dup_ids=0, unresolved_refs=0, leftover_transforms=0`.

### Step 5 — (optional) Multi-canvas .graffle

For one native OmniGraffle document with **one diagram per canvas** — usually what people
actually want:

```bash
$SKILL/scripts/make_multicanvas.sh OUTDIR/diagrams.graffle \
  "OUTDIR/svg/01-foo.svg=01 · First diagram" \
  "OUTDIR/svg/02-bar.svg=02 · Second diagram"
```

Requires OmniGraffle installed; it drives the app via AppleScript (there is no headless
mode) and will focus it repeatedly. Each canvas is auto-sized to its own diagram.

### Step 6 — Verify in OmniGraffle

Structural checks do not prove OmniGraffle parsed the file. Read the text back out:

```bash
osascript $SKILL/scripts/dump_graffle_text.applescript FILE.graffle
```

Compare against the `.mmd` label fragments. Text present per canvas, with nothing bleeding
between canvases, is the only real pass condition.

---

## Why each step exists

Each row is a real OmniGraffle behaviour, confirmed by reading geometry and text back out
of OmniGraffle via AppleScript. **All of these render correctly in a browser**, which is
why they are so easy to ship broken.

| OmniGraffle behaviour | Symptom if unhandled | Handled by |
|---|---|---|
| Ignores `<foreignObject>` | Every flowchart shape imports **blank**. Mermaid puts flowchart labels in embedded XHTML by default | `render_mermaid.sh` (`htmlLabels:false`) |
| Merges sibling `<tspan>`s into one left-aligned paragraph, ignoring per-tspan `x` / `text-anchor` | Multi-line labels collapse and stop being centred in their shape | `og_fix_svg.mjs` — one `<text>` per row |
| Cannot parse `rgba()` (not valid SVG 1.1 paint); falls back to **black** | Black boxes behind edge labels | `og_fix_svg.mjs` — `rgb()` + `*-opacity` |
| Ignores the `<style>` block | Shapes lose all fill/stroke/font | `og_fix_svg.mjs` — inline computed styles |
| Renders `<marker>` **defs** as real objects, and does **not** apply them to paths | Arrowheads lost *and* a pile of junk shapes dumped at the origin | `og_fix_svg.mjs` — real `<polygon>` arrowheads, markers deleted |
| Draws zero-area rects as visible filled boxes | Stray boxes; Mermaid emits empty placeholder rects | `og_fix_svg.mjs` |
| Ignores **ancestor transforms** for some elements | Parts of a diagram scattered at raw coordinates when diagrams are offset for stacking | `combine_svgs.py` — bakes all transforms into coordinates |
| Mangles `<line>` | Lifelines collapse to 1×1 objects | `og_fix_svg.mjs` — `<line>` → `<path>` |
| Mermaid's `insertEdgeLabel()` passes `width: undefined`, so edge labels ignore `flowchart.wrappingWidth` and use a hardcoded 200px | Long identifiers hard-split **mid-word** (`requeueRequestsPCollectio` / `n`) | `render_mermaid.sh` patch |

### Automation limits (do not waste time here)

- **Clipboard copy/paste is ignored.** Scripted `⌘C`/`⌘V` between documents silently pastes nothing.
- **`duplicate` fails across documents** — `Can't make ... into type reference`.
- **`export` via AppleScript is unreliable** — `-10000` / `-1701` even with explicit settings.
- **`move` works within a single document**, but is fragile in bulk.

Multi-canvas assembly therefore happens **at the file level, not the GUI level**: a
`.graffle` is a ZIP whose `data.plist` holds a `Sheets` array, one entry per canvas.
`merge_graffle.py` merges sheets and offsets graphic `ID`s per sheet (they restart near 0
in every file, and `Head`/`Tail` connection references also carry `ID`).

---

## Rules

1. **Never skip `verify_svg.py`.** Every bug this skill exists for is invisible in a browser.
2. **Never claim OmniGraffle renders correctly from a browser screenshot.** Read the text
   back out of OmniGraffle, or say you did not verify it.
3. **Preserve the individual SVGs.** They stay valid for browsers/GitHub; the combined SVG
   and `.graffle` are additional artifacts, not replacements.
4. **Do not hand-edit generated SVGs.** Re-run the pipeline; the scripts are idempotent.
5. **Warn before Step 5** that OmniGraffle will be focused repeatedly and open documents
   will be closed (`close every document saving no`).

## Requirements

- `node` + `npm` (toolchain is provisioned automatically on first run)
- `python3` (stdlib only)
- OmniGraffle + macOS `osascript` — Steps 5 and 6 only
