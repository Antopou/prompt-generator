import random
from dataclasses import dataclass

from .config import LoraConfig
from .scenes import SCENES, NEGATIVE, QUALITY_BASE
from .tags import TagStats, classify


@dataclass
class Prompt:
    positive: str
    negative: str
    model: str
    lora: str
    size: str
    seed: int = -1

    def render(self, idx: int) -> str:
        return (
            f"=== Prompt {idx} ===\n"
            f"POSITIVE: {self.positive}\n"
            f"NEGATIVE: {self.negative}\n"
            f"MODEL: {self.model}\n"
            f"LORA: {self.lora}\n"
            f"SIZE: {self.size}\n"
            f"SEED: {self.seed}\n"
        )


def _pick(rng: random.Random, pool: list[tuple[str, int]], k: int) -> list[str]:
    if not pool:
        return []
    tags = [t for t, _ in pool]
    k = min(k, len(tags))
    return rng.sample(tags, k)


def _pick_first(pool: list[tuple[str, int]]) -> str | None:
    return pool[0][0] if pool else None


def build_prompt(
    cfg: LoraConfig,
    stats: TagStats,
    scene: str,
    rng: random.Random,
) -> Prompt:
    if scene not in SCENES:
        raise KeyError(f"Unknown scene '{scene}'. Options: {list(SCENES)}")
    recipe = SCENES[scene]
    buckets = classify(stats)

    parts: list[str] = [cfg.trigger, "1girl", "solo"]

    # identity tags — always include top-1 of each
    for key in ("hair_length", "hair_color", "eye_color", "bangs"):
        pick = _pick_first(buckets[key])
        if pick and pick not in parts:
            parts.append(pick)

    # outfit — sample a real caption's outfit cluster to preserve co-occurrence
    outfit_clusters = [o for o in stats.outfits if o]
    if recipe.get("outfit_pick") and outfit_clusters:
        cluster = rng.choice(outfit_clusters)
        for t in cluster:
            if t not in parts:
                parts.append(t)

    # pose
    if recipe.get("pose_force"):
        for t in recipe["pose_force"]:
            if t not in parts:
                parts.append(t)
    if recipe.get("pose_pick"):
        for t in _pick(rng, buckets["pose"], recipe["pose_pick"]):
            if t not in parts:
                parts.append(t)

    # expression
    if recipe.get("expression_pick"):
        top_exp = buckets["expression"][:5]
        for t in _pick(rng, top_exp, recipe["expression_pick"]):
            if t not in parts:
                parts.append(t)

    # framing
    if recipe.get("framing_force"):
        for t in recipe["framing_force"]:
            if t not in parts:
                parts.append(t)

    # background
    if recipe.get("background_force"):
        for t in recipe["background_force"]:
            if t not in parts:
                parts.append(t)
    if recipe.get("background_pick"):
        for t in _pick(rng, buckets["background"], recipe["background_pick"]):
            if t not in parts:
                parts.append(t)

    # extras + quality
    parts.extend(recipe.get("extra", []))
    parts.extend(QUALITY_BASE)

    lora_tag = f"<lora:{cfg.lora_file}:{cfg.lora_weight}>"
    positive = ", ".join(parts) + f" {lora_tag}"

    return Prompt(
        positive=positive,
        negative=NEGATIVE,
        model=cfg.base_model,
        lora=lora_tag,
        size=recipe["size"],
    )


def build_many(
    cfg: LoraConfig,
    stats: TagStats,
    scene: str,
    n: int,
    seed: int | None = None,
) -> list[Prompt]:
    rng = random.Random(seed)
    return [build_prompt(cfg, stats, scene, rng) for _ in range(n)]
