@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe -c "from PIL import ImageGrab; img=ImageGrab.grab(); img.save(r'C:\Users\tangy\Desktop\HandJob3000\build\desktop_now2.png')" > C:\Users\tangy\Desktop\HandJob3000\build\shot_now_out.txt 2>&1
echo SHOT_DONE >> C:\Users\tangy\Desktop\HandJob3000\build\shot_now_out.txt
