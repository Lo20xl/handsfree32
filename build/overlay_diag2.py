"""Overlay render diagnosis v2 — find why the orb never reaches the screen.

Instruments UpdateLayeredWindow (records ok + GetLastError per call), then
captures the screen BOTH ways: PIL ImageGrab (no CAPTUREBLT) and a raw BitBlt
WITH CAPTUREBLT (which includes layered windows). If the orb appears only in
the CAPTUREBLT shot, rendering is fine and only the capture was blind.
"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = os.path.dirname(os.path.abspath(__file__))

def log(msg):
    print(msg, flush=True)

from handjob.engine import CursorBus
from handjob.overlay import Overlay
import handjob.overlay as ovmod

bus = CursorBus()
ov = Overlay(bus, fps=60)

# instrument UpdateLayeredWindow BEFORE the thread starts
ulw_log = []
orig_ulw = ovmod.user32.UpdateLayeredWindow
def ulw_spy(hwnd, hdc_dst, ppt_dst, psize, hdc_src, ppt_src, cr_key, pblend, flags):
    r = orig_ulw(hwnd, hdc_dst, ppt_dst, psize, hdc_src, ppt_src, cr_key, pblend, flags)
    err = ctypes.get_last_error()
    if len(ulw_log) < 5 or r == 0:
        ulw_log.append((bool(r), err))
    return r
ovmod.user32.UpdateLayeredWindow = ulw_spy

ov.start()
time.sleep(1.0)

with bus.lock:
    bus.armed = True
    bus.found = True
    bus.dim = False
    bus.position = (700.0, 500.0)
    bus.style = "sky"

time.sleep(1.5)
log(f"error={bus.error!r} visible={ov._visible} loop_errors={getattr(ov,'_loop_errors',0)}")
log(f"ULW results (first 5 + any failures): {ulw_log[:8]}")

# window geometry
u = ovmod.user32
hwnd = ov._hwnd
rect = wintypes.RECT()
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.GetWindowRect(hwnd, ctypes.byref(rect))
log(f"GetWindowRect: ({rect.left},{rect.top})-({rect.right},{rect.bottom})")
log(f"IsWindowVisible={u.IsWindowVisible(hwnd)} IsIconic={u.IsIconic(hwnd)}")

# --- capture 1: PIL ImageGrab (no CAPTUREBLT) ---
from PIL import Image
try:
    from PIL import ImageGrab
    img1 = ImageGrab.grab(all_screens=True)
    img1.save(os.path.join(OUT, "diag2_pil.png"))
    px = img1.load()
    sky = sum(1 for yy in range(455, 545, 3) for xx in range(655, 745, 3)
              if (lambda c: c[2] > 180 and 120 < c[1] < 230 and c[0] < 140)(px[xx, yy][:3]))
    log(f"PIL grab: {img1.size}, SKY_PIXELS={sky}, @700,500={px[700,500]}")
except Exception as e:
    log(f"PIL grab failed: {e!r}")

# --- capture 2: raw BitBlt with CAPTUREBLT ---
try:
    gdi32 = ovmod.gdi32
    user32 = ovmod.user32
    SRCCOPY = 0x00CC0020
    CAPTUREBLT = 0x40000000
    w, h = 1920, 1080
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HANDLE
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    ok = gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, 0, 0, SRCCOPY | CAPTUREBLT)
    log(f"BitBlt CAPTUREBLT ok={ok}")

    class BMIH(ctypes.Structure):
        _fields_ = (("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD))
    bmi = BMIH()
    bmi.biSize = ctypes.sizeof(BMIH); bmi.biWidth = w; bmi.biHeight = -h
    bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.POINTER(BMIH), wintypes.UINT]
    n = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    data = buf.raw
    img2 = Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", 0, 1)
    img2.save(os.path.join(OUT, "diag2_captureblt.png"))
    px = img2.load()
    sky = 0
    for yy in range(455, 545, 3):
        for xx in range(655, 745, 3):
            r_, g_, b_, a_ = px[xx, yy]
            if b_ > 180 and 120 < g_ < 230 and r_ < 140:
                sky += 1
    log(f"CAPTUREBLT grab rows={n}: SKY_PIXELS={sky}, @700,500={px[700,500]}")
except Exception as e:
    log(f"CAPTUREBLT path failed: {e!r}")

with bus.lock:
    bus.armed = False
time.sleep(0.3)
ov.stop()
log("DONE")
