"""One OpenAI-compatible client for OpenRouter, llama.cpp's llama-server and Ollama."""
import os
import tomllib

from openai import OpenAI

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """Read KEY=VALUE lines from the repo's .env into the environment (existing variables win)."""
    try:
        with open(os.path.join(os.path.dirname(HERE), ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip().removeprefix("export "), v.strip().strip("\"'"))
    except FileNotFoundError:
        pass


def load_config(path=None):
    load_env()
    with open(path or os.path.join(HERE, "config.toml"), "rb") as f:
        return tomllib.load(f)


def make_client(cfg):
    key = os.environ.get(cfg.get("api_key_env", "OPENROUTER_API_KEY"), "")
    if not key and not cfg["base_url"].startswith("http://localhost"):
        raise RuntimeError(f"set {cfg.get('api_key_env', 'OPENROUTER_API_KEY')} in the environment")
    return OpenAI(base_url=cfg["base_url"], api_key=key or "none")


class Usage:
    """Running token / cost totals, read from each response's usage block."""

    def __init__(self):
        self.prompt = self.cached = self.completion = 0
        self.cost = 0.0
        self.calls = 0

    def add(self, u):
        if u is None:
            return
        self.calls += 1
        self.prompt += u.prompt_tokens or 0
        self.completion += u.completion_tokens or 0
        details = getattr(u, "prompt_tokens_details", None)
        self.cached += (getattr(details, "cached_tokens", 0) or 0) if details else 0
        self.cost += (getattr(u, "cost", None) or (u.model_extra or {}).get("cost") or 0)

    def line(self):
        return (f"calls={self.calls} prompt={self.prompt} (cached {self.cached}) "
                f"completion={self.completion} cost=${self.cost:.4f}")
