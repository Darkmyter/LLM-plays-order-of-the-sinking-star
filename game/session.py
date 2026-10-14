"""A play session: perform actions one confirmed step at a time and describe what changed."""
import json
import os
import re
import struct
import time

from game import keys
from game.dialogue import bark_text
from game.game_state import (Game, blocks_tile, nkey, render, numbering, label, dialogue_lines, on_grid, in_window,
                        fence_edges, FENCE_STEP, POSITION, OPEN_WORLD_LEVELS, ST_ACTIVE, sunk_rocks)

# Camera-relative WASD -> grid directions (verified in heroes1: D=+x/east, S=-y/south).
MOVES = {"north": "W", "south": "S", "west": "A", "east": "D"}
ACTIONS = {"undo": "Z", "restart": "R", "activate": "X", "take_or_drop": "V",
           "switch_character": "C"}
SHORT = {"n": "north", "s": "south", "e": "east", "w": "west"}
YAW = {"east": 0, "north": 90, "west": 180, "south": 270}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Used when no run folder is given (dev scripts like tools/play.py).
SCRATCH_STATE = os.path.join(ROOT, "runs", "_scratch", "state")

# Timing, measured in the game: a key is answered within ~60 ms; a step takes ~560 ms to
# finish visually, but the next key is accepted once the hero is within 0.1 tile of its target.
RESPONSE_TIMEOUT = 0.6      # no reaction at all within this -> "no response"
LATE_RESPONSE = 1.4         # extra time we keep watching before giving up
NEAR_TARGET = 0.1           # tiles: close enough to send the next key
POLL = 0.004
TRANSITION_WAIT = 5.0       # how long an action may take to start a level change
LOAD_TIMEOUT = 20.0


def transcript(name):
    for key in (name, f"audiolog_{name}"):
        said = bark_text(key) if key else None
        if said:
            return said
    return None


def yaw_name(yaw):
    for n, a in YAW.items():
        if abs((yaw - a + 180) % 360 - 180) < 10:
            return n
    return f"{yaw:.0f}deg"


