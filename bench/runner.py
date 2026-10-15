"""Runs an experiment: every trial is a single-level API run, one after another (there is one game window).

Trials are ordered round by round (run 1 of every cell, then run 2 of every cell, ...), so a slow drift in
the model or the provider does not favour one cell. Finished trials are in bench/results/<experiment>/trials.jsonl,
so an interrupted experiment resumes where it stopped.

Between trials the level is reset with `restart`. A solved level leaves the game in the open world, and the
harness cannot walk back into it: it then waits until the game is in the level again (you enter it).
"""
import threading
import time

from bench import store
from bench.metrics import trial_metrics
from game import runs
from game.game_state import Game

DEFAULT_LIMITS = {"max_turns": 80, "max_cost_usd": 1.0}
WAIT_FOR_LEVEL = 20 * 60      # seconds the runner waits for the game to be in the level before giving up


def cells(exp):
    """The experiment's cells: one per (level, model, variant)."""
    return [{"level": lv, "model": m, "variant": v, "variant_name": store.variant_name(v)}
            for lv in exp["levels"] for m in exp["models"] for v in exp["variants"]]


def plan(exp):
    """Every trial in order: [{index, cell, run}]. `index` is stable, so a resumed experiment skips what is done."""
    cs, out = cells(exp), []
    for r in range(exp["runs"]):
        for c in cs:
            out.append({"index": len(out) + 1, "cell": c, "run": r + 1})
    return out


class Benchmark:
    def __init__(self, exp):
        self.exp = exp
        self.trials = plan(exp)
        self.done = {t["index"] for t in store.read_trials(exp["name"])}
        self.state = "idle"        # idle | running | waiting | done | stopped | error
        self.message = ""
        self.current = None        # the trial being run
        self.run = None            # its Run
        self.stop_flag = threading.Event()
        self.thread = None
        self.game = None
        self._reset = None         # a Session used only to restart the level between trials

    # ---- control ----
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_flag.clear()
        self.state = "running"
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()
        if self.run is not None:
            self.run.stop()

    def alive(self):
        return bool(self.thread and self.thread.is_alive())

    def status(self):
        cur = self.current
        return {"experiment": self.exp["name"], "state": self.state, "message": self.message,
                "total": len(self.trials), "done": len(self.done),
                "current": ({"index": cur["index"], "level": cur["cell"]["level"], "model": cur["cell"]["model"],
                             "variant": cur["cell"]["variant_name"], "run": cur["run"],
                             "run_name": self.run.name if self.run else None,
                             "turns": self.run.turns if self.run else 0,
                             "cost": round(self.run.usage.cost, 4) if self.run else 0} if cur else None)}

    # ---- the loop ----
    def _loop(self):
        try:
            for t in self.trials:
                if self.stop_flag.is_set():
                    break
                if t["index"] in self.done:
                    continue
                self.current = t
                self._trial(t)
                self.run = None
            self.current = None
            self.state = "stopped" if self.stop_flag.is_set() else "done"
            self.message = "" if self.state == "done" else "stopped"
        except Exception as e:
            self.state, self.message = "error", str(e)
        finally:
            self.run = None

    def _game(self):
        if self.game is None:
            self.game = Game(zero_origin=True)
        return self.game

    def _current_level(self):
        g = self._game()
        return g.level_name(g.current_manager())

    def _ready(self, level):
        """Put the game at the start of `level`: restart it if it is in it, else wait for the player to enter it."""
        info = store.read_level(level)
        t0 = time.time()
        while not self.stop_flag.is_set():
            try:
                here = self._current_level()
            except Exception:
                self.game = None
                here = None
            if here == info["game_level"]:
                self.state, self.message = "running", ""
                from game.session import Session
                if self._reset is None:
                    self._reset = Session(zero_origin=True)
                self._reset.close_menu_if_open()
                self._reset.do("restart")
                return True
            self.state, self.message = "waiting", f"waiting for the game to be in level '{level}' (now: {here or 'not running'})"
            if time.time() - t0 > WAIT_FOR_LEVEL:
                raise RuntimeError(self.message)
            time.sleep(1.0)
        return False

    def _trial(self, t):
        from api_player.llm import load_config
        from api_player.player import Run
        c, exp = t["cell"], self.exp
        if not self._ready(c["level"]):
            return
        cfg = load_config()
        cfg["model"] = c["model"]
        cfg["limits"] = {**cfg["limits"], **DEFAULT_LIMITS, **(exp.get("limits") or {})}
        cfg["recording"] = {**(cfg.get("recording") or {}), "enabled": bool(exp.get("record", False))}
        name = f"b-{exp['name'][:24]}-{t['index']:03d}"
        if runs.exists("api", name):
            name += time.strftime("-%H%M%S")
        names = {k: v for k, v in c["variant"].items() if k in ("prompt", "rules", "rulebook", "view", "actions")}
        run = Run(name, cfg, create=True, scope="level", template_names=names)
        run.prepare_level()
        run.effort = exp.get("effort", "")
        runs.write_meta("api", run.name, bench={"experiment": exp["name"], "index": t["index"], "level": c["level"],
                                               "variant": c["variant_name"], "run": t["run"]})
        self.run = run
        run.start()
        while run.thread and run.thread.is_alive():
            if self.stop_flag.is_set():
                run.stop()
            run.thread.join(0.5)
        run.save()
        if self.stop_flag.is_set() and run.status not in ("solved",):
            return        # an interrupted trial is not a result; it is rerun when the experiment resumes
        m = trial_metrics(run.name)
        trial = {"index": t["index"], "run_index": t["run"], "level": c["level"], "model": c["model"],
                 "variant": c["variant_name"], "templates": run.templates, "run_name": run.name,
                 "finished": time.time(), **m}
        store.append_trial(exp["name"], trial)
        self.done.add(t["index"])
