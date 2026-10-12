"""The API player: runs one playthrough ("run") against any OpenAI-compatible model.

A run is a folder runs/api/<name>/ (see game/runs.py) holding meta.json, history.json (the
message list the model sees, pruned; saved every turn so a run can be resumed), transcript.jsonl
(every message ever sent or received, append-only, for the viewer), notes.md, log.jsonl (every
tool call) and state/ (discovered signs, object labels).
"""
import json
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # so `game` and `api_player` import when run as a script

from api_player.compact import compact_result, stub_result  # noqa: E402
from api_player.llm import Usage, load_config, make_client  # noqa: E402
from game import runs  # noqa: E402

MODE = "api"
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")

TOOLS = [
    {"type": "function", "function": {
        "name": "act",
        "description": "Do game actions in order, e.g. \"north 3, e2, activate, undo\". Items: "
                       "north/south/east/west (n/s/e/w), undo, restart, activate, take_or_drop, "
                       "switch_character, select_1..select_9, each with an optional repeat count. "
                       "Stops at the first step that does not go as asked; shows the view at the end.",
        "parameters": {"type": "object", "properties": {"commands": {"type": "string"}},
                       "required": ["commands"]}}},
    {"type": "function", "function": {
        "name": "look", "description": "Show the current view without acting.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "world_map", "description": "Discovered areas and teleporters (open world only).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "note",
        "description": "Add one line to your notes (shown at the top of every turn). kind 'seen': something "
                       "you directly observed, with where. kind 'believe': a guess or a general rule, with how "
                       "sure you are. Cheap, so use it the moment you learn or guess something.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["seen", "believe"]}, "text": {"type": "string"}},
            "required": ["kind", "text"]}}},
    {"type": "function", "function": {
        "name": "write_note",
        "description": "Replace all your notes (markdown): use it to tidy them, e.g. merge lines, drop guesses "
                       "that turned out wrong. Keep the '## Seen' and '## Believe' sections.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}},
                       "required": ["text"]}}},
]


