"""HandJob3000 overlay cursor + trail — a click-through layered window.

Renders the custom cursor (GPT-sky orb / glow ring), the motion trail and the
drag sparkles as one transparent, always-on-top window covering the desktop.

Rendering (`render_frame`) is a pure PIL function so it can be tested headless;
this module keeps all Win32 bits in the Overlay thread class.
"""
import ctypes
import math
import random
import threading
import time
from ctypes import wintypes

from PIL import Image, ImageDraw

SKY = (56, 189, 248)
SKY_DEEP = (14, 165, 233)
SKY_PALE = (186, 230, 253)
WHITE = (255, 255, 255)
SPARK = (255, 245, 200)

CURSOR_R = 15          # orb radius at 100%
GLOW_R = 44


# ----------------------------------------------------------------------------
# Pure rendering — no Win32, testable with just PIL.
# ----------------------------------------------------------------------------

_LUT = None


def _premultiply_lut():
    """[alpha, channel] -> channel*alpha//255 lookup table (built once)."""
    import numpy as np
    global _LUT
    if _LUT is None:
        v = np.arange(256, dtype=np.uint16)
        _LUT = ((v[:, None] * v[None, :]) // 255).astype(np.uint8)
    return _LUT


def _premultiplied_bgra(img, out=None):
    """PIL RGBA image -> premultiplied BGRA uint8 array (UpdateLayeredWindow format).

    The overlay is mostly transparent, so: memset the reused buffer once, then
    premultiply ONLY the drawn bounding box with a LUT gather. Full-screen
    per-pixel math was measured at ~45-65 ms at 1080p; this path is ~2 ms.
    """
    import numpy as np
    arr = np.asarray(img, dtype=np.uint8)
    h, w = arr.shape[:2]
    if out is None or out.shape[0] != h or out.shape[1] != w:
        out = np.empty((h, w, 4), dtype=np.uint8)
    out.fill(0)
    bbox = img.getbbox()          # C-speed scan; None when fully transparent
    if bbox:
        x0, y0, x1, y1 = bbox
        sub = arr[y0:y1, x0:x1]
        dst = out[y0:y1, x0:x1]
        alpha = sub[:, :, 3]
        lut = _premultiply_lut()
        dst[:, :, 0] = lut[alpha, sub[:, :, 2]]   # B
        dst[:, :, 1] = lut[alpha, sub[:, :, 1]]   # G
        dst[:, :, 2] = lut[alpha, sub[:, :, 0]]   # R
        dst[:, :, 3] = alpha
    return out


def _premultiply_into(img, dst):
    """PIL RGBA -> premultiplied BGRA written straight into `dst`, an
    (h, w, 4) uint8 view (a sub-rectangle of the layered window's DIB).
    No full-screen buffer, no memmove: only the sprite's own pixels move."""
    import numpy as np
    arr = np.asarray(img, dtype=np.uint8)
    dst.fill(0)
    bbox = img.getbbox()
    if bbox:
        x0, y0, x1, y1 = bbox
        sub = arr[y0:y1, x0:x1]
        d = dst[y0:y1, x0:x1]
        alpha = sub[:, :, 3]
        lut = _premultiply_lut()
        d[:, :, 0] = lut[alpha, sub[:, :, 2]]
        d[:, :, 1] = lut[alpha, sub[:, :, 1]]
        d[:, :, 2] = lut[alpha, sub[:, :, 0]]
        d[:, :, 3] = alpha


def _premultiplied_bgra_bytes(img):
    """Compat wrapper returning raw bytes (tests / callers that need them)."""
    return _premultiplied_bgra(img).tobytes()


def _star(draw, x, y, r, fill):
    pts = []
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else r * 0.22
        pts.append((x + rr * math.cos(ang), y + rr * math.sin(ang)))
    draw.polygon(pts, fill=fill)


def draw_cursor_sky(d, x, y, scale=1.0, press=0.0, dim=False):
    """The GPT-sky orb: layered glow, glossy blue orb, white core."""
    r = CURSOR_R * scale
    glow = GLOW_R * scale
    alpha_mul = 0.45 if dim else 1.0
    steps = 6
    for i in range(steps):
        f = (i + 1) / steps
        rr = glow * f
        a = int((30 if not dim else 12) * (1.0 - f) * 255 / steps * 2.2 * alpha_mul)
        if a <= 0:
            continue
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=SKY + (a,))
    # orb body with vertical-ish highlight
    d.ellipse((x - r, y - r, x + r, y + r), fill=SKY_DEEP + (255,))
    d.ellipse((x - r * 0.92, y - r * 0.95, x + r * 0.8, y + r * 0.6), fill=SKY + (255,))
    core = r * (0.62 - 0.10 * press)
    d.ellipse((x - core, y - core, x + core, y + core), fill=WHITE + (255,))
    d.ellipse((x - core * 0.45, y - core * 0.55, x - core * 0.05, y - core * 0.15),
              fill=(224, 246, 255, 255))
    if press > 0.01:  # squish ring on click
        rr = r + press * 16 * scale
        d.ellipse((x - rr, y - rr, x + rr, y + rr), outline=SKY + (int(180 * (1 - press)),),
                  width=max(2, int(3 * scale)))


