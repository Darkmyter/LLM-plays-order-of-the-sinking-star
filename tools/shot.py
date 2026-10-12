"""Save a screenshot of the game window (debug helper; not used by the player)."""
import ctypes, ctypes.wintypes as wt, sys
from PIL import ImageGrab
from game import keys
from game.memreader import Process

u32 = ctypes.WinDLL("user32")
u32.SetProcessDPIAware()
hwnd = keys.find_window(Process().pid)
r = wt.RECT(); u32.GetWindowRect(hwnd, ctypes.byref(r))
img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
img.thumbnail((1280, 1280))
out = sys.argv[1] if len(sys.argv) > 1 else "shot.png"
img.save(out)
print(out, img.size)
