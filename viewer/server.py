"""Live viewer: shows what a player sees, every action it takes, and the game right now.

    uv run python -m viewer.server        # then open http://127.0.0.1:8765

Pick a player (API player or coding agent), then a run. For one run it reads
runs/<mode>/<name>/ (log.jsonl, notes, speech) and, for the "Game now" map, the game's memory
(read-only: no keys, not logged, no discoveries marked). Local only.
"""
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from api_player.notes import Notes  # noqa: E402
from game import runs, stats  # noqa: E402

PORT = 8765
WORKSPACE = os.path.join(ROOT, "coding_player", "workspace")


def read_jsonl(path, start=0):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    out = []
    for i, line in enumerate(lines[start:], start):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            break  # partially written last line
        e["i"] = i
        out.append(e)
    return out


_games, _game_lock = {}, threading.Lock()   # one Game per coordinate style (zero_origin False / True)


def get_game(zero_origin=False):
    from game.game_state import Game
    if zero_origin not in _games:
        _games[zero_origin] = Game(zero_origin=zero_origin)
    return _games[zero_origin]


def current_screen(rdir):
    """Read the game right now (read-only, no keys pressed, not logged, no discoveries marked).
    Uses the run's saved labels so 'Rock 3' means the same rock in both maps."""
    zero = False
    try:   # single-level runs show coordinates from 0
        with open(os.path.join(rdir, "meta.json"), encoding="utf-8") as f:
            zero = json.load(f).get("scope") == "level"
    except (FileNotFoundError, ValueError):
        pass
    with _game_lock:
        try:
            from game.game_state import nkey, render
            state = get_game(zero).snapshot()
            try:
                with open(os.path.join(rdir, "state", "labels.json"), encoding="utf-8") as f:
                    saved = json.load(f).get(state["level"], {})
            except (FileNotFoundError, ValueError):
                saved = {}
            numbered = {(int(k.split(":")[1]), k.split(":")[0]): v for k, v in saved.items()}
            for o in sorted(state["objects"], key=lambda o: (nkey(o)[1], o["id"])):
                if nkey(o) not in numbered:
                    numbered[nkey(o)] = 1 + max(
                        (v for (_, k), v in numbered.items() if k == nkey(o)[1]), default=0)
            return render(state, numbered)
        except Exception as e:
            _games.pop(zero, None)
            return f"error: {e} (is the game running and in a level?)"


def debug_level():
    """The game's current level as the single-level player would get it: the view (no player needed, no keys
    pressed, no labels saved), the rules written for the objects in it, and the full system prompt."""
    with _game_lock:
        try:
            from game.game_state import render
            from game.level_rules import rules_text
            from api_player.actions import action_list, disabled_for
            state = get_game(True).snapshot()
        except Exception as e:
            _games.pop(True, None)
            return {"error": f"{e} (is the game running and in a level?)"}
    rules, missing = rules_text(state)
    try:
        with open(os.path.join(ROOT, "api_player", "level_prompt.md"), encoding="utf-8") as f:
            prompt = (f.read().replace("{rules}", rules or "(nothing described)")
                      .replace("{actions}", action_list(disabled_for(state["objects"]))))
    except FileNotFoundError:
        prompt = ""
    return {"level": state["level"], "open_world": state["open_world"], "screen": render(state),
            "rules": rules, "missing": missing, "prompt": prompt}


def read_speech(rdir, limit=300):
    """Last commentary lines (from the `say` tool) with their voice state from voice_worker.py."""
    lines = read_jsonl(os.path.join(rdir, "speech.jsonl"))[-limit:]
    state = {}
    for s in read_jsonl(os.path.join(rdir, "voice.jsonl")):
        state[s["id"]] = s
    for l in lines:
        s = state.get(l["id"])
        l["state"] = s["state"] if s else "waiting"
        if s and s["state"] == "speaking":
            l["ends"] = s["t"] + s.get("dur", 0)
    return lines


