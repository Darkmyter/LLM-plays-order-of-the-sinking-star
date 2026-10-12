"""Gameplay recording: one video of the game window and one of the viewer window while a player runs.

Each window is captured by ffmpeg's `gfxcapture` source (Windows Graphics Capture, the API OBS uses for window
capture). It runs on the GPU, works for GPU-drawn windows and when other windows overlap them, timestamps every
frame with the real time (so playback speed is right) and keeps the window's own resolution until it is scaled
to the configured width. Videos go to <run folder>/recordings/<game|viewer>_<index>_<date-time>.mp4, one per
stretch of recording:

- recording runs while the player is running; pause, stop or an error ends the videos, and resuming
  starts new ones (the index keeps counting across resumes);
- if a window is lost (closed, minimised, or the viewer tab is no longer the one showing the viewer) that
  video ends, and a new one starts when the window is back while the player is still running.

The mp4 is fragmented, so a video is playable even if the process dies before ffmpeg can finish it.
"""
import os
import re
import shutil
import subprocess
import threading
import time

import win32gui

GAME_TITLE = "Order of the Sinking Star"
VIEWER_TITLE = "Sinking Star Live"      # the viewer page's <title>; browsers add their own name after it


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


def next_path(folder, name):
    """recordings/<name>_<index>_<date-time>.mp4, the index continuing after any earlier videos."""
    os.makedirs(folder, exist_ok=True)
    taken = [int(m.group(1)) for f in os.listdir(folder) if (m := re.match(rf"{name}_(\d+)_", f))]
    return os.path.join(folder, f"{name}_{max(taken, default=0) + 1:03d}_{time.strftime('%Y%m%d-%H%M%S')}.mp4")


class WindowRecorder:
    """Records one window into one mp4 until stop() or until the window is lost."""

    def __init__(self, name, find, folder, fps=30, max_width=1920, crf=22, encoder="libx264", preset="veryfast"):
        self.name, self.find, self.folder = name, find, folder
        self.fps, self.max_width, self.crf = fps, max_width, crf
        self.encoder, self.preset = encoder, preset
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
            self.thread.join(timeout=30)

    def _command(self, hwnd, path):
        source = (f"gfxcapture=hwnd={hwnd}:max_framerate={self.fps}:capture_cursor=false:resize_mode=scale_aspect,"
                  f"hwdownload,format=bgra,scale='min({self.max_width},iw)':-2:flags=lanczos,format=yuv420p")
        if self.encoder == "h264_nvenc":     # the GPU encoder: the same look at almost no CPU
            codec = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(self.crf), "-b:v", "0"]
        else:
            codec = ["-c:v", "libx264", "-preset", self.preset, "-crf", str(self.crf)]
        return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", source,
                "-r", str(self.fps), "-fps_mode", "cfr", *codec, "-g", str(self.fps * 2),
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof", path]

    def _run(self, hwnd, path):
        reason = "stopped"
        proc = subprocess.Popen(self._command(hwnd, path), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            while not self.stop_flag.wait(0.5):
                if proc.poll() is not None:
                    reason = "ffmpeg stopped"
                    break
                if not usable(hwnd):
                    reason = "window lost"
                    break
        except Exception as e:           # never let a recording problem reach the player
            reason = f"error: {e}"
        finally:
            try:
                proc.stdin.write(b"q")   # ffmpeg's way to finish a video cleanly
                proc.stdin.flush()
                proc.stdin.close()
                proc.wait(timeout=30)
            except Exception:
                proc.kill()
            self.ended = reason
            if os.path.exists(path) and os.path.getsize(path) < 2048:
                os.remove(path)          # nothing was recorded


class RunRecorder:
    """Records the game and the viewer for one run. start() and stop() are safe to call repeatedly."""

    def __init__(self, run_dir, cfg=None):
        cfg = cfg or {}
        folder = os.path.join(run_dir, "recordings")
        common = {"encoder": cfg.get("encoder", "libx264"), "preset": cfg.get("preset", "veryfast")}
        game = {"fps": int(cfg.get("fps", 30)), "max_width": int(cfg.get("max_width", 1920)),
                "crf": int(cfg.get("crf", 22)), **common}
        viewer = {"fps": int(cfg.get("viewer_fps", 15)), "max_width": int(cfg.get("viewer_max_width", 2560)),
                  "crf": int(cfg.get("viewer_crf", 18)), **common}     # text needs native size and a low crf
        self.streams = {"game": WindowRecorder("game", find_game, folder, **game),
                        "viewer": WindowRecorder("viewer", find_viewer, folder, **viewer)}
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
            self.thread.join(timeout=30)

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
