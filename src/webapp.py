"""Gradio web UI for Prompt Generator.

Tabs:
  Generate — pick LoRA, scene, N; get prompts
  Manage   — add/remove/sync LoRAs, browse Drive folders
  Tags     — inspect tag frequency for a LoRA
"""
from collections import Counter
from pathlib import Path

import gradio as gr

from . import config as cfgmod
from . import drive_sync, generate, groups, presets, tags
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

def do_generate(lora, scene, n, extra_text, selections):
    if not lora:
        return [], "no LoRA selected. Add one in the Manage tab."
    try:
        cfg = cfgmod.load(lora)
    except KeyError as e:
        return [], f"config error: {e}"
    stats = _load_stats(lora)
    if stats is None:
        return [], f"no .txt tag files in cache for '{lora}'. Sync from Drive first (Manage tab)."
    overrides, extras_from_groups = groups.resolve_selection(selections or {})
    extra = list(extras_from_groups)
    for t in presets.parse_tags(extra_text or ""):
        if t not in extra:
            extra.append(t)
    prompts = generate.build_many(
        cfg, stats, scene, int(n), extra_tags=extra, overrides=overrides
    )
    return [p.positive for p in prompts], ""


# ------- Preset helpers -------

def _preset_choices() -> list[str]:
    return presets.list_names()


def load_preset(name):
    return presets.get(name) if name else ""


def save_preset(name, text):
    name = (name or "").strip()
    if not name:
        return "empty name", gr.update()
    presets.save(name, text or "")
    names = _preset_choices()
    return f"saved preset '{name}'", gr.update(choices=names, value=name)


def delete_preset(name):
    if not name:
        return "no preset selected", gr.update(), ""
    ok = presets.delete(name)
    names = _preset_choices()
    val = names[0] if names else None
    msg = f"deleted '{name}'" if ok else f"'{name}' not found"
    new_tags = presets.get(val) if val else ""
    return msg, gr.update(choices=names, value=val), new_tags


# ------- Groups tab helpers -------

_OVERRIDES_UI = ["none", "outfit", "pose", "expression", "framing", "background"]


def _to_ov(v):
    return None if not v or v == "none" else v


def _from_ov(v):
    return "none" if v is None else v


def _cat_choices():
    return groups.category_names()


def gt_save_category(name, overrides_ui):
    name = (name or "").strip()
    if not name:
        return "empty name", gr.update()
    try:
        groups.upsert_category(name, _to_ov(overrides_ui))
    except ValueError as e:
        return f"error: {e}", gr.update()
    names = _cat_choices()
    return f"saved category '{name}'", gr.update(choices=names, value=name)


def gt_delete_category(name):
    if not name:
        return "no category selected", gr.update(), gr.update(), gr.update(choices=[], value=None), "", ""
    ok = groups.delete_category(name)
    names = _cat_choices()
    val = names[0] if names else None
    cat = groups.get_category(val) if val else None
    return (
        (f"deleted '{name}'" if ok else f"'{name}' not found"),
        gr.update(choices=names, value=val),
        gr.update(value=_from_ov((cat or {}).get("overrides"))) if cat else gr.update(value="none"),
        gr.update(choices=groups.list_groups(val) if val else [], value=None),
        "",
        "",
    )


def gt_pick_category(name):
    """Selected a category → load its overrides + refresh group dropdown."""
    if not name:
        return gr.update(value="none"), gr.update(choices=[], value=None), "", ""
    c = groups.get_category(name) or {}
    ov = _from_ov(c.get("overrides"))
    gnames = groups.list_groups(name)
    return (
        gr.update(value=ov),
        gr.update(choices=gnames, value=None),
        "",  # clear group name box
        "",  # clear tags box
    )


def gt_pick_group(cat_name, group_name):
    if not cat_name or not group_name:
        return "", ""
    return group_name, groups.get_group(cat_name, group_name)


def gt_save_group(cat_name, group_name, tags_text):
    if not cat_name:
        return "pick a category first", gr.update()
    try:
        groups.upsert_group(cat_name, (group_name or "").strip(), tags_text or "")
    except (ValueError, KeyError) as e:
        return f"error: {e}", gr.update()
    gnames = groups.list_groups(cat_name)
    return f"saved group '{group_name}' in '{cat_name}'", gr.update(choices=gnames, value=group_name)


