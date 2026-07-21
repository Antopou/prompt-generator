import random
from dataclasses import dataclass

from .config import LoraConfig
from .scenes import SCENES
from .tags import TagStats, classify


@dataclass
class Prompt:
    positive: str

    def render(self, idx: int) -> str:
        return f"=== Prompt {idx} ===\n{self.positive}\n"


def _pick(rng: random.Random, pool: list[tuple[str, int]], k: int) -> list[str]:
    if not pool:
        return []
    tags = [t for t, _ in pool]
    k = min(k, len(tags))
    return rng.sample(tags, k)


def _pick_first(pool: list[tuple[str, int]]) -> str | None:
    return pool[0][0] if pool else None


def build_prompt(cfg: LoraConfig, stats: TagStats, scene: str, rng: random.Random) -> Prompt:
    if scene not in SCENES:
        raise KeyError(f"Unknown scene '{scene}'. Options: {list(SCENES)}")
    recipe = SCENES[scene]
    buckets = classify(stats)

    parts: list[str] = [cfg.trigger, "1girl", "solo"]

    # identity — top-1 of each if present
    for key in ("hair_length", "hair_color", "eye_color", "bangs"):
        pick = _pick_first(buckets[key])
        if pick and pick not in parts:
            parts.append(pick)

    # outfit — one real caption's outfit cluster
    if recipe.get("outfit"):
        outfit_clusters = [o for o in stats.outfits if o]
        if outfit_clusters:
            for t in rng.choice(outfit_clusters):
                if t not in parts:
                    parts.append(t)

    # pose
    n = recipe.get("pose_n", 0)
    if n:
        for t in _pick(rng, buckets["pose"], n):
            if t not in parts:
                parts.append(t)

    # expression
    n = recipe.get("expression_n", 0)
    if n:
        for t in _pick(rng, buckets["expression"][:5], n):
            if t not in parts:
                parts.append(t)

    # framing — prefer the scene bias if present in bucket, else top framing
    bias = recipe.get("framing_bias")
    framing_tags = {t for t, _ in buckets["framing"]}
    chosen = bias if bias and bias in framing_tags else _pick_first(buckets["framing"])
    if chosen and chosen not in parts:
        parts.append(chosen)

    # background
    n = recipe.get("background_n", 0)
    if n:
        for t in _pick(rng, buckets["background"], n):
            if t not in parts:
                parts.append(t)

    return Prompt(positive=", ".join(parts))


def build_many(cfg, stats, scene, n, seed=None):
    rng = random.Random(seed)
    return [build_prompt(cfg, stats, scene, rng) for _ in range(n)]
