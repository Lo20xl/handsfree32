"""native_cursor.py — make the orb / ring THE operating-system cursor (2.6).

The problem this solves.  Until 2.5 the orb was a click-through overlay window
drawn on top of the real arrow, and the arrow was "hidden" with ShowCursor(FALSE).
ShowCursor's display counter is per input queue: it only hides the cursor while
it is over windows of the calling thread, so over every other app the arrow kept
being drawn.  The result was two cursors: the arrow (drawn by the display
hardware at scan-out, zero latency) and the orb (a composited window, 1-2 frames
behind and only updated when the overlay thread got to it).  At speed the arrow
peeked out ahead of the orb and the pair "shimmered" — the jittery ring.

Now the sprite is installed as the system cursor itself (SetSystemCursor).  The
OS draws it exactly where it draws the pointer, in the same pass, with the same
latency: nothing can lag or jitter relative to the pointer because it IS the
pointer.  The overlay window keeps only the decorations (trail, sparkles, click
ripple), which nobody can see lagging by a frame.

Safety (a pointer that vanishes would be a disaster):
  * a one-time self-test draws a probe cursor with DrawIconEx and reads the pixels
    back.  That proves CreateIconIndirect + alpha work on this machine AND tells
    us whether this Windows treats the cursor bitmap as premultiplied or straight
    alpha, so the sprite is always converted correctly.  Any doubt -> not installed
    (the app falls back to the overlay path).
  * every installed cursor is a visible sprite; a crash can leave the orb behind,
    never an invisible pointer.
  * restore() = SystemParametersInfo(SPI_SETCURSORS), which reloads the user's own
    scheme from the registry.  It runs on disarm, hand lost, exit (atexit), at
    every app start (clears anything a previous crash left) and via
    `HandJob3000.exe --restore-cursors`.

The Win32 calls live in `Win32CursorBackend`; `NativeCursor` is pure logic over
a backend, so it is unit-tested with a fake one.
"""
from __future__ import annotations

import atexit
import logging
import threading

log = logging.getLogger("handjob.native_cursor")

# system cursor ids (OCR_*): every shape gets the sprite so the pointer never changes identity
OCR_NORMAL, OCR_IBEAM, OCR_WAIT, OCR_CROSS, OCR_UP = 32512, 32513, 32514, 32515, 32516
OCR_SIZENWSE, OCR_SIZENESW, OCR_SIZEWE, OCR_SIZENS, OCR_SIZEALL = 32642, 32643, 32644, 32645, 32646
OCR_NO, OCR_HAND, OCR_APPSTARTING = 32648, 32649, 32650
ALL_IDS = (OCR_NORMAL, OCR_IBEAM, OCR_WAIT, OCR_CROSS, OCR_UP, OCR_SIZENWSE, OCR_SIZENESW,
           OCR_SIZEWE, OCR_SIZENS, OCR_SIZEALL, OCR_NO, OCR_HAND, OCR_APPSTARTING)

PRESS_LEVEL = 0.75        # the sprite variant used while a button is held


