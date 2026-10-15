"""Does a row-by-row floor list help a model find the opening in a wall? (read-only, no keys)"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api_player.llm import load_config, make_client
from api_player.compact import compact_result
from game.session import Session
from game.game_state import floor_rows, render

s = Session(tempfile.mkdtemp())
st = s.game.snapshot()
zh = st.get("layer", 0)
floor_list = floor_rows(st)
raw = compact_result(render(st, s._labels(st)))
hero = next(o for o in st["objects"] if o.get("selected"))
print("hero", hero["pos"], "window", st["window"])
print(floor_list[:600])

cfg = load_config(); client = make_client(cfg)
system = open("templates/prompts/game/default.md", encoding="utf-8").read()
q = ("Situation: you are at (42,-3). You came from the south along x=45. Moving north from x=47, 46, 44 and 42 "
     "was blocked by raised terrain at y=-1. Which x column is the opening through the wall at y=-1 "
     "(the row below the chamber)? Answer with just the x number and one sentence.")
for label, obs in (("MAP ONLY", raw), ("MAP + FLOOR LIST", raw + "\n\n" + floor_list)):
    answers = []
    for _ in range(3):
        r = client.chat.completions.create(model=cfg["model"], max_tokens=3000, temperature=0.3,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": obs + "\n\n" + q}],
            extra_body={"reasoning": {"effort": "low"}})
        answers.append((r.choices[0].message.content or "").strip().replace("\n", " ")[:140])
    print("\n==", label); [print("  -", a) for a in answers]
