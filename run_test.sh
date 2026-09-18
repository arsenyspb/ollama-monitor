#!/bin/bash
# Start Xvfb
Xvfb :99 -screen 0 1024x768x24 &
XVFB_PID=$!
export DISPLAY=:99

# Give Xvfb a moment to start
sleep 1

# Run xterm with make dashboard
xterm -geometry 120x40 -e "make dashboard" &
XTERM_PID=$!

# Give it some time to start and render
sleep 10

# Take a screenshot
scrot /tmp/dashboard.png

# Kill processes
kill $XTERM_PID
kill $XVFB_PID

# Run OCR on the screenshot
tesseract /tmp/dashboard.png /tmp/dashboard_ocr
cat /tmp/dashboard_ocr.txt
