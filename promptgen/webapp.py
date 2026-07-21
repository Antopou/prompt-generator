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

def _load_stats(lora: str) -> tags.TagStats | None:
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

def do_generate(lora, scene, n):
    if not lora:
        return [], "no LoRA selected. Add one in the Manage tab."
    try:
        cfg = cfgmod.load(lora)
    except KeyError as e:
        return [], f"config error: {e}"
    stats = _load_stats(lora)
    if stats is None:
        return [], f"no .txt tag files in cache for '{lora}'. Sync from Drive first (Manage tab)."
    prompts = generate.build_many(cfg, stats, scene, int(n))
    return [p.positive for p in prompts], ""


# ------- Manage tab -------

def refresh_choices():
    names = _lora_choices()
    return gr.update(choices=names, value=(names[0] if names else None))


def _find_loras_root() -> tuple[str | None, str]:
    """Return (folder_id, status_msg). Uses saved setting; else looks for 'Loras' in My Drive root."""
    saved = cfgmod.get_setting("loras_root_id")
    if saved:
        return saved, f"using saved Loras root ({saved[:12]}…)"
    try:
        top = drive_sync.list_folders("root")
    except Exception as e:
        return None, f"error listing My Drive: {e}"
    for f in top:
        if f["title"].lower() == "loras":
            cfgmod.set_setting("loras_root_id", f["id"])
            return f["id"], f"found 'Loras' folder in My Drive"
    return None, "no 'Loras' folder found in My Drive — click 'Set Loras root' to pick one"


def list_all_loras():
    """Return (rows, status). Rows: [name, imported?, drive_id]."""
    root_id, status = _find_loras_root()
    if root_id is None:
        return [], status
    try:
        folders = drive_sync.list_folders(root_id)
    except Exception as e:
        return [], f"error: {e}"
    existing = set(cfgmod.list_loras())
    rows = [[f["title"], "yes" if f["title"] in existing else "no", f["id"]] for f in folders]
    return rows, f"{len(rows)} LoRA folder(s) found — click a row to import"


def import_lora(folder_name: str, folder_id: str, progress=gr.Progress()):
    """Import a LoRA: find its `dataset` subfolder, sync, save config, detect trigger."""
    name = folder_name.strip()
    if not name or not folder_id:
        yield f"invalid selection: name='{name}' id='{folder_id}'"
        return
    yield f"[1/4] resolving '{name}' → looking for 'dataset' subfolder…"
    try:
        subs = drive_sync.list_folders(folder_id)
    except Exception as e:
        yield f"failed to list '{name}': {e}"; return
    ds = next((s for s in subs if s["title"].lower() == "dataset"), None)
    if not ds:
        yield f"no 'dataset' subfolder inside '{name}'. Aborting."; return
    dataset_id = ds["id"]

    yield f"[2/4] saving config…"
    cfg = cfgmod.LoraConfig(
        name=name, drive_folder=dataset_id, trigger=name,
        base_model="", lora_file=name, lora_weight=0.8,
    )
    cfgmod.upsert_lora(cfg)

    yield f"[3/4] syncing .txt tag files…"
    try:
        def prog(i, total, msg):
            progress(i / max(total, 1), desc=f"{i}/{total} {msg}")
        dl, sk = drive_sync.sync(name, dataset_id, progress=prog)
    except Exception as e:
        yield f"sync failed: {e}"; return

    t = _detect_trigger(name)
    if t:
        cfg.trigger = t
        cfgmod.upsert_lora(cfg)
    yield (
        f"[4/4] done — {name}: {dl} downloaded, {sk} unchanged, "
        f"trigger='{t or name}'. Switch to Generate tab."
    )


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

