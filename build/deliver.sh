#!/usr/bin/env bash
# Final delivery: copy the installer + README to Downloads. Run after build3 completes.
set -e
cd ~/Desktop/HandJob3000

# sanity gates before delivery
SETUP=$(ls dist-installer/HandJob3000-Setup-*.exe | tail -1)
test -n "$SETUP"
test -f dist/HandJob3000/HandJob3000.exe
head -c 2 "$SETUP" | od -c | head -1

# frozen selftest (model load in the packaged exe)
"dist/HandJob3000/HandJob3000.exe" --selftest

# copy to Downloads (user asked: folder in Downloads or Drive; no Drive mounted)
cp -f "$SETUP" ~/Downloads/$(basename "$SETUP")
cp -f README-INSTALL.txt ~/Downloads/HandJob3000-README.txt
# ...and as a ready-to-transfer folder
mkdir -p ~/Downloads/HandJob3000
cp -f "$SETUP" README-INSTALL.txt ~/Downloads/HandJob3000/
ls -la ~/Downloads/HandJob3000-Setup-*.exe ~/Downloads/HandJob3000-README.txt ~/Downloads/HandJob3000/

# zip (exe + README) alongside, for drag-drop transfer — name follows the built setup
cd ~/Downloads
ZIP="$(basename "$SETUP" .exe).zip"
rm -f "$ZIP"
"/c/Program Files/7-Zip/7z.exe" a -tzip -mx=5 "$ZIP" "$(basename "$SETUP")" HandJob3000-README.txt | tail -2
ls -la "$ZIP"
echo DELIVERY_DONE
