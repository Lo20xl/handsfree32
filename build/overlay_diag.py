"""Overlay render diagnosis: instrument the blit, check window state, capture pixels.

Run as the logged-in user (session 1). Prints a report; screenshot saved to
build/overlay_diag_shot.png (screen) and build/overlay_diag_window.png (PrintWindow).
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

# instrument _blit before starting the thread
blit_log = []
orig_blit = ov._blit
def blit_spy(img):
    try:
        orig_blit(img)
        blit_log.append(("ok", img.getbbox()))
    except Exception as e:
        blit_log.append(("ERR", repr(e)))
        raise
ov._blit = blit_spy

ov.start()
time.sleep(1.0)
log(f"after start: error={bus.error!r} hwnd={ov._hwnd} visible={ov._visible}")

with bus.lock:
    bus.armed = True
    bus.found = True
    bus.dim = False
    bus.position = (700.0, 500.0)
    bus.style = "sky"

time.sleep(1.5)
log(f"after arm: error={bus.error!r} visible={ov._visible} loop_errors={getattr(ov,'_loop_errors',0)}")
log(f"blit calls: {len(blit_log)}; last 3: {blit_log[-3:]}")

# is the window real and visible?
user32 = ovmod.user32
hwnd = user32.FindWindowW("HandJob3500OverlayWnd", None)
log(f"FindWindowW -> {hwnd}; IsWindowVisible -> {user32.IsWindowVisible(hwnd)}")

# 1) capture the window itself via PrintWindow
try:
    from PIL import Image
    import ctypes as ct
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi32 = ovmod.gdi32
    w, h = ov._w, ov._h
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ct.c_int, ct.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HANDLE
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)

    class BITMAPINFOHEADER(ct.Structure):
        _fields_ = (("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD))
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ct.sizeof(BITMAPINFOHEADER); bmi.biWidth = w; bmi.biHeight = -h
    bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
    buf = ct.create_string_buffer(w * h * 4)
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                                ct.c_void_p, ct.POINTER(BITMAPINFOHEADER), wintypes.UINT]
    ok = user32.PrintWindow(hwnd, mem_dc, 2)  # PW_RENDERFULLCONTENT
    n = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ct.byref(bmi), 0)
    log(f"PrintWindow ok={ok} GetDIBits rows={n}")
    # count non-black pixels in BGRA buffer
    data = buf.raw
    nonzero = sum(1 for i in range(0, len(data), 4) if data[i] or data[i+1] or data[i+2] or data[i+3])
    log(f"PrintWindow nonzero px: {nonzero}")
    if nonzero:
        img = Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", 0, 1)
        img.save(os.path.join(OUT, "overlay_diag_window.png"))
        # sample around 700,500
        px = img.load()
        log(f"window px @700,500: {px[700,500]}")
        log(f"window px @700,488: {px[700,488]}")
except Exception as e:
    log(f"PrintWindow path failed: {e!r}")

# 2) screen capture
try:
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)
    img.save(os.path.join(OUT, "overlay_diag_shot.png"))
    px = img.load()
    log(f"screen px @700,500: {px[700,500]}")
    sky = 0
    for yy in range(455, 545, 3):
        for xx in range(655, 745, 3):
            r, g, b = px[xx, yy][:3]
            if b > 180 and 120 < g < 230 and r < 140:
                sky += 1
    log(f"screen SKY_PIXELS: {sky}")
except Exception as e:
    log(f"screen grab failed: {e!r}")

with bus.lock:
    bus.armed = False
time.sleep(0.3)
ov.stop()
log("DONE")
