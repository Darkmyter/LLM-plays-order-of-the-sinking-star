"""Compare the trials of an experiment: per cell (level, model, variant) and per variant across the rest.

Medians, not means: a few runs are noisy and one runaway trial would hide the rest. Moves, turns, tokens and cost
are medians over the SOLVED trials (what it takes to solve), plus the solve rate over all trials.
"""
import statistics

from bench import store

FIELDS = ("moves", "actions", "undos", "restarts", "turns", "tokens", "prompt", "cached", "completion", "cost",
          "seconds", "blocked")


def _median(xs):
    return round(statistics.median(xs), 4) if xs else None


def summarize(trials):
    solved = [t for t in trials if t.get("solved")]
    out = {"n": len(trials), "solved": len(solved), "solve_rate": round(len(solved) / len(trials), 3) if trials else 0,
           "cost_total": round(sum(t.get("cost", 0) for t in trials), 4)}
    for f in FIELDS:
        out[f] = _median([t[f] for t in solved if f in t])
    # What a failed attempt costs is part of the price too: cost per solved level, over everything spent.
    out["cost_per_solve"] = round(out["cost_total"] / len(solved), 4) if solved else None
    spread = [t["moves"] for t in solved]
    out["moves_min"], out["moves_max"] = (min(spread), max(spread)) if spread else (None, None)
    return out


def report(experiment, baseline=True):
    """{cells: [...], variants: [...], trials: n}; each row has the summary numbers."""
    trials = store.read_trials(experiment)
    sol = {}

    def solution_moves(level):
        if level not in sol:
            s = store.read_solution(level)
            sol[level] = s["moves"] if s and s.get("verified") else None
        return sol[level]

    groups = {}
    for t in trials:
        groups.setdefault((t["level"], t["model"], t["variant"]), []).append(t)
    cells = []
    for (level, model, variant), ts in sorted(groups.items()):
        row = {"level": level, "model": model, "variant": variant, **summarize(ts)}
        if baseline:
            row["known_moves"] = solution_moves(level)
        cells.append(row)
    by_variant = {}
    for t in trials:
        by_variant.setdefault(t["variant"], []).append(t)
    variants = [{"variant": v, **summarize(ts)} for v, ts in sorted(by_variant.items())]
    return {"experiment": experiment, "trials": len(trials), "cells": cells, "variants": variants}


def table(rep):
    """The report as text, for the CLI."""
    def f(v):
        return "-" if v is None else (f"{v:.0f}" if isinstance(v, float) and abs(v) >= 100 else f"{v:.3g}" if isinstance(v, float) else str(v))
    head = ("level", "model", "variant", "n", "solve", "moves", "turns", "tokens", "cost$", "cost/solve", "secs")
    rows = [head]
    for c in rep["cells"]:
        rows.append((c["level"], c["model"].split("/")[-1], c["variant"], str(c["n"]), f"{c['solved']}/{c['n']}",
                     f(c["moves"]), f(c["turns"]), f(c["tokens"]), f(c["cost_total"]), f(c["cost_per_solve"]),
                     f(c["seconds"])))
    w = [max(len(r[i]) for r in rows) for i in range(len(head))]
    lines = ["  ".join(x.ljust(w[i]) for i, x in enumerate(r)) for r in rows]
    lines.insert(1, "  ".join("-" * x for x in w))
    if len(rep["variants"]) > 1:
        lines += ["", "By variant (all levels and models):"]
        for v in rep["variants"]:
            lines.append(f"  {v['variant']}: solved {v['solved']}/{v['n']}, median moves {f(v['moves'])}, "
                         f"tokens {f(v['tokens'])}, cost per solve {f(v['cost_per_solve'])}")
    return "\n".join(lines)
