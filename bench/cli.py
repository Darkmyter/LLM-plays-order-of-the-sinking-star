"""Command line for the benchmark (the viewer uses the same code through api_player.control).

    uv run python -m bench.cli levels
    uv run python -m bench.cli capture [name]                  # the game must be in the level; the name defaults to the game's level name
    uv run python -m bench.cli solution <level> --run <run>    # from a solved run   (or: --moves "north 3, e2, activate")
    uv run python -m bench.cli verify <level>                  # replay the solution in the game
    uv run python -m bench.cli experiment <file.json>          # save an experiment definition
    uv run python -m bench.cli run <experiment>
    uv run python -m bench.cli report <experiment>
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bench import report, runner, solutions, store  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("levels")
    sub.add_parser("experiments")
    p = sub.add_parser("capture"); p.add_argument("name", nargs="?")
    p = sub.add_parser("solution"); p.add_argument("level"); p.add_argument("--run"); p.add_argument("--moves")
    p = sub.add_parser("verify"); p.add_argument("level")
    p = sub.add_parser("experiment"); p.add_argument("file")
    p = sub.add_parser("run"); p.add_argument("experiment")
    p = sub.add_parser("report"); p.add_argument("experiment")
    a = ap.parse_args(argv)

    if a.cmd == "levels":
        for l in store.list_levels():
            sol = f"solution {l['solution_steps']} steps" + (" (verified)" if l["solution_verified"] else "") if l["solution"] else "no solution"
            print(f"{l['name']:20} {l['game_level']:24} {sol}   kinds: {', '.join(l['kinds'])}")
    elif a.cmd == "experiments":
        for e in store.list_experiments():
            print(f"{e['name']:20} levels={e['levels']} models={len(e['models'])} variants={len(e['variants'])} runs={e['runs']}")
    elif a.cmd == "capture":
        print(json.dumps(store.capture_level(a.name), indent=1))
    elif a.cmd == "solution":
        sol = (solutions.record_from_run(a.level, a.run) if a.run else solutions.record_from_text(a.level, a.moves or ""))
        print(f"saved: {sol['steps']} steps ({sol['moves']} moves): {sol['commands']}")
    elif a.cmd == "verify":
        sol = solutions.verify(a.level)
        print("verified" if sol["verified"] else "NOT solved by replay")
    elif a.cmd == "experiment":
        with open(a.file, encoding="utf-8") as f:
            e = store.save_experiment(json.load(f))
        print(f"saved '{e['name']}': {len(runner.plan(e))} trials")
    elif a.cmd == "run":
        bench = runner.Benchmark(store.read_experiment(a.experiment))
        print(f"{len(bench.trials)} trials, {len(bench.done)} already done")
        bench.start()
        last = None
        try:
            while bench.alive():
                s = bench.status()
                line = f"[{s['state']}] {s['done']}/{s['total']} {s['message']}"
                if s["current"]:
                    c = s["current"]
                    line += f" | #{c['index']} {c['level']} {c['model']} {c['variant']} turns={c['turns']} ${c['cost']}"
                if line != last:
                    print(line, flush=True)
                    last = line
                time.sleep(2)
        except KeyboardInterrupt:
            print("stopping after the current step...")
            bench.stop()
            bench.thread.join()
        print(bench.status()["state"], bench.message)
    elif a.cmd == "report":
        print(report.table(report.report(a.experiment)))


if __name__ == "__main__":
    main()
