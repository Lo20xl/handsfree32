@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
set HJ3_FAKE_CAM=C:\Users\tangy\Desktop\HandJob3000\assets\woman_hands.jpg
start "" ".venv\Scripts\pythonw.exe" -m handjob.main
echo FAKECAM_LAUNCHED