# ------------------------------------------------------------------ pure part
def sprite_geometry(style, scale=1.0):
    """(size, hotspot) of the square sprite for a style: big enough for the glow + press ring."""
    from .overlay import view_bounds
    view = {"cursor": (0.0, 0.0), "style": style, "scale": scale}
    b = view_bounds(view, (-600, -600, 1200, 1200), 0.0)
    r = max(abs(v) for v in b) + 3 if b else 40
    size = int(2 * r)
    return size, (size // 2, size // 2)


def render_sprite(style, scale=1.0, press=0.0):
    """PIL RGBA sprite of the cursor, centred, anti-aliased. Returns (image, (hot_x, hot_y))."""
    from .overlay import render_frame
    size, hot = sprite_geometry(style, scale)
    view = {"cursor": (float(hot[0]), float(hot[1])), "style": style, "scale": scale,
            "press": press, "dim": False, "trail": [], "particles": [], "pulse": None, "origin": (0, 0)}
    return render_frame((size, size), view, 0.0, ss=2), hot


def to_bgra(img, premultiplied):
    """PIL RGBA -> top-down BGRA bytes, straight or premultiplied alpha."""
    import numpy as np
    arr = np.asarray(img, dtype=np.uint8)
    if premultiplied:
        from .overlay import _premultiplied_bgra
        return _premultiplied_bgra(img).tobytes()
    out = np.empty_like(arr)
    out[..., 0], out[..., 1], out[..., 2], out[..., 3] = arr[..., 2], arr[..., 1], arr[..., 0], arr[..., 3]
    return out.tobytes()


class NativeCursor:
    """Installs/updates/removes the sprite as the system cursor, over a backend.

    Backend protocol: probe_alpha_mode() -> "straight" | "premultiplied" | None,
    create_cursor(bgra, w, h, hot_x, hot_y) -> handle, copy(handle) -> handle,
    set_system_cursor(handle, ocr_id) -> bool, destroy(handle), restore_all().
    """

    def __init__(self, backend, ids=ALL_IDS, renderer=render_sprite):
        self._b = backend
        self._ids = tuple(ids)
        self._render = renderer
        self._lock = threading.RLock()
        self._alpha = None            # cached probe result
        self._tpl = {}                # variant -> template handle
        self._style = None
        self._scale = 1.0
        self._variant = None
        self.active = False
        self.failed = False           # install proved impossible on this machine: don't retry
        self.error = None
        atexit.register(self.restore)

    # ------------------------------------------------------------------ install
    def install(self, style="sky", scale=1.0):
        """Make the sprite the OS cursor. False (and nothing changed) when impossible."""
        with self._lock:
            if self.failed or style not in ("sky", "glow"):
                return False
            try:
                if self._alpha is None:
                    self._alpha = self._b.probe_alpha_mode()
                if self._alpha not in ("straight", "premultiplied"):
                    raise RuntimeError(f"cursor alpha self-test inconclusive ({self._alpha!r})")
                self._drop_templates()
                for name, press in (("normal", 0.0), ("press", PRESS_LEVEL)):
                    img, (hx, hy) = self._render(style, scale, press)
                    data = to_bgra(img, self._alpha == "premultiplied")
                    self._tpl[name] = self._b.create_cursor(data, img.size[0], img.size[1], hx, hy)
                self._style, self._scale = style, scale
                self._variant = None
                if not self._apply("normal"):
                    raise RuntimeError("SetSystemCursor refused the arrow cursor")
                self.active = True
                self.error = None
                log.info("native cursor installed (%s, alpha=%s)", style, self._alpha)
                return True
            except Exception as e:
                self.error = str(e)
                log.warning("native cursor unavailable: %s", e)
                self.failed = True
                self.restore()
                return False

    def set_press(self, pressed):
        """Swap to the pressed/normal sprite (cheap: copies + SetSystemCursor)."""
        with self._lock:
            if not self.active:
                return
            want = "press" if pressed else "normal"
            if want != self._variant:
                self._apply(want)

    def matches(self, style, scale=1.0):
        return self.active and style == self._style and abs(scale - self._scale) < 1e-6

    def restore(self):
        """Give the user's own cursors back. Idempotent; safe from any thread / atexit."""
        with self._lock:
            was = self.active
            self.active = False
            self._variant = None
            try:
                if was or self._tpl:
                    self._b.restore_all()
            except Exception as e:
                log.warning("cursor restore failed: %s", e)
            self._drop_templates()

    # ----------------------------------------------------------------- internals
    def _apply(self, variant):
        tpl = self._tpl.get(variant)
        if tpl is None:
            return False
        ok_first = None
        for i, ocr in enumerate(self._ids):
            ok = False
            try:
                h = self._b.copy(tpl)
                ok = bool(self._b.set_system_cursor(h, ocr))     # the system takes ownership of h
                if not ok:
                    self._b.destroy(h)
            except Exception as e:
                log.debug("SetSystemCursor %s failed: %s", ocr, e)
            if i == 0:
                ok_first = ok
        if ok_first:
            self._variant = variant
        return bool(ok_first)

    def _drop_templates(self):
        for h in self._tpl.values():
            try:
                self._b.destroy(h)
            except Exception:
                pass
        self._tpl = {}


# ----------------------------------------------------------------- win32 part
class Win32CursorBackend:
    """ctypes bindings. Handles are pointer-sized (wintypes.HANDLE) — never default c_int."""

    DIB_RGB_COLORS = 0
    DI_NORMAL = 0x0003
    SPI_SETCURSORS = 0x0057

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        H, U, I = wintypes.HANDLE, wintypes.UINT, ctypes.c_int

        class ICONINFO(ctypes.Structure):
            _fields_ = (("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                        ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP))

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = (("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD))

        self.ICONINFO, self.BIH = ICONINFO, BITMAPINFOHEADER
        u, g = self.user32, self.gdi32
        u.GetDC.argtypes, u.GetDC.restype = [wintypes.HWND], wintypes.HDC
        u.ReleaseDC.argtypes, u.ReleaseDC.restype = [wintypes.HWND, wintypes.HDC], I
        u.CreateIconIndirect.argtypes, u.CreateIconIndirect.restype = [ctypes.POINTER(ICONINFO)], H
        u.CopyIcon.argtypes, u.CopyIcon.restype = [H], H
        u.DestroyIcon.argtypes, u.DestroyIcon.restype = [H], wintypes.BOOL
        u.SetSystemCursor.argtypes, u.SetSystemCursor.restype = [H, wintypes.DWORD], wintypes.BOOL
        u.SystemParametersInfoW.argtypes = [U, U, ctypes.c_void_p, U]
        u.SystemParametersInfoW.restype = wintypes.BOOL
        u.DrawIconEx.argtypes = [wintypes.HDC, I, I, H, I, I, U, H, U]
        u.DrawIconEx.restype = wintypes.BOOL
        g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), U,
                                       ctypes.POINTER(ctypes.c_void_p), H, wintypes.DWORD]
        g.CreateDIBSection.restype = H
        g.CreateBitmap.argtypes = [I, I, U, U, ctypes.c_void_p]
        g.CreateBitmap.restype = H
        g.DeleteObject.argtypes, g.DeleteObject.restype = [H], wintypes.BOOL
        g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [wintypes.HDC], wintypes.HDC
        g.SelectObject.argtypes, g.SelectObject.restype = [wintypes.HDC, H], H
        g.DeleteDC.argtypes, g.DeleteDC.restype = [wintypes.HDC], wintypes.BOOL

    # -- bitmaps / cursors
    def _dib(self, hdc, w, h):
        bih = self.BIH()
        bih.biSize = self.ct.sizeof(self.BIH)
        bih.biWidth, bih.biHeight = w, -h            # top-down
        bih.biPlanes, bih.biBitCount, bih.biCompression = 1, 32, 0
        bits = self.ct.c_void_p()
        hbm = self.gdi32.CreateDIBSection(hdc, self.ct.byref(bih), self.DIB_RGB_COLORS, self.ct.byref(bits), None, 0)
        if not hbm or not bits.value:
            raise OSError(f"CreateDIBSection failed ({self.ct.get_last_error()})")
        return hbm, bits

    def create_cursor(self, bgra, w, h, hot_x, hot_y):
        ct = self.ct
        hdc = self.user32.GetDC(None)
        try:
            hbm_color, bits = self._dib(hdc, w, h)
            ct.memmove(bits, bgra, w * h * 4)
            hbm_mask = self.gdi32.CreateBitmap(w, h, 1, 1, None)     # ignored when the colour bitmap has alpha
            ii = self.ICONINFO(False, hot_x, hot_y, hbm_mask, hbm_color)
            hcur = self.user32.CreateIconIndirect(ct.byref(ii))
            self.gdi32.DeleteObject(hbm_color)
            self.gdi32.DeleteObject(hbm_mask)
        finally:
            self.user32.ReleaseDC(None, hdc)
        if not hcur:
            raise OSError(f"CreateIconIndirect failed ({ct.get_last_error()})")
        return hcur

    def copy(self, handle):
        h = self.user32.CopyIcon(handle)
        if not h:
            raise OSError(f"CopyIcon failed ({self.ct.get_last_error()})")
        return h

    def destroy(self, handle):
        self.user32.DestroyIcon(handle)

    def set_system_cursor(self, handle, ocr_id):
        return bool(self.user32.SetSystemCursor(handle, int(ocr_id)))

    def restore_all(self):
        self.user32.SystemParametersInfoW(self.SPI_SETCURSORS, 0, None, 0)

    # -- self-test
    def probe_alpha_mode(self):
        """Draw a half-transparent probe cursor onto black and read it back.

        Probe pixels are B=G=R=200, A=128.  Straight-alpha handling shows ~100 (200 * 128/255),
        premultiplied handling adds the bytes as-is and shows ~200.  Returns 'straight',
        'premultiplied', or None when the result is something else (don't trust this path)."""
        ct, n = self.ct, 8
        px = bytes((200, 200, 200, 128)) * (n * n)
        probe = None
        hdc = self.user32.GetDC(None)
        mem = None
        try:
            probe = self.create_cursor(px, n, n, 0, 0)
            mem = self.gdi32.CreateCompatibleDC(hdc)
            hbm, bits = self._dib(hdc, n, n)
            old = self.gdi32.SelectObject(mem, hbm)
            ct.memset(bits, 0, n * n * 4)
            ok = self.user32.DrawIconEx(mem, 0, 0, probe, n, n, 0, None, self.DI_NORMAL)
            val = ct.string_at(bits.value + ((n // 2) * n + n // 2) * 4, 4)[0] if ok else -1
            self.gdi32.SelectObject(mem, old)
            self.gdi32.DeleteObject(hbm)
        finally:
            if mem:
                self.gdi32.DeleteDC(mem)
            self.user32.ReleaseDC(None, hdc)
            if probe:
                self.destroy(probe)
        log.info("cursor alpha probe read-back: %s", val)
        if 70 <= val <= 135:
            return "straight"
        if 170 <= val <= 215:
            return "premultiplied"
        return None


def restore_system_cursors():
    """Reload the user's own cursor scheme (safe no-op off Windows). Used at start-up / by --restore-cursors."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
        u.SystemParametersInfoW.restype = wintypes.BOOL
        return bool(u.SystemParametersInfoW(Win32CursorBackend.SPI_SETCURSORS, 0, None, 0))
    except Exception:
        return False


def system_dpi_scale():
    """Display scaling factor of the primary monitor (1.0 = 96 dpi); cursors are drawn 1:1, so scale the sprite."""
    try:
        import ctypes
        dpi = ctypes.WinDLL("user32").GetDpiForSystem()
        return max(1.0, min(2.5, dpi / 96.0)) if dpi else 1.0
    except Exception:
        return 1.0
