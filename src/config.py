import tomllib
from dataclasses import dataclass
from .paths import CONFIG_PATH, ensure_app_dir

DEFAULT_CONFIG = """# promptgen config
# LoRAs are added via the GUI (or `promptgen add`). Each becomes a [loras.<name>] section.
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


def get_setting(key: str, default=None):
    bootstrap_config()
    data = tomllib.loads(CONFIG_PATH.read_text())
    return (data.get("settings") or {}).get(key, default)


def set_setting(key: str, value: str) -> None:
    bootstrap_config()
    text = CONFIG_PATH.read_text()
    line = f'{key} = "{value}"'
    import re
    if "[settings]" in text:
        # replace or append inside existing [settings] section
        block = re.search(r"\[settings\]\n((?:(?!^\[).*\n?)*)", text, re.MULTILINE)
        section_text = block.group(1) if block else ""
        if re.search(rf"^{re.escape(key)}\s*=", section_text, re.MULTILINE):
            new_section = re.sub(
                rf"^{re.escape(key)}\s*=.*$", line, section_text, count=1, flags=re.MULTILINE
            )
        else:
            new_section = section_text.rstrip("\n") + f"\n{line}\n"
        text = text.replace(block.group(0), f"[settings]\n{new_section}")
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += f"\n[settings]\n{line}\n"
    CONFIG_PATH.write_text(text)


def remove_lora(name: str) -> bool:
    bootstrap_config()
    text = CONFIG_PATH.read_text()
    header = f"[loras.{name}]"
    if header not in text:
        return False
    import re
    pattern = re.compile(rf"{re.escape(header)}\n(?:(?!^\[).*\n?)*", re.MULTILINE)
    CONFIG_PATH.write_text(pattern.sub("", text, count=1))
    return True


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
