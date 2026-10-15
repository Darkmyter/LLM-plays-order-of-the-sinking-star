"""The benchmark's HTTP routes, mounted by api_player/control.py (one player process owns the game).

GET  /bench/levels                    captured levels
GET  /bench/experiments               experiment definitions
GET  /bench/templates                 variants available per kind
GET  /bench/status                    the running (or last) experiment's progress
GET  /bench/report?experiment=NAME    per-cell and per-variant comparison
GET  /bench/trials?experiment=NAME    every finished trial
GET  /bench/level?name=NAME           one level: how it looks, rules needed, its solution
POST /bench/capture    {name?}                             save the level the game is in now (named after the game's level unless a name is given)
POST /bench/solution   {level, run? | commands?}           record a solution from a solved run, or pasted moves
POST /bench/verify     {level}                             replay the solution in the game (the game must be in the level)
POST /bench/experiment {name, levels, models, variants, runs, limits?, effort?}   save an experiment
POST /bench/start      {experiment}                        run it (resumes if some trials are done)
POST /bench/stop
Routes that only read files or the game's memory (LOCAL_*) are also served by the viewer server, so the benchmark
page works without a player process. Running trials, stopping them and verifying a solution press keys in the
game, so they need the control server.
"""
from bench import report as report_mod
from bench import runner, solutions, store
from game import templates

_bench = None   # the Benchmark of the latest start

LOCAL_GET = {"/bench/levels", "/bench/experiments", "/bench/templates", "/bench/report", "/bench/trials", "/bench/level"}
LOCAL_POST = {"/bench/capture", "/bench/solution", "/bench/experiment"}


def running():
    return bool(_bench and _bench.alive())


def get(path, q):
    """JSON for a GET route, or None if the path is not a bench route."""
    one = lambda k: (q.get(k) or [""])[0]
    if path == "/bench/levels":
        return store.list_levels()
    if path == "/bench/experiments":
        return store.list_experiments()
    if path == "/bench/templates":
        return templates.describe()
    if path == "/bench/status":
        return _bench.status() if _bench else {"state": "idle"}
    if path == "/bench/report":
        return report_mod.report(one("experiment"))
    if path == "/bench/trials":
        return store.read_trials(one("experiment"))
    if path == "/bench/level":
        info = store.read_level(one("name"))
        return {**{k: v for k, v in info.items() if k != "state"}, "solution": store.read_solution(info["name"])}
    return None


def post(path, body, run_active):
    """JSON for a POST route, or None. run_active() says whether a normal player run is using the game."""
    global _bench
    try:
        if path == "/bench/capture":      # reads the game's memory only; fine while a run is going
            return store.capture_level(body.get("name"))
        if path == "/bench/solution":
            if body.get("run"):
                return solutions.record_from_run(body["level"], body["run"])
            return solutions.record_from_text(body["level"], body.get("commands", ""))
        if path == "/bench/verify":
            if running() or run_active():
                return {"error": "the game is in use by a run; stop it first"}
            return solutions.verify(body["level"])
        if path == "/bench/experiment":
            return store.save_experiment(body)
        if path == "/bench/start":
            if running():
                return {"error": "an experiment is already running"}
            if run_active():
                return {"error": "a player run is active; stop it first"}
            _bench = runner.Benchmark(store.read_experiment(body["experiment"]))
            _bench.start()
            return _bench.status()
        if path == "/bench/stop":
            if _bench:
                _bench.stop()
            return _bench.status() if _bench else {"state": "idle"}
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as e:
        return {"error": str(e.args[0]) if isinstance(e, KeyError) else str(e)}
    return None
