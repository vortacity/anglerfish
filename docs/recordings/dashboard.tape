Output docs/images/dashboard.gif

# Run from the repo root:
#   cd /path/to/anglerfish
#   vhs docs/recordings/dashboard.tape
#
# Requires: vhs, ffmpeg, ttyd
# Output:   docs/images/dashboard.gif

Set Theme "Dracula"
Set FontSize 16
Set Width 1200
Set Height 650
Set TypingSpeed 80ms

# Activate venv
Type "source .venv/bin/activate"
Enter
Sleep 1s
Ctrl+L

# Launch dashboard in demo mode
Type "anglerfish dashboard --demo"
Enter
Sleep 4s

# Trigger first alert (r = refresh in demo mode → generates synthetic alert on right panel)
Type "r"
Sleep 3s

# Trigger second alert
Type "r"
Sleep 2s

# Quit
Type "q"
Sleep 1s

# End of recording
