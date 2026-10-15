"""What the model's system message is made of, assembled the same way for a live run and for the viewer.

    general prompt        templates/prompts/<scope>/<name>.md ({actions} filled in; {view_help} and {results_help}
                          with the `help` of the view and actions templates: how to read what the player gets)
    rulebook section      templates/rules/<name>/ : the prompt for the chosen mode, then the rulebook itself
    notes                 the player's own pages
    action log            when the actions template asks for it
    journal               every sign and recording read, kept by the harness (read-only)

The rulebook modes: "empty" (the player writes it, with rulebook_add / rulebook_write) and "prefilled" (given,
read-only; level play only).
"""
from game import templates

JOURNAL_HEAD = "# Journal (read-only: the game keeps every sign and recording you have read or heard)\n"


def rulebook_section(rules_name, mode, rulebook):
    """The rulebook section: the template's prompt for this mode, then the rulebook (or '(empty)')."""
    prompt = templates.read_rules(rules_name)[mode].rstrip()
    return f"{prompt}\n\n{rulebook.strip() or '(empty)'}"


def system_text(scope, tpl, actions, rulebook, notes, journal="", log_text=""):
    """tpl: the run's template names {prompt, rules, rulebook, view, actions}."""
    from api_player.presentation import Presentation
    pres = Presentation.load(tpl["view"], tpl["actions"])
    general = templates.read_text(templates.prompt_kind(scope), tpl["prompt"]).replace("{actions}", actions)
    for slot, text in (("{view_help}", pres.help), ("{results_help}", pres.results_help)):
        # A template without help text leaves no empty line behind.
        general = general.replace(slot + "\n", text + "\n" if text else "").replace(slot, text)
    parts = [general,
             rulebook_section(tpl["rules"], tpl["rulebook"], rulebook),
             "# Your notes\n" + notes]
    if log_text:
        parts.append(log_text)
    if journal:
        parts.append(JOURNAL_HEAD + journal)
    return "\n\n".join(parts)


def resolve_templates(cfg, scope, saved=None):
    """The template names for a run: config.toml [templates] defaults, then what the run saved. Runs made before the
    templates were split (prompt 'game'/'level', rules 'default') map onto the current names."""
    t = cfg.get("templates", {})
    out = {"prompt": t.get("prompt_level" if scope == "level" else "prompt_game", "default"),
           "rules": t.get("rules", "free"), "view": t.get("view", "default"), "actions": t.get("actions", "default"),
           "rulebook": t.get("rulebook_level", "prefilled") if scope == "level" else "empty"}
    saved = dict(saved or {})
    if "presentation" in saved:   # one template before the world view and the action results were split
        old = saved.pop("presentation")
        if old in ("changes_only", "with_log", "changes_only_log"):
            saved.setdefault("actions", old)
        else:
            saved.setdefault("view", old)
    out.update(saved)
    if out["prompt"] in ("game", "level"):     # the names before the prompts were split into folders per scope
        out["prompt"] = "default"
    if out["rules"] == "default":              # the name before rulebook formats existed
        out["rules"] = "free"
    if scope != "level":
        out["rulebook"] = "empty"      # a given rulebook is for level play: the game is too big to list in advance
    return out


def for_saved_run(cfg, scope, saved):
    """The template names of a run read back from its meta.json. A run from before rulebook modes had no `rulebook`
    key: its level rules were given and read-only, and a whole-game run had no rulebook at all (empty)."""
    tpl = resolve_templates(cfg, scope, saved)
    if "rulebook" not in (saved or {}):
        tpl["rulebook"] = "prefilled" if scope == "level" else "empty"
    return tpl


def problems(tpl, scope):
    """What is wrong with a choice of templates, as a message, or "" when all of it exists."""
    for kind, key in ((templates.prompt_kind(scope), "prompt"), ("rules", "rules"), ("view", "view"), ("actions", "actions")):
        if not templates.exists(kind, tpl[key]):
            return f"no {key} template named {tpl[key]!r} ({kind})"
    if tpl["rulebook"] not in templates.RULEBOOK_MODES:
        return f"rulebook mode must be one of {templates.RULEBOOK_MODES}"
    return ""
