"""Gradio web UI for promptgen.

Tabs:
  Generate — pick LoRA, scene, N; get prompts
  Manage   — add/remove/sync LoRAs, browse Drive folders
  Tags     — inspect tag frequency for a LoRA
"""
from collections import Counter
from pathlib import Path

import gradio as gr

from . import config as cfgmod
from . import drive_sync, generate, tags
from .paths import lora_cache_dir
from .scenes import SCENES


# ------- helpers -------

def _load_stats(lora: str, local_path: str = "") -> tags.TagStats | None:
    if local_path:
        dataset_dir = Path(local_path).expanduser()
    else:
        dataset_dir = lora_cache_dir(lora)
    if not any(dataset_dir.glob("*.txt")):
        return None
    caps = tags.load_captions(dataset_dir)
    return tags.analyze(caps)


def _detect_trigger(lora: str) -> str | None:
    cache = lora_cache_dir(lora)
    firsts: Counter[str] = Counter()
    for p in cache.glob("*.txt"):
        cap = tags.parse_caption(p.read_text(encoding="utf-8", errors="ignore"))
        if cap:
            firsts[cap[0]] += 1
    if not firsts:
        return None
    return firsts.most_common(1)[0][0]


def _lora_choices() -> list[str]:
    return cfgmod.list_loras()


# ------- Generate tab -------

def do_generate(lora, scene, n, weight, seed, local_path):
    if not lora:
        return "no LoRA selected. Add one in the Manage tab."
    try:
        cfg = cfgmod.load(lora)
    except KeyError as e:
        return f"config error: {e}"
    cfg.lora_weight = float(weight)
    stats = _load_stats(lora, local_path.strip())
    if stats is None:
        return f"no .txt tag files in cache for '{lora}'. Sync from Drive first (Manage tab)."
    seed_val = int(seed) if str(seed).strip() else None
    prompts = generate.build_many(cfg, stats, scene, int(n), seed=seed_val)
    return "\n".join(p.render(i + 1) for i, p in enumerate(prompts))


def first_positive(output_text: str) -> str:
    for line in output_text.splitlines():
        if line.startswith("POSITIVE: "):
            return line[len("POSITIVE: "):]
    return ""


# ------- Manage tab -------

def refresh_choices():
    names = _lora_choices()
    return gr.update(choices=names, value=(names[0] if names else None))


def _list_at(folder_id: str):
    """Return (rows, status). Rows: [title, id]."""
    try:
        folders = drive_sync.list_folders(folder_id)
    except Exception as e:
        return [], f"error: {e}"
    rows = [[f["title"], f["id"]] for f in folders]
    return rows, f"{len(rows)} subfolder(s)"


def browse_navigate(target_id: str, target_name: str, crumbs: list):
    """Navigate INTO a folder. Returns (rows, status, breadcrumb_md, new_crumbs, current_id)."""
    if not crumbs:
        crumbs = [{"id": "root", "name": "My Drive"}]
    if target_id and target_id != crumbs[-1]["id"]:
        crumbs = crumbs + [{"id": target_id, "name": target_name or target_id}]
    current_id = crumbs[-1]["id"]
    rows, status = _list_at(current_id)
    return rows, status, _crumb_md(crumbs), crumbs, current_id


def browse_up(crumbs: list):
    if not crumbs:
        crumbs = [{"id": "root", "name": "My Drive"}]
    if len(crumbs) > 1:
        crumbs = crumbs[:-1]
    current_id = crumbs[-1]["id"]
    rows, status = _list_at(current_id)
    return rows, status, _crumb_md(crumbs), crumbs, current_id


def browse_home(_crumbs=None):
    crumbs = [{"id": "root", "name": "My Drive"}]
    rows, status = _list_at("root")
    return rows, status, _crumb_md(crumbs), crumbs, "root"


def _crumb_md(crumbs: list) -> str:
    if not crumbs:
        return "**My Drive**"
    return "**" + " / ".join(c["name"] for c in crumbs) + "**"


def add_and_sync(name, drive_folder, trigger, base_model, lora_file, weight, do_sync,
                 progress=gr.Progress()):
    """Generator: yields log-string updates as steps complete."""
    name = (name or "").strip()
    drive_folder = (drive_folder or "").strip()
    if not (name and drive_folder):
        yield "ERROR: name + drive folder required"
        return

    cfg = cfgmod.LoraConfig(
        name=name,
        drive_folder=drive_folder,
        trigger=(trigger or "").strip() or name,
        base_model=(base_model or "").strip(),
        lora_file=(lora_file or "").strip() or name,
        lora_weight=float(weight),
    )
    cfgmod.upsert_lora(cfg)
    log = [f"[1/3] saved config: [loras.{name}]"]
    yield "\n".join(log)

    if not do_sync:
        return

    log.append(f"[2/3] syncing from Drive folder {drive_folder} …")
    yield "\n".join(log)
    progress(0, desc="sync starting")

    try:
        state = {"i": 0, "n": 0}

        def prog(i, total, msg):
            state["i"], state["n"] = i, total
            progress(i / max(total, 1), desc=f"{i}/{total} {msg}")

        dl, sk = drive_sync.sync(name, drive_folder, progress=prog)
        log.append(f"     synced: {dl} downloaded, {sk} unchanged (of {state['n']} files)")
        yield "\n".join(log)
    except Exception as e:
        log.append(f"     sync FAILED: {type(e).__name__}: {e}")
        yield "\n".join(log)
        return

    if not (trigger or "").strip():
        t = _detect_trigger(name)
        if t:
            cfg.trigger = t
            cfgmod.upsert_lora(cfg)
            log.append(f"[3/3] auto-detected trigger tag: '{t}'")
        else:
            log.append("[3/3] no captions found for trigger detection")
    else:
        log.append(f"[3/3] using trigger tag: '{trigger}'")
    log.append("DONE — switch to Generate tab and pick this LoRA")
    yield "\n".join(log)


