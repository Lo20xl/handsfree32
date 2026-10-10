"""Overlay diagnosis v3 — typed CAPTUREBLT capture + DIB buffer inspection.

1. Arm overlay, orb at (700,500).
2. Read the actual DIB pixel bytes at the orb center (proves buffer content).
3. Screen capture WITH CAPTUREBLT (includes layered windows; PIL's grab is blind to them).
4. PrintWindow of the overlay window.
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
ov.start()
time.sleep(1.0)

with bus.lock:
    bus.armed = True
    bus.found = True
    bus.dim = False
    bus.position = (700.0, 500.0)
    bus.style = "sky"

time.sleep(1.2)
log(f"error={bus.error!r} visible={ov._visible} loop_errors={getattr(ov,'_loop_errors',0)}")

w, h = ov._w, ov._h
log(f"window size: {w}x{h}")

# --- 1) DIB buffer content at orb center ---
try:
    off = (500 * w + 700) * 4
    raw = ctypes.string_at(ov._bits, off + 16)
    b, g, r, a = raw[off], raw[off+1], raw[off+2], raw[off+3]
    log(f"DIB px @700,500: B={b} G={g} R={r} A={a}  (expect ~248/189/56/255)")
    off2 = (500 * w + 700 - 8) * 4
    log(f"DIB px @692,500: {tuple(raw[off2:off2+4])}")
except Exception as e:
    log(f"DIB read failed: {e!r}")

# --- 2) typed helpers ---
gdi32 = ovmod.gdi32
user32 = ovmod.user32
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000

gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HANDLE
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.SelectObject.restype = wintypes.HANDLE
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int

class BMIH(ctypes.Structure):
    _fields_ = (("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD))

def grab(captureblt):
    from PIL import Image
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    flags = SRCCOPY | (CAPTUREBLT if captureblt else 0)
    ok = gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, 0, 0, flags)
    bmi = BMIH()
    bmi.biSize = ctypes.sizeof(BMIH); bmi.biWidth = w; bmi.biHeight = -h
    bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    n = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    return ok, n, buf.raw

# --- 3) capture with CAPTUREBLT ---
try:
    from PIL import Image
    ok, n, data = grab(True)
    img = Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", 0, 1)
    img.save(os.path.join(OUT, "diag3_captureblt.png"))
    px = img.load()
    sky = 0
    for yy in range(450, 550, 2):
        for xx in range(650, 750, 2):
            r_, g_, b_, a_ = px[xx, yy]
            if b_ > 180 and 120 < g_ < 230 and r_ < 140:
                sky += 1
    log(f"CAPTUREBLT ok={ok} rows={n}: SKY_PIXELS={sky} @700,500={px[700,500]}")
except Exception as e:
    log(f"CAPTUREBLT failed: {e!r}")

# --- 4) capture WITHOUT CAPTUREBLT (same path, control) ---
try:
    from PIL import Image
    ok, n, data = grab(False)
    img = Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", 0, 1)
    px = img.load()
    sky = 0
    for yy in range(450, 550, 2):
        for xx in range(650, 750, 2):
            r_, g_, b_, a_ = px[xx, yy]
            if b_ > 180 and 120 < g_ < 230 and r_ < 140:
                sky += 1
    log(f"no-CAPTUREBLT: SKY_PIXELS={sky} @700,500={px[700,500]}")
except Exception as e:
    log(f"no-CAPTUREBLT failed: {e!r}")

# --- 5) PrintWindow of the overlay window ---
try:
    from PIL import Image
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    pok = user32.PrintWindow(ov._hwnd, mem_dc, 2)  # PW_RENDERFULLCONTENT
    bmi = BMIH()
    bmi.biSize = ctypes.sizeof(BMIH); bmi.biWidth = w; bmi.biHeight = -h
    bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    n = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    data = buf.raw
    img = Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", 0, 1)
    img.save(os.path.join(OUT, "diag3_printwindow.png"))
    px = img.load()
    sky = 0
    for yy in range(450, 550, 2):
        for xx in range(650, 750, 2):
            r_, g_, b_, a_ = px[xx, yy]
            if b_ > 180 and 120 < g_ < 230 and r_ < 140:
                sky += 1
    log(f"PrintWindow ok={pok} rows={n}: SKY_PIXELS={sky} @700,500={px[700,500]}")
except Exception as e:
    log(f"PrintWindow failed: {e!r}")

with bus.lock:
    bus.armed = False
time.sleep(0.3)
ov.stop()
log("DONE")
