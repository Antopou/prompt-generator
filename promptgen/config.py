import tomllib
from dataclasses import dataclass
from .paths import CONFIG_PATH, ensure_app_dir

DEFAULT_CONFIG = """# promptgen config
# One [loras.<name>] section per LoRA you train.

[loras.chika]
drive_folder = "Loras/kaguyasama_chika/dataset"
trigger = "chika"
base_model = "waiIllustriousSDXL_v160"
lora_file = "kaguyasama_chika"
lora_weight = 0.8
"""


@dataclass
class LoraConfig:
    name: str
    drive_folder: str
    trigger: str
    base_model: str
    lora_file: str
    lora_weight: float = 0.8


def bootstrap_config() -> None:
    ensure_app_dir()
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG)


def list_loras() -> list[str]:
    bootstrap_config()
    data = tomllib.loads(CONFIG_PATH.read_text())
    return sorted((data.get("loras") or {}).keys())


def upsert_lora(cfg: LoraConfig) -> None:
    """Append or replace a [loras.<name>] section in config.toml (text-level, preserves rest)."""
    bootstrap_config()
    text = CONFIG_PATH.read_text()
    header = f"[loras.{cfg.name}]"
    block = (
        f"{header}\n"
        f'drive_folder = "{cfg.drive_folder}"\n'
        f'trigger = "{cfg.trigger}"\n'
        f'base_model = "{cfg.base_model}"\n'
        f'lora_file = "{cfg.lora_file}"\n'
        f"lora_weight = {cfg.lora_weight}\n"
    )
    if header in text:
        # replace existing section (from header until next [ or EOF)
        import re
        pattern = re.compile(
            rf"{re.escape(header)}\n(?:(?!^\[).*\n?)*", re.MULTILINE
        )
        text = pattern.sub(block, text, count=1)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + block
    CONFIG_PATH.write_text(text)


def load(lora: str) -> LoraConfig:
    bootstrap_config()
    data = tomllib.loads(CONFIG_PATH.read_text())
    loras = data.get("loras", {})
    if lora not in loras:
        raise KeyError(
            f"LoRA '{lora}' not in {CONFIG_PATH}. Add a [loras.{lora}] section."
        )
    entry = loras[lora]
    return LoraConfig(
        name=lora,
        drive_folder=entry["drive_folder"],
        trigger=entry["trigger"],
        base_model=entry.get("base_model", ""),
        lora_file=entry.get("lora_file", lora),
        lora_weight=float(entry.get("lora_weight", 0.8)),
    )