def sync_existing(lora):
    if not lora:
        return "pick a LoRA first"
    try:
        cfg = cfgmod.load(lora)
    except KeyError as e:
        return f"config error: {e}"
    try:
        dl, sk = drive_sync.sync(lora, cfg.drive_folder)
        return f"{lora}: {dl} downloaded, {sk} unchanged"
    except Exception as e:
        return f"sync failed: {e}"


def remove_lora(lora):
    if not lora:
        return "pick a LoRA first", refresh_choices()
    ok = cfgmod.remove_lora(lora)
    return (f"removed '{lora}'" if ok else f"'{lora}' not found"), refresh_choices()


# ------- Tags tab -------

def show_tags(lora, local_path):
    if not lora:
        return "no LoRA selected"
    stats = _load_stats(lora, local_path.strip())
    if stats is None:
        return f"no cached tags for '{lora}'. Sync first."
    buckets = tags.classify(stats)
    lines = [f"{stats.total_captions} captions\n"]
    for bucket, items in buckets.items():
        lines.append(f"[{bucket}]")
        for t, c in items:
            lines.append(f"  {c:>3}  {t}")
        lines.append("")
    return "\n".join(lines)


# ------- UI -------

def build_ui() -> gr.Blocks:
    initial = _lora_choices()
    with gr.Blocks(title="promptgen") as demo:
        gr.Markdown("## promptgen — SDXL prompt generator from LoRA training tags")

        with gr.Tabs():
            # ---- Generate ----
            with gr.Tab("Generate"):
                with gr.Row():
                    lora_dd = gr.Dropdown(choices=initial, value=(initial[0] if initial else None),
                                          label="LoRA", allow_custom_value=False, scale=2)
                    refresh_btn = gr.Button("↻", scale=0)
                with gr.Row():
                    scene_dd = gr.Dropdown(choices=list(SCENES), value="portrait", label="Scene")
                    n_num = gr.Number(value=3, precision=0, label="N", minimum=1, maximum=20)
                    weight_num = gr.Number(value=0.8, label="LoRA weight", minimum=0.1, maximum=1.5, step=0.05)
                    seed_txt = gr.Textbox(value="", label="Seed (blank = random)")
                local_txt = gr.Textbox(value="", label="Local dataset path (optional, overrides cache)")
                gen_btn = gr.Button("Generate", variant="primary")
                output_box = gr.Textbox(label="Prompts", lines=20)
                copy_first_btn = gr.Button("Extract first POSITIVE (copyable)")
                first_pos_box = gr.Textbox(label="First POSITIVE prompt", lines=3)

                gen_btn.click(
                    do_generate,
                    inputs=[lora_dd, scene_dd, n_num, weight_num, seed_txt, local_txt],
                    outputs=output_box,
                )
                copy_first_btn.click(first_positive, inputs=output_box, outputs=first_pos_box)
                refresh_btn.click(refresh_choices, outputs=lora_dd)

            # ---- Manage ----
            with gr.Tab("Manage LoRAs"):
                gr.Markdown("### Add a LoRA")
                with gr.Row():
                    with gr.Column(scale=1):
                        m_name = gr.Textbox(label="Name (short key, e.g. character name)")
                        m_drive = gr.Textbox(label="Drive folder ID / share URL / slash-path",
                                             placeholder="paste share URL or click a row below")
                        m_trigger = gr.Textbox(label="Trigger tag (leave blank = auto-detect after sync)")
                        m_base = gr.Textbox(label="Base model (informational)",
                                            value="waiIllustriousSDXL_v160")
                        m_file = gr.Textbox(label="LoRA filename without extension (blank = name)")
                        m_weight = gr.Number(value=0.8, label="LoRA weight", minimum=0.1, maximum=1.5, step=0.05)
                        m_sync = gr.Checkbox(value=True, label="Sync from Drive after saving")
                        m_save_btn = gr.Button("Save + Sync", variant="primary")
                    with gr.Column(scale=1):
                        gr.Markdown("### Browse your Google Drive")
                        gr.Markdown(
                            "Click **Connect / Load My Drive** → browser will pop up first time "
                            "asking you to log in with Google. After login, folder list appears. "
                            "**Click any row to go into that folder.** Use ⬆ Up to go back. "
                            "When you're inside your dataset folder, click **Use this folder** — "
                            "the Drive folder field on the left gets filled automatically."
                        )
                        with gr.Row():
                            b_home = gr.Button("Connect / Load My Drive", variant="primary")
                            b_up = gr.Button("⬆ Up")
                            b_use = gr.Button("✔ Use this folder", variant="secondary")
                        b_crumb = gr.Markdown("**(not connected)**")
                        b_current = gr.State("root")
                        b_crumbs_state = gr.State([])
                        b_table = gr.Dataframe(headers=["folder name", "id"], datatype=["str", "str"],
                                               interactive=False, wrap=True)
                        b_status = gr.Markdown("")

                gr.Markdown("### Existing LoRAs")
                with gr.Row():
                    ex_dd = gr.Dropdown(choices=initial, value=(initial[0] if initial else None), label="LoRA")
                    ex_sync = gr.Button("Sync")
                    ex_remove = gr.Button("Remove", variant="stop")
                ex_status = gr.Markdown("")

                manage_log = gr.Textbox(label="Log", lines=6)

                m_save_btn.click(
                    add_and_sync,
                    inputs=[m_name, m_drive, m_trigger, m_base, m_file, m_weight, m_sync],
                    outputs=manage_log,
                ).then(refresh_choices, outputs=lora_dd
                ).then(refresh_choices, outputs=ex_dd)

                b_home.click(
                    browse_home,
                    outputs=[b_table, b_status, b_crumb, b_crumbs_state, b_current],
                )
                b_up.click(
                    browse_up,
                    inputs=b_crumbs_state,
                    outputs=[b_table, b_status, b_crumb, b_crumbs_state, b_current],
                )

                def _row_click(evt: gr.SelectData, table, crumbs):
                    """Row click = navigate INTO that folder."""
                    try:
                        row = table.values.tolist()[evt.index[0]] if hasattr(table, "values") else table[evt.index[0]]
                        name, folder_id = row[0], row[1]
                    except Exception as e:
                        return [], f"row error: {e}", _crumb_md(crumbs or []), crumbs or [], (crumbs[-1]["id"] if crumbs else "root")
                    return browse_navigate(folder_id, name, crumbs or [])

                b_table.select(
                    _row_click,
                    inputs=[b_table, b_crumbs_state],
                    outputs=[b_table, b_status, b_crumb, b_crumbs_state, b_current],
                )

                b_use.click(lambda cid: cid, inputs=b_current, outputs=m_drive)

                ex_sync.click(sync_existing, inputs=ex_dd, outputs=ex_status)
                ex_remove.click(remove_lora, inputs=ex_dd, outputs=[ex_status, lora_dd]).then(
                    refresh_choices, outputs=ex_dd
                )

            # ---- Tags ----
            with gr.Tab("Tags"):
                with gr.Row():
                    t_lora = gr.Dropdown(choices=initial, value=(initial[0] if initial else None), label="LoRA")
                    t_refresh = gr.Button("↻", scale=0)
                t_local = gr.Textbox(value="", label="Local dataset path (optional)")
                t_btn = gr.Button("Show tags", variant="primary")
                t_out = gr.Textbox(label="Frequency buckets", lines=25)
                t_btn.click(show_tags, inputs=[t_lora, t_local], outputs=t_out)
                t_refresh.click(refresh_choices, outputs=t_lora)

    return demo