def draw_cursor_glow(d, x, y, scale=1.0, press=0.0, dim=False):
    r = CURSOR_R * scale
    alpha_mul = 0.4 if dim else 1.0
    for i in range(7):
        f = (i + 1) / 7
        rr = r * (1.0 + 2.4 * f)
        a = int(60 * (1.0 - f) * alpha_mul)
        d.ellipse((x - rr, y - rr, x + rr, y + rr), outline=SKY + (a,), width=2)
    d.ellipse((x - r * 0.5, y - r * 0.5, x + r * 0.5, y + r * 0.5),
              fill=WHITE + (235,), outline=SKY + (255,), width=2)
    if press > 0.01:
        rr = r * (0.9 + press * 1.6)
        d.ellipse((x - rr, y - rr, x + rr, y + rr), outline=SKY + (int(160 * (1 - press)),), width=2)


class _SSDraw:
    """Drawing proxy that scales coordinates + line widths by `k`.

    The draw_* helpers keep working unchanged; the frame is rendered at k x the
    size and box-filtered down, which anti-aliases the rings. Without it PIL's
    ellipses snap to whole pixels, so a slowly moving ring visibly "crawls".
    """

    def __init__(self, d, k):
        self._d = d
        self._k = k

    def ellipse(self, xy, fill=None, outline=None, width=1):
        k = self._k
        self._d.ellipse(tuple(v * k for v in xy), fill=fill, outline=outline,
                        width=max(1, int(round(width * k))))

    def polygon(self, pts, fill=None):
        k = self._k
        self._d.polygon([(x * k, y * k) for (x, y) in pts], fill=fill)


def view_bounds(view, vs, t):
    """Screen-space bounding box (x0, y0, x1, y1) of everything `render_frame`
    would draw for `view`, clamped to the virtual screen `vs` = (x, y, w, h).
    None when nothing is visible.

    This is what lets the overlay touch a few hundred pixels per frame instead
    of the whole desktop (the full-screen path cost 14 ms @1080p, 47 ms @4K
    in pure CPU before the OS even composited the 8-33 MB surface).
    """
    boxes = []

    def add(x, y, r):
        boxes.append((x - r, y - r, x + r, y + r))

    for (px, py, age) in view.get("trail", ()):
        if age < 0.45:
            add(px, py, 10.0)
    for (px, py, vx, vy, born, kind) in view.get("particles", ()):
        age = t - born
        if age <= (0.55 if kind == "star" else 0.35):
            add(px + vx * age, py + vy * age + 26 * age * age, 10.0)
    pulse = view.get("pulse")
    if pulse and 0 <= t - pulse[2] < 0.35:
        add(pulse[0], pulse[1], CURSOR_R + 32.0)
    cur = view.get("cursor")
    if cur:
        s = view.get("scale", 1.0)
        style = view.get("style", "sky")
        if style == "glow":
            add(cur[0], cur[1], CURSOR_R * s * 3.4 + 4.0)
        elif style == "sky":
            add(cur[0], cur[1], max(GLOW_R * s, CURSOR_R * s + 16 * s) + 4.0)
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes) - 2
    y0 = min(b[1] for b in boxes) - 2
    x1 = max(b[2] for b in boxes) + 2
    y1 = max(b[3] for b in boxes) + 2
    vx0, vy0, vw, vh = vs
    x0 = max(vx0, int(math.floor(x0)))
    y0 = max(vy0, int(math.floor(y0)))
    x1 = min(vx0 + vw, int(math.ceil(x1)))
    y1 = min(vy0 + vh, int(math.ceil(y1)))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    return x0, y0, x1, y1


