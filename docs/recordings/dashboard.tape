Output docs/images/dashboard.gif

# Run from the repo root:
#   cd /path/to/anglerfish
#   vhs docs/recordings/dashboard.tape
#
# Requires: vhs, ffmpeg, ttyd (see docs/plans/2026-03-08-arsenal-readme-improvements.md)
# Output:   docs/images/dashboard.gif

Set Theme "Dracula"
Set FontSize 13
Set Width 1200
Set Height 650
Set TypingSpeed 50ms

Type "source .venv/bin/activate && anglerfish dashboard --demo"
Enter
Sleep 8s

# Quit
Type "q"
Sleep 1s

# End of recording
