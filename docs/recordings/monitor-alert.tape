Output docs/images/monitor-alert.gif

# Run from the repo root:
#   cd /path/to/anglerfish
#   vhs docs/recordings/monitor-alert.tape
#
# Requires: vhs, ffmpeg, ttyd
# Output:   docs/images/monitor-alert.gif

Set Theme "Dracula"
Set FontSize 16
Set Width 1200
Set Height 400
Set TypingSpeed 80ms

# Activate venv
Type "source .venv/bin/activate"
Enter
Sleep 1s
Ctrl+L

# Show one Outlook MailItemsAccessed alert for the primary demo path.
Type "anglerfish monitor --demo --count 1"
Enter
Sleep 5s

# End of recording
