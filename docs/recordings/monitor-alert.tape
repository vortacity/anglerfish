Output docs/images/monitor-alert.gif

# Run from the repo root:
#   cd /path/to/anglerfish
#   vhs docs/recordings/monitor-alert.tape
#
# Requires: vhs, ffmpeg, ttyd (see docs/plans/2026-03-08-arsenal-readme-improvements.md)
# Output:   docs/images/monitor-alert.gif

Set Theme "Dracula"
Set FontSize 13
Set Width 1200
Set Height 400
Set TypingSpeed 50ms

# Show simulated canary access alert
Type "source .venv/bin/activate && anglerfish monitor --demo"
Enter
Sleep 3s

# End of recording