def show_tags(lora):
    if not lora:
        return "no LoRA selected"
    stats = _load_stats(lora)
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
    css = """
    .prompt-card {
        background: var(--background-fill-secondary);
        border: 1px solid var(--border-color-primary);
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 12px;
        font-family: var(--font-mono);
        font-size: 14px;
        line-height: 1.6;
        color: var(--body-text-color);
        position: relative;
        box-shadow: var(--shadow-sm);
    }
    .prompt-card .txt { white-space: pre-wrap; word-break: break-word; padding-right: 70px; }
    .prompt-card button.copy {
        position: absolute; top: 12px; right: 12px;
        background: var(--primary-500); color: white; border: none;
        padding: 4px 12px; border-radius: 6px; cursor: pointer;
        font-size: 12px; font-family: var(--font);
        transition: background 0.2s;
    }
    .prompt-card button.copy:hover { background: var(--primary-600); }
    .prompt-card button.copy.done { background: #16a34a; }
    """
    with gr.Blocks(title="promptgen") as demo:
        demo._promptgen_css = css
        gr.Markdown("## promptgen")

        with gr.Tabs():
            # ---- Generate ----
            with gr.Tab("Generate"):
                with gr.Group():
                    with gr.Row():
                        lora_dd = gr.Dropdown(choices=initial, value=(initial[0] if initial else None),
                                              label="LoRA", scale=3)
                        scene_dd = gr.Dropdown(choices=list(SCENES), value="portrait", label="Scene", scale=2)
                        n_num = gr.Number(value=3, precision=0, label="N", minimum=1, maximum=20, scale=1)
                    with gr.Row():
                        refresh_btn = gr.Button("↻ Refresh", scale=1)
                        gen_btn = gr.Button("Generate", variant="primary", scale=3)
                gen_error = gr.Markdown("")
                prompts_state = gr.State([])

                @gr.render(inputs=prompts_state)
                def _render_prompts(prompts):
                    if not prompts:
                        gr.Markdown("_no prompts yet — click Generate_")
                        return
                    import html as _html
                    for text in prompts:
                        esc = _html.escape(text)
                        gr.HTML(
                            f'<div class="prompt-card">'
                            f'<button class="copy" onclick="'
                            f"navigator.clipboard.writeText(this.nextElementSibling.textContent);"
                            f"this.textContent='copied';this.classList.add('done');"
                            f"setTimeout(()=>{{this.textContent='copy';this.classList.remove('done');}},1200);"
                            f'">copy</button>'
                            f'<div class="txt">{esc}</div>'
                            f'</div>'
                        )

                gen_btn.click(do_generate,
                              inputs=[lora_dd, scene_dd, n_num],
                              outputs=[prompts_state, gen_error])
                refresh_btn.click(refresh_choices, outputs=lora_dd)

            # ---- Manage ----
            with gr.Tab("Manage LoRAs"):
                with gr.Row():
                    with gr.Column(scale=1):
                        with gr.Group():
                            root_txt = gr.Textbox(
                                label="Drive root",
                                placeholder="Loras root folder ID",
                                value=cfgmod.get_setting("loras_root_id", ""),
                                lines=1, max_lines=1,
                            )
                            with gr.Row():
                                connect_btn = gr.Button("Connect / Refresh", variant="primary")
                                set_root_btn = gr.Button("Save")
                    
                    with gr.Column(scale=1):
                        with gr.Group():
                            ex_dd = gr.Dropdown(
                                choices=initial, value=(initial[0] if initial else None),
                                label="Existing LoRA",
                            )
                            with gr.Row():
                                ex_sync = gr.Button("Re-sync")
                                ex_remove = gr.Button("Remove", variant="stop")

                m_status = gr.Markdown("")
                ex_status = gr.Markdown("")
                m_table = gr.Dataframe(
                    headers=["name", "imported", "id"],
                    datatype=["str", "str", "str"],
                    interactive=False, wrap=True,
                )
                m_log = gr.Textbox(label="Log", lines=3)

                connect_btn.click(list_all_loras, outputs=[m_table, m_status])

                def _save_root(v):
                    v = (v or "").strip()
                    if v:
                        cfgmod.set_setting("loras_root_id", v)
                        return f"saved root = {v}"
                    return "empty — not saved"
                set_root_btn.click(_save_root, inputs=root_txt, outputs=m_status)

                def _row_import(evt: gr.SelectData, table):
                    try:
                        row = table.values.tolist()[evt.index[0]] if hasattr(table, "values") else table[evt.index[0]]
                        name, _imported, fid = row[0], row[1], row[2]
                    except Exception as e:
                        yield f"row error: {e}"; return
                    yield from import_lora(name, fid)

                m_table.select(_row_import, inputs=m_table, outputs=m_log).then(
                    refresh_choices, outputs=lora_dd
                ).then(refresh_choices, outputs=ex_dd
                ).then(list_all_loras, outputs=[m_table, m_status])

                ex_sync.click(sync_existing, inputs=ex_dd, outputs=ex_status)
                ex_remove.click(remove_lora, inputs=ex_dd, outputs=[ex_status, lora_dd]).then(
                    refresh_choices, outputs=ex_dd
                ).then(list_all_loras, outputs=[m_table, m_status])

    return demo


def _modern_theme() -> gr.themes.Base:
    """Clean, modern, and simple theme."""
    return gr.themes.Soft(
        primary_hue=gr.themes.colors.indigo,
        secondary_hue=gr.themes.colors.indigo,
        neutral_hue=gr.themes.colors.slate,
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("Fira Code"), "monospace"],
    )


def run(share: bool = False, port: int = 7871) -> None:
    ui = build_ui()
    ui.launch(
        server_port=port, share=share, inbrowser=True,
        theme=_modern_theme(), css=getattr(ui, "_promptgen_css", None),
    )