def _draw_view(d, view, t):
    origin = view.get("origin", (0, 0))
    ox, oy = origin

    def sx(v):  # to window-local
        return v[0] - ox, v[1] - oy

    # motion trail
    for (px, py, age) in view.get("trail", ()):  # newest last
        a = max(0.0, 1.0 - age / 0.45)
        if a <= 0:
            continue
        x, y = sx((px, py))
        rr = 2.5 + 7 * a
        d.ellipse((x - rr, y - rr, x + rr, y + rr),
                  fill=SKY + (int(110 * a),))
        d.ellipse((x - rr * 0.4, y - rr * 0.4, x + rr * 0.4, y + rr * 0.4),
                  fill=WHITE + (int(90 * a),))

    # drag sparkle particles
    for (px, py, vx, vy, born, kind) in view.get("particles", ()):
        age = t - born
        life = 0.55 if kind == "star" else 0.35
        if age > life:
            continue
        x = px + vx * age
        y = py + vy * age + 26 * age * age  # slight gravity
        a = 1.0 - age / life
        w, h = sx((x, y))
        if kind == "star":
            _star(d, w, h, 3 + 6 * a, SPARK + (int(230 * a),))
            _star(d, w, h, 1.6 + 3 * a, WHITE + (int(180 * a),))
        else:
            d.ellipse((w - 2 * a, h - 2 * a, w + 2 * a, h + 2 * a),
                      fill=SKY_PALE + (int(160 * a),))

    # click ripple
    pulse = view.get("pulse")
    if pulse:
        px, py, born = pulse
        age = t - born
        if 0 <= age < 0.35:
            f = age / 0.35
            x, y = sx((px, py))
            rr = CURSOR_R + 30 * f
            d.ellipse((x - rr, y - rr, x + rr, y + rr),
                      outline=SKY + (int(200 * (1 - f)),), width=max(1, int(3 * (1 - f))))

    cursor = view.get("cursor")
    if cursor:
        x, y = sx(cursor)
        style = view.get("style", "sky")
        press = view.get("press", 0.0)
        dim = view.get("dim", False)
        if style == "glow":
            draw_cursor_glow(d, x, y, view.get("scale", 1.0), press, dim)
        elif style == "sky":
            draw_cursor_sky(d, x, y, view.get("scale", 1.0), press, dim)


def render_frame(size, view, t, ss=1):
    """Render one overlay frame.

    view: dict with keys
      cursor: (x, y) or None          - screen coords of the orb (window-local)
      style: 'sky' | 'glow' | 'system'
      dim: bool                       - hand lost recently
      trail: list[(x, y, age_s)]      - recent cursor points, newest last
      drag: bool
      particles: list[(x, y, vx, vy, born, kind)]
      pulse: (x, y, born) or None     - click ripple
      origin: (x, y)                  - screen position of the image's top-left
      pinches: dict of bools for debug markers (optional)
    ss: supersampling factor (2 = anti-aliased, 1 = legacy hard edges).
    Returns a PIL RGBA image of `size`.
    """
    if ss <= 1:
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        _draw_view(ImageDraw.Draw(img, "RGBA"), view, t)
        return img
    big = Image.new("RGBA", (size[0] * ss, size[1] * ss), (0, 0, 0, 0))
    _draw_view(_SSDraw(ImageDraw.Draw(big, "RGBA"), ss), view, t)
    # RGBA resize is done in premultiplied space by Pillow -> no dark fringes
    return big.resize(size, Image.BOX)


# ----------------------------------------------------------------------------
# Win32 layered window
# ----------------------------------------------------------------------------

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
SW_HIDE = 0
ULW_ALPHA = 0x00000002
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


