#!/usr/bin/env bash
#
# Import one SVG into OmniGraffle and save it as a single-canvas .graffle.
#
#   svg_to_graffle.sh IN.svg OUT.graffle
#
# OmniGraffle has no headless mode, so this drives the running app via
# AppleScript. It polls until the import has produced geometry rather than
# sleeping a fixed amount, because large diagrams take noticeably longer.
#
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: svg_to_graffle.sh IN.svg OUT.graffle" >&2
  exit 2
fi

IN="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT_DIR="$(cd "$(dirname "$2")" && pwd)"
OUT="$OUT_DIR/$(basename "$2")"

[ -f "$IN" ] || { echo "error: $IN not found" >&2; exit 1; }
rm -f "$OUT"

osascript <<APPLESCRIPT
with timeout of 600 seconds
	tell application "OmniGraffle"
		activate
		close every document saving no
		delay 1
		open POSIX file "$IN"
		-- wait for the import to materialise geometry
		set ok to false
		repeat with i from 1 to 90
			try
				if (count of documents) > 0 then
					if (count of graphics of canvas 1 of document 1) > 0 then
						set ok to true
						exit repeat
					end if
				end if
			end try
			delay 1
		end repeat
		if not ok then error "OmniGraffle did not import $IN within 90s"
		delay 2
		save document 1 in POSIX file "$OUT"
		set k to count of graphics of canvas 1 of document 1
		close every document saving no
		return "objects=" & k
	end tell
end timeout
APPLESCRIPT

[ -f "$OUT" ] || { echo "error: OmniGraffle did not write $OUT" >&2; exit 1; }
echo "==> $OUT"
