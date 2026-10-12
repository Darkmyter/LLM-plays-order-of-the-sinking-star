"""Look up bark/dialogue keys (e.g. Guy.initial_bark) in the game's English subtitles."""
import functools
import re

KEY_LINE = re.compile(r"^:{1,3}\s+(\S+)")

SUBTITLES = r"D:\Games\Order of the Sinking Star\data\strings\subtitles\en.subtitles"


@functools.lru_cache(maxsize=1)
def _load():
    barks, key, lines, speaker, text = {}, None, [], None, []

    def flush_line():
        if speaker and speaker != "_" and text:
            lines.append(f"{speaker}: {' '.join(text)}")

    with open(SUBTITLES, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            m = KEY_LINE.match(line)
            if m:
                flush_line()
                if key:
                    barks[key] = lines
                key, lines, speaker, text = m.group(1), [], None, []
            elif line.startswith("= "):
                flush_line()
                speaker, text = line[2:].split()[0], []
            elif line.startswith("+"):      # "++" director notes, "+ " cues
                continue
            elif line.strip():
                text.append(line.strip())
        flush_line()
        if key:
            barks[key] = lines
    return barks


LOCALIZATION = r"D:\Games\Order of the Sinking Star\data\strings\en.localization"


@functools.lru_cache(maxsize=1)
def _load_localization():
    """en.localization: '`key' line followed by the text, entries separated by blank lines."""
    out, key, text = {}, None, []
    with open(LOCALIZATION, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("`"):
                if key:
                    out[key] = "\n".join(text).strip()
                key, text = line[1:].strip(), []
            elif key is not None and not line.startswith("#"):
                text.append(line)
    if key:
        out[key] = "\n".join(text).strip()
    return out


def localized(key):
    return _load_localization().get(key)


def bark_text(key):
    """Return the dialogue lines for a bark key, or None if unknown."""
    return _load().get(key)


# Key-binding placeholders in sign text, written as the tool action that does the same thing.
_PLACEHOLDERS = {"undo": "undo", "reset": "restart", "north": "north", "south": "south",
                 "east": "east", "west": "west", "north_alt": "north", "south_alt": "south",
                 "east_alt": "east", "west_alt": "west"}


def sign_text(keys):
    """Readable text of a sign from its line keys (localization keys or literal text)."""
    parts = []
    for k in keys:
        if not k:
            continue
        t = localized(k)
        parts.append(t if t is not None else k)
    text = " / ".join(" ".join(p.split()) for p in parts if p.strip())
    return re.sub(r"\$([a-z_]+)", lambda m: f"[{_PLACEHOLDERS.get(m[1], m[1])}]", text)
