import json
import re
from collections import Counter
from dataclasses import dataclass, asdict, field
from pathlib import Path

OUTFIT_KEYWORDS = {
    # tops
    "shirt", "blouse", "dress", "bikini", "uniform", "jacket", "bra",
    "swimsuit", "coat", "sweater", "hoodie", "kimono", "cape", "cardigan",
    "vest", "apron", "leotard", "turtleneck", "crop top", "camisole",
    "tank top", "off-shoulder", "bare shoulders", "bare arms", "cleavage",
    "sideboob", "underboob", "navel", "midriff",
    # bottoms
    "skirt", "miniskirt", "pleated skirt", "shorts", "pants", "jeans",
    "hakama", "bloomers",
    # legs / underwear
    "panties", "lingerie", "underwear", "thighhighs", "stockings", "socks",
    "kneehighs", "garter", "garter belt", "bare legs", "pantyhose",
    "zettai ryouiki",
    # feet
    "shoes", "boots", "sandals", "flip-flops", "footwear", "high heels",
    "loafers", "sneakers",
    # neck / chest accents
    "ribbon", "necktie", "tie", "scarf", "collar", "collared", "choker",
    "necklace", "bow", "bowtie",
    # sleeves / hands
    "sleeves", "long sleeves", "short sleeves", "detached sleeves",
    "puffy sleeves", "sleeveless", "gloves", "fingerless gloves", "wristband",
    "bracelet",
    # head
    "hat", "cap", "beret", "hood", "hairband", "headband", "hair ornament",
    "hair ribbon", "hair bow", "hairclip", "veil", "crown",
    # face
    "glasses", "sunglasses", "eyepatch", "mask", "earrings",
    # details
    "frills", "belt", "buckle", "zipper", "pocket", "pockets", "buttons",
    "sash", "cross", "pendant",
}
POSE_KEYWORDS = {
    "standing", "sitting", "squatting", "kneeling", "lying", "arms up",
    "hands up", "arms behind back", "leaning forward", "leaning back",
    "crossed arms", "hand on hip", "hands on hips", "hand on chest",
    "arms crossed", "looking at viewer", "looking back", "looking down",
    "looking up", "looking away", "cowboy shot", "own hands together",
    "steepled fingers", "tiptoes", "spread legs", "legs crossed", "walking",
    "running", "jumping", "stretching",
}
EXPRESSION_KEYWORDS = {
    "smile", "blush", "open mouth", "closed mouth", "grin", "laughing",
    "crying", "tears", "pout", "frown", "sad", "angry", "surprised",
    "embarrassed", "one eye closed", "closed eyes", "wink", ";d", ";)",
    ":d", ":)", ":o", "split mouth",
}
BACKGROUND_KEYWORDS = {
    "simple background", "white background", "transparent background",
    "black background", "gradient background", "outdoors", "indoors",
    "day", "night", "sunset", "sky", "cloud", "clouds", "beach", "forest",
    "classroom", "bedroom", "kitchen", "street", "city", "park",
}
FRAMING_KEYWORDS = {
    "full body", "upper body", "cowboy shot", "portrait", "close-up",
    "lower body", "from above", "from below", "from side", "from behind",
}
HAIR_COLOR_RE = re.compile(r"^(pink|blonde|blue|red|black|white|silver|brown|purple|green|orange|grey|gray) hair$")
EYE_COLOR_RE = re.compile(r"^(pink|blonde|blue|red|black|white|silver|brown|purple|green|orange|grey|gray|aqua|yellow) eyes$")
HAIR_LENGTH_RE = re.compile(r"^(long|short|medium|very long|very short) hair$")
BANGS_RE = re.compile(r".*bangs$")

SKIP_TAGS = {"1girl", "solo", "1boy", "2girls"}


@dataclass
class TagStats:
    total_captions: int
    counter: dict[str, int]
    outfits: list[list[str]] = field(default_factory=list)  # per-caption outfit tag lists

    def top(self, n: int, in_set: set[str] | None = None, pred=None) -> list[tuple[str, int]]:
        items = sorted(self.counter.items(), key=lambda kv: (-kv[1], kv[0]))
        out = []
        for tag, cnt in items:
            if in_set is not None and tag not in in_set:
                continue
            if pred is not None and not pred(tag):
                continue
            out.append((tag, cnt))
            if len(out) >= n:
                break
        return out


def parse_caption(text: str) -> list[str]:
    return [t.strip().lower() for t in text.split(",") if t.strip()]


def load_captions(dataset_dir: Path) -> list[list[str]]:
    caps = []
    for p in sorted(dataset_dir.glob("*.txt")):
        caps.append(parse_caption(p.read_text(encoding="utf-8", errors="ignore")))
    return caps


def _is_outfit(tag: str) -> bool:
    for kw in OUTFIT_KEYWORDS:
        if kw in tag:
            return True
    return False


def analyze(captions: list[list[str]]) -> TagStats:
    counter: Counter[str] = Counter()
    outfits: list[list[str]] = []
    for cap in captions:
        counter.update(cap)
        outfits.append([t for t in cap if _is_outfit(t)])
    return TagStats(
        total_captions=len(captions),
        counter=dict(counter),
        outfits=outfits,
    )


def save_stats(stats: TagStats, path: Path) -> None:
    path.write_text(json.dumps(asdict(stats), indent=2))


def load_stats(path: Path) -> TagStats:
    d = json.loads(path.read_text())
    return TagStats(
        total_captions=d["total_captions"],
        counter=d["counter"],
        outfits=d.get("outfits", []),
    )


def classify(stats: TagStats) -> dict[str, list[tuple[str, int]]]:
    """Return top tags per bucket."""
    return {
        "hair_color": stats.top(3, pred=lambda t: bool(HAIR_COLOR_RE.match(t))),
        "eye_color": stats.top(3, pred=lambda t: bool(EYE_COLOR_RE.match(t))),
        "hair_length": stats.top(2, pred=lambda t: bool(HAIR_LENGTH_RE.match(t))),
        "bangs": stats.top(2, pred=lambda t: bool(BANGS_RE.match(t))),
        "pose": stats.top(10, in_set=POSE_KEYWORDS),
        "expression": stats.top(8, in_set=EXPRESSION_KEYWORDS),
        "background": stats.top(8, in_set=BACKGROUND_KEYWORDS),
        "framing": stats.top(6, in_set=FRAMING_KEYWORDS),
    }
