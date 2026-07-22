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
from . import drive_sync, generate, groups, tags
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

def _parse_exclude(text: str) -> set[str]:
    return {t.strip() for t in (text or "").split(",") if t.strip()}


def do_generate(lora, scene, n, selections):
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
    exclude = _parse_exclude(cfgmod.get_setting("exclude_tags", ""))
    prompts = generate.build_many(
        cfg, stats, scene, int(n),
        extra_tags=list(extras_from_groups), overrides=overrides,
        exclude=exclude,
    )
    return [p.positive for p in prompts], ""


def save_exclude(text):
    cfgmod.set_setting("exclude_tags", (text or "").strip())
    n = len(_parse_exclude(text))
    return f"saved {n} excluded tag(s)"


# ------- Groups tab helpers -------


def _cat_choices():
    return groups.category_names()


def _bucket_label(name):
    if not name:
        return ""
    if name == "none":
        return "*uncategorized — tags go to extras*"
    ov = groups.infer_overrides(name)
    text = f"overrides {ov}" if ov else "extras (no override)"
    return f"*{text}*"


def gt_pick_category(name):
    """Pick category → refresh group dropdown, clear editor."""
    if not name:
        return gr.update(choices=[], value=None), "", "", ""
    gnames = groups.list_groups(name)
    return (
        gr.update(choices=gnames, value=None),
        "",
        "",
        _bucket_label(name),
    )


def gt_add_category(new_name):
    name = (new_name or "").strip()
    if not name:
        return "empty name", gr.update(), gr.update(visible=False), "", gr.update()
    try:
        groups.upsert_category(name, groups.infer_overrides(name))
    except ValueError as e:
        return f"error: {e}", gr.update(), gr.update(visible=True), new_name, gr.update()
    names = _cat_choices()
    return (
        f"added category '{name}'",
        gr.update(choices=names, value=name),
        gr.update(visible=False),
        "",
        _bucket_label(name),
    )


def gt_rename_category(old_name, new_name):
    if not old_name:
        return "no category selected", gr.update(), gr.update(visible=False), "", gr.update()
    new_name = (new_name or "").strip()
    if not new_name:
        return "empty name", gr.update(), gr.update(visible=True), new_name, gr.update()
    if old_name in groups.BUILTIN_CATEGORIES:
        return (
            f"'{old_name}' is built-in, cannot rename",
            gr.update(), gr.update(visible=False), "", gr.update(),
        )
    try:
        groups.rename_category(old_name, new_name)
    except (ValueError, KeyError) as e:
        return f"error: {e}", gr.update(), gr.update(visible=True), new_name, gr.update()
    names = _cat_choices()
    return (
        f"renamed '{old_name}' → '{new_name}'",
        gr.update(choices=names, value=new_name),
        gr.update(visible=False),
        "",
        _bucket_label(new_name),
    )


def gt_delete_category(name):
    if not name:
        return "no category selected", gr.update(), gr.update(choices=[], value=None), "", "", ""
    if name in groups.BUILTIN_CATEGORIES:
        return f"'{name}' is built-in, cannot delete", gr.update(), gr.update(), "", "", _bucket_label(name)
    ok = groups.delete_category(name)
    names = _cat_choices()
    val = "none" if "none" in names else (names[0] if names else None)
    gnames = groups.list_groups(val) if val else []
    return (
        (f"deleted '{name}'" if ok else f"'{name}' not found"),
        gr.update(choices=names, value=val),
        gr.update(choices=gnames, value=None),
        "",
        "",
        _bucket_label(val),
    )


def gt_pick_group(cat_name, group_name):
    if not cat_name or not group_name:
        return "", ""
    return group_name, groups.get_group(cat_name, group_name)


