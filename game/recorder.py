"""Gameplay recording: one video of the game window and one of the viewer window while a player runs.

Each window is captured with PrintWindow (PW_RENDERFULLCONTENT), which works for GPU-drawn windows and
when other windows overlap them, and is piped as raw frames to ffmpeg. Videos go to
<run folder>/recordings/<game|viewer>_<index>_<date-time>.mp4, one per stretch of recording:

- recording runs while the player is running; pause, stop or an error ends the videos, and resuming
  starts new ones (the index keeps counting across resumes);
- if a window is lost (closed, minimised, or the viewer tab is no longer the one showing the viewer) that
  video ends, and a new one starts when the window is back while the player is still running.

The mp4 is fragmented, so a video is playable even if the process dies before ffmpeg can finish it.
"""
import ctypes
import os
import re
import shutil
import subprocess
import threading
import time

import win32con
import win32gui
import win32ui

GAME_TITLE = "Order of the Sinking Star"
VIEWER_TITLE = "Sinking Star Live"      # the viewer page's <title>; browsers add their own name after it
PW_RENDERFULLCONTENT = 2
HALFTONE = 4

try:
    ctypes.windll.user32.SetProcessDPIAware()    # real pixel sizes, not DPI-scaled ones
except Exception:
    pass


def find_game():
    return win32gui.FindWindow(None, GAME_TITLE)


def find_viewer():
    found = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd).startswith(VIEWER_TITLE):
            found.append(hwnd)

    win32gui.EnumWindows(visit, None)
    return found[0] if found else 0


def usable(hwnd):
    """A window that can be captured: it exists, is visible, is not minimised and is not tiny."""
    if not hwnd or not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
        return False
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    return r - l >= 64 and b - t >= 64


def target_size(hwnd, max_width):
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w = min(r - l, max_width) // 2 * 2
    return w, round((b - t) * w / (r - l)) // 2 * 2


def grab(hwnd, out_w, out_h):
    """One frame of the window as BGRA bytes, scaled to out_w x out_h; None if the window is not capturable."""
    if not usable(hwnd):
        return None
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    wdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(wdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    small = sbmp = None
    try:
        bmp.CreateCompatibleBitmap(src, w, h)
        mem.SelectObject(bmp)
        ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), PW_RENDERFULLCONTENT)
        if (w, h) == (out_w, out_h):
            return bmp.GetBitmapBits(True)
        small = src.CreateCompatibleDC()
        sbmp = win32ui.CreateBitmap()
        sbmp.CreateCompatibleBitmap(src, out_w, out_h)
        small.SelectObject(sbmp)
        ctypes.windll.gdi32.SetStretchBltMode(small.GetSafeHdc(), HALFTONE)
        small.StretchBlt((0, 0), (out_w, out_h), mem, (0, 0), (w, h), win32con.SRCCOPY)
        return sbmp.GetBitmapBits(True)
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        if sbmp is not None:
            win32gui.DeleteObject(sbmp.GetHandle())
        for dc in (small, mem, src):
            if dc is not None:
                dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, wdc)


def next_path(folder, name):
    """recordings/<name>_<index>_<date-time>.mp4, the index continuing after any earlier videos."""
    os.makedirs(folder, exist_ok=True)
    taken = [int(m.group(1)) for f in os.listdir(folder) if (m := re.match(rf"{name}_(\d+)_", f))]
    return os.path.join(folder, f"{name}_{max(taken, default=0) + 1:03d}_{time.strftime('%Y%m%d-%H%M%S')}.mp4")


class WindowRecorder:
    """Records one window into one mp4 until stop() or until the window is lost."""

    def __init__(self, name, find, folder, fps=10, max_width=1280, crf=28):
        self.name, self.find, self.folder = name, find, folder
        self.fps, self.max_width, self.crf = fps, max_width, crf
        self.thread = None
        self.stop_flag = threading.Event()
        self.path = ""
        self.ended = ""       # why the last video ended

    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self, hwnd):
        self.stop_flag.clear()
        self.path = next_path(self.folder, self.name)
        self.ended = ""
        self.thread = threading.Thread(target=self._run, args=(hwnd, self.path), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()
        if self.thread:
            self.thread.join(timeout=15)

    def _run(self, hwnd, path):
        w, h = target_size(hwnd, self.max_width)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
               "-s", f"{w}x{h}", "-framerate", str(self.fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", str(self.crf), "-pix_fmt", "yuv420p",
               "-movflags", "+frag_keyframe+empty_moov+default_base_moof", path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        t0, written, reason = time.time(), 0, "stopped"
        try:
            while not self.stop_flag.is_set():
                frame = grab(hwnd, w, h)
                if frame is None:
                    reason = "window lost"
                    break
                # Keep the video in real time: if capturing fell behind, repeat the frame to catch up.
                due = int((time.time() - t0) * self.fps) + 1
                for _ in range(max(1, min(due - written, self.fps))):
                    proc.stdin.write(frame)
                    written += 1
                self.stop_flag.wait(max(0.0, t0 + written / self.fps - time.time()))
        except (BrokenPipeError, OSError):
            reason = "ffmpeg stopped"
        except Exception as e:           # never let a capture problem reach the player
            reason = f"error: {e}"
        finally:
            try:
                proc.stdin.close()
                proc.wait(timeout=20)
            except Exception:
                proc.kill()
            self.ended = reason
            if not written and os.path.exists(path):
                os.remove(path)          # nothing was recorded


class RunRecorder:
    """Records the game and the viewer for one run. start() and stop() are safe to call repeatedly."""

    def __init__(self, run_dir, cfg=None):
        cfg = cfg or {}
        folder = os.path.join(run_dir, "recordings")
        opts = {"fps": int(cfg.get("fps", 10)), "max_width": int(cfg.get("max_width", 1280)),
                "crf": int(cfg.get("crf", 28))}
        self.streams = {"game": WindowRecorder("game", find_game, folder, **opts),
                        "viewer": WindowRecorder("viewer", find_viewer, folder, **opts)}
        self.active = False
        self.error = "" if shutil.which("ffmpeg") else "ffmpeg not found: recording is off"
        self.thread = None

    def start(self):
        if self.active or self.error:
            return
        self.active = True
        self.thread = threading.Thread(target=self._supervise, daemon=True)
        self.thread.start()

    def stop(self):
        self.active = False
        for s in self.streams.values():
            s.stop()
        if self.thread:
            self.thread.join(timeout=20)

    def _supervise(self):
        while self.active:
            for s in self.streams.values():
                if self.active and not s.running():
                    hwnd = s.find()
                    if usable(hwnd):
                        s.start(hwnd)
            time.sleep(1.0)

    def status(self):
        """For the viewer: per stream 'recording', 'waiting for window' or 'off'."""
        if self.error:
            return {"error": self.error}
        return {n: ("recording" if s.running() else "waiting for window" if self.active else "off")
                for n, s in self.streams.items()}