def _sd_theme() -> gr.themes.Base:
    """A1111/Forge-inspired theme: orange primary, dark bg, Source Sans font."""
    return gr.themes.Default(
        primary_hue=gr.themes.colors.orange,
        secondary_hue=gr.themes.colors.orange,
        neutral_hue=gr.themes.colors.slate,
        font=[gr.themes.GoogleFont("Source Sans Pro"), "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "Menlo", "monospace"],
    ).set(
        body_background_fill="#0b0f19",
        body_background_fill_dark="#0b0f19",
        background_fill_primary="#1f2937",
        background_fill_primary_dark="#1f2937",
        background_fill_secondary="#111827",
        background_fill_secondary_dark="#111827",
        block_background_fill="#111827",
        block_background_fill_dark="#111827",
        block_border_color="#374151",
        block_border_color_dark="#374151",
        block_label_background_fill="#f97316",
        block_label_background_fill_dark="#f97316",
        block_label_text_color="#ffffff",
        block_label_text_color_dark="#ffffff",
        button_primary_background_fill="#f97316",
        button_primary_background_fill_dark="#f97316",
        button_primary_background_fill_hover="#ea580c",
        button_primary_background_fill_hover_dark="#ea580c",
        button_primary_text_color="#ffffff",
        button_primary_text_color_dark="#ffffff",
        button_secondary_background_fill="#374151",
        button_secondary_background_fill_dark="#374151",
        button_secondary_text_color="#ffffff",
        button_secondary_text_color_dark="#ffffff",
        input_background_fill="#0b0f19",
        input_background_fill_dark="#0b0f19",
        input_border_color="#374151",
        input_border_color_dark="#374151",
    )


def run(share: bool = False, port: int = 7871) -> None:
    build_ui().launch(server_port=port, share=share, inbrowser=True, theme=_sd_theme())
