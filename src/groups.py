"""User-defined tag-group library stored at ~/.promptgen/groups.json.

Data shape:
{
  "categories": [
    {"name": "outfit", "overrides": "outfit",
     "groups": {"school": "white shirt, pleated skirt", ...}},
    {"name": "extras", "overrides": None, "groups": {...}},
    ...
  ]
}

`overrides` is one of: None, "outfit", "pose", "expression", "framing",
"background". When set, selected groups' tags replace the auto-pick for
that bucket during generation.
"""
import json
from pathlib import Path

from .paths import APP_DIR, ensure_app_dir

GROUPS_PATH: Path = APP_DIR / "groups.json"

VALID_BUCKETS = {"outfit", "pose", "expression", "framing", "background"}

BUILTIN_CATEGORIES: tuple[str, ...] = (
    "none", "outfit", "pose", "expression", "framing", "background",
)

_DEPRECATED_EMPTY: set[str] = {"extras", "general"}


def infer_overrides(name: str) -> str | None:
    """Category named after a bucket overrides that bucket; else None."""
    return name if name in VALID_BUCKETS else None


def ensure_builtins() -> None:
    """Preseed built-in categories; strip empty deprecated ones."""
    data = load()
    changed = False
    before = len(data["categories"])
    data["categories"] = [
        c for c in data["categories"]
        if not (c["name"] in _DEPRECATED_EMPTY and not (c.get("groups") or {}))
    ]
    if len(data["categories"]) != before:
        changed = True
    have = {c["name"] for c in data["categories"]}
    for name in BUILTIN_CATEGORIES:
        if name in have:
            continue
        data["categories"].append({
            "name": name,
            "overrides": infer_overrides(name),
            "groups": {},
        })
        changed = True
    if changed:
        save(data)


def rename_category(old: str, new: str) -> None:
    new = new.strip()
    if not new:
        raise ValueError("new name empty")
    if old == new:
        return
    data = load()
    if any(c["name"] == new for c in data["categories"]):
        raise ValueError(f"'{new}' already exists")
    for c in data["categories"]:
        if c["name"] == old:
            c["name"] = new
            c["overrides"] = infer_overrides(new)
            save(data)
            return
    raise KeyError(f"category '{old}' not found")


def rename_group(cat_name: str, old: str, new: str) -> None:
    new = new.strip()
    if not new:
        raise ValueError("new name empty")
    if old == new:
        return
    data = load()
    for c in data["categories"]:
        if c["name"] == cat_name:
            grps = c.setdefault("groups", {})
            if old not in grps:
                raise KeyError(f"group '{old}' not found")
            if new in grps:
                raise ValueError(f"'{new}' already exists in '{cat_name}'")
            grps[new] = grps.pop(old)
            save(data)
            return
    raise KeyError(f"category '{cat_name}' not found")


def load() -> dict:
    ensure_app_dir()
    if not GROUPS_PATH.exists():
        return {"categories": []}
    try:
        data = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"categories": []}
    if not isinstance(data, dict) or not isinstance(data.get("categories"), list):
        return {"categories": []}
    return data


def save(data: dict) -> None:
    ensure_app_dir()
    GROUPS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_categories() -> list[dict]:
    return load()["categories"]


def category_names() -> list[str]:
    return [c["name"] for c in list_categories()]


def get_category(name: str) -> dict | None:
    for c in list_categories():
        if c["name"] == name:
            return c
    return None


def upsert_category(name: str, overrides: str | None) -> None:
    name = name.strip()
    if not name:
        raise ValueError("category name empty")
    if overrides is not None and overrides not in VALID_BUCKETS:
        raise ValueError(f"invalid overrides '{overrides}'; must be one of {sorted(VALID_BUCKETS)} or None")
    data = load()
    for c in data["categories"]:
        if c["name"] == name:
            c["overrides"] = overrides
            save(data)
            return
    data["categories"].append({"name": name, "overrides": overrides, "groups": {}})
    save(data)


def delete_category(name: str) -> bool:
    data = load()
    before = len(data["categories"])
    data["categories"] = [c for c in data["categories"] if c["name"] != name]
    if len(data["categories"]) == before:
        return False
    save(data)
    return True


def list_groups(cat_name: str) -> list[str]:
    c = get_category(cat_name)
    return sorted((c or {}).get("groups", {}).keys())


def get_group(cat_name: str, group_name: str) -> str:
    c = get_category(cat_name)
    if not c:
        return ""
    return c.get("groups", {}).get(group_name, "")


def upsert_group(cat_name: str, group_name: str, tags: str) -> None:
    group_name = group_name.strip()
    if not group_name:
        raise ValueError("group name empty")
    data = load()
    for c in data["categories"]:
        if c["name"] == cat_name:
            c.setdefault("groups", {})[group_name] = (tags or "").strip()
            save(data)
            return
    raise KeyError(f"category '{cat_name}' does not exist")


def delete_group(cat_name: str, group_name: str) -> bool:
    data = load()
    for c in data["categories"]:
        if c["name"] == cat_name:
            groups = c.setdefault("groups", {})
            if group_name in groups:
                del groups[group_name]
                save(data)
                return True
    return False


def parse_tags(text: str) -> list[str]:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def resolve_selection(
    selection: dict[str, list[str]],
) -> tuple[dict[str, list[str]], list[str]]:
    """Turn {category_name: [group_names]} into (overrides_by_bucket, extras).

    - overrides_by_bucket: bucket -> deduped tag list from selected groups
      in categories whose `overrides` matches that bucket.
    - extras: deduped tag list from selected groups in categories whose
      `overrides` is None.
    """
    data = load()
    by_bucket: dict[str, list[str]] = {}
    extras: list[str] = []
    for c in data["categories"]:
        picked = selection.get(c["name"]) or []
        if not picked:
            continue
        tags: list[str] = []
        for gname in picked:
            tags.extend(parse_tags(c.get("groups", {}).get(gname, "")))
        # dedupe preserving order
        seen = set()
        deduped = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                deduped.append(t)
        bucket = c.get("overrides")
        if bucket in VALID_BUCKETS:
            existing = by_bucket.setdefault(bucket, [])
            for t in deduped:
                if t not in existing:
                    existing.append(t)
        else:
            for t in deduped:
                if t not in extras:
                    extras.append(t)
    return by_bucket, extras
