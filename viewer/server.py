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
from bench import api as bench_api  # noqa: E402
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


def preview(q):
    """What a player with these templates would be shown and told, for the start options. Reads the game right
    now (no keys, nothing saved); when the game is not in a puzzle level it uses a level captured earlier
    (bench/levels). Query: scope=level|game, prompt, rules, rulebook, view, actions (each optional)."""
    from api_player.actions import action_list, disabled_for
    from api_player import prompting
    from api_player.llm import load_config
    from api_player.presentation import Presentation
    from game.game_state import floor_rows, render
    from game.level_rules import rulebook_text
    one = lambda k: (q.get(k) or [""])[0]
    scope = "game" if one("scope") == "game" else "level"
    tpl = prompting.resolve_templates(load_config(), scope, {k: one(k) for k in ("prompt", "rules", "rulebook", "view", "actions") if one(k)})
    bad = prompting.problems(tpl, scope)
    if bad:
        return {"error": bad}
    state, source = None, ""
    with _game_lock:
        try:
            state = get_game(scope == "level").snapshot()
            source = f"the game right now ({state['level']})"
            if scope == "level" and (state["open_world"] or state["level"].startswith("menu_")):
                state = None
        except Exception as e:
            _games.pop(scope == "level", None)
            source = f"the game is not reachable ({e})"
    if state is None:
        from bench import store
        saved = store.list_levels()
        if not saved:
            return {"error": "the game is not in a puzzle level and no level has been captured yet; "
                             "put the game in a level to see the preview", "templates": tpl}
        state = store.load_state(store.read_level(saved[0]["name"])["state"])
        source = f"captured level {saved[0]['name']} (the game is not in a puzzle level)"
    pres = Presentation.load(tpl["view"], tpl["actions"])
    shown = render(state, None, pres.render_opts()) + "\n\nStatus: ready for input."
    screen = pres.finish("look", shown, lambda: floor_rows(state))
    hero = next((o for o in state["objects"] if o.get("selected")), None)
    x, y = (round(hero["pos"][0]), round(hero["pos"][1])) if hero else (0, 0)
    sample = f"> north\n  Hero moved ({x},{y}) -> ({x},{y + 1})   (an example: the real report depends on what happens)\n\n"
    act = pres.finish("act", sample + shown, lambda: floor_rows(state))
    rulebook, missing = "", []
    if scope == "level" and tpl["rulebook"] == "prefilled":
        rulebook, missing = rulebook_text(state, tpl["rules"])
    actions = action_list(disabled_for(state["objects"]) if scope == "level" else [])
    system = prompting.system_text(scope, tpl, actions, rulebook, "(your notes appear here)",
                                   log_text=pres.log_text(["#1 north: (your actions appear here)"]))
    return {"scope": scope, "source": source, "level": state["level"], "templates": tpl, "screen": screen, "act": act,
            "original": render(state),
            "rulebook": prompting.rulebook_section(tpl["rules"], tpl["rulebook"], rulebook), "missing": missing,
            "system": system, "tools": ["act", "look", "note", "write_note"] + (
                ["rulebook_add", "rulebook_write"] if tpl["rulebook"] == "empty" else [])
            + (["world_map"] if scope == "game" else [])}


def debug_level(q=None):
    """The game's current level as the single-level player would get it: the preview with the templates in the query
    (default templates otherwise). `screen` is the text the player is sent; `original` is the original view, which
    the viewer's map UI is drawn from whatever the world view template."""
    out = preview({"scope": ["level"], **{k: v for k, v in (q or {}).items() if k in ("prompt", "rules", "rulebook", "view", "actions")}})
    if out.get("error"):
        return out
    return {"level": out["level"], "open_world": False, "source": out["source"], "screen": out["screen"],
            "original": out["original"], "templates": out["templates"], "rules": out["rulebook"],
            "missing": out["missing"], "prompt": out["system"]}


_debug_session = None


