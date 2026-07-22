# Prompt Generator

SDXL prompt generator built from LoRA training tag datasets. Gradio web interface, Google Drive dataset sync, reusable tag-group library, scene-aware auto-composition.

## Launch on Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/antopou/prompt-generator/blob/main/Prompt_Generator_Colab.ipynb)

## Run locally

```bash
git clone https://github.com/antopou/prompt-generator.git
cd prompt-generator
pip install .
prompt-generator web
```

Requires Python 3.11+.

## Interface

- **Generate** — pick a LoRA and scene, produce prompts. Tag-group multi-select per category overrides the auto-picked bucket; free-form extras appended.
- **Groups** — build a reusable library of named tag groups organized by user-defined categories (outfit, place, action, …). Each category can override one of the standard buckets (`outfit`, `pose`, `expression`, `framing`, `background`) or simply append its tags as extras.
- **Manage LoRAs** — import LoRA datasets from Google Drive, re-sync, or remove them.
- **Tags** — inspect the tag-frequency distribution for a synced LoRA dataset.

## Data locations

| Path | Purpose |
|---|---|
| `~/.promptgen/config.toml` | LoRA registry and settings |
| `~/.promptgen/cache/<lora>/` | Synced caption files (`.txt`) |
| `~/.promptgen/presets.json` | Free-form preset extras |
| `~/.promptgen/groups.json` | Tag-group library |
| `~/.promptgen/client_secrets.json` | Google Drive OAuth client (user-supplied) |

## Command-line interface

```
prompt-generator gen <lora> [--scene portrait|pose|situation] [-n N] [--seed S]
prompt-generator sync <lora>
prompt-generator tags <lora>
prompt-generator add <lora> --drive <folder-id|url> --trigger <tag>
prompt-generator list
prompt-generator web [--port 7871] [--share]
prompt-generator gui
```
