"""Discriminator: which window/transparency technique actually composites here?

A: regular WS_POPUP topmost window, red bg            @ (600,200)-(900,500)
B: ULW layered fullscreen, red square                 @ (300,300)-(500,500)
C: color-key layered window (LWA_COLORKEY), red paint @ (1200,200)-(1500,500)
D: small ULW layered window 200x200                   @ (1000,700)-(1200,900)

Then PIL-grabs the screen in-process and counts red pixels per region.
"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def log(m): print(m, flush=True)

u = ctypes.WinDLL("user32", use_last_error=True)
g = ctypes.WinDLL("gdi32", use_last_error=True)
k = ctypes.WinDLL("kernel32", use_last_error=True)

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x02
LWA_COLORKEY = 0x01
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
HWND_TOPMOST = -1
SWP_NOMOVE = 2; SWP_NOSIZE = 1; SWP_NOACTIVATE = 0x10
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
COLOR_RED = 0x000000FF   # COLORREF BGR

class BLENDFUNCTION(ctypes.Structure):
    _fields_ = (("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte))

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD))

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

class WNDCLASSW(ctypes.Structure):
    _fields_ = (("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR))

u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.DefWindowProcW.restype = ctypes.c_ssize_t
u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]; u.RegisterClassW.restype = wintypes.ATOM
u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                              ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
u.CreateWindowExW.restype = wintypes.HWND
u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                  ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                  ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
                                  ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
u.UpdateLayeredWindow.restype = wintypes.BOOL
u.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_byte, wintypes.DWORD]
u.GetDC.argtypes = [wintypes.HWND]; u.GetDC.restype = wintypes.HDC
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, wintypes.UINT]
g.CreateCompatibleDC.argtypes = [wintypes.HDC]; g.CreateCompatibleDC.restype = wintypes.HDC
g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                               ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
g.CreateDIBSection.restype = wintypes.HANDLE
g.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]; g.SelectObject.restype = wintypes.HANDLE
k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]; k.GetModuleHandleW.restype = wintypes.HMODULE
u.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]; u.BeginPaint.restype = wintypes.HDC
u.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
u.FillRect.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.HBRUSH]
g.CreateSolidBrush.argtypes = [wintypes.DWORD]; g.CreateSolidBrush.restype = wintypes.HBRUSH

import numpy as np

refs = []
def wndproc(hwnd, msg, wparam, lparam):
    if msg == WM_PAINT:
        ps = ctypes.create_string_buffer(64)
        hdc = u.BeginPaint(hwnd, ps)
        r = wintypes.RECT(0, 0, 2000, 2000)
        u.FillRect(hdc, ctypes.byref(r), g.CreateSolidBrush(COLOR_RED))
        u.EndPaint(hwnd, ps)
        return 0
    if msg == WM_CLOSE:
        u.DestroyWindow(hwnd)
        return 0
    return u.DefWindowProcW(hwnd, msg, wparam, lparam)

def main():
    ref = WNDPROC(wndproc); refs.append(ref)
    hinst = k.GetModuleHandleW(None)

    def make_class(name, bg=None):
        cls = WNDCLASSW()
        cls.lpfnWndProc = ref
        cls.hInstance = hinst
        cls.lpszClassName = name
        cls.hbrBackground = g.CreateSolidBrush(bg) if bg is not None else None
        u.RegisterClassW(ctypes.byref(cls))

    make_class("HJDiscA", COLOR_RED)
    make_class("HJDiscC")
    make_class("HJDiscD")

    hwnds = {}

    # A: regular window, red bg via class brush
    hwnds["A_regular"] = u.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "HJDiscA", "A", WS_POPUP | WS_VISIBLE,
        600, 200, 300, 300, None, None, hinst, None)

    # C: color-key layered window
    hc = u.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
        "HJDiscC", "C", WS_POPUP, 1200, 200, 300, 300, None, None, hinst, None)
    u.SetLayeredWindowAttributes(hc, 0x000000, 0, LWA_COLORKEY)
    u.ShowWindow(hc, SW_SHOWNOACTIVATE)
    hwnds["C_colorkey"] = hc

    # B: ULW fullscreen
    screen_dc = u.GetDC(None)
    mem_dc = g.CreateCompatibleDC(screen_dc)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER); bmi.biWidth = 1920; bmi.biHeight = -1080
    bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
    bits = ctypes.c_void_p()
    bmp = g.CreateDIBSection(mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    g.SelectObject(mem_dc, bmp)
    canvas = np.zeros((1080, 1920, 4), dtype=np.uint8)
    canvas[300:500, 300:500, 2] = 255
    canvas[300:500, 300:500, 3] = 255
    ctypes.memmove(bits, canvas.ctypes.data, 1920 * 1080 * 4)
    hb = u.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
        "HJDiscC", "B", WS_POPUP, 0, 0, 1920, 1080, None, None, hinst, None)
    size = wintypes.SIZE(1920, 1080); src = wintypes.POINT(0, 0)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    okb = u.UpdateLayeredWindow(hb, screen_dc, None, None, mem_dc, ctypes.byref(src), 0,
                                ctypes.byref(blend), ULW_ALPHA)
    u.SetWindowPos(hb, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    u.ShowWindow(hb, SW_SHOWNOACTIVATE)
    hwnds["B_ulw_full"] = hb
    log(f"B ULW fullscreen ok={okb}")

    # D: small ULW
    mem_dc2 = g.CreateCompatibleDC(screen_dc)
    bmi2 = BITMAPINFOHEADER()
    bmi2.biSize = ctypes.sizeof(BITMAPINFOHEADER); bmi2.biWidth = 200; bmi2.biHeight = -200
    bmi2.biPlanes = 1; bmi2.biBitCount = 32; bmi2.biCompression = 0
    bits2 = ctypes.c_void_p()
    bmp2 = g.CreateDIBSection(mem_dc2, ctypes.byref(bmi2), 0, ctypes.byref(bits2), None, 0)
    g.SelectObject(mem_dc2, bmp2)
    canvas2 = np.zeros((200, 200, 4), dtype=np.uint8)
    canvas2[:, :, 2] = 255
    canvas2[:, :, 3] = 255
    ctypes.memmove(bits2, canvas2.ctypes.data, 200 * 200 * 4)
    hd = u.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
        "HJDiscD", "D", WS_POPUP, 1000, 700, 200, 200, None, None, hinst, None)
    size2 = wintypes.SIZE(200, 200)
    okd = u.UpdateLayeredWindow(hd, screen_dc, None, None, mem_dc2, ctypes.byref(src), 0,
                                ctypes.byref(blend), ULW_ALPHA)
    u.SetWindowPos(hd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    u.ShowWindow(hd, SW_SHOWNOACTIVATE)
    hwnds["D_ulw_small"] = hd
    log(f"D ULW small ok={okd}")

    for name, hwnd in hwnds.items():
        log(f"{name}: hwnd={hwnd} visible={u.IsWindowVisible(hwnd)}")

    time.sleep(2.0)

    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)
    px = img.load()

    def count_red(x0, y0, x1, y1):
        n = 0
        for yy in range(y0, y1, 4):
            for xx in range(x0, x1, 4):
                r, gg, b = px[xx, yy][:3]
                if r > 180 and gg < 90 and b < 90:
                    n += 1
        return n

    log(f"A_regular  (600,200)-(900,500):   red={count_red(600,200,900,500)}")
    log(f"B_ulw_full (300,300)-(500,500):   red={count_red(300,300,500,500)}")
    log(f"C_colorkey (1200,200)-(1500,500): red={count_red(1200,200,1500,500)}")
    log(f"D_ulw_small(1000,700)-(1200,900): red={count_red(1000,700,1200,900)}")

    # also capture the same via WGC for cross-check
    try:
        from windows_capture import WindowsCapture
        got = {"f": None}
        cap = WindowsCapture(cursor_capture=False, monitor_index=1)
        @cap.event
        def on_frame_arrived(frame, control):
            got["f"] = np.array(frame.frame_buffer)
        @cap.event
        def on_closed():
            pass
        cap.start_free_threaded()
        time.sleep(2.0)
        f = got["f"]
        if f is not None:
            def wred(x0, y0, x1, y1):
                box = f[y0:y1, x0:x1]
                r = box[:, :, 2].astype(int); gg = box[:, :, 1].astype(int); b = box[:, :, 0].astype(int)
                return int(((r > 180) & (gg < 90) & (b < 90)).sum())
            log(f"WGC: A red={wred(600,200,900,500)}  B red={wred(300,300,500,500)}  "
                f"C red={wred(1200,200,1500,500)}  D red={wred(1000,700,1200,900)}")
    except Exception as e:
        log(f"WGC cross-check failed: {e!r}")

    for hwnd in hwnds.values():
        u.DestroyWindow(hwnd)
    log("DONE")
    return 0

if __name__ == "__main__":
    sys.exit(main())
