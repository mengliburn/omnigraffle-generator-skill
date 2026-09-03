#!/usr/bin/env bash
#
# Build a multi-canvas .graffle (one canvas per diagram) from OmniGraffle-safe SVGs.
#
#   make_multicanvas.sh OUT.graffle IN.svg[=Canvas Title] [IN.svg[=Canvas Title] ...]
#
# Each SVG is imported on its own and saved as a single-canvas .graffle, then
# the sheets are merged at the plist level by merge_graffle.py.
#
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: make_multicanvas.sh OUT.graffle IN.svg[=Title] [...]" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$1"; shift

WORK="$(mktemp -d "${TMPDIR:-/tmp}/og-multicanvas.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

args=()
i=0
for spec in "$@"; do
  i=$((i + 1))
  svg="${spec%%=*}"
  title="${spec#*=}"
  [ "$title" = "$spec" ] && title="$(basename "$svg" .svg)"
  stage="$WORK/$(printf '%02d' "$i").graffle"
  echo "==> [$i/$#] importing $(basename "$svg")"
  "$HERE/svg_to_graffle.sh" "$svg" "$stage" >/dev/null
  args+=("$stage=$title")
done

echo "==> merging $# canvases"
python3 "$HERE/merge_graffle.py" -o "$OUT" "${args[@]}"
