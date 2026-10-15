# Rulebook
This is your rulebook: your own record of how things in this game work. It starts empty. Keep it in this format, one block per kind of object:

OBJECT lantern
  properties:
    light enough to carry
  rules:
    R1  lit by touching a flame → stays lit until put out   [confirmed ×2]
    R2  carried over water → goes out                       [guess]
  open questions:
    Q1  can two lanterns be carried at once?

(lantern is only an example of the layout; it is not in this game.)
- properties: what the object is, from looking at it.
- rules: one line each, written as "what happens → what results". Number them R1, R2, ... in the order you add them and never reuse a number. After the rule, put its status in brackets: [guess], [confirmed ×N] or [contradicted: see R5].
- open questions: what you do not know yet, numbered Q1, Q2, ... Delete a question when you have answered it with a rule.
- When a rule turns out wrong, mark it [contradicted] and add the corrected rule; do not erase it.

`rulebook_add(text)` adds lines to the end; `rulebook_write(text)` replaces the whole rulebook (use it to add a rule inside an existing block, to tidy, or to merge). The rulebook is shown here at the top of every turn and survives context cuts. Your notes are for everything else (progress, places, people).