def gt_save_group(cat_name, picked_name, form_name, tags_text):
    """Save group. If picked_name set and differs from form_name → rename + upsert."""
    if not cat_name:
        return "pick a category first", gr.update()
    name = (form_name or "").strip()
    if not name:
        return "empty group name", gr.update()
    try:
        if picked_name and picked_name != name:
            groups.rename_group(cat_name, picked_name, name)
        groups.upsert_group(cat_name, name, tags_text or "")
    except (ValueError, KeyError) as e:
        return f"error: {e}", gr.update()
    gnames = groups.list_groups(cat_name)
    msg = (
        f"renamed '{picked_name}' → '{name}' in '{cat_name}'"
        if picked_name and picked_name != name
        else f"saved group '{name}' in '{cat_name}'"
    )
    return msg, gr.update(choices=gnames, value=name)


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
    groups.ensure_builtins()
    initial = _lora_choices()
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

                with gr.Accordion("Groups", open=False):
                    with gr.Row():
                        groups_reload_btn = gr.Button("↻ Reload groups", scale=1)
                        groups_clear_btn = gr.Button("Clear selections", scale=1)
                    categories_state = gr.State(groups.list_categories())
                    selections_state = gr.State({})

                    @gr.render(inputs=categories_state)
                    def _render_groups(cats):
                        non_empty = [c for c in (cats or []) if (c.get("groups") or {})]
                        if not non_empty:
                            gr.Markdown("*no groups yet — add some in the Groups tab*")
                            return
                        for c in non_empty:
                            cname = c["name"]
                            gnames = sorted((c.get("groups") or {}).keys())
                            dd = gr.Dropdown(
                                choices=gnames,
                                value=[],
                                multiselect=True,
                                label=cname,
                                interactive=True,
                                key=f"grp_dd_{cname}",
                            )

                            def _make_updater(cat=cname):
                                def _update(picked, current):
                                    current = dict(current or {})
                                    current[cat] = picked or []
                                    return current
                                return _update

                            dd.change(_make_updater(), inputs=[dd, selections_state],
                                      outputs=selections_state)

                with gr.Accordion("Excluded tags", open=False):
                    exclude_in = gr.Textbox(
                        label="Tags to exclude (comma-separated)",
                        lines=2,
                        placeholder="watermark, signature, text",
                        value=cfgmod.get_setting("exclude_tags", ""),
                    )
                    with gr.Row():
                        exclude_save_btn = gr.Button("Save", variant="primary")
                    exclude_status = gr.Markdown("")

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
                              inputs=[lora_dd, scene_dd, n_num, selections_state],
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

                exclude_save_btn.click(save_exclude, inputs=exclude_in, outputs=exclude_status)

            # ---- Groups (library editor) ----
            with gr.Tab("Groups"):
                initial_cats = _cat_choices()
                initial_cat_val = "none" if "none" in initial_cats else (initial_cats[0] if initial_cats else None)
                initial_group_names = groups.list_groups(initial_cat_val) if initial_cat_val else []

                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### Category")
                        cat_dd = gr.Dropdown(
                            choices=initial_cats, value=initial_cat_val,
                            label="Category", allow_custom_value=False,
                        )
                        cat_bucket_md = gr.Markdown(_bucket_label(initial_cat_val))
                        with gr.Row():
                            cat_new_btn = gr.Button("+ New", scale=1)
                            cat_rename_btn = gr.Button("Rename", scale=1)
                            cat_delete_btn = gr.Button("Delete", variant="stop", scale=1)
                        with gr.Row(visible=False) as cat_new_row:
                            cat_new_name = gr.Textbox(
                                label="New category name",
                                placeholder="e.g. place, action, mood",
                                scale=4,
                            )
                            cat_new_add = gr.Button("Add", variant="primary", scale=1)
                            cat_new_cancel = gr.Button("Cancel", scale=1)
                        with gr.Row(visible=False) as cat_rename_row:
                            cat_rename_name = gr.Textbox(
                                label="Rename to",
                                placeholder="new name",
                                scale=4,
                            )
                            cat_rename_confirm = gr.Button("Apply", variant="primary", scale=1)
                            cat_rename_cancel = gr.Button("Cancel", scale=1)
                        cat_status = gr.Markdown("")

                    with gr.Column(scale=1):
                        gr.Markdown("### Group")
                        group_dd = gr.Dropdown(
                            choices=initial_group_names, value=None,
                            label="Group (pick to edit, or blank to create new)",
                            allow_custom_value=False,
                        )
                        group_name_in = gr.Textbox(
                            label="Group name (change to rename)",
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
                    outputs=[group_dd, group_name_in, group_tags_in, cat_bucket_md],
                )

                cat_new_btn.click(
                    lambda: (gr.update(visible=True), "", gr.update(visible=False), ""),
                    outputs=[cat_new_row, cat_new_name, cat_rename_row, cat_rename_name],
                )
                cat_new_cancel.click(
                    lambda: (gr.update(visible=False), ""),
                    outputs=[cat_new_row, cat_new_name],
                )
                cat_new_add.click(
                    gt_add_category, inputs=cat_new_name,
                    outputs=[cat_status, cat_dd, cat_new_row, cat_new_name, cat_bucket_md],
                )

                cat_rename_btn.click(
                    lambda cur: (
                        gr.update(visible=bool(cur)),
                        cur or "",
                        gr.update(visible=False),
                        "",
                    ),
                    inputs=cat_dd,
                    outputs=[cat_rename_row, cat_rename_name, cat_new_row, cat_new_name],
                )
                cat_rename_cancel.click(
                    lambda: (gr.update(visible=False), ""),
                    outputs=[cat_rename_row, cat_rename_name],
                )
                cat_rename_confirm.click(
                    gt_rename_category, inputs=[cat_dd, cat_rename_name],
                    outputs=[cat_status, cat_dd, cat_rename_row, cat_rename_name, cat_bucket_md],
                )

                cat_delete_btn.click(
                    gt_delete_category, inputs=cat_dd,
                    outputs=[cat_status, cat_dd, group_dd, group_name_in, group_tags_in, cat_bucket_md],
                )

                group_dd.change(
                    gt_pick_group, inputs=[cat_dd, group_dd],
                    outputs=[group_name_in, group_tags_in],
                )
                group_save_btn.click(
                    gt_save_group,
                    inputs=[cat_dd, group_dd, group_name_in, group_tags_in],
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
                m_search = gr.Textbox(label="Search LoRAs", placeholder="Type to filter...", lines=1, max_lines=1)
                m_table = gr.Dataframe(
                    headers=["name", "imported", "id"],
                    datatype=["str", "str", "str"],
                    interactive=False, wrap=True,
                    row_count=7,
                    max_height=300,
                )
                m_log = gr.Textbox(label="Log", lines=3)
                m_full_table = gr.State([])

                def _filter_table(query, full_data):
                    if not full_data: return []
                    if not query: return full_data
                    q = query.lower()
                    return [r for r in full_data if q in str(r[0]).lower()]

                connect_btn.click(list_all_loras, outputs=[m_full_table, m_status]).then(
                    _filter_table, inputs=[m_search, m_full_table], outputs=m_table
                )
                m_search.change(_filter_table, inputs=[m_search, m_full_table], outputs=m_table)

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
                ).then(list_all_loras, outputs=[m_full_table, m_status]
                ).then(_filter_table, inputs=[m_search, m_full_table], outputs=m_table)

                ex_sync.click(sync_existing, inputs=ex_dd, outputs=ex_status)
                ex_remove.click(remove_lora, inputs=ex_dd, outputs=[ex_status, lora_dd]).then(
                    refresh_choices, outputs=ex_dd
                ).then(list_all_loras, outputs=[m_full_table, m_status]
                ).then(_filter_table, inputs=[m_search, m_full_table], outputs=m_table)

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
        prevent_thread_lock=False,
    )
    ui.block_thread()
