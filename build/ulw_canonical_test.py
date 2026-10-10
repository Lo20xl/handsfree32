"""Canonical ULW test — is the failure the NULL position/size args, or the machine?

A: layered bit set AFTER creation via SetWindowLong, ULW with EXPLICIT pptDst/psize
B: layered bit at creation, ULW with EXPLICIT pptDst/psize
C: layered bit at creation, cleared + re-set via SetWindowLong, ULW explicit
K: control LWA_COLORKEY red window (proves the capture method sees content)

Capture: typed BitBlt + CAPTUREBLT (sees layered windows), in-process, as user.
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
SW_SHOW = 5
ULW_ALPHA = 0x02
LWA_COLORKEY = 0x01
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
GWL_EXSTYLE = -20
HWND_TOPMOST = -1
SWP_NOMOVE = 2; SWP_NOSIZE = 1; SWP_NOACTIVATE = 0x10
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000

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
u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]; u.GetWindowLongW.restype = ctypes.c_long
u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]; u.SetWindowLongW.restype = ctypes.c_long
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
g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                               ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
g.CreateDIBSection.restype = wintypes.HANDLE
g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
g.CreateCompatibleBitmap.restype = wintypes.HANDLE
g.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]; g.SelectObject.restype = wintypes.HANDLE
g.CreateSolidBrush.argtypes = [wintypes.DWORD]; g.CreateSolidBrush.restype = wintypes.HBRUSH
g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                     wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
g.BitBlt.restype = wintypes.BOOL
g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
g.GetDIBits.restype = ctypes.c_int
k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]; k.GetModuleHandleW.restype = wintypes.HMODULE

import numpy as np

refs = []
def wndproc(hwnd, msg, wparam, lparam):
    if msg == 0x0010:
        u.DestroyWindow(hwnd)
        return 0
    return u.DefWindowProcW(hwnd, msg, wparam, lparam)

def main():
    ref = WNDPROC(wndproc); refs.append(ref)
    hinst = k.GetModuleHandleW(None)
    cls = WNDCLASSW()
    cls.lpfnWndProc = ref
    cls.hInstance = hinst
    cls.lpszClassName = "HJCanon"
    u.RegisterClassW(ctypes.byref(cls))

    screen_dc = u.GetDC(None)
    W, H = 300, 300

    # red canvas
    canvas = np.zeros((H, W, 4), dtype=np.uint8)
    canvas[:, :, 2] = 255   # R
    canvas[:, :, 3] = 255   # A

    def make_memdc():
        mem = g.CreateCompatibleDC(screen_dc)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER); bmi.biWidth = W; bmi.biHeight = -H
        bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
        bits = ctypes.c_void_p()
        bmp = g.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        g.SelectObject(mem, bmp)
        ctypes.memmove(bits, canvas.ctypes.data, W * H * 4)
        return mem

    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    src = wintypes.POINT(0, 0)

    def canonical(hwnd, x, y):
        dst = wintypes.POINT(x, y)
        size = wintypes.SIZE(W, H)
        ok = u.UpdateLayeredWindow(hwnd, screen_dc, ctypes.byref(dst), ctypes.byref(size),
                                   mem, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
        u.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        u.ShowWindow(hwnd, SW_SHOW)
        return ok

    base_ex = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
    mem = make_memdc()
    hwnds = {}

    # A: layered bit AFTER creation
    hA = u.CreateWindowExW(base_ex, "HJCanon", "A", WS_POPUP, 100, 100, W, H, None, None, hinst, None)
    u.SetWindowLongW(hA, GWL_EXSTYLE, u.GetWindowLongW(hA, GWL_EXSTYLE) | WS_EX_LAYERED)
    oka = canonical(hA, 100, 100)
    hwnds["A"] = (hA, oka)

    # B: layered at creation, explicit args
    hB = u.CreateWindowExW(base_ex | WS_EX_LAYERED, "HJCanon", "B", WS_POPUP, 500, 100, W, H, None, None, hinst, None)
    okb = canonical(hB, 500, 100)
    hwnds["B"] = (hB, okb)

    # C: layered at creation, cleared + re-set, explicit
    hC = u.CreateWindowExW(base_ex | WS_EX_LAYERED, "HJCanon", "C", WS_POPUP, 900, 100, W, H, None, None, hinst, None)
    u.SetWindowLongW(hC, GWL_EXSTYLE, u.GetWindowLongW(hC, GWL_EXSTYLE) & ~WS_EX_LAYERED)
    u.SetWindowLongW(hC, GWL_EXSTYLE, u.GetWindowLongW(hC, GWL_EXSTYLE) | WS_EX_LAYERED)
    okc = canonical(hC, 900, 100)
    hwnds["C"] = (hC, okc)

    # K: control colorkey window, class brush won't paint; draw red via window DC + key out black
    hK = u.CreateWindowExW(base_ex | WS_EX_LAYERED, "HJCanon", "K", WS_POPUP, 1300, 100, W, H, None, None, hinst, None)
    kdc = u.GetDC(hK)
    brush = g.CreateSolidBrush(0x000000FF)  # COLORREF red
    u.FillRect.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.HBRUSH]
    rk = wintypes.RECT(0, 0, W, H)
    u.FillRect(kdc, ctypes.byref(rk), brush)
    u.ReleaseDC(hK, kdc)
    u.SetLayeredWindowAttributes(hK, 0x000000, 0, LWA_COLORKEY)
    u.ShowWindow(hK, SW_SHOW)
    hwnds["K"] = (hK, True)

    for n, (hw, ok) in hwnds.items():
        log(f"{n}: ulw_ok={ok} visible={u.IsWindowVisible(hw)} err={ctypes.get_last_error()}")

    time.sleep(1.2)

    # capture the strip with CAPTUREBLT
    sw, sh = 1920, 1080
    mem2 = g.CreateCompatibleDC(screen_dc)
    bmp2 = g.CreateCompatibleBitmap(screen_dc, sw, sh)
    g.SelectObject(mem2, bmp2)
    okc2 = g.BitBlt(mem2, 0, 0, sw, sh, screen_dc, 0, 0, SRCCOPY | CAPTUREBLT)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER); bmi.biWidth = sw; bmi.biHeight = -sh
    bmi.biPlanes = 1; bmi.biBitCount = 32; bmi.biCompression = 0
    buf = ctypes.create_string_buffer(sw * sh * 4)
    n = g.GetDIBits(mem2, bmp2, 0, sh, buf, ctypes.byref(bmi), 0)
    arr = np.frombuffer(buf.raw, dtype=np.uint8).reshape(sh, sw, 4)
    log(f"capture blt_ok={okc2} rows={n}")

    for name, (x, y) in {"A": (150, 150), "B": (550, 150), "C": (950, 150), "K": (1350, 150)}.items():
        box = arr[y:y+200, x:x+200]
        red = int(((box[:, :, 2] > 180) & (box[:, :, 1] < 90) & (box[:, :, 0] < 90)).sum())
        log(f"{name} red_pixels@({x},{y}..): {red} / 40000")
        cy, cx = 250, x + 100
        log(f"   center px: {tuple(int(v) for v in arr[cy, cx])}")

    for hw, _ in hwnds.values():
        u.DestroyWindow(hw)
    log("DONE")
    return 0

if __name__ == "__main__":
    sys.exit(main())
