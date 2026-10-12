"""Token savers for game observations.

The game's text view is written for a human or coding agent: spacer rows, a legend that never
changes, and a full map after every action. This module shrinks it.
"""
import re

# Lines of the view that are identical every time; the system prompt explains them once.
STATIC_PREFIXES = ("Map (top-down;", "Fences are thin walls ON TILE EDGES")


def split_view(text):
    """Split a tool result into (before, view, after). The view runs from its title line
    ('intro, view around you (21x11)') to the line before 'Status:'. Without a view,
    returns (text, "", "")."""
    sym = text.find("\nSymbols:")
    if sym < 0:
        return text, "", ""
    start = text.rfind("\n", 0, sym)
    start = 0 if start < 0 else start + 1
    end = text.find("\nStatus:", sym)
    end = len(text) if end < 0 else end
    return text[:start].rstrip(), text[start:end].strip(), text[end:].strip()


def compact_view(view):
    """Drop static legend lines and rows that are empty apart from whitespace."""
    out = []
    for line in view.splitlines():
        if line.startswith(STATIC_PREFIXES) or not line.strip():
            continue
        out.append(line.rstrip())
    # Drop leading-space padding common to all lines of the map so columns stay aligned.
    return "\n".join(out)


def compact_result(text):
    before, view, after = split_view(text)
    parts = [before] if before else []
    if view:
        parts.append(compact_view(view))
    if after:
        parts.append(after)
    return "\n".join(parts)


def stub_result(text):
    """Old observation: keep what changed, drop the map and object list."""
    before, view, after = split_view(text)
    if not view:
        return text
    title = view.splitlines()[0]
    status = after.splitlines()[0] if after else ""
    parts = [before] if before else []
    parts.append(f"[{title}; map dropped] {status}".strip())
    return "\n".join(parts)


def tokens_estimate(text):
    return len(re.findall(r"\w+|[^\w\s]", text))
