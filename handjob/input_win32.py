"""Raw Win32 input via ctypes SendInput — no pywin32/pyautogui dependency.

Absolute moves use the 0..65535 normalized space with MOUSEEVENTF_VIRTUALDESK
so multi-monitor layouts are addressed correctly.
"""
import ctypes
from ctypes import wintypes  # module-level import: ctypes.wintypes can be missing in frozen exes

user32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

INPUT_MOUSE = 0
MOVE = 0x0001
LEFTDOWN = 0x0002
LEFTUP = 0x0004
RIGHTDOWN = 0x0008
RIGHTUP = 0x0010
WHEEL = 0x0800
ABSOLUTE = 0x8000
VIRTUALDESK = 0x4000
WHEEL_DELTA = 120


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class _U(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT),)


class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _U))

    def __init__(self, flags=0, dx=0, dy=0, data=0):
        super().__init__()
        self.type = INPUT_MOUSE
        self.u.mi.dx = dx
        self.u.mi.dy = dy
        self.u.mi.dwFlags = flags
        self.u.mi.mouseData = data


def _send(inp):
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        raise OSError(f"SendInput failed (err {ctypes.get_last_error()})")


def virtual_screen():
    g = user32.GetSystemMetrics
    return (
        g(76),  # SM_XVIRTUALSCREEN
        g(77),  # SM_YVIRTUALSCREEN
        g(78) or g(0),  # SM_CXVIRTUALSCREEN (fallback SM_CXSCREEN)
        g(79) or g(1),  # SM_CYVIRTUALSCREEN
    )


def move_absolute(x, y):
    x0, y0, w, h = virtual_screen()
    nx = (int(x) - x0) * 65535 // max(1, w - 1)
    ny = (int(y) - y0) * 65535 // max(1, h - 1)
    nx = 0 if nx < 0 else (65535 if nx > 65535 else nx)
    ny = 0 if ny < 0 else (65535 if ny > 65535 else ny)
    _send(INPUT(MOVE | ABSOLUTE | VIRTUALDESK, nx, ny))


def button(name, down):
    flags = {"left": (LEFTDOWN, LEFTUP), "right": (RIGHTDOWN, RIGHTUP)}[name][0 if down else 1]
    _send(INPUT(flags))


def wheel(notches):
    if not isinstance(notches, int) or not notches:
        return
    data = (int(notches) * WHEEL_DELTA) % (1 << 32)
    _send(INPUT(WHEEL, data=data))


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def show_cursor(show):
    """Show/hide the OS cursor regardless of its display-count refcount.

    Thread-affine: always call from the thread owning the engine loop.
    """
    for _ in range(64):
        cnt = user32.ShowCursor(bool(show))
        if (cnt >= 0) if show else (cnt < 0):
            return


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetCurrentThread.restype = wintypes.HANDLE
kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
kernel32.SetThreadPriority.restype = wintypes.BOOL


def boost_thread_priority(level=1):
    """Raise the CALLING thread's priority (1 = above normal, 2 = highest).

    The 144 Hz cursor emitter and the overlay thread sleep almost all the time;
    when they wake they must run NOW, not after the inference/UI threads have
    finished their time slice. Best-effort: returns False if refused."""
    try:
        return bool(kernel32.SetThreadPriority(kernel32.GetCurrentThread(), int(level)))
    except Exception:
        return False
