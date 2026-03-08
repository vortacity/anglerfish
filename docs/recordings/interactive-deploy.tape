Output docs/images/interactive-deploy.gif

# Run from the repo root:
#   cd /path/to/anglerfish
#   vhs docs/recordings/interactive-deploy.tape
#
# Requires: vhs, ffmpeg, ttyd (see docs/plans/2026-03-08-arsenal-readme-improvements.md)
# Output:   docs/images/interactive-deploy.gif

Set Theme "Dracula"
Set FontSize 13
Set Width 1200
Set Height 700
Set TypingSpeed 50ms

# Activate venv and run demo
Type "source .venv/bin/activate && anglerfish --demo"
Enter
Sleep 3s

# Select canary type: Outlook (first item, already selected)
Enter
Sleep 1s

# Select template: Fake Password Reset (first item, already selected)
Enter
Sleep 1s

# Accept default target_name: User
Enter
Sleep 1s

# Select delivery mode: Draft (first item, already selected)
Enter
Sleep 1s

# Accept default hidden folder name: IT Notifications
Enter
Sleep 1s

# Enter target mailbox
Type "cfo@contoso.com"
Enter
Sleep 4s

# End of recording
