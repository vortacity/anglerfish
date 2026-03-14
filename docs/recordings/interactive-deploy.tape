Output docs/images/interactive-deploy.gif

# Run from the repo root:
#   cd /path/to/anglerfish
#   vhs docs/recordings/interactive-deploy.tape
#
# Requires: vhs, ffmpeg, ttyd
# Output:   docs/images/interactive-deploy.gif

Set Theme "Dracula"
Set FontSize 16
Set Width 1200
Set Height 700
Set TypingSpeed 50ms

# Activate venv
Type "source .venv/bin/activate"
Enter
Sleep 1s
Ctrl+L

# Deploy canary non-interactively — command is the story, success panel is the payoff
Type "anglerfish --demo --non-interactive --canary-type outlook --template 'Fake Password Reset' --target adele.vance@contoso.com"
Enter
Sleep 5s

# End of recording