# LRESULT is LONG_PTR: 64-bit on x64. c_long (32-bit) truncates real messages.
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

class WNDCLASSW(ctypes.Structure):
    """ctypes.wintypes does not define WNDCLASSW — define it here."""
    _fields_ = (("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR))


# Without argtypes, ctypes coerces every argument to a 32-bit C int: a 64-bit
# handle (hInstance!) then raises "OverflowError: int too long to convert".
# Declared AFTER the struct definitions and with REAL types — string
# forward-refs in POINTER() resolve to garbage here and crash the native call.
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
    ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
    wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER),
                                   wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HANDLE
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.SelectObject.restype = wintypes.HANDLE
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


class Overlay(threading.Thread):
    """Threaded click-through overlay. Reads a CursorBus; never touches input.

    2.5 — dirty-rect rendering. The layered window used to be the size of the
    whole desktop and was fully redrawn + re-uploaded every frame (8 MB @1080p,
    33 MB @4K): ~15-50 ms of CPU plus a full-surface DWM composite, i.e. a
    10-30 fps cursor highlight that lagged behind the (144 Hz) real cursor.
    Now the DIB is still allocated once at desktop size (it is just memory), but
    each frame only the sprite's bounding box is drawn, premultiplied straight
    into that sub-rectangle, and handed to UpdateLayeredWindow with a matching
    pptSrc/psize/pptDst — a few hundred pixels per frame. The loop is woken by
    the emitter (bus.visual_event) so the ring moves in lock-step with the cursor.
    """

    SS_MAX_PIXELS = 160_000     # supersample (anti-alias) while the sprite is small

    def __init__(self, bus, fps=120):
        super().__init__(daemon=True, name="HJ3-Overlay")
        self.bus = bus
        self.fps = fps
        self._halt_evt = threading.Event()   # NOT `_stop`: that shadows threading.Thread._stop() and breaks join()
        self._hwnd = None
        self._visible = False
        self._rect = None          # DIB rect (x0, y0, x1, y1) currently holding pixels
        self.frames = 0            # diagnostics: frames pushed
        self.last_frame_ms = 0.0   # diagnostics: CPU time of the last frame

    def stop(self):
        self._halt_evt.set()
        try:
            self.bus.visual_event.set()
        except Exception:
            pass

    # -- win32 plumbing -----------------------------------------------------
    def _create_window(self):
        vs = self.bus.virtual_screen
        self._x, self._y, self._w, self._h = vs

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == 0x0010:  # WM_CLOSE
                user32.DestroyWindow(hwnd)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(wndproc)
        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW()
        cls.lpfnWndProc = self._wndproc_ref
        cls.hInstance = hinst
        cls.lpszClassName = "HandJob3000OverlayWnd"
        cls.hCursor = None
        cls.hbrBackground = None
        if not user32.RegisterClassW(ctypes.byref(cls)):
            err = ctypes.get_last_error()
            if err != 1410:  # class already exists is fine
                raise OSError(f"RegisterClassW failed: {err}")
        ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
        # created tiny: UpdateLayeredWindow resizes it to the sprite every frame
        hwnd = user32.CreateWindowExW(ex, "HandJob3000OverlayWnd", "HandJob3000Overlay",
                                      WS_POPUP, self._x, self._y, 1, 1,
                                      None, None, hinst, None)
        if not hwnd:
            raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
        self._hwnd = hwnd
        # ONE desktop-sized DIB + memory DC, allocated once and never copied whole
        self._screen_dc = user32.GetDC(None)
        self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = self._w
        bmi.biHeight = -self._h  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        self._bits = ctypes.c_void_p()
        self._bmp = gdi32.CreateDIBSection(self._mem_dc, ctypes.byref(bmi), 0,
                                           ctypes.byref(self._bits), None, 0)
        if not self._bmp or not self._bits.value:
            raise OSError(f"CreateDIBSection failed: {ctypes.get_last_error()}")
        gdi32.SelectObject(self._mem_dc, self._bmp)
        import numpy as np
        self._buf_size = self._w * self._h * 4
        # numpy view over the DIB memory: the premultiply writes straight into it
        self._dib = np.frombuffer((ctypes.c_ubyte * self._buf_size).from_address(self._bits.value),
                                  dtype=np.uint8).reshape(self._h, self._w, 4)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def _push(self, rect_screen):
        """Hand the DIB sub-rectangle for `rect_screen` to the compositor."""
        x0, y0, x1, y1 = rect_screen
        # pptDst/psize are MANDATORY on every call: passing NULL leaves the
        # window without a layered surface on Win11/DWM (the orb silently
        # never composites — root cause of the invisible custom cursor).
        dst = wintypes.POINT(x0, y0)
        size = wintypes.SIZE(x1 - x0, y1 - y0)
        src = wintypes.POINT(x0 - self._x, y0 - self._y)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(self._hwnd, self._screen_dc, ctypes.byref(dst),
                                        ctypes.byref(size), self._mem_dc,
                                        ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
        if not ok:
            err = ctypes.get_last_error()
            if err not in (0, 87):  # transient lag errors happen under load
                raise OSError(f"UpdateLayeredWindow failed: {err}")

    def _clear_rect(self):
        if self._rect is not None:
            x0, y0, x1, y1 = self._rect
            self._dib[y0:y1, x0:x1].fill(0)
            self._rect = None

    def _hide(self):
        if self._visible:
            self._clear_rect()
            user32.ShowWindow(self._hwnd, SW_HIDE)
            self._visible = False

    def _draw(self, view, t):
        """Render + present one frame. Returns False when nothing is visible."""
        vs = (self._x, self._y, self._w, self._h)
        bounds = view_bounds(view, vs, t)
        if bounds is None:
            self._hide()
            return False
        x0, y0, x1, y1 = bounds
        bw, bh = x1 - x0, y1 - y0
        view["origin"] = (x0, y0)
        ss = 2 if bw * bh <= self.SS_MAX_PIXELS else 1
        img = render_frame((bw, bh), view, t, ss=ss)
        self._clear_rect()                      # previous sprite (small)
        lx, ly = x0 - self._x, y0 - self._y
        _premultiply_into(img, self._dib[ly:ly + bh, lx:lx + bw])
        self._rect = (lx, ly, lx + bw, ly + bh)
        self._push(bounds)
        if not self._visible:
            user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
            self._visible = True
        return True

    # -- thread -------------------------------------------------------------
    def run(self):
        try:
            self._create_window()
        except Exception as e:
            self.bus.error = f"overlay init failed: {e}"
            return
        try:
            from .input_win32 import boost_thread_priority
            boost_thread_priority(1)            # keep the ring ahead of UI/inference threads
        except Exception:
            pass
        ev = self.bus.visual_event
        min_dt = 1.0 / max(15.0, float(self.fps))
        last = 0.0
        last_sig = None
        animating = False
        loop_errors = 0
        while not self._halt_evt.is_set():
            # sleep until the emitter says the cursor moved; while a trail / ripple
            # is fading we also tick on a timer so the animation keeps running
            ev.wait(0.016 if animating else 0.08)
            ev.clear()
            if self._halt_evt.is_set():
                break
            dt = time.perf_counter() - last
            if dt < min_dt:
                time.sleep(min_dt - dt)         # coalesce bursts to <= fps
                ev.clear()
            last = time.perf_counter()

            if not self.bus.overlay_enabled:
                self._hide()
                animating = False
                continue
            try:
                view = self.bus.snapshot()      # position is read NOW (freshest value)
                if view is None:
                    self._hide()
                    animating = False
                    last_sig = None
                    continue
                animating = bool(view["trail"] or view["particles"] or view["pulse"])
                sig = (view["cursor"], view["style"], view["dim"], round(view["press"], 2))
                if not animating and sig == last_sig and self._visible:
                    continue                    # nothing changed: don't touch the compositor
                last_sig = sig
                t0 = time.perf_counter()
                self._draw(view, time.time())
                self.last_frame_ms = (time.perf_counter() - t0) * 1000.0
                self.frames += 1
                loop_errors = 0
            except Exception as e:
                loop_errors += 1
                self.bus.error = f"overlay render error: {e}"
                if loop_errors > 30:
                    return
                time.sleep(0.1)
        try:
            user32.DestroyWindow(self._hwnd)
        except Exception:
            pass
