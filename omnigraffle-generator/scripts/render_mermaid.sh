#!/usr/bin/env bash
#
# Render Mermaid sources to SVG with settings that survive an OmniGraffle import.
#
#   render_mermaid.sh OUTDIR FILE.mmd [FILE.mmd ...]
#
# Two things differ from a stock `mmdc` run, both mandatory for OmniGraffle:
#
#   1. htmlLabels:false — by default Mermaid puts flowchart label text inside
#      <foreignObject> (embedded XHTML). OmniGraffle ignores foreignObject
#      entirely, so every shape imports blank.
#   2. A patch to Mermaid's edge-label wrapping. insertEdgeLabel() passes
#      `width: undefined` to createText(), which falls back to a hardcoded
#      200px and ignores flowchart.wrappingWidth. Long identifiers then get
#      hard-split mid-word (e.g. "requeueRequestsPCollectio" / "n").
#
set -euo pipefail

if [ "$#" -lt 2 ]; then
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi

OUTDIR="$1"; shift
mkdir -p "$OUTDIR"

CACHE="${OG_GEN_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/omnigraffle-generator}"
TOOLCHAIN="$CACHE/toolchain"

if [ ! -x "$TOOLCHAIN/node_modules/.bin/mmdc" ]; then
  echo "==> installing @mermaid-js/mermaid-cli into $TOOLCHAIN (one time)"
  mkdir -p "$TOOLCHAIN"
  ( cd "$TOOLCHAIN" && npm init -y >/dev/null 2>&1 && npm install @mermaid-js/mermaid-cli >/dev/null )
fi

# Patch the edge-label wrapping-width fallback. Idempotent; a Mermaid upgrade that
# renames the symbol simply leaves the file untouched and we warn.
python3 - "$TOOLCHAIN" <<'PY'
import glob, pathlib, sys
old = 'width: isMarkdown ? markdownWidth : void 0'
new = 'width: isMarkdown ? markdownWidth : (config.flowchart?.wrappingWidth ?? void 0)'
patched = already = 0
for f in glob.glob(f'{sys.argv[1]}/node_modules/mermaid/dist/chunks/*/*.mjs'):
    p = pathlib.Path(f); s = p.read_text()
    if new in s:
        already += 1
    elif old in s:
        p.write_text(s.replace(old, new)); patched += 1
if patched:
    print(f'==> patched edge-label wrapping in {patched} Mermaid chunk(s)')
elif not already:
    print('WARNING: edge-label wrap patch did not apply; long edge labels may break mid-word',
          file=sys.stderr)
PY

cat > "$TOOLCHAIN/og-puppeteer.json" <<'JSON'
{ "args": ["--no-sandbox", "--disable-setuid-sandbox"] }
JSON

cat > "$TOOLCHAIN/og-mermaid.json" <<'JSON'
{
  "theme": "default",
  "htmlLabels": false,
  "flowchart": { "htmlLabels": false, "useMaxWidth": false, "wrappingWidth": 2000 },
  "sequence": { "useMaxWidth": false, "wrap": false },
  "themeVariables": { "fontFamily": "Helvetica, Arial, sans-serif" }
}
JSON

for f in "$@"; do
  name="$(basename "$f" .mmd)"
  echo "==> rendering $name"
  "$TOOLCHAIN/node_modules/.bin/mmdc" \
    -i "$f" -o "$OUTDIR/$name.svg" \
    -b white \
    -c "$TOOLCHAIN/og-mermaid.json" \
    -p "$TOOLCHAIN/og-puppeteer.json" >/dev/null
done

echo "==> wrote $# SVG(s) to $OUTDIR (still needs og_fix_svg.mjs)"