class Session:
    def __init__(self, state_dir=None, zero_origin=False, disabled=()):
        """state_dir holds what persists for one playthrough: which signs / recordings /
        checkpoints were discovered (discovered.json) and object labels per level (labels.json)
        so 'Rock 3' stays Rock 3 when you come back."""
        state_dir = state_dir or SCRATCH_STATE
        self.discovered_path = os.path.join(state_dir, "discovered.json")
        self.labels_path = os.path.join(state_dir, "labels.json")
        self.game = Game(zero_origin=zero_origin)
        self.disabled = set(disabled)   # actions this player may not use: names, or "select" for select_1..9
        self.hwnd = keys.find_window(self.game.p.pid)
        self.last_level = None
        self._labels_level = None
        self.numbered = {}
        self.discovered = set(self._load(self.discovered_path, []))
        self.labels_by_level = self._load(self.labels_path, {})

    @staticmethod
    def _load(path, default):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return default

    @staticmethod
    def _save(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=0)

    # ---------- observation ----------
    def _labels(self, state):
        """Keep labels (Rock 3, ...) stable within a level and across visits."""
        if state["level"] != self._labels_level:
            self._labels_level = state["level"]
            saved = self.labels_by_level.get(state["level"])
            if saved:
                self.numbered = {(int(k.split(":")[1]), k.split(":")[0]): v for k, v in saved.items()}
            else:
                self.numbered = {}
        changed = False
        for o in sorted(state["objects"], key=lambda o: (nkey(o)[1], o["id"])):
            key = nkey(o)
            if key not in self.numbered:
                self.numbered[key] = 1 + max((v for (_, k), v in self.numbered.items()
                                              if k == key[1]), default=0)
                changed = True
        if changed:
            self.labels_by_level[state["level"]] = {f"{k}:{i}": v for (i, k), v in self.numbered.items()}
            self._save(self.labels_path, self.labels_by_level)
        return self.numbered

    def _arrival_text(self, state):
        """Text for entering a new level/area: name + the dialogue that plays."""
        out = ["", f"== You entered: {'the open world' if state['open_world'] else state['level']} =="]
        # Heroes carry the level's intro dialogue; the open world has no level intro.
        intro = [] if state["open_world"] else dialogue_lines(
            o["barks"].get("initial_bark")
            for o in state["objects"] if o["kind"] == "Guy" and o.get("selected"))
        if intro:
            out += ["Dialogue:"] + intro
        return out

    def discover(self, state):
        """Reveal sign text / recordings / checkpoint stories only once the player reaches them.
        Returns report lines for new discoveries and marks each object's status for the view."""
        lab = self._labels(state)
        hero = next((o for o in state["objects"] if o.get("selected")), None)
        hx, hy, hz = (round(v) for v in hero["pos"]) if hero else (None, None, None)
        lines, added = [], False
        for o in state["objects"]:
            h = o.get("hidden")
            if not h:
                continue
            key = f"{state['level']}:{o['kind']}:{o['id']}"
            new = key not in self.discovered
            name = label(o, lab)
            x, y, z = (round(v) for v in o["pos"])
            if o["kind"] == "Sign":
                near = hero is not None and abs(x - hx) + abs(y - hy) <= 1 and abs(z - hz) <= 1
                if new and near:
                    lines.append(f'You read {name}: "{h["text"] or "(nothing written)"}"')
                    self.discovered.add(key)
                    added = True
                read = key in self.discovered
                o.setdefault("props", {})["status"] = "read" if read else "not read"
            elif o["kind"] == "Voice_Log":
                if new and h["played"]:
                    said = transcript(h["name"])
                    lines.append(f"{name} played a recording" + (":" if said else " (no transcript available)."))
                    lines += [f"    {l}" for l in said or []]
                    self.discovered.add(key)
                    added = True
                o.setdefault("props", {})["status"] = "played" if key in self.discovered else "not played yet"
            elif o["kind"] == "Checkpoint":
                if new and h["triggered"]:
                    lines.append(f"You activated {name}.")
                    said = transcript(h["story"]) if h["story"] else None
                    lines += [f"    {l}" for l in said or []]
                    self.discovered.add(key)
                    added = True
                o.setdefault("props", {})["status"] = "activated" if key in self.discovered else "not activated"
        if added:
            self._save(self.discovered_path, sorted(self.discovered))
        return lines

    def look(self):
        out = []
        if self.close_menu_if_open():
            out.append("(the game menu was open; it was closed)")
        state = self.wait_settled(timeout=1.0)
        if state["level"] != self.last_level:
            self._labels(state)
            out += self._arrival_text(state)
            self.last_level = state["level"]
        found = self.discover(state)
        if found:
            out += ["Discovered:"] + ["  " + l for l in found]
        out.append(render(state, self._labels(state)))
        out.append("")
        out.append(self.status_line(state))
        return "\n".join(out).strip()

    def status_line(self, state):
        hero = next((o for o in state["objects"] if o.get("selected")), None)
        if hero is None:
            return "Status: no hero visible (loading, cutscene or menu?). Use look() again shortly."
        if not all(o["settled"] for o in state["objects"] if on_grid(o)):
            return "Status: things are still moving. Use look() again before acting."
        return "Status: ready for input."

    # ---------- waiting ----------
    def wait_settled(self, timeout=4.0, quiet=0.1):
        """Wait until every object sits at its logical position and the state is stable."""
        last, since, state = None, None, None
        t0 = time.time()
        while time.time() - t0 < timeout:
            state = self.game.snapshot()
            sig = (state["level"], len(state["solid"]),
                   tuple(sorted((o["kind"], o["id"], o["pos"], o.get("facing"), o["dead"])
                                for o in state["objects"])))
            settled = all(o["settled"] for o in state["objects"] if on_grid(o))
            if sig == last and settled:
                if time.time() - since >= quiet:
                    return state
            else:
                last, since = sig, time.time()
            time.sleep(0.02)
        return state or self.game.snapshot()

    def close_menu_if_open(self):
        """The game menu runs as its own 'menu_*' scene. Close it (Esc = back) before acting."""
        lv = self._level()
        if not lv or not lv.startswith("menu_"):
            return False
        keys.press(self.hwnd, "ESC")
        t0 = time.time()
        while time.time() - t0 < 3.0:
            time.sleep(0.1)
            lv = self._level()
            if lv and not lv.startswith("menu_"):
                time.sleep(0.3)
                return True
        return True

    def _level(self):
        try:
            return self.game.level_name(self.game.current_manager())
        except Exception:
            return None

    def wait_for_level_load(self, old_level):
        """After a level change starts: wait until the new level is loaded and the hero can act."""
        t0 = time.time()
        while time.time() - t0 < LOAD_TIMEOUT:
            lv = self._level()
            if lv and lv != old_level:
                break
            time.sleep(0.05)
        time.sleep(0.5)
        while time.time() - t0 < LOAD_TIMEOUT:
            try:
                state = self.wait_settled(timeout=3.0, quiet=0.6)
            except Exception:
                time.sleep(0.3)
                continue
            if any(o.get("selected") for o in state["objects"]):
                return state
            time.sleep(0.3)
        return self.game.snapshot()

    def _hero(self, state):
        return next((o for o in state["objects"] if o.get("selected")), None)

    # ---------- one key, confirmed ----------
    def _press_confirmed(self, key, hero, level):
        """Press one key and watch the hero until the game has clearly answered it.

        Returns (kind, info): kind is one of moved / turned / level / other / none.
        """
        g = self.game
        h0 = g.hero_fast(hero["addr"]) if hero else None
        keys.press(self.hwnd, key)
        t0 = time.perf_counter()
        next_level_check = t0 + 0.15
        while True:
            el = time.perf_counter() - t0
            h = g.hero_fast(hero["addr"]) if hero else None
            if h and h0:
                (p, v, yaw, st), (p0, v0, yaw0, st0) = h, h0
                if any(abs(a - b) > 0.01 for a, b in zip(p, p0)):
                    # Moved: wait until it is close enough to its new tile for the next key.
                    while time.perf_counter() - t0 < 3.0:
                        p, v, yaw, st = g.hero_fast(hero["addr"])
                        if all(abs(a - b) < NEAR_TARGET for a, b in zip(p, v)):
                            break
                        time.sleep(POLL)
                    return "moved", (p0, p, yaw)
                if not st & ST_ACTIVE:
                    return "other", None          # another hero got selected
            if time.perf_counter() >= next_level_check:   # level change check, ~10x per second
                next_level_check = time.perf_counter() + 0.1
                if self._level() != level:
                    return "level", None
            if h and h0 and abs((h[2] - h0[2] + 180) % 360 - 180) > 5:
                # Turning without moving (yet): wait for the turn to finish, then see if it walks.
                last, stable_since = h[2], time.perf_counter()
                while time.perf_counter() - t0 < 2.0:
                    p, v, yaw, st = g.hero_fast(hero["addr"])
                    if any(abs(a - b) > 0.01 for a, b in zip(p, h0[0])):
                        break
                    if abs(yaw - last) > 0.5:
                        last, stable_since = yaw, time.perf_counter()
                    elif time.perf_counter() - stable_since > 0.12:
                        return "turned", yaw
                    time.sleep(POLL)
                continue
            if el > RESPONSE_TIMEOUT:
                return "none", None
            time.sleep(POLL)

    # ---------- actions ----------
    @staticmethod
    def _key(action):
        key = MOVES.get(action) or ACTIONS.get(action)
        if key is None and action.startswith("select_") and action[7:].isdigit():
            key = action[7:]
        return key

    def _step(self, action, times, before=None):
        """Perform one action (maybe repeated). Returns (report lines, state after, outcome).

        outcome: "ok", "level" (level changed), or "unexpected" (did not do what was asked)."""
        if self.close_menu_if_open():
            before = None
        before = before or self.wait_settled(timeout=2.0)
        self._labels(before)
        level = before["level"]
        key = self._key(action)
        out = [f"> {action}" + (f" x{times}" if times > 1 else "")]
        hero = self._hero(before)
        notes, outcome, done, res = [], "ok", 0, None

        if action in MOVES:
            dx, dy = FENCE_STEP[action]
            for i in range(times):
                if hero is None:
                    notes.append("no hero to move")
                    outcome = "unexpected"
                    break
                res, info = self._press_confirmed(key, hero, level)
                if res == "moved":
                    p0, p, _ = info
                    mx, my = round(p[0] - p0[0]), round(p[1] - p0[1])
                    if (mx, my) == (dx, dy):
                        done += 1
                        if round(p[2] - p0[2]):
                            notes.append(f"you changed height by {round(p[2] - p0[2]):+d}")
                        continue
                    notes.append(f"unexpected: the key moved you by ({mx:+d},{my:+d}) instead of one tile {action}")
                    outcome = "unexpected"
                    break
                if res == "turned":
                    notes.append(f"turned to face {yaw_name(info)} (did not move)")
                    outcome = "unexpected"
                    break
                if res == "level":
                    outcome = "level"
                    break
                if res == "none":
                    # Blocked while already facing that way, or the game is busy.
                    outcome = "unexpected"
                    break
                outcome = "unexpected"
                break
        else:
            for _ in range(times):
                res, _ = self._press_confirmed(key, hero, level)
                if res == "level":
                    outcome = "level"
                    break
                if res == "none":
                    # Undo/restart/actions may change things other than the hero; give them a moment.
                    time.sleep(0.1)
                done += 1

        # Some actions start a level change a moment later (entering a level, stepping on an exit).
        after = None
        if outcome != "level":
            after = self.wait_settled(timeout=2.0)
            hero_after = self._hero(after)
            may_transition = (
                hero_after is None or hero_after.get("on_exit")
                or (action in ("take_or_drop", "activate")
                    and self.describe_changes(before, after) == ["nothing changed"]))
            if may_transition:
                t0 = time.time()
                while time.time() - t0 < TRANSITION_WAIT:
                    if self._level() != level:
                        outcome = "level"
                        break
                    time.sleep(0.05)

        if outcome == "level":
            after = self.wait_for_level_load(level)
            self.last_level = after["level"]
            self._labels(after)
            out += [f"  you left {self._level_title(level)}" + self._solved_note(level, after)]
            out += self._arrival_text(after)
            out += ["  " + l for l in self.discover(after)]
            out.append("  the new level is loaded; ready for input")
            return out, after, "level"

        if after is None:
            after = self.wait_settled(timeout=2.0)
        changes = self.describe_changes(before, after)
        if action in ACTIONS or action.startswith("select_"):
            if changes == ["nothing changed"]:
                changes = ["nothing changed (no visible effect)"]
        out += ["  " + l for l in changes]
        out += ["  " + l for l in self.discover(after)]
        out += ["  " + n for n in notes]
        if action == "activate" and changes[0].startswith("nothing changed"):
            out += ["  " + l for l in self.activate_hint(after)]
        if action in MOVES and done < times:
            why = self.blocked_reason(after, action, self._labels(after))
            if res == "none" and not why:
                why = ("the game did not respond to the key (it may be busy with dialogue or "
                       "a transition; use look() and try again)")
            out.append(f"  you were stopped after {done} of {times} step(s) {action}: "
                       + (why or "nothing visible on the map explains it"))
        return out, after, outcome

    def activate_hint(self, state):
        """Why activate did nothing, when a fence separates you from a neighbouring voice log."""
        hero = self._hero(state)
        if hero is None:
            return []
        hx, hy = round(hero["pos"][0]), round(hero["pos"][1])
        lab, out = self._labels(state), []
        for o in state["objects"]:
            if o["kind"] != "Voice_Log" or not on_grid(o):
                continue
            ox, oy = round(o["pos"][0]), round(o["pos"][1])
            d = next((n for n, (dx, dy) in FENCE_STEP.items() if (hx + dx, hy + dy) == (ox, oy)), None)
            if d and (why := self.blocked_reason(state, d, lab)) and why.startswith("a fence"):
                out.append(f"nothing happened: you must stand ON {label(o, lab)} to activate it; "
                           f"it is next to you, but a fence on the {d} edge of your tile is in the way, "
                           "so find a route onto its tile.")
            elif d:
                out.append(f"nothing happened: you must stand ON {label(o, lab)} to activate it, "
                           "not next to it. Step onto its tile first.")
        return out

    def _level_title(self, level):
        return "the open world" if level in OPEN_WORLD_LEVELS else f"level {level}"

    def _solved_note(self, old_level, state):
        """When you come back to the open world from a puzzle level, say whether it is now solved."""
        if old_level in OPEN_WORLD_LEVELS or not state["open_world"]:
            return ""
        g = self.game
        try:
            mgr = g.current_manager()
            b = g.buckets(mgr, state["level"])
            F = g.types.fields("Level_Entry")
            for a in g.entities_of(mgr, b.get("Level_Entry", 0)) if "Level_Entry" in b else []:
                buf = g.p.read(a, g.types.size("Level_Entry"))
                if g.decode_field(buf, *F["level_name"]) == old_level:
                    solved = (g.decode_field(buf, *F["solved_t_target"]) or 0) > 0.5
                    return " - LEVEL SOLVED" if solved else " (not solved)"
        except Exception:
            pass
        return ""

    def do(self, action, times=1):
        if self._key(action) is None:
            return f"unknown action {action!r}"
        out, after, _ = self._step(action, times)
        out += ["", render(after, self._labels(after)), "", self.status_line(after)]
        return "\n".join(out)

    @staticmethod
    def blocked_reason(state, direction, numbered=None):
        """If the selected hero cannot step `direction`, say what is in the way (as seen on screen)."""
        hero = next((o for o in state["objects"] if o.get("selected")), None)
        if not hero:
            return None
        x, y, z = (round(v) for v in hero["pos"])
        dx, dy = FENCE_STEP[direction]
        tx, ty = x + dx, y + dy
        fences = [o for o in state["objects"] if o["kind"] == "Fence" and on_grid(o)]
        horiz, vert, _ = fence_edges(fences, z)
        if (dy and (x, min(y, ty)) in horiz) or (dx and (min(x, tx), y) in vert):
            return f"a fence on the {direction} edge of your tile"
        lab = numbered or numbering(state["objects"])
        in_water = sunk_rocks(state, z)
        water = state.get("water", set())
        floor_tiles = {(round(o["pos"][0]), round(o["pos"][1])) for o in in_water}
        there = [o for o in state["objects"] if o["kind"] != "Fence" and not o.get("selected") and on_grid(o)
                 and blocks_tile(o) and o not in in_water
                 and (round(o["pos"][0]), round(o["pos"][1])) == (tx, ty) and abs(round(o["pos"][2]) - z) <= 1]
        if there:
            names = " and ".join(label(o, lab) for o in there)
            why = f"{names} at ({tx},{ty}) is in the way"
            if len(there) == 1:
                # Say what is behind it (visible), never why it is heavy or stuck.
                bx, by = tx + dx, ty + dy
                behind = [label(o, lab) for o in state["objects"] if o["kind"] != "Fence" and on_grid(o)
                          and (round(o["pos"][0]), round(o["pos"][1])) == (bx, by)
                          and abs(round(o["pos"][2]) - z) <= 1]
                col = [zz for (cx, cy, zz) in state["solid"] if (cx, cy) == (bx, by)]
                if (dy and (tx, min(ty, by)) in horiz) or (dx and (min(tx, bx), ty) in vert):
                    behind.append("a fence")
                elif any(zz >= z for zz in col):
                    behind.append("a wall")
                elif not any(z - 3 <= zz < z for zz in col) and (bx, by) not in floor_tiles:
                    behind.append("water" if (bx, by) in water else "no floor")
                why += " (it did not move; behind it at " + f"({bx},{by}): " + (
                    " and ".join(behind) if behind else "open floor") + ")"
            return why
        column = [zz for (cx, cy, zz) in state["solid"] if (cx, cy) == (tx, ty)]
        if any(zz >= z for zz in column):
            return f"a wall at ({tx},{ty})"
        if not any(z - 3 <= zz < z for zz in column) and (tx, ty) not in floor_tiles:
            return f"{'water' if (tx, ty) in water else 'no floor'} at ({tx},{ty})"
        return None

    @staticmethod
    def parse_sequence(text):
        """'north 3, e2, activate, undo' -> [('north', 3), ('east', 2), ('activate', 1), ('undo', 1)]"""
        steps = []
        for tok in re.split(r"[,;\n]+", text.strip().lower()):
            tok = tok.strip()
            if not tok:
                continue
            m = re.fullmatch(r"(select_\d|[a-z_]+?)\s*(?:x\s*)?(\d*)", tok)
            if not m:
                raise ValueError(f"can't read {tok!r}")
            name, n = SHORT.get(m[1], m[1]), int(m[2] or 1)
            if Session._key(name) is None:
                raise ValueError(f"unknown action {m[1]!r}")
            steps.append((name, max(1, min(n, 20))))
        if not steps:
            raise ValueError("empty sequence")
        return steps

    def do_sequence(self, text, stop_on_surprise=True):
        """Run several actions in order and report each. Stops when the level changes and, by
        default, as soon as a step does not do exactly what was asked."""
        try:
            steps = self.parse_sequence(text)
        except ValueError as e:
            return f"error: {e}"
        for name, _ in steps:
            if name in self.disabled or (name.startswith("select_") and "select" in self.disabled):
                return f"error: '{name}' is not available here"
        out, after = [], None
        for i, (name, n) in enumerate(steps):
            lines, after, outcome = self._step(name, n, before=after)
            out += lines
            left = len(steps) - 1 - i
            if outcome == "level" and left:
                out.append(f"(stopped: the level changed; skipped {left} remaining step(s))")
                break
            if outcome == "unexpected" and stop_on_surprise and left:
                out.append(f"(stopped: that step did not go as asked; skipped {left} remaining step(s): "
                           + ", ".join(f"{a}" + (f" {k}" if k > 1 else "") for a, k in steps[i + 1:]) + ")")
                break
        out += ["", render(after, self._labels(after)), "", self.status_line(after)]
        return "\n".join(out)

    def describe_changes(self, before, after):
        lab = self._labels(after)
        b = {(o["kind"], o["id"]): o for o in before["objects"]}
        a = {(o["kind"], o["id"]): o for o in after["objects"]}
        p = lambda o: tuple(round(v) for v in o["pos"])
        wb, wa = before["window"], after["window"]
        # Only things inside both views can be seen to change; the rest just scrolled.
        # Things at other heights are not on the map or in the object list, so their changes are not shown either.
        levels = {before.get("layer", 0), after.get("layer", 0)}

        def shown(pos, kind=None):
            """Terrain tiles come as (x, y); objects as (x, y, z). A rock one level down is floor, so it counts."""
            return len(pos) < 3 or round(pos[2]) in levels or (kind == "Rock" and round(pos[2]) + 1 in levels)

        both = lambda pos, kind=None: ((wb is None or in_window(pos, wb))
                                       and (wa is None or in_window(pos, wa)) and shown(pos, kind))
        out = []
        if wb != wa and wa is not None:
            out.append(f"the view moved: now showing x={wa[0]}..{wa[2]}, y={wa[1]}..{wa[3]}")
        for k in a.keys() - b.keys():
            if both(a[k]["pos"], a[k]["kind"]) and a[k]["kind"] != "Fence":
                out.append(f"{label(a[k], lab)} appeared at {p(a[k])}")
        for k in b.keys() - a.keys():
            o = b[k]
            if not both(o["pos"], o["kind"]) or o["kind"] == "Fence":
                continue
            if o["kind"] == "Freezer":
                held = [label(b[kk], lab) for kk in o.get("holding", []) if kk in b]
                out.append(f"{label(o, lab)} at {p(o)} THAWED and melted away"
                           + (f": {' and '.join(held)} is free" if held else ""))
            elif o["kind"] == "Area_Pin":
                out.append(f"you picked up {label(o, lab)} at {p(o)}"
                           + (f": the area '{o['area']}' is now on your world map" if o.get("area") else ""))
            elif o["kind"] == "View_Giver":
                out.append(f"you picked up {label(o, lab)} at {p(o)}: you can now open the world map "
                           "(world_map() shows it, like the Tab key in the game)")
            else:
                out.append(f"{label(o, lab)} disappeared from {p(o)}")
        for k in a.keys() & b.keys():
            o, n = b[k], a[k]
            if not (shown(o["pos"], o["kind"]) or shown(n["pos"], n["kind"])):
                continue                       # something at another height: not on the map, so not reported
            name = label(n, lab)
            if p(o) != p(n):
                out.append(f"{name} moved {p(o)} -> {p(n)}")
            if o.get("facing") != n.get("facing"):
                out.append(f"{name} turned {o.get('facing')} -> {n.get('facing')}")
            if o.get("selected") != n.get("selected"):
                out.append(f"{name} is {'now' if n.get('selected') else 'no longer'} selected")
            for flag in ("dead", "falling"):
                if o.get(flag) != n.get(flag):
                    out.append(f"{name} {'is ' + flag if n.get(flag) else 'no longer ' + flag}")
            op, np_ = o.get("props", {}), n.get("props", {})
            for f in sorted(op.keys() | np_.keys()):
                if f == "status":   # discovery status; reported by discover() instead
                    continue
                if op.get(f) == np_.get(f):
                    continue
                if n["kind"] == "Freezer" and f == "state":
                    held = [label(b2, lab) for kk in o.get("holding", []) if (b2 := b.get(kk))]
                    if np_.get(f) == "thawed":
                        out.append(f"{name} THAWED" + (f": {' and '.join(held)} is free" if held else ""))
                    else:
                        out.append(f"{name} froze" + (f" around {' and '.join(held)}" if held else ""))
                    continue
                out.append(f"{name}: {f} {op.get(f)} -> {np_.get(f)}")
        added = sorted({(x, y) for x, y, _ in after["solid"] - before["solid"] if both((x, y))})
        removed = sorted({(x, y) for x, y, _ in before["solid"] - after["solid"] if both((x, y))})
        if added:
            out.append(f"terrain appeared at {added}")
        if removed:
            out.append(f"terrain disappeared at {removed}")
        return out or ["nothing changed"]
