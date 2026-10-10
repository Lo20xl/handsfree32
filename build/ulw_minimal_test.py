"""Minimal ULW smoke test: draw a red square via UpdateLayeredWindow, then
verify with Windows.Graphics.Capture. No PIL, no threads, textbook recipe.
Also reports DWM cloak state + actual extended styles of the window.
"""
import sys, os, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def log(m): print(m, flush=True)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x02
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

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

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                       ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                       ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
                                       ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]; user32.GetDC.restype = wintypes.HDC
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]; user32.GetWindowLongW.restype = wintypes.LONG
user32.IsWindowVisible.argtypes = [wintypes.HWND]; user32.IsWindowVisible.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]; gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HANDLE
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]; gdi32.SelectObject.restype = wintypes.HANDLE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]; kernel32.GetModuleHandleW.restype = wintypes.HMODULE

W, H = 1920, 1080

def wndproc(hwnd, msg, wparam, lparam):
    if msg == 0x0010:
        user32.DestroyWindow(hwnd)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

def main():
    ref = WNDPROC(wndproc)
    hinst = kernel32.GetModuleHandleW(None)
    cls = WNDCLASSW()
    cls.lpfnWndProc = ref
    cls.hInstance = hinst
    cls.lpszClassName = "HJMinimalULWTest"
    if not user32.RegisterClassW(ctypes.byref(cls)):
        err = ctypes.get_last_error()
        log(f"RegisterClassW err={err} (1410 = exists, ok)")
    ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
    hwnd = user32.CreateWindowExW(ex, "HJMinimalULWTest", "HJMinimalULWTest",
                                  WS_POPUP, 0, 0, W, H, None, None, hinst, None)
    log(f"hwnd={hwnd} err={ctypes.get_last_error()}")
    if not hwnd:
        return 1

    # build a red square (alpha 255) at (300,300)-(500,500), rest alpha 0
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER); bmi.biWidth = W; bmi.biHeight = -H
    bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    gdi32.SelectObject(mem_dc, bmp)
    log(f"mem_dc={mem_dc} bmp={bmp} bits={bits.value}")

    import numpy as np
    canvas = np.zeros((H, W, 4), dtype=np.uint8)
    canvas[300:500, 300:500, 2] = 255  # R premultiplied
    canvas[300:500, 300:500, 3] = 255  # A
    ctypes.memmove(bits, canvas.ctypes.data, W * H * 4)

    # verify buffer
    off = (400 * W + 400) * 4
    chk = ctypes.string_at(bits, off + 4)
    log(f"buffer @400,400: {tuple(chk[off:off+4])} (expect 0,0,255,255)")

    size = wintypes.SIZE(W, H)
    src = wintypes.POINT(0, 0)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    ok = user32.UpdateLayeredWindow(hwnd, screen_dc, None, None, mem_dc,
                                    ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
    log(f"ULW ok={ok} err={ctypes.get_last_error()}")
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    log(f"visible={user32.IsWindowVisible(hwnd)} exstyle=0x{user32.GetWindowLongW(hwnd, -20) & 0xffffffff:08x}")

    # DWM cloak check
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        cloak = ctypes.c_int(0)
        hr = dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloak), 4)  # DWMWA_CLOAKED
        log(f"DwmGetWindowAttribute cloaked hr={hr} cloaked={cloak.value}")
    except Exception as e:
        log(f"cloak check failed: {e!r}")

    # WGC capture check
    time.sleep(1.5)
    try:
        import numpy as np
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
        try:
            cap.stop()
        except Exception:
            pass  # free-threaded handle has no stop(); process exit cleans up
        f = got["f"]
        if f is not None:
            px = f[400, 400]
            log(f"WGC px @400,400: {tuple(int(v) for v in px[:4])} (expect ~0,0,255,255)")
            r_ = f[:, :, 2].astype(int); g_ = f[:, :, 1].astype(int); b_ = f[:, :, 0].astype(int)
            red = int(((r_ > 200) & (g_ < 80) & (b_ < 80)).sum())
            log(f"RED_PIXELS on screen: {red} (expect ~40000)")
        else:
            log("WGC got no frame")
    except Exception as e:
        log(f"WGC check failed: {e!r}")

    user32.DestroyWindow(hwnd)
    log("DONE")
    return 0

if __name__ == "__main__":
    sys.exit(main())
