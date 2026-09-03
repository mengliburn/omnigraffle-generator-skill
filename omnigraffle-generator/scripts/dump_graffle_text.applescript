-- Dump all text OmniGraffle actually holds, per canvas, recursing into groups.
--
--   osascript dump_graffle_text.applescript FILE.graffle
--
-- Structural checks on an SVG do not prove OmniGraffle parsed it. This reads the
-- text back out of the application, which is the only real verification. Output is
-- "@@@CANVAS <name>" section headers followed by one text object per line.
--
-- Warning: this closes every open OmniGraffle document without saving.

on collectText(gs)
	set acc to {}
	tell application "OmniGraffle"
		repeat with g in gs
			if (class of g as text) contains "group" then
				set acc to acc & my collectText(graphics of g)
			else
				try
					set tx to text of g as text
					if tx is not "" then set end of acc to tx
				end try
			end if
		end repeat
	end tell
	return acc
end collectText

on run argv
	if (count of argv) is not 1 then
		error "usage: osascript dump_graffle_text.applescript FILE.graffle"
	end if
	set theFile to item 1 of argv

	tell application "OmniGraffle"
		activate
		close every document saving no
		delay 1
		open POSIX file theFile

		-- wait for the document to finish loading rather than sleeping blindly
		set ok to false
		repeat with i from 1 to 90
			try
				if (count of documents) > 0 then
					if (count of canvases of document 1) > 0 then
						set ok to true
						exit repeat
					end if
				end if
			end try
			delay 1
		end repeat
		if not ok then error "OmniGraffle did not open " & theFile & " within 90s"
		delay 2

		set d to document 1
		set outStr to ""
		repeat with i from 1 to (count of canvases of d)
			set outStr to outStr & "@@@CANVAS " & (name of canvas i of d) & linefeed
			repeat with s in my collectText(graphics of canvas i of d)
				set outStr to outStr & s & linefeed
			end repeat
		end repeat
		return outStr
	end tell
end run
