"""User-defined tag presets stored as JSON at ~/.promptgen/presets.json.

Each preset = name -> comma-separated tag string. Injected into generated
prompts as extra tags (deduped against existing).
"""
import json
from pathlib import Path

from .paths import APP_DIR, ensure_app_dir

PRESETS_PATH: Path = APP_DIR / "presets.json"


def _load() -> dict[str, str]:
    ensure_app_dir()
    if not PRESETS_PATH.exists():
        return {}
    try:
        data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _save(d: dict[str, str]) -> None:
    ensure_app_dir()
    PRESETS_PATH.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def list_names() -> list[str]:
    return sorted(_load().keys())


def get(name: str) -> str:
    return _load().get(name, "")


def save(name: str, tags: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("preset name is empty")
    d = _load()
    d[name] = tags.strip()
    _save(d)


def delete(name: str) -> bool:
    d = _load()
    if name not in d:
        return False
    del d[name]
    _save(d)
    return True


def parse_tags(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]
