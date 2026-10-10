"""ULW final matrix — isolate why UpdateLayeredWindow never composites here.

H: ULW, DIB-section source, WITHOUT WS_EX_TRANSPARENT
I: ULW, compatible-bitmap source (SetDIBits), without WS_EX_TRANSPARENT
J: ULW, compatible-bitmap source, WITH WS_EX_TRANSPARENT
K: control — same flags as H but LWA_ALPHA instead of ULW (must show)

Captures: PIL + WGC red counts per region.
"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def log(m): print(m, flush=True)

u = ctypes.WinDLL("user32", use_last_error=True)
g = ctypes.WinDLL("gdi32", use_last_error=True)
k = ctypes.WinDLL("kernel32", use_last_error=True)

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x02
LWA_ALPHA = 0x02
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
HWND_TOPMOST = -1
SWP_NOMOVE = 2; SWP_NOSIZE = 1; SWP_NOACTIVATE = 0x10
COLOR_RED = 0x000000FF

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
u.IsWindowVisible.argtypes = [wintypes.HWND]; u.IsWindowVisible.restype = wintypes.BOOL
g.CreateCompatibleDC.argtypes = [wintypes.HDC]; g.CreateCompatibleDC.restype = wintypes.HDC
g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
g.CreateCompatibleBitmap.restype = wintypes.HANDLE
g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                               ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
g.CreateDIBSection.restype = wintypes.HANDLE
g.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]; g.SelectObject.restype = wintypes.HANDLE
g.SetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                        ctypes.c_void_p, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT]
g.SetDIBits.restype = ctypes.c_int
k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]; k.GetModuleHandleW.restype = wintypes.HMODULE

import numpy as np

refs = []
def wndproc(hwnd, msg, wparam, lparam):
    if msg == 0x0010:
        u.DestroyWindow(hwnd)
        return 0
    return u.DefWindowProcW(hwnd, msg, wparam, lparam)

def red_canvas(w, h):
    c = np.zeros((h, w, 4), dtype=np.uint8)
    c[:, :, 2] = 255
    c[:, :, 3] = 255
    return c

def main():
    ref = WNDPROC(wndproc); refs.append(ref)
    hinst = k.GetModuleHandleW(None)
    cls = WNDCLASSW()
    cls.lpfnWndProc = ref
    cls.hInstance = hinst
    cls.lpszClassName = "HJMatrix"
    u.RegisterClassW(ctypes.byref(cls))

    screen_dc = u.GetDC(None)
    W, H = 400, 300
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    src = wintypes.POINT(0, 0)
    size = wintypes.SIZE(W, H)
    canvas = red_canvas(W, H)

    def make_ulw(x, y, dib_source, transparent):
        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if transparent:
            ex |= WS_EX_TRANSPARENT
        hwnd = u.CreateWindowExW(ex, "HJMatrix", "M", WS_POPUP,
                                 x, y, W, H, None, None, hinst, None)
        mem_dc = g.CreateCompatibleDC(screen_dc)
        if dib_source:
            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER); bmi.biWidth = W; bmi.biHeight = -H
            bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
            bits = ctypes.c_void_p()
            bmp = g.CreateDIBSection(mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            g.SelectObject(mem_dc, bmp)
            ctypes.memmove(bits, canvas.ctypes.data, W * H * 4)
        else:
            bmp = g.CreateCompatibleBitmap(screen_dc, W, H)
            g.SelectObject(mem_dc, bmp)
            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER); bmi.biWidth = W; bmi.biHeight = -H
            bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
            r = g.SetDIBits(mem_dc, bmp, 0, H, canvas.ctypes.data, ctypes.byref(bmi), 0)
            log(f"    SetDIBits rows={r}")
        ok = u.UpdateLayeredWindow(hwnd, screen_dc, None, None, mem_dc, ctypes.byref(src), 0,
                                   ctypes.byref(blend), ULW_ALPHA)
        u.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        log(f"    ULW ok={ok} err={ctypes.get_last_error()} visible={u.IsWindowVisible(hwnd)}")
        return hwnd

    hwnds = {}
    log("H: ULW DIB-section, NO transparent flag")
    hwnds["H"] = make_ulw(100, 100, True, False)
    log("I: ULW compatible-bitmap, NO transparent flag")
    hwnds["I"] = make_ulw(600, 100, False, False)
    log("J: ULW compatible-bitmap, WITH transparent flag")
    hwnds["J"] = make_ulw(1100, 100, False, True)

    log("K: control LWA_ALPHA window")
    hk = u.CreateWindowExW(WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                           "HJMatrix", "K", WS_POPUP, 100, 500, W, H, None, None, hinst, None)
    cls_bg = g.CreateSolidBrush(COLOR_RED)
    # paint K via WM_PAINT would need a proc; cheat: set class bg — but class already made.
    # Instead: use SetLayeredWindowAttributes + paint via sending WM_PAINT won't work; use
    # FillRect on its DC directly:
    kdc = u.GetDC(hk)
    rk = wintypes.RECT(0, 0, W, H)
    u.FillRect(kdc, ctypes.byref(rk), cls_bg)
    u.ReleaseDC(hk, kdc)
    okk = u.SetLayeredWindowAttributes(hk, 0, 200, LWA_ALPHA)
    u.ShowWindow(hk, SW_SHOWNOACTIVATE)
    hwnds["K"] = hk
    log(f"    K ok={okk} err={ctypes.get_last_error()}")

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

    log(f"PIL: H red={count_red(100,100,500,400)}  I red={count_red(600,100,1000,400)}  "
        f"J red={count_red(1100,100,1500,400)}  K red={count_red(100,500,500,800)}")

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
            log(f"WGC: H red={wred(100,100,500,400)}  I red={wred(600,100,1000,400)}  "
                f"J red={wred(1100,100,1500,400)}  K red={wred(100,500,500,800)}")
    except Exception as e:
        log(f"WGC failed: {e!r}")

    for h in hwnds.values():
        u.DestroyWindow(h)
    log("DONE")
    return 0

if __name__ == "__main__":
    sys.exit(main())
