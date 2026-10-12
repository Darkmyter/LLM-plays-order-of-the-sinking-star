"""Press keys in the game window via SendInput (hardware scan codes)."""
import ctypes
import ctypes.wintypes as wt
import time

u32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x2, 0x8
VK_MENU = 0x12

# Set-1 scan codes for the keys the game uses.
SCAN = {"W": 0x11, "A": 0x1E, "S": 0x1F, "D": 0x20, "Z": 0x2C, "X": 0x2D, "C": 0x2E,
        "V": 0x2F, "R": 0x13, "F": 0x21, "Q": 0x10, "TAB": 0x0F, "ESC": 0x01, "SPACE": 0x39,
        "ENTER": 0x1C, **{str(n): 0x01 + n for n in range(1, 10)}}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _send(scan=0, vk=0, up=False):
    flags = (KEYEVENTF_SCANCODE if scan else 0) | (KEYEVENTF_KEYUP if up else 0)
    i = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags))
    u32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def find_window(pid):
    found = []
    PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    u32.EnumWindows(PROC(cb), 0)
    return found[0] if found else None


def focus(hwnd):
    if u32.GetForegroundWindow() == hwnd:
        return True
    # Tapping ALT lets a background process take foreground (Windows focus-steal rule).
    _send(vk=VK_MENU)
    _send(vk=VK_MENU, up=True)
    u32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    return u32.GetForegroundWindow() == hwnd


def press(hwnd, key, hold=0.06):
    if not focus(hwnd):
        raise RuntimeError("could not focus the game window")
    sc = SCAN[key.upper()]
    _send(scan=sc)
    time.sleep(hold)
    _send(scan=sc, up=True)


# ---------- mouse (only used to pick a menu item safely) ----------
class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


def mouse_pos():
    p = POINT()
    u32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def mouse_move(x, y):
    u32.SetCursorPos(int(x), int(y))


def window_rect(hwnd):
    """Client area of the window in screen pixels: (left, top, width, height)."""
    u32.SetProcessDPIAware()
    r = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    p = POINT(0, 0)
    u32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y, r.right - r.left, r.bottom - r.top


MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4


def click(x, y):
    mouse_move(x, y)
    time.sleep(0.15)
    u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
