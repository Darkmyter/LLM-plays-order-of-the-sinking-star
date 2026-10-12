"""Leave a puzzle level through the in-game menu ("Exit to Overworld"), safely.

The menu follows the mouse pointer, so: open the menu, point at the first item, confirm from a
screenshot that exactly that line is highlighted, and only then press Enter. Anything unexpected
closes the menu again without choosing anything.
"""
import time

from PIL import ImageGrab

from game import keys

# Item positions as fractions of the window's client area (measured from screenshots).
FIRST_ITEM = (0.5, 0.315)      # "Exit to Overworld" inside a level ("Resume Game" in the open world)
DANGER_ITEM = (0.5, 0.755)     # "Start a New Campaign": must never be highlighted when we press Enter


def _highlighted(img, fy, w, h):
    """Count bright yellow (highlighted text) pixels in a horizontal band around fy."""
    y0, y1 = int((fy - 0.025) * h), int((fy + 0.025) * h)
    band = img.crop((int(0.25 * w), y0, int(0.75 * w), y1)).convert("RGB")
    n = 0
    for r, g, b in band.getdata():
        if r > 200 and g > 170 and b < 160 and r - b > 70:
            n += 1
    return n


def _grab(rect):
    left, top, w, h = rect
    return ImageGrab.grab(bbox=(left, top, left + w, top + h), all_screens=True)


def exit_to_overworld(hwnd):
    """Returns (ok, message)."""
    rect = keys.window_rect(hwnd)
    left, top, w, h = rect
    saved = keys.mouse_pos()
    try:
        keys.press(hwnd, "ESC")
        time.sleep(0.8)
        keys.mouse_move(left + FIRST_ITEM[0] * w, top + FIRST_ITEM[1] * h)
        time.sleep(0.4)
        img = _grab(rect)
        first = _highlighted(img, FIRST_ITEM[1], w, h)
        danger = _highlighted(img, DANGER_ITEM[1], w, h)
        if first < 30 or danger > 10:
            keys.press(hwnd, "ESC")
            time.sleep(0.5)
            return False, (f"could not safely select 'Exit to Overworld' (highlight check failed: "
                           f"{first}/{danger}); the menu was closed again")
        keys.press(hwnd, "ENTER")
        return True, "chose 'Exit to Overworld'"
    finally:
        keys.mouse_move(*saved)
