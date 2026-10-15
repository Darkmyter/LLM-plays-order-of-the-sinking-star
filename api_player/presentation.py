"""How the player is shown the game, from two templates (see game/templates.py):

    templates/view/<name>.toml      the world view: map style, legend, lists, lines from you ([view]) and `help`,
                                    how to read it ({view_help} in the general prompt)
    templates/actions/<name>.toml   what an action returns: the view after it or only the changes, the action log
                                    ([result]) and `help` ({results_help} in the general prompt)

The defaults below are what the API player always did, so the `default` templates change nothing.
"""
import re

from api_player.compact import compact_result, split_view
from game import templates

DEFAULTS = {
    "view": {"map": "grid", "rays": False, "legend": True, "fence_list": True, "object_list": True, "floor_rows": True,
             "compact": True},
    "result": {"view": "always", "log": "none", "log_lines": 60},
}
LOG_ENTRY_MAX = 300
TITLE = re.compile(r"^Puzzle level '|, view around you \(\d+x\d+\)")


class Presentation:
    def __init__(self, name, data=None):
        self.name = name
        data = data or {}
        # How to read this view / these results: they replace {view_help} and {results_help} in the general prompt,
        # so the prompt always matches what the player gets.
        self.help = (data.get("help") or "").strip()
        self.results_help = (data.get("results_help") or "").strip()
        self.view = {**DEFAULTS["view"], **data.get("view", {})}
        self.result = {**DEFAULTS["result"], **data.get("result", {})}

    @classmethod
    def load(cls, view="default", actions="default"):
        v, a = templates.read_toml("view", view), templates.read_toml("actions", actions)
        return cls(f"{view}+{actions}", {"view": v.get("view", {}), "help": v.get("help", ""),
                                          "result": a.get("result", {}), "results_help": a.get("help", "")})

    def render_opts(self):
        """What game_state.render() leaves out."""
        return {k: self.view[k] for k in ("map", "rays", "legend", "fence_list", "object_list")}

    def is_default_view(self):
        """True when the game draws exactly the original view (the viewer parses that one)."""
        from game.game_state import RENDER_DEFAULTS
        return self.render_opts() == RENDER_DEFAULTS

    def finish(self, tool, result, floor_rows):
        """The tool result as the player sees it. floor_rows() gives the 'Floor tiles by row' text."""
        if self.view["floor_rows"]:
            result = self._add_floor_rows(result, floor_rows)
        if self.view["compact"]:
            result = compact_result(result)
        if tool == "act" and self.result["view"] == "changes_only":
            before, view, after = split_view(result)
            if view:
                head = before.split("\n")
                if TITLE.search(head[-1]):     # with several heroes the title line sits just outside the view block
                    before = "\n".join(head[:-1]).rstrip()
                result = "\n".join(p for p in (before, after) if p)
        return result

    @staticmethod
    def _add_floor_rows(result, floor_rows):
        """Append the exact floor coordinates to a view, inside the view block, so it is dropped together
        with the map when old observations are stubbed."""
        idx = result.rfind("\nStatus:")
        if idx < 0 or "Symbols:" not in result:
            return result
        try:
            rows = floor_rows()
        except Exception:
            return result
        return result[:idx].rstrip() + ("\n" + rows if rows else "") + "\n" + result[idx:]

    # ---- action log ----
    def logging(self):
        return self.result["log"] != "none"

    @staticmethod
    def log_entries(steps, start):
        """One log line per step of the latest act, numbered from `start`: the step and what the game reported."""
        out = []
        for i, (name, times, lines, _outcome) in enumerate(steps):
            said = "; ".join(l.strip() for l in lines[1:] if l.strip()) or "ok"
            entry = f"#{start + i} {name}" + (f" x{times}" if times > 1 else "") + f": {said}"
            out.append(entry if len(entry) <= LOG_ENTRY_MAX else entry[:LOG_ENTRY_MAX - 3] + "...")
        return out

    def log_text(self, entries):
        """The system-prompt section for the action log, or "" when the log is off."""
        if not self.logging():
            return ""
        shown = entries[-self.result["log_lines"]:]
        head = "# Your actions so far (one line per step, oldest first"
        head += f"; the {len(shown)} latest of {len(entries)})" if len(shown) < len(entries) else ")"
        return head + "\n" + ("\n".join(shown) if shown else "(none yet)")
