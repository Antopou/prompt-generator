from pathlib import Path

APP_DIR = Path.home() / ".promptgen"
CACHE_DIR = APP_DIR / "cache"
CONFIG_PATH = APP_DIR / "config.toml"
TOKEN_PATH = APP_DIR / "token.json"
CLIENT_SECRETS_PATH = APP_DIR / "client_secrets.json"


def lora_cache_dir(lora: str) -> Path:
    d = CACHE_DIR / lora
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
