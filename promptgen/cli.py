import argparse
import subprocess
import sys
from pathlib import Path

from . import config as cfgmod
from . import drive_sync, generate, tags
from .paths import lora_cache_dir


def _copy_to_clipboard(text: str) -> bool:
    try:
        p = subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return p.returncode == 0
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _load_stats(lora: str, local: Path | None) -> tags.TagStats:
    if local is not None:
        dataset_dir = local
    else:
        dataset_dir = lora_cache_dir(lora)
    if not any(dataset_dir.glob("*.txt")):
        raise SystemExit(
            f"No .txt tag files found in {dataset_dir}. "
            f"Run `promptgen sync {lora}` first, or pass --local <dataset_dir>."
        )
    caps = tags.load_captions(dataset_dir)
    return tags.analyze(caps)


def cmd_sync(args: argparse.Namespace) -> int:
    cfg = cfgmod.load(args.lora)
    print(f"Syncing '{args.lora}' from Drive: {cfg.drive_folder}")
    def _p(i, total, msg):
        print(f"  [{i}/{total}] {msg}")
    downloaded, skipped = drive_sync.sync(args.lora, cfg.drive_folder, progress=_p)
    print(f"Done. {downloaded} downloaded, {skipped} unchanged.")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    cfg = cfgmod.LoraConfig(
        name=args.lora,
        drive_folder=args.drive,
        trigger=args.trigger,
        base_model=args.base_model or "",
        lora_file=args.lora_file or args.lora,
        lora_weight=args.weight,
    )
    cfgmod.upsert_lora(cfg)
    print(f"Saved [loras.{args.lora}] to {cfgmod.CONFIG_PATH}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    for name in cfgmod.list_loras():
        print(name)
    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    from . import gui
    gui.run()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from . import webapp
    webapp.run(share=args.share, port=args.port)
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    cfg = cfgmod.load(args.lora)
    local = Path(args.local).expanduser() if args.local else None
    stats = _load_stats(args.lora, local)
    prompts = generate.build_many(cfg, stats, args.scene, args.n, seed=args.seed)
    blocks = [p.render(i + 1) for i, p in enumerate(prompts)]
    output = "\n".join(blocks)
    print(output)
    if prompts and _copy_to_clipboard(prompts[0].positive):
        print("(first prompt POSITIVE copied to clipboard)")
    return 0


def cmd_tags(args: argparse.Namespace) -> int:
    cfgmod.load(args.lora)  # validate
    local = Path(args.local).expanduser() if args.local else None
    stats = _load_stats(args.lora, local)
    buckets = tags.classify(stats)
    print(f"Total captions: {stats.total_captions}\n")
    for bucket, items in buckets.items():
        print(f"[{bucket}]")
        for t, c in items:
            print(f"  {c:>3}  {t}")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="promptgen", description="SDXL prompt generator from LoRA training tags")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen", help="Generate prompts")
    g.add_argument("lora")
    g.add_argument("--scene", default="portrait", choices=["portrait", "pose", "situation"])
    g.add_argument("-n", type=int, default=3)
    g.add_argument("--seed", type=int, default=None)
    g.add_argument("--local", help="Use local dataset dir instead of Drive cache")
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("sync", help="Sync tag files from Google Drive")
    s.add_argument("lora")
    s.set_defaults(func=cmd_sync)

    t = sub.add_parser("tags", help="Show tag frequency buckets for a LoRA")
    t.add_argument("lora")
    t.add_argument("--local", help="Use local dataset dir instead of Drive cache")
    t.set_defaults(func=cmd_tags)

    a = sub.add_parser("add", help="Add/update a LoRA in config")
    a.add_argument("lora", help="LoRA key name")
    a.add_argument("--drive", required=True, help="Drive folder path, ID, or share URL")
    a.add_argument("--trigger", required=True, help="Trigger tag (first tag in captions)")
    a.add_argument("--base-model", default="", help="Base checkpoint name (informational)")
    a.add_argument("--lora-file", default=None, help="LoRA filename without extension (default = <lora>)")
    a.add_argument("--weight", type=float, default=0.8)
    a.set_defaults(func=cmd_add)

    sub.add_parser("list", help="List configured LoRAs").set_defaults(func=cmd_list)
    sub.add_parser("gui", help="Launch Tkinter GUI (legacy)").set_defaults(func=cmd_gui)

    w = sub.add_parser("web", help="Launch Gradio web UI (recommended)")
    w.add_argument("--port", type=int, default=7871)
    w.add_argument("--share", action="store_true", help="Create public Gradio share link")
    w.set_defaults(func=cmd_web)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
