"""Tkinter GUI for Prompt Generator.

Layout:
  Top row: LoRA dropdown | Sync btn | Add LoRA btn
  Controls: scene, n, weight, seed, --local override
  Buttons: Generate | Show Tags | Copy All | Clear
  Output: scrollable text
"""
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import config as cfgmod
from . import drive_sync, generate, tags
from .paths import lora_cache_dir
from .scenes import SCENES


def _copy(text: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Prompt Generator — SDXL prompt generator")
        root.geometry("900x680")

        frm = ttk.Frame(root, padding=10)
        frm.pack(fill="both", expand=True)

        # --- Row 0: LoRA selector ---
        row0 = ttk.Frame(frm); row0.pack(fill="x", pady=(0, 8))
        ttk.Label(row0, text="LoRA:").pack(side="left")
        self.lora_var = tk.StringVar()
        self.lora_combo = ttk.Combobox(row0, textvariable=self.lora_var, state="readonly", width=28)
        self.lora_combo.pack(side="left", padx=6)
        ttk.Button(row0, text="Refresh", command=self.refresh_loras).pack(side="left", padx=2)
        ttk.Button(row0, text="Sync from Drive", command=self.on_sync).pack(side="left", padx=6)
        ttk.Button(row0, text="Add LoRA…", command=self.on_add).pack(side="left", padx=2)

        # --- Row 1: scene, n, weight, seed ---
        row1 = ttk.Frame(frm); row1.pack(fill="x", pady=4)
        ttk.Label(row1, text="Scene:").pack(side="left")
        self.scene_var = tk.StringVar(value="portrait")
        ttk.Combobox(row1, textvariable=self.scene_var, values=list(SCENES),
                     state="readonly", width=12).pack(side="left", padx=6)

        ttk.Label(row1, text="N:").pack(side="left", padx=(12, 0))
        self.n_var = tk.IntVar(value=3)
        ttk.Spinbox(row1, from_=1, to=20, textvariable=self.n_var, width=5).pack(side="left", padx=4)

        ttk.Label(row1, text="LoRA weight:").pack(side="left", padx=(12, 0))
        self.weight_var = tk.DoubleVar(value=0.8)
        ttk.Spinbox(row1, from_=0.1, to=1.5, increment=0.05, textvariable=self.weight_var, width=6).pack(side="left", padx=4)

        ttk.Label(row1, text="Seed:").pack(side="left", padx=(12, 0))
        self.seed_var = tk.StringVar(value="")
        ttk.Entry(row1, textvariable=self.seed_var, width=8).pack(side="left", padx=4)

        # --- Row 2: local override ---
        row2 = ttk.Frame(frm); row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="Local dataset (override cache, optional):").pack(side="left")
        self.local_var = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=self.local_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row2, text="Browse…", command=self.on_browse).pack(side="left")

        # --- Row 3: actions ---
        row3 = ttk.Frame(frm); row3.pack(fill="x", pady=8)
        ttk.Button(row3, text="Generate", command=self.on_generate).pack(side="left", padx=2)
        ttk.Button(row3, text="Show Tags", command=self.on_tags).pack(side="left", padx=2)
        ttk.Button(row3, text="Copy All", command=self.on_copy).pack(side="left", padx=2)
        ttk.Button(row3, text="Copy First POSITIVE", command=self.on_copy_first).pack(side="left", padx=2)
        ttk.Button(row3, text="Clear", command=self.on_clear).pack(side="left", padx=2)

        # --- Output ---
        self.out = tk.Text(frm, wrap="word", height=24, font=("Menlo", 11))
        yscroll = ttk.Scrollbar(frm, command=self.out.yview)
        self.out.configure(yscrollcommand=yscroll.set)
        self.out.pack(side="left", fill="both", expand=True, pady=(4, 0))
        yscroll.pack(side="right", fill="y", pady=(4, 0))

        # --- Status bar ---
        self.status = tk.StringVar(value="ready")
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x", side="bottom")

        self.refresh_loras()

    # ---- helpers ----
    def _log(self, msg: str) -> None:
        self.out.insert("end", msg + "\n")
        self.out.see("end")

    def _set_status(self, msg: str) -> None:
        self.status.set(msg)
        self.root.update_idletasks()

    def _current_lora(self) -> str | None:
        v = self.lora_var.get().strip()
        return v or None

    def _load_stats(self, lora: str):
        local = self.local_var.get().strip()
        dataset_dir = Path(local).expanduser() if local else lora_cache_dir(lora)
        if not any(dataset_dir.glob("*.txt")):
            messagebox.showerror(
                "No tags",
                f"No .txt tag files in {dataset_dir}.\n"
                "Sync from Drive first, or set a local dataset path.",
            )
            return None
        caps = tags.load_captions(dataset_dir)
        return tags.analyze(caps)

    # ---- handlers ----
    def refresh_loras(self) -> None:
        names = cfgmod.list_loras()
        self.lora_combo["values"] = names
        if names and not self.lora_var.get():
            self.lora_var.set(names[0])
        self._set_status(f"{len(names)} LoRA(s) configured")

    def on_browse(self) -> None:
        d = filedialog.askdirectory(title="Select dataset directory")
        if d:
            self.local_var.set(d)

    def on_generate(self) -> None:
        lora = self._current_lora()
        if not lora:
            messagebox.showwarning("No LoRA", "Add a LoRA first.")
            return
        try:
            cfg = cfgmod.load(lora)
        except KeyError as e:
            messagebox.showerror("Config", str(e))
            return
        cfg.lora_weight = self.weight_var.get()
        stats = self._load_stats(lora)
        if stats is None:
            return
        seed_txt = self.seed_var.get().strip()
        seed = int(seed_txt) if seed_txt else None
        prompts = generate.build_many(
            cfg, stats, self.scene_var.get(), self.n_var.get(), seed=seed
        )
        for i, p in enumerate(prompts, 1):
            self._log(p.render(i))
        self._set_status(f"generated {len(prompts)} prompt(s)")

    def on_tags(self) -> None:
        lora = self._current_lora()
        if not lora:
            return
        stats = self._load_stats(lora)
        if stats is None:
            return
        buckets = tags.classify(stats)
        self._log(f"--- tags for {lora} ({stats.total_captions} captions) ---")
        for bucket, items in buckets.items():
            self._log(f"[{bucket}]")
            for t, c in items:
                self._log(f"  {c:>3}  {t}")
        self._log("")

    def on_copy(self) -> None:
        text = self.out.get("1.0", "end").rstrip()
        if _copy(text):
            self._set_status("copied all output to clipboard")

    def on_copy_first(self) -> None:
        text = self.out.get("1.0", "end")
        for line in text.splitlines():
            if line.startswith("POSITIVE: "):
                if _copy(line[len("POSITIVE: "):]):
                    self._set_status("copied first POSITIVE to clipboard")
                return
        self._set_status("no POSITIVE line found")

    def on_clear(self) -> None:
        self.out.delete("1.0", "end")

    def on_sync(self) -> None:
        lora = self._current_lora()
        if lora:
            self._do_sync(lora)

    def on_add(self) -> None:
        AddLoraDialog(self.root, on_saved=self._on_added)

    def _on_added(self, name: str, sync: bool = False, auto_trigger: bool = False) -> None:
        self.refresh_loras()
        self.lora_var.set(name)
        self._set_status(f"added LoRA '{name}'")
        if sync:
            self._do_sync(name, auto_trigger=auto_trigger)

    def _do_sync(self, lora: str, auto_trigger: bool = False) -> None:
        try:
            cfg = cfgmod.load(lora)
        except KeyError as e:
            messagebox.showerror("Config", str(e)); return
        self._log(f"--- sync {lora} from {cfg.drive_folder} ---")
        self._set_status("syncing…")

        def worker():
            try:
                def prog(i, total, msg):
                    self.root.after(0, lambda: (self._log(f"  [{i}/{total}] {msg}"),
                                                self._set_status(f"sync {i}/{total}")))
                dl, sk = drive_sync.sync(lora, cfg.drive_folder, progress=prog)
                self.root.after(0, lambda: (self._log(f"done: {dl} downloaded, {sk} unchanged"),
                                            self._set_status("sync complete")))
                if auto_trigger:
                    self._detect_trigger(lora)
            except Exception as e:
                self.root.after(0, lambda: (
                    messagebox.showerror("Sync failed", str(e)),
                    self._set_status("sync failed"),
                ))
        threading.Thread(target=worker, daemon=True).start()

    def _detect_trigger(self, lora: str) -> None:
        """Set trigger = most common first-position tag across cached captions."""
        from collections import Counter
        cache = lora_cache_dir(lora)
        firsts = Counter()
        for p in cache.glob("*.txt"):
            cap = tags.parse_caption(p.read_text(encoding="utf-8", errors="ignore"))
            if cap:
                firsts[cap[0]] += 1
        if not firsts:
            return
        trigger, _ = firsts.most_common(1)[0]
        cfg = cfgmod.load(lora)
        cfg.trigger = trigger
        cfgmod.upsert_lora(cfg)
        self.root.after(0, lambda: (
            self._log(f"auto-detected trigger for {lora}: '{trigger}'"),
            self._set_status(f"trigger = {trigger}"),
        ))