def gt_delete_group(cat_name, group_name):
    if not cat_name or not group_name:
        return "no group selected", gr.update(), "", ""
    ok = groups.delete_group(cat_name, group_name)
    gnames = groups.list_groups(cat_name)
    return (
        f"deleted '{group_name}'" if ok else f"'{group_name}' not found",
        gr.update(choices=gnames, value=None),
        "",
        "",
    )


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
    initial_presets = _preset_choices()
    css = """
    button:not(.copy) {
        padding: 4px 12px !important;
        min-height: 28px !important;
        font-size: 13px !important;
        line-height: 1 !important;
    }
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
    with gr.Blocks(title="Prompt Generator") as demo:
        demo._promptgen_css = css
        gr.Markdown("## Prompt Generator\n---")

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

                with gr.Accordion("Groups (pick per category)", open=True):
                    with gr.Row():
                        groups_reload_btn = gr.Button("↻ Reload groups", scale=1)
                        groups_clear_btn = gr.Button("Clear selections", scale=1)
                    categories_state = gr.State(groups.list_categories())
                    selections_state = gr.State({})

                    @gr.render(inputs=[categories_state, selections_state])
                    def _render_groups(cats, sel):
                        if not cats:
                            return
                        for c in cats:
                            cname = c["name"]
                            ov = c.get("overrides") or "extras"
                            gnames = sorted((c.get("groups") or {}).keys())
                            dd = gr.Dropdown(
                                choices=gnames,
                                value=sel.get(cname, []),
                                multiselect=True,
                                label=f"{cname} → {ov}",
                                interactive=True,
                            )

                            def _make_updater(cat=cname):
                                def _update(picked, current):
                                    current = dict(current or {})
                                    current[cat] = picked or []
                                    return current
                                return _update

                            dd.change(_make_updater(), inputs=[dd, selections_state],
                                      outputs=selections_state)

                with gr.Accordion("Presets (extra tags)", open=False):
                    with gr.Row():
                        preset_dd = gr.Dropdown(
                            choices=initial_presets,
                            value=(initial_presets[0] if initial_presets else None),
                            label="Preset", scale=2, allow_custom_value=False,
                        )
                        preset_name = gr.Textbox(
                            label="Name (for save)", scale=2,
                            value=(initial_presets[0] if initial_presets else ""),
                            placeholder="e.g. side_view",
                        )
                    preset_tags = gr.Textbox(
                        label="Tags (comma-separated, appended to prompt)",
                        lines=2, placeholder="from side, looking to the side",
                        value=(presets.get(initial_presets[0]) if initial_presets else ""),
                    )
                    with gr.Row():
                        preset_save = gr.Button("Save")
                        preset_delete = gr.Button("Delete", variant="stop")
                        preset_refresh = gr.Button("↻")
                    preset_status = gr.Markdown("")

                gen_error = gr.Markdown("")
                prompts_state = gr.State([])

                @gr.render(inputs=prompts_state)
                def _render_prompts(prompts):
                    if not prompts:
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
                              inputs=[lora_dd, scene_dd, n_num, preset_tags, selections_state],
                              outputs=[prompts_state, gen_error])
                refresh_btn.click(refresh_choices, outputs=lora_dd)

                # groups wiring
                def _reload_groups_state():
                    cats = groups.list_categories()
                    return cats, {}
                groups_reload_btn.click(
                    _reload_groups_state,
                    outputs=[categories_state, selections_state],
                )
                groups_clear_btn.click(lambda: {}, outputs=selections_state)

                # preset wiring
                def _on_preset_pick(name):
                    return presets.get(name) if name else "", (name or "")
                preset_dd.change(_on_preset_pick, inputs=preset_dd,
                                 outputs=[preset_tags, preset_name])
                preset_save.click(save_preset, inputs=[preset_name, preset_tags],
                                  outputs=[preset_status, preset_dd])
                preset_delete.click(delete_preset, inputs=preset_dd,
                                    outputs=[preset_status, preset_dd, preset_tags])

                def _refresh_presets():
                    names = _preset_choices()
                    return gr.update(choices=names, value=(names[0] if names else None))
                preset_refresh.click(_refresh_presets, outputs=preset_dd)

            # ---- Groups (library editor) ----
            with gr.Tab("Groups"):
                initial_cats = _cat_choices()
                initial_cat_val = initial_cats[0] if initial_cats else None
                initial_cat_obj = groups.get_category(initial_cat_val) if initial_cat_val else None
                initial_ov = _from_ov((initial_cat_obj or {}).get("overrides"))
                initial_group_names = groups.list_groups(initial_cat_val) if initial_cat_val else []

                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### Category")
                        cat_dd = gr.Dropdown(
                            choices=initial_cats, value=initial_cat_val,
                            label="Existing category", allow_custom_value=False,
                        )
                        cat_name_in = gr.Textbox(
                            label="Name (new or existing)",
                            value=initial_cat_val or "",
                            placeholder="e.g. outfit, place, action",
                        )
                        cat_ov_dd = gr.Dropdown(
                            choices=_OVERRIDES_UI, value=initial_ov,
                            label="Overrides bucket",
                        )
                        with gr.Row():
                            cat_save_btn = gr.Button("Save category", variant="primary")
                            cat_delete_btn = gr.Button("Delete category", variant="stop")
                        cat_status = gr.Markdown("")

                    with gr.Column(scale=1):
                        gr.Markdown("### Group (inside selected category)")
                        group_dd = gr.Dropdown(
                            choices=initial_group_names, value=None,
                            label="Existing group", allow_custom_value=False,
                        )
                        group_name_in = gr.Textbox(
                            label="Group name",
                            placeholder="e.g. school_uniform",
                        )
                        group_tags_in = gr.Textbox(
                            label="Tags (comma-separated)",
                            lines=4,
                            placeholder="white shirt, pleated skirt, red ribbon, thighhighs",
                        )
                        with gr.Row():
                            group_save_btn = gr.Button("Save group", variant="primary")
                            group_delete_btn = gr.Button("Delete group", variant="stop")
                        group_status = gr.Markdown("")

                cat_dd.change(
                    gt_pick_category, inputs=cat_dd,
                    outputs=[cat_ov_dd, group_dd, group_name_in, group_tags_in],
                ).then(lambda v: v or "", inputs=cat_dd, outputs=cat_name_in)

                cat_save_btn.click(
                    gt_save_category, inputs=[cat_name_in, cat_ov_dd],
                    outputs=[cat_status, cat_dd],
                )
                cat_delete_btn.click(
                    gt_delete_category, inputs=cat_dd,
                    outputs=[cat_status, cat_dd, cat_ov_dd, group_dd, group_name_in, group_tags_in],
                )

                group_dd.change(
                    gt_pick_group, inputs=[cat_dd, group_dd],
                    outputs=[group_name_in, group_tags_in],
                )
                group_save_btn.click(
                    gt_save_group, inputs=[cat_dd, group_name_in, group_tags_in],
                    outputs=[group_status, group_dd],
                )
                group_delete_btn.click(
                    gt_delete_group, inputs=[cat_dd, group_dd],
                    outputs=[group_status, group_dd, group_name_in, group_tags_in],
                )

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
    theme = gr.themes.Soft(
        primary_hue=gr.themes.colors.indigo,
        secondary_hue=gr.themes.colors.indigo,
        neutral_hue=gr.themes.colors.slate,
        font=["ui-monospace", "Consolas", "monospace"],
        font_mono=["ui-monospace", "Consolas", "monospace"],
        text_size=gr.themes.sizes.text_sm,
        spacing_size=gr.themes.sizes.spacing_sm,
        radius_size=gr.themes.sizes.radius_none,
    )
    theme.set(
        block_label_background_fill="transparent",
        block_label_text_color="*neutral_500",
        block_label_text_weight="bold",
        block_title_background_fill="transparent",
        block_title_text_color="*neutral_500",
        block_title_text_weight="bold",
        button_large_padding="4px 12px",
        button_small_padding="4px 8px",
        block_padding="6px",
        input_padding="4px 8px",
    )
    return theme


def run(share: bool = False, port: int = 7871, inline: bool = True) -> None:
    ui = build_ui()
    ui.launch(
        server_port=port, share=share, inbrowser=True, inline=inline,
        theme=_modern_theme(), css=getattr(ui, "_promptgen_css", None),
    )
