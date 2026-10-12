"""The API player's notes: separate pages by topic (progress, mechanics, characters, levels/<name>, ...).

Each page is a markdown file in <run folder>/notes/ (a slash in a name makes a folder), the same layout the
coding player uses. All pages are shown to the model at the top of every turn. The player decides which
pages exist; the prompt only suggests some.
"""
import os
import re

# Shown first, in this order; everything else follows alphabetically.
ORDER = ("progress", "mechanics", "characters", "world")


def clean_name(name):
    """'Levels/Mirror 1' -> 'levels/mirror-1'; '' if nothing usable is left."""
    parts = [re.sub(r"[^a-z0-9_-]+", "-", p.strip().lower()).strip("-") for p in str(name or "").split("/")]
    parts = [p for p in parts if p]
    return "/".join(parts)[:60]


class Notes:
    def __init__(self, folder):
        self.folder = folder
        self.pages = {}

    def load(self, legacy_file=None):
        """Read the pages from disk. A run from before notes had pages keeps its single notes.md as page 'notes'."""
        self.pages = {}
        for root, _, files in os.walk(self.folder):
            for f in files:
                if f.endswith(".md"):
                    path = os.path.join(root, f)
                    rel = os.path.relpath(path, self.folder).replace(os.sep, "/")[:-3]
                    with open(path, encoding="utf-8") as fh:
                        self.pages[rel] = fh.read()
        if not self.pages and legacy_file and os.path.isfile(legacy_file):
            with open(legacy_file, encoding="utf-8") as fh:
                self.pages["notes"] = fh.read()

    def save(self):
        keep = set()
        for name, text in self.pages.items():
            path = os.path.join(self.folder, *name.split("/")) + ".md"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            keep.add(os.path.abspath(path))
        for root, _, files in os.walk(self.folder):          # pages the player deleted
            for f in files:
                path = os.path.abspath(os.path.join(root, f))
                if f.endswith(".md") and path not in keep:
                    os.remove(path)

    def append(self, name, text, turn):
        name = clean_name(name)
        if not name or not str(text).strip():
            return "note needs a page name (e.g. progress, mechanics, characters) and some text"
        page = self.pages.get(name, "")
        self.pages[name] = page.rstrip() + ("\n" if page.strip() else "") + f"- (turn {turn}) {str(text).strip()}\n"
        return f"added to '{name}'"

    def write(self, name, text):
        name = clean_name(name)
        if not name:
            return "write_note needs a page name (e.g. progress, mechanics, characters) and the new text"
        if not str(text).strip():
            return f"deleted '{name}'" if self.pages.pop(name, None) is not None else f"'{name}' did not exist"
        self.pages[name] = str(text).rstrip() + "\n"
        return f"'{name}' saved ({len(self.pages[name])} chars)"

    def names(self):
        rank = {n: i for i, n in enumerate(ORDER)}
        return sorted(self.pages, key=lambda n: (rank.get(n, len(ORDER)), n))

    def render(self):
        """The text shown to the model."""
        if not self.pages:
            return "(empty)"
        return "\n\n".join(f"=== {n} ===\n{self.pages[n].strip()}" for n in self.names())
