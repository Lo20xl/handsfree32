"""Discriminator round 2 — colorkey done RIGHT (class brush), layered alpha,
ULW re-test with buffer proof at call time, session/dwm diagnostics.
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
LWA_ALPHA = 0x02
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
HWND_TOPMOST = -1
SWP_NOMOVE = 2; SWP_NOSIZE = 1; SWP_NOACTIVATE = 0x10
COLOR_RED = 0x000000FF  # COLORREF

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
u.SetLayeredWindowAttributes.restype = wintypes.BOOL
u.GetDC.argtypes = [wintypes.HWND]; u.GetDC.restype = wintypes.HDC
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, wintypes.UINT]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.IsWindowVisible.argtypes = [wintypes.HWND]; u.IsWindowVisible.restype = wintypes.BOOL
g.CreateCompatibleDC.argtypes = [wintypes.HDC]; g.CreateCompatibleDC.restype = wintypes.HDC
g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                               ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
g.CreateDIBSection.restype = wintypes.HANDLE
g.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]; g.SelectObject.restype = wintypes.HANDLE
g.CreateSolidBrush.argtypes = [wintypes.DWORD]; g.CreateSolidBrush.restype = wintypes.HBRUSH
k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]; k.GetModuleHandleW.restype = wintypes.HMODULE
k.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]

import numpy as np

refs = []
def wndproc(hwnd, msg, wparam, lparam):
    if msg == 0x0010:
        u.DestroyWindow(hwnd)
        return 0
    return u.DefWindowProcW(hwnd, msg, wparam, lparam)

def main():
    # session diagnostics
    pid = k.GetCurrentProcessId()
    sid = wintypes.DWORD(0)
    k.ProcessIdToSessionId(pid, ctypes.byref(sid))
    log(f"test pid={pid} session={sid.value} console_session={k.WTSGetActiveConsoleSessionId() if hasattr(k,'WTSGetActiveConsoleSessionId') else '?'}")

    ref = WNDPROC(wndproc); refs.append(ref)
    hinst = k.GetModuleHandleW(None)

    def make_class(name, brush):
        cls = WNDCLASSW()
        cls.lpfnWndProc = ref
        cls.hInstance = hinst
        cls.lpszClassName = name
        cls.hbrBackground = brush
        u.RegisterClassW(ctypes.byref(cls))

    red_brush = g.CreateSolidBrush(COLOR_RED)
    make_class("HJDisc2E", red_brush)   # colorkey
    make_class("HJDisc2F", red_brush)   # alpha
    make_class("HJDisc2G", None)        # ULW

    hwnds = {}

    # E: colorkey — class brush paints red; key out black
    he = u.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        "HJDisc2E", "E", WS_POPUP, 100, 100, 300, 300, None, None, hinst, None)
    oke = u.SetLayeredWindowAttributes(he, 0x000000, 0, LWA_COLORKEY)
    u.ShowWindow(he, SW_SHOWNOACTIVATE)
    hwnds["E_colorkey"] = he
    log(f"E colorkey set ok={oke} err={ctypes.get_last_error()}")

    # F: layered alpha 180 — class brush red
    hf = u.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        "HJDisc2F", "F", WS_POPUP, 500, 100, 300, 300, None, None, hinst, None)
    okf = u.SetLayeredWindowAttributes(hf, 0, 180, LWA_ALPHA)
    u.ShowWindow(hf, SW_SHOWNOACTIVATE)
    hwnds["F_alpha180"] = hf
    log(f"F alpha set ok={okf} err={ctypes.get_last_error()}")

    # G: ULW small (400x300 at 900,100) with buffer proof at call time
    screen_dc = u.GetDC(None)
    mem_dc = g.CreateCompatibleDC(screen_dc)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER); bmi.biWidth = 400; bmi.biHeight = -300
    bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
    bits = ctypes.c_void_p()
    bmp = g.CreateDIBSection(mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    g.SelectObject(mem_dc, bmp)
    canvas = np.zeros((300, 400, 4), dtype=np.uint8)
    canvas[:, :, 2] = 255
    canvas[:, :, 3] = 255
    ctypes.memmove(bits, canvas.ctypes.data, 400 * 300 * 4)
    chk = ctypes.string_at(bits, 16)
    log(f"G buffer[0]: {tuple(chk[:4])} (expect 0,0,255,255)")
    hg = u.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
        "HJDisc2G", "G", WS_POPUP, 900, 100, 400, 300, None, None, hinst, None)
    size = wintypes.SIZE(400, 300); src = wintypes.POINT(0, 0)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    okg = u.UpdateLayeredWindow(hg, screen_dc, None, None, mem_dc, ctypes.byref(src), 0,
                                ctypes.byref(blend), ULW_ALPHA)
    log(f"G ULW ok={okg} err={ctypes.get_last_error()}")
    u.SetWindowPos(hg, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    u.ShowWindow(hg, SW_SHOWNOACTIVATE)
    hwnds["G_ulw"] = hg

    for name, hwnd in hwnds.items():
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        log(f"{name}: hwnd={hwnd} rect=({r.left},{r.top},{r.right},{r.bottom}) visible={u.IsWindowVisible(hwnd)}")

    time.sleep(2.0)

    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)
    px = img.load()

    def count_red(x0, y0, x1, y1):
        n = 0
        for yy in range(y0, y1, 4):
            for xx in range(x0, x1, 4):
                r, gg, b = px[xx, yy][:3]
                if r > 150 and gg < 100 and b < 100:
                    n += 1
        return n

    log(f"PIL: E_colorkey red={count_red(100,100,400,400)}  F_alpha red={count_red(500,100,800,400)}  G_ulw red={count_red(900,100,1300,400)}")

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
                return int(((r > 150) & (gg < 100) & (b < 100)).sum())
            log(f"WGC: E red={wred(100,100,400,400)}  F red={wred(500,100,800,400)}  G red={wred(900,100,1300,400)}")
    except Exception as e:
        log(f"WGC failed: {e!r}")

    for hwnd in hwnds.values():
        u.DestroyWindow(hwnd)
    log("DONE")
    return 0

if __name__ == "__main__":
    sys.exit(main())
