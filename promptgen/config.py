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