def read_notes(mode, rdir):
    """Both players keep their notes as pages in a notes/ folder. API runs also have journal.md
    (read-only: the signs and recordings the harness kept), and older API runs a single notes.md."""
    files = []
    base = os.path.join(rdir, "notes")
    for root, _, names in os.walk(base):
        for n in names:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, base).replace(os.sep, "/")
            with open(p, encoding="utf-8", errors="replace") as f:
                files.append({"name": rel, "mtime": os.path.getmtime(p), "content": f.read()})
    if mode == "api":
        order = {n + ".md": i for i, n in enumerate(("progress", "mechanics", "characters", "world"))}
        files.sort(key=lambda f: (order.get(f["name"], len(order)), f["name"]))
        for name in (("notes.md",) if not files else ()) + ("journal.md",):
            p = os.path.join(rdir, name)
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as f:
                    files.append({"name": name, "mtime": os.path.getmtime(p), "content": f.read()})
        return files
    return sorted(files, key=lambda f: f["name"])


def read_context(rdir):
    """What the API player's next model call would send: system prompt + notes, then history."""
    def text(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""
    try:
        history = json.loads(text(os.path.join(rdir, "history.json")) or "[]")
    except ValueError:
        history = []
    pages = Notes(os.path.join(rdir, "notes"))
    pages.load(legacy_file=os.path.join(rdir, "notes.md"))
    meta = runs.read_meta("api", os.path.basename(rdir)) or {}
    prompt = text(os.path.join(ROOT, "api_player", "level_prompt.md" if meta.get("scope") == "level" else "prompt.md"))
    from api_player.actions import action_list
    system = (prompt.replace("{rules}", text(os.path.join(rdir, "level_rules.md")) or "(nothing described)")
              .replace("{actions}", action_list(meta.get("disabled", []))))
    system += "\n\n# Your notes\n" + pages.render()
    journal = text(os.path.join(rdir, "journal.md"))
    if journal:
        system += ("\n\n# Journal (read-only: the game keeps every sign and recording you have read or heard)\n"
                   + journal)
    return [{"role": "system", "content": system}] + history


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj):
        self.send(json.dumps(obj), "application/json")

    @staticmethod
    def run_of(q):
        """(mode, run dir) from the query, or (None, None) when no valid run is selected."""
        mode, name = q.get("mode", [""])[0], q.get("run", [""])[0]
        if mode in runs.MODES and runs.exists(mode, name):
            return mode, runs.run_dir(mode, name)
        return None, None

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/":
            with open(os.path.join(HERE, "page.html"), encoding="utf-8") as f:
                self.send(f.read(), "text/html; charset=utf-8")
        elif url.path == "/runs":
            mode = q.get("mode", [""])[0]
            self.send_json(runs.list_runs(mode) if mode in runs.MODES else [])
        elif url.path == "/compare":
            mode = q.get("mode", [""])[0]
            self.send_json(stats.compare(mode) if mode in runs.MODES else [])
        elif url.path == "/levels":
            try:   # every level and area of the game, from tools/dump_levels.py
                with open(os.path.join(ROOT, "game", "levels.json"), encoding="utf-8") as f:
                    self.send_json(json.load(f))
            except (FileNotFoundError, ValueError):
                self.send_json({})
        elif url.path == "/debug":
            self.send_json(debug_level())
        elif url.path == "/info":
            self.send_json({"workspace": WORKSPACE})
        elif url.path in ("/log", "/snapshot", "/voice", "/notes", "/messages", "/context", "/stats"):
            mode, rdir = self.run_of(q)
            if rdir is None:
                if url.path == "/snapshot":
                    self.send("error: no run selected", "text/plain; charset=utf-8")
                else:
                    self.send_json([])
            elif url.path == "/log":
                self.send_json(read_jsonl(os.path.join(rdir, "log.jsonl"), int(q.get("from", ["0"])[0])))
            elif url.path == "/snapshot":
                self.send(current_screen(rdir), "text/plain; charset=utf-8")
            elif url.path == "/voice":
                self.send_json(read_speech(rdir))
            elif url.path == "/messages":
                self.send_json(read_jsonl(os.path.join(rdir, "transcript.jsonl"), int(q.get("from", ["0"])[0])))
            elif url.path == "/stats":
                self.send_json(stats.cached(mode, q["run"][0]))
            elif url.path == "/context":
                self.send_json(read_context(rdir))
            else:
                self.send_json(read_notes(mode, rdir))
        else:
            self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        if url.path == "/new" and parse_qs(url.query).get("mode") == ["agent"]:
            try:
                self.send_json({"name": runs.create("agent", body.get("name"))})
            except FileExistsError as e:
                self.send_json({"error": str(e)})
        else:
            self.send_error(404)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Live viewer on {url}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