def debug_act(body):
    """Do actions in the game from the debug window and return the report exactly as a player with these templates
    would get it (and the action-log lines, when the actions template keeps a log). This PRESSES KEYS in the game,
    so it refuses while a player run is active. Body: {commands, view?, actions?}."""
    global _debug_session
    import urllib.request
    from api_player.presentation import Presentation
    from game.game_state import floor_rows
    try:
        with urllib.request.urlopen("http://127.0.0.1:8766/status", timeout=1) as r:
            st = json.loads(r.read() or b"{}")
        if st.get("active") and st.get("status") in ("running", "paused"):
            return {"error": f"run '{st['active']}' is {st['status']}; stop it before acting from here"}
    except Exception:
        pass    # no control server: no player run can be active
    try:
        pres = Presentation.load(body.get("view") or "default", body.get("actions") or "default")
    except (FileNotFoundError, ValueError) as e:
        return {"error": str(e)}
    commands = str(body.get("commands", "")).strip()
    if not commands:
        return {"error": "type an action, e.g. north, east 2, undo"}
    with _game_lock:
        try:
            if _debug_session is None:
                from game.session import Session
                _debug_session = Session(os.path.join(ROOT, "runs", "_scratch", "debug"), zero_origin=True)
            s = _debug_session
            s.render_opts = pres.render_opts()
            raw = s.do_sequence(commands)
            shown = pres.finish("act", raw, lambda: floor_rows(s.game.snapshot()))
        except Exception as e:
            _debug_session = None
            return {"error": f"{e} (is the game running?)"}
    entries = pres.log_entries(s.last_steps, 1) if pres.logging() else []
    return {"result": shown, "log": pres.log_text(entries) if entries else "", "templates": pres.name}


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
        for name in (("notes.md",) if not files else ()) + ("rulebook.md", "journal.md"):
            p = os.path.join(rdir, name)
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as f:
                    files.append({"name": name, "mtime": os.path.getmtime(p), "content": f.read()})
        return files
    return sorted(files, key=lambda f: f["name"])


def read_context(rdir):
    """What the API player's next model call would send: the system message, then the history."""
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
    from api_player import prompting
    from api_player.actions import action_list
    from api_player.llm import load_config
    from api_player.presentation import Presentation
    scope = meta.get("scope", "game")
    tpl = prompting.for_saved_run(load_config(), scope, meta.get("templates"))
    try:
        log_text = Presentation.load(tpl["view"], tpl["actions"]).log_text(json.loads(text(os.path.join(rdir, "action_log.json")) or "[]"))
        rulebook = text(os.path.join(rdir, "rulebook.md")) or text(os.path.join(rdir, "level_rules.md"))
        system = prompting.system_text(scope, tpl, action_list(meta.get("disabled", [])), rulebook, pages.render(),
                                       text(os.path.join(rdir, "journal.md")), log_text)
    except (ValueError, FileNotFoundError) as e:
        system = f"(cannot rebuild the system message: {e})"
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
        elif url.path in bench_api.LOCAL_GET:
            try:
                self.send_json(bench_api.get(url.path, q))
            except (FileNotFoundError, ValueError) as e:
                self.send_json({"error": str(e)})
        elif url.path == "/bench":
            with open(os.path.join(HERE, "bench.html"), encoding="utf-8") as f:
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
            self.send_json(debug_level(q))
        elif url.path == "/preview":
            self.send_json(preview(q))
        elif url.path == "/templates":
            from api_player import prompting
            from api_player.llm import load_config
            from game import templates
            cfg = load_config()
            self.send_json({"templates": templates.describe(),
                            "defaults": {sc: prompting.resolve_templates(cfg, sc) for sc in templates.SCOPES}})
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
        if url.path == "/debug/act":
            self.send_json(debug_act(body))
        elif url.path in bench_api.LOCAL_POST:
            with _game_lock:
                self.send_json(bench_api.post(url.path, body, lambda: False))
        elif url.path == "/new" and parse_qs(url.query).get("mode") == ["agent"]:
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
