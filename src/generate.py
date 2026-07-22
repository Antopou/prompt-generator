import random
from dataclasses import dataclass

from .config import LoraConfig
from .scenes import SCENES
from .tags import TagStats, classify

_CLOSED_EYES = {"closed eyes", "eyes closed", "one eye closed", "^_^", ">_<"}

# body-region order for outfit tags. Lower index = closer to head.
_REGION_ORDER = [
    # head
    ("head", ("hat", "cap", "beret", "hood", "hairband", "headband",
              "hair ornament", "hair ribbon", "hair bow", "hairclip",
              "veil", "crown")),
    # face
    ("face", ("glasses", "sunglasses", "eyepatch", "mask", "earrings")),
    # neck
    ("neck", ("choker", "necklace", "necktie", "tie", "bowtie", "scarf",
              "collar", "collared", "pendant", "cross")),
    # top
    ("top", ("shirt", "blouse", "sweater", "hoodie", "cardigan", "jacket",
             "coat", "cape", "kimono", "vest", "turtleneck", "crop top",
             "camisole", "tank top", "leotard", "dress", "uniform",
             "bikini", "swimsuit", "bra", "apron", "off-shoulder",
             "bare shoulders", "bare arms", "cleavage", "sideboob",
             "underboob", "navel", "midriff", "sleeves", "long sleeves",
             "short sleeves", "detached sleeves", "puffy sleeves",
             "sleeveless")),
    # arms/hands
    ("hands", ("gloves", "fingerless gloves", "wristband", "bracelet")),
    # waist
    ("waist", ("belt", "buckle", "sash", "ribbon", "bow")),
    # bottom
    ("bottom", ("skirt", "miniskirt", "pleated skirt", "shorts", "pants",
                "jeans", "hakama", "bloomers", "panties", "underwear",
                "lingerie")),
    # legs
    ("legs", ("thighhighs", "stockings", "pantyhose", "kneehighs", "socks",
              "garter belt", "garter", "zettai ryouiki", "bare legs")),
    # feet
    ("feet", ("shoes", "boots", "sandals", "flip-flops", "high heels",
              "loafers", "sneakers", "footwear")),
    # misc details
    ("detail", ("frills", "zipper", "pocket", "pockets", "buttons")),
]


def _region_index(tag: str) -> int:
    for i, (_, kws) in enumerate(_REGION_ORDER):
        for kw in kws:
            if kw in tag:
                return i
    return len(_REGION_ORDER)


def _dedupe_generic(tags: list[str]) -> list[str]:
    """Drop bare `jacket` when `black jacket` (or any `X jacket`) present."""
    keep = []
    for t in tags:
        redundant = any(
            other != t and other.endswith(" " + t)
            for other in tags
        )
        if not redundant:
            keep.append(t)
    return keep


def _order_outfit(tags: list[str]) -> list[str]:
    return sorted(tags, key=_region_index)


def _pick_outfit_cluster(outfits: list[list[str]], rng: random.Random) -> list[str]:
    """Bias toward more complete captions: sample from top-quartile by length."""
    non_empty = [o for o in outfits if o]
    if not non_empty:
        return []
    ranked = sorted(non_empty, key=len, reverse=True)
    cutoff = max(1, len(ranked) // 4)
    return rng.choice(ranked[:cutoff])


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


def build_prompt(
    cfg: LoraConfig,
    stats: TagStats,
    scene: str,
    rng: random.Random,
    extra_tags: list[str] | None = None,
    overrides: dict[str, list[str]] | None = None,
    exclude: set[str] | None = None,
    block_closed_eyes: bool = False,
) -> Prompt:
    if scene not in SCENES:
        raise KeyError(f"Unknown scene '{scene}'. Options: {list(SCENES)}")
    recipe = SCENES[scene]
    buckets = classify(stats)
    ov = overrides or {}
    ex = {e.lower() for e in (exclude or set())}

    parts: list[str] = [cfg.trigger, "1girl", "solo"]

    def _append(tag: str) -> None:
        if tag and tag not in parts and tag.strip().lower() not in ex:
            parts.append(tag)

    # pre-pick expression so we can skip eye_color if eyes are closed
    if ov.get("expression"):
        expression_picks = list(ov["expression"])
    else:
        _n_expr = recipe.get("expression_n", 0)
        _expr_pool = buckets["expression"][:5]
        if block_closed_eyes:
            _expr_pool = [it for it in _expr_pool if it[0].strip().lower() not in _CLOSED_EYES]
        expression_picks = _pick(rng, _expr_pool, _n_expr) if _n_expr else []

    skip_eye_color = any(t.strip().lower() in _CLOSED_EYES for t in expression_picks)

    # identity — top-1 of each if present (never overridable)
    for key in ("hair_length", "hair_color", "eye_color", "bangs"):
        if key == "eye_color" and skip_eye_color:
            continue
        pick = _pick_first(buckets[key])
        if pick:
            _append(pick)

    # outfit
    if ov.get("outfit"):
        cluster = _dedupe_generic(list(ov["outfit"]))
        cluster = _order_outfit(cluster)
        for t in cluster:
            _append(t)
    elif recipe.get("outfit"):
        cluster = _pick_outfit_cluster(stats.outfits, rng)
        cluster = _dedupe_generic(cluster)
        cluster = _order_outfit(cluster)
        for t in cluster:
            _append(t)

    # pose
    if ov.get("pose"):
        for t in ov["pose"]:
            _append(t)
    else:
        n = recipe.get("pose_n", 0)
        if n:
            for t in _pick(rng, buckets["pose"], n):
                _append(t)

    # expression (already picked above)
    for t in expression_picks:
        _append(t)

    # framing
    if ov.get("framing"):
        for t in ov["framing"]:
            _append(t)
    else:
        bias = recipe.get("framing_bias")
        framing_tags = {t for t, _ in buckets["framing"]}
        chosen = bias if bias and bias in framing_tags else _pick_first(buckets["framing"])
        if chosen:
            _append(chosen)

    # background
    if ov.get("background"):
        for t in ov["background"]:
            _append(t)
    else:
        n = recipe.get("background_n", 0)
        if n:
            for t in _pick(rng, buckets["background"], n):
                _append(t)

    # extra tags — appended last, deduped
    if extra_tags:
        for t in extra_tags:
            _append(t)

    return Prompt(positive=", ".join(parts))


def build_many(cfg, stats, scene, n, seed=None, extra_tags=None, overrides=None, exclude=None):
    rng = random.Random(seed)
    n = int(n)
    max_closed = max(1, round(n / 3))
    closed_count = 0
    results = []
    for _ in range(n):
        block = closed_count >= max_closed
        p = build_prompt(
            cfg, stats, scene, rng, extra_tags, overrides, exclude,
            block_closed_eyes=block,
        )
        tokens = {t.strip().lower() for t in p.positive.split(",")}
        if tokens & _CLOSED_EYES:
            closed_count += 1
        results.append(p)
    return results