class Run:
    def __init__(self, name, cfg, create=False):
        self.name = runs.slug(name)
        self.dir = runs.run_dir(MODE, name)
        self.cfg = cfg
        self.lim = cfg["limits"]
        self.usage = Usage()
        self.messages = []
        self.turns = 0
        self.last_note_turn = 0
        self.last_nudge_turn = 0
        self.seen_kinds, self.seen_stops = set(), set()
        self.effort = ""          # reasoning effort for this run; "" = the config.toml default
        self.notes = ""
        self.status = "idle"
        self.last_line = ""
        self.phase, self.phase_since = "idle", time.time()
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()
        self.thread = None
        self._session = None
        if create:
            runs.create(MODE, self.name)
            self.save()
        else:
            self._load()

    # ---- persistence ----
    def _path(self, f):
        return os.path.join(self.dir, f)

    def _load(self):
        meta = runs.read_meta(MODE, self.name)
        self.turns = meta.get("turns", 0)
        self.effort = meta.get("effort", "")
        for k, v in meta.get("usage", {}).items():
            setattr(self.usage, k, v)
        for fname, attr, default in (("history.json", "messages", []), ("notes.md", "notes", "")):
            try:
                with open(self._path(fname), encoding="utf-8") as f:
                    setattr(self, attr, json.load(f) if fname.endswith(".json") else f.read())
            except FileNotFoundError:
                setattr(self, attr, default)

    def save(self):
        with open(self._path("history.json"), "w", encoding="utf-8") as f:
            json.dump(self.messages, f)
        with open(self._path("notes.md"), "w", encoding="utf-8") as f:
            f.write(self.notes)
        u = self.usage
        runs.write_meta(MODE, self.name, model=self.cfg["model"], effort=self.effort, turns=self.turns,
                        status=self.status,
                        usage={"prompt": u.prompt, "cached": u.cached, "completion": u.completion,
                               "cost": u.cost, "calls": u.calls})

    def log(self, entry):
        with open(self._path("log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def record(self, msg, **extra):
        """Append a message to the full transcript (history.json is pruned, this is not)."""
        line = dict(msg, turn=self.turns, t=time.time(), **extra)
        with open(self._path("transcript.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    # ---- tools ----
    def session(self):
        if self._session is None:
            from game.session import Session
            self._session = Session(os.path.join(self.dir, "state"))
        return self._session

    def call_tool(self, name, args):
        t0 = time.time()
        try:
            if name == "act":
                result = self.session().do_sequence(str(args.get("commands", "")))
            elif name == "look":
                result = self.session().look()
            elif name == "world_map":
                from game.game_state import world_map
                result = world_map(self.session().game)
            elif name == "write_note":
                self.notes = str(args.get("text", ""))
                result = f"notes saved ({len(self.notes)} chars)"
            elif name == "note":
                result = self.add_note(str(args.get("kind", "")), str(args.get("text", "")))
            else:
                result = f"unknown tool {name}"
        except Exception as e:  # game closed or restarted: reconnect on the next call
            self._session = None
            result = f"error: {e} (is the game running and in a level?)"
        self.log({"t": t0, "ms": round((time.time() - t0) * 1000), "tool": name, "args": args,
                  "result": result})
        return result

    def add_note(self, kind, text):
        """Append one bullet to the '## Seen' or '## Believe' section of the notes (created if missing)."""
        if kind not in ("seen", "believe") or not text.strip():
            return "note needs kind 'seen' or 'believe' and some text"
        head = "## Seen" if kind == "seen" else "## Believe"
        lines = self.notes.rstrip().split("\n") if self.notes.strip() else []
        at = next((i for i, l in enumerate(lines) if l.strip() == head), None)
        if at is None:
            lines += ([""] if lines else []) + [head]
            at = len(lines) - 1
        end = at + 1
        while end < len(lines) and not lines[end].startswith("## "):
            end += 1
        while end - 1 > at and not lines[end - 1].strip():
            end -= 1
        lines.insert(end, f"- (turn {self.turns}) {text.strip()}")
        self.notes = "\n".join(lines) + "\n"
        return f"noted under {head[3:]}"

    def nudges(self, result):
        """Neutral prompts to learn from what just happened. They say nothing about how the game works."""
        out = []
        m = re.search(r"you were stopped after \d+ of \d+ step\(s\) \w+: ([^\n]*)", result)
        if m:
            reason = re.sub(r"\s*\(.*$", "", m.group(1))  # drop the "(it did not move; ...)" detail
            kind = re.sub(r"\d+", "N", re.sub(r"\b(north|south|east|west)\b", "D", reason)).strip()
            pos = re.search(r"@ Hero[^\n]*? at \((-?\d+),(-?\d+)", result)
            key = (pos.groups() if pos else None, kind)
            if kind not in self.seen_kinds:
                self.seen_kinds.add(kind)
                out.append("(A kind of stop you have not met before. If it taught you something, "
                           "record it with note().)")
            elif key in self.seen_stops:
                out.append("(This exact stop has happened on this tile before.)")
            self.seen_stops.add(key)
        if self.turns - max(self.last_note_turn, self.last_nudge_turn) >= 15:
            self.last_nudge_turn = self.turns
            out.append("(You have not touched your notes for a while. Anything seen or guessed since? "
                       "note() takes one line.)")
        return ("\n" + "\n".join(out)) if out else ""

    def add_floor_rows(self, result):
        """Append the exact floor coordinates to a view (see game_state.floor_rows). It goes inside
        the view block, so it is dropped together with the map when old observations are stubbed."""
        idx = result.rfind("\nStatus:")
        if idx < 0 or "Symbols:" not in result:
            return result
        try:
            from game.game_state import floor_rows
            rows = floor_rows(self.session().game.snapshot())
        except Exception:
            return result
        return result[:idx].rstrip() + ("\n" + rows if rows else "") + "\n" + result[idx:]

    # ---- context ----
    def build_messages(self):
        system = self.system_prompt() + (f"\n\n# Your notes\n{self.notes}" if self.notes else
                                         "\n\n# Your notes\n(empty)")
        return [{"role": "system", "content": system}] + self.messages

    @staticmethod
    def system_prompt():
        with open(os.path.join(HERE, "prompt.md"), encoding="utf-8") as f:
            return f.read()

    def add(self, msg, **extra):
        self.messages.append(msg)
        self.record(msg, **extra)

    def prune(self):
        """Stub all but the newest full views, then cut old turns in one batch."""
        keep = self.lim["full_views_kept"]
        seen = 0
        for m in reversed(self.messages):
            if m["role"] == "tool" and "Symbols:" in m["content"]:
                seen += 1
                if seen > keep:
                    m["content"] = stub_result(m["content"])
        if len(self.messages) > self.lim["history_high"]:
            cut = len(self.messages) - self.lim["history_low"]
            while cut < len(self.messages) and self.messages[cut]["role"] != "assistant":
                cut += 1  # start at an assistant turn so no tool result is orphaned
            self.messages = self.messages[cut:]
            self.record({"role": "event", "content": f"context pruned: dropped {cut} old messages, "
                         f"{len(self.messages)} kept"})

    # ---- loop ----
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_flag.clear()
        self.pause_flag.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()

    def _loop(self):
        self.status = "running"
        try:
            client = make_client(self.cfg)
            if not self.messages:
                self.add({"role": "user", "content": "Begin. Call look() first."})
            while not self.stop_flag.is_set():
                if self.pause_flag.is_set():
                    self.status = "paused"
                    time.sleep(0.3)
                    continue
                self.status = "running"
                if self.turns >= self.lim["max_turns"]:
                    self.status = "stopped: turn limit"
                    break
                if self.usage.cost >= self.lim["max_cost_usd"]:
                    self.status = "stopped: cost limit"
                    break
                self.step(client)
        except Exception as e:
            self.status = f"error: {e}"
        else:
            if self.status in ("running", "paused"):
                self.status = "stopped"
        self.set_phase("idle")
        self.save()

    def set_phase(self, phase):
        self.phase, self.phase_since = phase, time.time()

    def step(self, client):
        self.prune()
        self.set_phase("waiting for the model")
        # The run's own effort (set in the viewer) wins over the config.toml default.
        reasoning = {"effort": self.effort} if self.effort in EFFORTS else self.cfg.get("reasoning")
        resp = client.chat.completions.create(
            model=self.cfg["model"], messages=self.build_messages(), tools=TOOLS,
            temperature=self.cfg.get("temperature", 0.3),
            max_tokens=self.cfg.get("max_output_tokens", 4000),
            extra_body={"usage": {"include": True}, **({"reasoning": reasoning} if reasoning else {})})
        self.usage.add(resp.usage)
        self.turns += 1
        choice = resp.choices[0]
        msg = choice.message
        # Reasoning models think before answering; OpenRouter returns that text in `reasoning`.
        thinking = getattr(msg, "reasoning", None) or (msg.model_extra or {}).get("reasoning") or ""
        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [{"id": c.id, "type": "function", "function": {
                "name": c.function.name, "arguments": c.function.arguments}} for c in msg.tool_calls]
        u = resp.usage
        details = getattr(u, "prompt_tokens_details", None)
        self.add(entry, model=self.cfg["model"], reasoning=thinking, finish=choice.finish_reason, usage={
            "prompt": u.prompt_tokens, "completion": u.completion_tokens,
            "cached": (getattr(details, "cached_tokens", 0) or 0) if details else 0,
            "cost": getattr(u, "cost", None) or (u.model_extra or {}).get("cost") or 0})
        if not msg.tool_calls:
            cut = choice.finish_reason == "length"
            self.add({"role": "user", "content": (
                "Your reply hit the output limit before you acted. Think less this time: "
                "two or three sentences, then call a tool." if cut else "Continue: call a tool.")})
        for c in msg.tool_calls or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except ValueError:
                args = {}
            if c.function.name in ("write_note", "note"):
                self.last_note_turn = self.turns
            self.set_phase(f"running {c.function.name} in the game")
            out = compact_result(self.add_floor_rows(self.call_tool(c.function.name, args)))
            out += self.nudges(out)
            self.add({"role": "tool", "tool_call_id": c.id, "content": out}, name=c.function.name)
        self.last_line = (f"turn {self.turns}: prompt={u.prompt_tokens} "
                          f"out={u.completion_tokens} total_cost=${self.usage.cost:.4f}")
        print(self.last_line, flush=True)
        self.save()
