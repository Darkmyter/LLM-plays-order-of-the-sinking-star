"""Control server for the API player: the viewer talks to this, nothing else does.

    uv run python -m api_player.control        # http://127.0.0.1:8766

GET  /runs                 -> list of runs (name, model, turns, cost, status, updated)
GET  /status               -> the active run's live status
GET  /templates            -> the variants available per kind, with descriptions
POST /new     {name?, model?, effort?, scope?, templates?: {prompt?, rules?, rulebook?, view?, actions?}}   create a run and start it; scope "level" = solve the level
                                the game is in now (prompt written from the objects in it), then stop
POST /resume  {name}            load an existing run and start it
POST /pause | /unpause | /stop
POST /config  {model?, effort?} change the model / reasoning effort for the active run (next turn)
The benchmark routes (/bench/...) are in bench/api.py.
Local only.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_player.llm import load_config  # noqa: E402
from api_player.player import EFFORTS, MODE, Run  # noqa: E402
from bench import api as bench_api  # noqa: E402
from api_player import prompting  # noqa: E402
from game import runs, templates  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

PORT = 8766
active = None


def status():
    if active is None:
        return {"active": None}
    u = active.usage
    return {"active": active.name, "status": active.status, "model": active.cfg["model"], "effort": active.effort,
            "turns": active.turns, "last": active.last_line, "prompt": u.prompt,
            "cached": u.cached, "completion": u.completion, "cost": round(u.cost, 4),
            "phase": active.phase, "phase_for": round(time.time() - active.phase_since, 1),
            "recording": active.recording_status()}


def start_run(name, create, model=None, effort=None, scope="game", template_names=None):
    global active
    if active is not None and active.thread and active.thread.is_alive():
        return {"error": f"run '{active.name}' is still running; stop it first"}
    if bench_api.running():
        return {"error": "a benchmark experiment is running; stop it first"}
    cfg = load_config()
    if model:
        cfg["model"] = model
    name = runs.slug(name) or time.strftime("run-%Y%m%d-%H%M%S")
    if create and runs.exists(MODE, name):
        return {"error": f"run '{name}' already exists"}
    if not create and not runs.exists(MODE, name):
        return {"error": f"no run named '{name}'"}
    if create:
        bad = prompting.problems(prompting.resolve_templates(cfg, scope, template_names), scope)
        if bad:
            return {"error": bad}
    run = Run(name, cfg, create=create, scope=scope if create else "game", template_names=template_names)
    missing = []
    if create and scope == "level":
        try:
            missing = run.prepare_level()
        except Exception as e:
            import shutil
            shutil.rmtree(run.dir, ignore_errors=True)
            return {"error": f"cannot start a single-level run: {e}"}
    active = run  # a resumed run uses the model from config.toml unless given
    if effort is not None:                  # "" = the config.toml default
        active.effort = effort if effort in EFFORTS else ""
        active.save()                       # so a page opened right now shows it, not the old value
    active.start()
    return dict(status(), missing_rules=missing)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in (("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Headers", "*"),
                     ("Access-Control-Allow-Methods", "GET, POST")):
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/bench/"):
            try:
                out = bench_api.get(url.path, parse_qs(url.query))
            except (FileNotFoundError, ValueError) as e:
                out = {"error": str(e)}
            return self.reply(out if out is not None else {"error": "not found"}, 200 if out is not None else 404)
        if self.path == "/runs":
            self.reply(runs.list_runs(MODE))
        elif self.path == "/defaults":
            cfg = load_config()
            self.reply({"model": cfg["model"], "suggested": cfg.get("suggested_models", []),
                        "efforts": list(EFFORTS), "effort": (cfg.get("reasoning") or {}).get("effort", "")})
        elif self.path == "/status":
            self.reply(status())
        elif self.path == "/templates":
            self.reply(templates.describe())
        else:
            self.reply({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        p = self.path
        if p.startswith("/bench/"):
            out = bench_api.post(p, body, lambda: bool(active is not None and active.thread and active.thread.is_alive()))
            return self.reply(out if out is not None else {"error": "not found"}, 200 if out is not None else 404)
        if p == "/new":
            self.reply(start_run(body.get("name"), True, body.get("model"), body.get("effort"),
                                  "level" if body.get("scope") == "level" else "game", body.get("templates")))
        elif p == "/resume":
            self.reply(start_run(body.get("name"), False, body.get("model"), body.get("effort")))
        elif active is None:
            self.reply({"error": "no active run"}, 409)
        elif p == "/pause":
            active.pause_flag.set()
            self.reply(status())
        elif p == "/unpause":
            active.pause_flag.clear()
            self.reply(status())
        elif p == "/stop":
            active.stop()
            self.reply(status())
        elif p == "/config":
            if body.get("model"):
                active.cfg["model"] = body["model"]
            if "effort" in body:
                active.effort = body["effort"] if body["effort"] in EFFORTS else ""
                active.save()
            self.reply(status())
        else:
            self.reply({"error": "not found"}, 404)


def main():
    os.makedirs(runs.mode_dir(MODE), exist_ok=True)
    print(f"API player control on http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
