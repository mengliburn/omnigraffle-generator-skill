#!/usr/bin/env bash
#
# Mermaid -> native multi-canvas OmniGraffle document, end to end.
#
#   make_native_graffle.sh OUT.graffle DOC.md
#   make_native_graffle.sh OUT.graffle a.mmd b.mmd ...
#
# Produces OmniGraffle's own objects (no groups, connectors that are really
# connected, arrowheads as line properties), one diagram per canvas, then
# verifies the result.
#
# Canvas titles come from the Markdown headings above each diagram when a .md is
# given; otherwise from the file name.
#
set -euo pipefail

if [ "$#" -lt 2 ]; then
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$1"; shift

WORK="$(mktemp -d "${TMPDIR:-/tmp}/og-native.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/mmd" "$WORK/raw"

titles_file="$WORK/titles.tsv"
if [ "$#" -eq 1 ] && [[ "$1" == *.md ]]; then
  echo "==> extracting mermaid blocks from $(basename "$1")"
  python3 "$HERE/extract_mermaid.py" "$1" "$WORK/mmd" > "$titles_file"
else
  for f in "$@"; do cp "$f" "$WORK/mmd/"; done
  : > "$titles_file"
fi

echo "==> rendering"
"$HERE/render_mermaid.sh" "$WORK/raw" "$WORK"/mmd/*.mmd >/dev/null

args=()
n=0
for svg in "$WORK"/raw/*.svg; do
  name="$(basename "$svg" .svg)"
  n=$((n + 1))
  title="$(awk -F'\t' -v k="$name" '$1==k && $2!="" {print $2}' "$titles_file" | head -1)"
  [ -n "$title" ] || title="$name"
  title="$(printf '%02d · %s' "$n" "$title")"

  # Sequence diagrams and flowcharts have different semantic markup
  if grep -q 'messageLine' "$svg"; then
    kind=sequence
    node "$HERE/extract_sequence_layout.mjs" "$svg" > "$WORK/$name.json"
    python3 "$HERE/mermaid_sequence_to_graffle.py" "$WORK/$name.json" \
        "$WORK/$name.graffle" --title "$title" | sed 's/^/    /'
  else
    kind=flowchart
    node "$HERE/extract_flowchart_layout.mjs" "$svg" > "$WORK/$name.json"
    python3 "$HERE/mermaid_flowchart_to_graffle.py" "$WORK/$name.json" \
        "$WORK/$name.graffle" --title "$title" | sed 's/^/    /'
  fi
  echo "==> [$n] $name ($kind)"
  args+=("$WORK/$name.graffle=$title")
done

echo "==> merging $n canvases"
python3 "$HERE/merge_graffle.py" -o "$OUT" "${args[@]}" >/dev/null

echo "==> verifying"
python3 "$HERE/verify_graffle.py" "$OUT" "$WORK/mmd"