class DrivePickerDialog(tk.Toplevel):
    """Lazy-loading Drive folder browser. Returns selected {id, title, path}."""
    ROOT_ID = "root"

    def __init__(self, parent, on_pick) -> None:
        super().__init__(parent)
        self.title("Pick Drive folder")
        self.geometry("520x480")
        self.transient(parent)
        self.grab_set()
        self.on_pick = on_pick

        top = ttk.Frame(self, padding=8); top.pack(fill="both", expand=True)
        ttk.Label(top, text="Double-click to expand. Select the dataset folder, then Choose.",
                  foreground="#666").pack(anchor="w", pady=(0, 4))

        self.tree = ttk.Treeview(top, show="tree")
        yscroll = ttk.Scrollbar(top, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        # id -> drive folder id
        self.node_drive_id: dict[str, str] = {}
        # nodes already expanded
        self.loaded: set[str] = set()

        root_node = self.tree.insert("", "end", text="My Drive", open=False)
        self.node_drive_id[root_node] = self.ROOT_ID
        # placeholder child so expand arrow shows
        self.tree.insert(root_node, "end", text="loading…")

        self.tree.bind("<<TreeviewOpen>>", self._on_open)

        btns = ttk.Frame(self, padding=8); btns.pack(fill="x")
        self.status = tk.StringVar(value="")
        ttk.Label(btns, textvariable=self.status, foreground="#888").pack(side="left")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Choose", command=self._choose).pack(side="right")

    def _load_children(self, node: str) -> None:
        parent_id = self.node_drive_id[node]
        self.status.set("loading…")
        self.update_idletasks()
        try:
            children = drive_sync.list_folders(parent_id)
        except Exception as e:
            self.status.set("")
            messagebox.showerror("Drive error", str(e), parent=self)
            return
        # clear placeholder
        for c in self.tree.get_children(node):
            self.tree.delete(c)
        for f in children:
            child = self.tree.insert(node, "end", text=f["title"], open=False)
            self.node_drive_id[child] = f["id"]
            # placeholder to keep arrow visible; removed on next expand
            self.tree.insert(child, "end", text="loading…")
        self.loaded.add(node)
        self.status.set(f"{len(children)} subfolder(s)")

    def _on_open(self, _event) -> None:
        node = self.tree.focus()
        if node and node not in self.loaded:
            self._load_children(node)

    def _path_of(self, node: str) -> str:
        parts = []
        cur = node
        while cur:
            parts.append(self.tree.item(cur, "text"))
            cur = self.tree.parent(cur)
        return "/".join(reversed(parts))

    def _choose(self) -> None:
        node = self.tree.focus()
        if not node:
            messagebox.showwarning("Pick", "Select a folder first.", parent=self)
            return
        drive_id = self.node_drive_id[node]
        if drive_id == self.ROOT_ID:
            messagebox.showwarning("Pick", "Pick a subfolder, not My Drive root.", parent=self)
            return
        self.on_pick({
            "id": drive_id,
            "title": self.tree.item(node, "text"),
            "path": self._path_of(node),
        })
        self.destroy()


class AddLoraDialog(tk.Toplevel):
    def __init__(self, parent, on_saved) -> None:
        super().__init__(parent)
        self.title("Add LoRA")
        self.transient(parent)
        self.grab_set()
        self.on_saved = on_saved

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        self.vars = {
            "name": tk.StringVar(),
            "drive": tk.StringVar(),
            "trigger": tk.StringVar(),
            "base_model": tk.StringVar(value="waiIllustriousSDXL_v160"),
            "lora_file": tk.StringVar(),
            "weight": tk.DoubleVar(value=0.8),
        }
        self.drive_display = tk.StringVar(value="(none picked)")
        self.auto_sync = tk.BooleanVar(value=True)

        r = 0
        ttk.Label(frm, text="Name (key):").grid(row=r, column=0, sticky="e", padx=4, pady=3)
        ttk.Entry(frm, textvariable=self.vars["name"], width=40).grid(row=r, column=1, sticky="ew", pady=3)
        ttk.Label(frm, text="short key for this LoRA", foreground="#888").grid(row=r, column=2, sticky="w", padx=4)
        r += 1

        ttk.Label(frm, text="Drive folder:").grid(row=r, column=0, sticky="e", padx=4, pady=3)
        pick_row = ttk.Frame(frm); pick_row.grid(row=r, column=1, columnspan=2, sticky="ew", pady=3)
        ttk.Label(pick_row, textvariable=self.drive_display, foreground="#333",
                  wraplength=380, justify="left").pack(side="left", fill="x", expand=True)
        ttk.Button(pick_row, text="Pick from Drive…", command=self.on_pick_drive).pack(side="right", padx=(6, 0))
        r += 1

        ttk.Label(frm, text="Or paste URL/ID:").grid(row=r, column=0, sticky="e", padx=4, pady=3)
        ttk.Entry(frm, textvariable=self.vars["drive"], width=40).grid(row=r, column=1, sticky="ew", pady=3)
        r += 1

        ttk.Label(frm, text="Trigger tag:").grid(row=r, column=0, sticky="e", padx=4, pady=3)
        ttk.Entry(frm, textvariable=self.vars["trigger"], width=40).grid(row=r, column=1, sticky="ew", pady=3)
        ttk.Label(frm, text="auto-detected after sync if blank", foreground="#888").grid(row=r, column=2, sticky="w", padx=4)
        r += 1

        ttk.Label(frm, text="Base model:").grid(row=r, column=0, sticky="e", padx=4, pady=3)
        ttk.Entry(frm, textvariable=self.vars["base_model"], width=40).grid(row=r, column=1, sticky="ew", pady=3)
        r += 1

        ttk.Label(frm, text="LoRA filename:").grid(row=r, column=0, sticky="e", padx=4, pady=3)
        ttk.Entry(frm, textvariable=self.vars["lora_file"], width=40).grid(row=r, column=1, sticky="ew", pady=3)
        ttk.Label(frm, text="no .safetensors; default = name", foreground="#888").grid(row=r, column=2, sticky="w", padx=4)
        r += 1

        ttk.Label(frm, text="Weight:").grid(row=r, column=0, sticky="e", padx=4, pady=3)
        ttk.Spinbox(frm, from_=0.1, to=1.5, increment=0.05,
                    textvariable=self.vars["weight"], width=8).grid(row=r, column=1, sticky="w", pady=3)
        r += 1

        ttk.Checkbutton(frm, text="Sync from Drive immediately after save",
                        variable=self.auto_sync).grid(row=r, column=1, sticky="w", pady=(6, 0))
        r += 1

        btns = ttk.Frame(frm); btns.grid(row=r, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self.save).pack(side="right")

    def on_pick_drive(self) -> None:
        def picked(info):
            self.vars["drive"].set(info["id"])
            self.drive_display.set(f"{info['path']}\n(id: {info['id']})")
            if not self.vars["name"].get().strip():
                # suggest name from folder title (lowercase, spaces->underscore)
                suggested = info["title"].lower().replace(" ", "_")
                self.vars["name"].set(suggested)
        DrivePickerDialog(self, on_pick=picked)

    def save(self) -> None:
        name = self.vars["name"].get().strip()
        drive = self.vars["drive"].get().strip()
        if not (name and drive):
            messagebox.showwarning("Missing", "Name and Drive folder required.", parent=self)
            return
        cfg = cfgmod.LoraConfig(
            name=name,
            drive_folder=drive,
            trigger=self.vars["trigger"].get().strip() or name,
            base_model=self.vars["base_model"].get().strip(),
            lora_file=self.vars["lora_file"].get().strip() or name,
            lora_weight=float(self.vars["weight"].get()),
        )
        cfgmod.upsert_lora(cfg)
        do_sync = self.auto_sync.get()
        auto_trigger = not self.vars["trigger"].get().strip()
        self.on_saved(name, sync=do_sync, auto_trigger=auto_trigger)
        self.destroy()


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
