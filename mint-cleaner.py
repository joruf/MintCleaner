#!/usr/bin/env python3
"""
MintCleaner – selective temp and cache cleanup for Linux Mint.

Features:
- Single privileged helper via pkexec for root tasks, one authentication at startup.
- GUI becomes visible only AFTER authentication succeeded.
- Live size analysis per measurable category, labels show current MB.
- Auto select items above a configurable threshold in MB.
- Auto deselect items that are 0 MB or unknown size.
- User deletion mode selectable: Move to Trash (default) or Delete immediately.
  Note: Mode applies only to user scoped paths.
  Trash contents (~/.local/share/Trash/*) are always deleted when selected.

No popups before or after deletion, progress is logged in the UI.
"""

import os
import sys
import shlex
import glob
import json
import shutil
import getpass
import subprocess
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Tuple, List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import quote

# ----------------------------- Config -----------------------------

AUTOCHECK_THRESHOLD_MB = 100  # Auto select items larger than this many MB; set 0 to disable

# ----------------------------- Utilities (unprivileged) -----------------------------

def human_mb(n_bytes: int) -> str:
    """
    Convert bytes to a human friendly MB string with one decimal.
    """
    mb = n_bytes / (1024 * 1024)
    return f"{mb:.1f} MB"


def size_of_path(path: str) -> int:
    """
    Compute size in bytes of a file, directory or glob pattern.
    Ignores permission errors and broken symlinks.

    :param path: File, directory or glob pattern.
    :return: Total size in bytes.
    """
    path = os.path.expanduser(path)
    if os.path.exists(path) and not glob.has_magic(path):
        if os.path.isdir(path) and not os.path.islink(path):
            total = 0
            for root, _, files in os.walk(path, onerror=lambda e: None):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        if not os.path.islink(fp):
                            total += os.path.getsize(fp)
                    except Exception:
                        pass
            return total
        if os.path.isfile(path) and not os.path.islink(path):
            try:
                return os.path.getsize(path)
            except Exception:
                return 0
    total = 0
    for p in glob.glob(path, recursive=False):
        total += size_of_path(p)
    return total


def size_of_patterns(patterns: List[str]) -> int:
    """
    Compute the combined size in bytes for a list of patterns.

    :param patterns: List of file or directory patterns.
    :return: Total size in bytes.
    """
    total = 0
    for pat in patterns:
        try:
            total += size_of_path(pat)
        except Exception:
            pass
    return total


def exists_in_path(binary: str) -> bool:
    """
    Return True if a binary exists in PATH.

    :param binary: Command name to search.
    :return: True if found, else False.
    """
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, binary)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return True
    return False


def log_append(widget: tk.Text, text: str) -> None:
    """
    Append text to the log Text widget.
    """
    widget.insert("end", text if text.endswith("\n") else text + "\n")
    widget.see("end")
    widget.update_idletasks()


def _unique_dest(base_dir: str, name: str) -> str:
    """
    Return a unique destination path inside base_dir for given name.
    Adds numeric suffix if file exists already.
    """
    dest = os.path.join(base_dir, name)
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(name)
    i = 1
    while True:
        cand = os.path.join(base_dir, f"{stem}-{i}{ext}")
        if not os.path.exists(cand):
            return cand
        i += 1


def _write_trashinfo(info_dir: str, original_path: str, trashed_name: str) -> None:
    """
    Write a .trashinfo file according to the Freedesktop Trash spec.
    """
    encoded = quote(os.path.abspath(original_path), safe="/")
    deletion_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    info_path = os.path.join(info_dir, f"{trashed_name}.trashinfo")
    content = "[Trash Info]\n" \
              f"Path={encoded}\n" \
              f"DeletionDate={deletion_date}\n"
    with open(info_path, "w", encoding="utf-8") as fh:
        fh.write(content)


def trash_paths(patterns: List[str]) -> Tuple[int, str]:
    """
    Move user space files and directories to the user's Trash with correct metadata.
    Prefer gio if available, else compliant fallback that writes .trashinfo files.

    :param patterns: Patterns to move to trash.
    :return: (num_trashed, log_text)
    """
    logs: List[str] = []
    moved = 0
    use_gio = exists_in_path("gio")
    trash_dir = os.path.expanduser("~/.local/share/Trash/files")
    info_dir = os.path.expanduser("~/.local/share/Trash/info")

    os.makedirs(trash_dir, exist_ok=True)
    os.makedirs(info_dir, exist_ok=True)

    for pattern in patterns:
        for p in glob.glob(os.path.expanduser(pattern), recursive=False):
            if os.path.abspath(p).startswith(os.path.abspath(os.path.expanduser("~/.local/share/Trash/"))):
                continue
            try:
                if use_gio:
                    proc = subprocess.run(["gio", "trash", p], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    if proc.returncode == 0:
                        logs.append(f"Trashed: {p}")
                        moved += 1
                    else:
                        logs.append(f"Failed to trash with gio: {p}, {proc.stdout.strip()}")
                else:
                    name = os.path.basename(p.rstrip(os.sep))
                    dest = _unique_dest(trash_dir, name)
                    shutil.move(p, dest)
                    _write_trashinfo(info_dir, p, os.path.basename(dest))
                    logs.append(f"Moved to Trash: {p} -> {dest}")
                    moved += 1
            except Exception as e:
                logs.append(f"Failed to move to Trash: {p}: {e}")
    return moved, "\n".join(logs)


def rm_paths(patterns: List[str]) -> Tuple[int, str]:
    """
    Remove user space files and directories using Python, skipping non existing paths.

    :param patterns: List of file or directory patterns.
    :return: (num_removed, log_text)
    """
    removed = 0
    logs = []
    for pattern in patterns:
        for p in glob.glob(os.path.expanduser(pattern), recursive=False):
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p, ignore_errors=True)
                    logs.append(f"Removed directory: {p}")
                    removed += 1
                elif os.path.isfile(p) or os.path.islink(p):
                    os.remove(p)
                    logs.append(f"Removed file: {p}")
                    removed += 1
            except Exception as e:
                logs.append(f"Failed to remove {p}: {e}")
    return removed, "\n".join(logs)

# ----------------------------- Single privileged helper via pkexec -----------------------------

class RootHelper:
    """
    Manage a single pkexec launched helper process that executes privileged actions.
    The helper implements a small RPC over JSON lines on stdin and stdout.
    """

    def __init__(self) -> None:
        """
        Initialize without starting the helper.
        """
        self.proc: Optional[subprocess.Popen[str]] = None

    def start(self, log: Optional[tk.Text] = None) -> bool:
        """
        Start the helper via pkexec once at app launch, return True if started.

        :param log: Optional Tk text widget to log status.
        :return: True if helper started and responded to ping, else False.
        """
        helper_cmd = [
            "pkexec",
            sys.executable,
            "-u",
            os.path.abspath(__file__),
            "--helper",
        ]
        try:
            self.proc = subprocess.Popen(
                helper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            ok = self._rpc({"action": "ping"}) is True
            if ok and log:
                log_append(log, "[OK] Privileged helper ready, authentication done.")
            return bool(ok)
        except Exception as e:
            if log:
                log_append(log, f"[ERR] Failed to start helper: {e}")
            return False

    def _rpc(self, payload: Dict[str, Any]) -> Any:
        """
        Send a single JSON request and return the 'data' or True or False.

        :param payload: Request dictionary with 'action' and optional 'args'.
        :return: Response data on success.
        :raises RuntimeError: On transport or helper error.
        """
        if not self.proc or not self.proc.stdin or not self.proc.stdout:
            raise RuntimeError("helper not running")
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("no response from helper")
        resp = json.loads(line)
        if resp.get("status") == "ok":
            return resp.get("data", True)
        raise RuntimeError(resp.get("error", "helper error"))

    def rm_rf_patterns(self, patterns: List[str]) -> Tuple[int, str]:
        """
        Recursively remove a list of root patterns, return rc and combined output.

        :param patterns: Patterns to remove as root.
        :return: (rc, combined_output)
        """
        try:
            return self._rpc({"action": "rm_rf_patterns", "args": {"patterns": patterns}})
        except Exception as e:
            return (1, str(e))

    def run_root_cmds(self, cmds: List[str]) -> List[Tuple[str, int, str]]:
        """
        Run a list of shell commands as root.

        :param cmds: List of shell commands to run.
        :return: List of tuples (cmd, rc, output).
        """
        try:
            return self._rpc({"action": "run_root_cmds", "args": {"cmds": cmds}})
        except Exception as e:
            return [(f"ERROR:{e}", 1, str(e))]


HELPER = RootHelper()

# ----------------------------- GUI application -----------------------------

class MintCleanerApp(tk.Tk):
    """
    Tkinter GUI for selective cleanup with dynamic size analysis and a single pkexec helper.
    """

    def __init__(self, start_helper: bool = False):
        """
        Initialize the MintCleaner application, build UI.
        The helper is expected to be started BEFORE the window is created.
        """
        super().__init__()
        self.title("Mint Cleaner, Selective Temp and Cache Cleanup")
        self.geometry("900x820")
        self.minsize(900, 820)

        self.username = getpass.getuser()

        # Deletion mode for user scoped actions
        self.delete_mode_var = tk.StringVar(value="trash")  # "trash" or "delete"

        # Checkboxes state
        self.var_tmp = tk.BooleanVar(value=False)                 # /tmp and /var/tmp
        self.var_user_cache = tk.BooleanVar(value=True)           # ~/.cache/*
        self.var_thumbnails = tk.BooleanVar(value=True)           # ~/.thumbnails/*
        self.var_trash = tk.BooleanVar(value=True)                # ~/.local/share/Trash/*
        self.var_firefox = tk.BooleanVar(value=False)             # Firefox caches
        self.var_chrome = tk.BooleanVar(value=False)              # Chrome or Chromium caches
        self.var_flatpak_user = tk.BooleanVar(value=False)        # flatpak uninstall --unused (user)
        self.var_flatpak_repair_user = tk.BooleanVar(value=False) # flatpak repair --user
        self.var_flatpak_syscache = tk.BooleanVar(value=False)    # /var/tmp/flatpak-cache/*
        self.var_flatpak_repair_system = tk.BooleanVar(value=False) # flatpak repair --system
        self.var_apt = tk.BooleanVar(value=False)                 # apt clean/autoclean/autoremove
        self.var_journal = tk.BooleanVar(value=False)             # journalctl vacuum

        self.journal_retention = tk.StringVar(value="3d")
        self.var_select_all = tk.BooleanVar(value=False)

        # Patterns for size analysis
        self.patterns: Dict[str, List[str]] = {
            "tmp": ["/tmp/*", "/var/tmp/*"],
            "user_cache": ["~/.cache/*"],
            "thumbnails": ["~/.thumbnails/*"],
            "trash": ["~/.local/share/Trash/*"],
            "firefox": [
                "~/.mozilla/firefox/*.default*/cache2/*",
                "~/.cache/mozilla/firefox/*.default*/cache2/*",
            ],
            "chrome": [
                "~/.config/google-chrome/Default/Cache/*",
                "~/.cache/google-chrome/Default/Cache/*",
                "~/.config/chromium/Default/Cache/*",
                "~/.cache/chromium/Default/Cache/*",
            ],
            "flatpak_syscache": ["/var/tmp/flatpak-cache/*"],
            "apt": ["/var/cache/apt/archives/*", "/var/cache/apt/archives/partial/*"],
            "journal": ["/var/log/journal/*", "/run/log/journal/*"],
        }

        # Bookkeeping
        self.sizes_before: Dict[str, int] = {}
        self.widgets: Dict[str, ttk.Checkbutton] = {}
        self.base_text: Dict[str, str] = {}

        self._build_ui()

        # Log that helper is ready and authenticated (already done by main())
        log_append(self.log, "[OK] Privileged helper ready, authentication done at startup.")
        self.refresh_sizes()

    def _build_ui(self) -> None:
        """
        Build the complete UI layout.
        """
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Mint Cleaner, choose what to clear", font=("Sans", 16, "bold")).pack(anchor="w", pady=(0, 10))

        # Top controls
        top_controls = ttk.Frame(frm)
        top_controls.pack(fill=tk.X, pady=(0, 6))

        ttk.Checkbutton(top_controls, text="Select all", variable=self.var_select_all, command=self.on_select_all_toggle)\
            .pack(side=tk.LEFT)

        # Deletion mode selectbox for user actions
        mode_frame = ttk.Frame(top_controls)
        mode_frame.pack(side=tk.RIGHT)
        ttk.Label(mode_frame, text="On user items:").pack(side=tk.LEFT, padx=(0, 6))
        mode_combo = ttk.Combobox(mode_frame, state="readonly",
                                  values=["Move to Trash", "Delete immediately"],
                                  width=20)
        mode_combo.pack(side=tk.LEFT)
        mode_combo.set("Move to Trash")

        def on_mode_change(event=None):
            """
            Update internal mode state when user selects from combobox.
            """
            val = mode_combo.get()
            self.delete_mode_var.set("trash" if val == "Move to Trash" else "delete")
        mode_combo.bind("<<ComboboxSelected>>", on_mode_change)

        ttk.Separator(frm).pack(fill=tk.X, pady=8)

        ttk.Label(frm, text="System tasks, require root", font=("Sans", 12, "bold")).pack(anchor="w")
        sys_frame = ttk.Frame(frm)
        sys_frame.pack(fill=tk.X, padx=(12, 0))

        self.widgets["tmp"] = ttk.Checkbutton(sys_frame, text="/tmp and /var/tmp", variable=self.var_tmp)
        self.widgets["tmp"].grid(row=0, column=0, sticky="w", pady=2)
        self.base_text["tmp"] = "/tmp and /var/tmp"

        self.widgets["apt"] = ttk.Checkbutton(sys_frame, text="Apt cleanup, clean autoclean autoremove", variable=self.var_apt)
        self.widgets["apt"].grid(row=1, column=0, sticky="w", pady=2)
        self.base_text["apt"] = "Apt cleanup, clean autoclean autoremove"

        self.widgets["flatpak_syscache"] = ttk.Checkbutton(sys_frame, text="System Flatpak cache", variable=self.var_flatpak_syscache)
        self.widgets["flatpak_syscache"].grid(row=2, column=0, sticky="w", pady=2)
        self.base_text["flatpak_syscache"] = "System Flatpak cache"

        self.widgets["flatpak_repair_system"] = ttk.Checkbutton(sys_frame, text="Flatpak repair system [size unknown]", variable=self.var_flatpak_repair_system)
        self.widgets["flatpak_repair_system"].grid(row=3, column=0, sticky="w", pady=2)
        self.base_text["flatpak_repair_system"] = "Flatpak repair system [size unknown]"

        jfrm = ttk.Frame(sys_frame)
        jfrm.grid(row=4, column=0, sticky="w", pady=2)
        self.widgets["journal"] = ttk.Checkbutton(jfrm, text="Systemd journal vacuum", variable=self.var_journal)
        self.widgets["journal"].pack(side=tk.LEFT)
        self.base_text["journal"] = "Systemd journal vacuum"
        ttk.Label(jfrm, text=" Retain:").pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(jfrm, width=8, textvariable=self.journal_retention).pack(side=tk.LEFT)
        ttk.Label(jfrm, text="examples 3d, 7d, 100M").pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(frm).pack(fill=tk.X, pady=8)

        ttk.Label(frm, text=f"User caches, running as {self.username}", font=("Sans", 12, "bold")).pack(anchor="w")
        user_frame = ttk.Frame(frm)
        user_frame.pack(fill=tk.X, padx=(12, 0))

        self.widgets["user_cache"] = ttk.Checkbutton(user_frame, text="~/.cache/*", variable=self.var_user_cache)
        self.widgets["user_cache"].grid(row=0, column=0, sticky="w", pady=2)
        self.base_text["user_cache"] = "~/.cache/*"

        self.widgets["thumbnails"] = ttk.Checkbutton(user_frame, text="~/.thumbnails/*", variable=self.var_thumbnails)
        self.widgets["thumbnails"].grid(row=1, column=0, sticky="w", pady=2)
        self.base_text["thumbnails"] = "~/.thumbnails/*"

        self.widgets["trash"] = ttk.Checkbutton(user_frame, text="~/.local/share/Trash/*", variable=self.var_trash)
        self.widgets["trash"].grid(row=2, column=0, sticky="w", pady=2)
        self.base_text["trash"] = "~/.local/share/Trash/*"

        self.widgets["firefox"] = ttk.Checkbutton(user_frame, text="Firefox cache, all profiles", variable=self.var_firefox)
        self.widgets["firefox"].grid(row=3, column=0, sticky="w", pady=2)
        self.base_text["firefox"] = "Firefox cache, all profiles"

        self.widgets["chrome"] = ttk.Checkbutton(user_frame, text="Chrome or Chromium cache, Default profile", variable=self.var_chrome)
        self.widgets["chrome"].grid(row=4, column=0, sticky="w", pady=2)
        self.base_text["chrome"] = "Chrome or Chromium cache, Default profile"

        self.widgets["flatpak_user_unused"] = ttk.Checkbutton(user_frame, text="Flatpak user uninstall unused [size unknown]", variable=self.var_flatpak_user)
        self.widgets["flatpak_user_unused"].grid(row=5, column=0, sticky="w", pady=2)
        self.base_text["flatpak_user_unused"] = "Flatpak user uninstall unused [size unknown]"

        self.widgets["flatpak_repair_user"] = ttk.Checkbutton(user_frame, text="Flatpak repair user [size unknown]", variable=self.var_flatpak_repair_user)
        self.widgets["flatpak_repair_user"].grid(row=6, column=0, sticky="w", pady=2)
        self.base_text["flatpak_repair_user"] = "Flatpak repair user [size unknown]"

        ttk.Separator(frm).pack(fill=tk.X, pady=8)

        # Bottom buttons row
        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X)

        # Left side: Clean selected as a green tk.Button
        clean_btn = tk.Button(btns, text="Clean selected",
                              command=self.on_clean_clicked,
                              bg="#3cb371", activebackground="#2e8b57",
                              fg="black", activeforeground="black")
        clean_btn.pack(side=tk.LEFT)

        # Right side: a container for Preview and Refresh
        right_box = ttk.Frame(btns)
        right_box.pack(side=tk.RIGHT)

        refresh_btn = ttk.Button(right_box, text="Refresh sizes", command=self.refresh_sizes)
        refresh_btn.pack(side=tk.LEFT)

        preview_btn = ttk.Button(right_box, text="Preview commands", command=self.on_preview)
        preview_btn.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(frm, text="Log output").pack(anchor="w", pady=(8, 0))
        self.log = ScrolledText(frm, height=16, wrap=tk.WORD, font=("Monospace", 10))
        self.log.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        log_append(self.log, "Ready.")

    def on_select_all_toggle(self) -> None:
        """
        Toggle all checkboxes according to the select all state.
        """
        state = self.var_select_all.get()
        self.var_tmp.set(state)
        self.var_user_cache.set(state)
        self.var_thumbnails.set(state)
        self.var_trash.set(state)
        self.var_firefox.set(state)
        self.var_chrome.set(state)
        self.var_flatpak_user.set(state)
        self.var_flatpak_repair_user.set(state)
        self.var_flatpak_syscache.set(state)
        self.var_flatpak_repair_system.set(state)
        self.var_apt.set(state)
        self.var_journal.set(state)

    def _apply_autoselect_by_threshold(self, sizes_now: Dict[str, int]) -> None:
        """
        Auto select checkboxes whose measurable size exceeds AUTOCHECK_THRESHOLD_MB.
        Non measurable items are ignored.
        """
        if AUTOCHECK_THRESHOLD_MB <= 0:
            return
        threshold_bytes = int(AUTOCHECK_THRESHOLD_MB * 1024 * 1024)

        key_to_var = {
            "tmp": self.var_tmp,
            "user_cache": self.var_user_cache,
            "thumbnails": self.var_thumbnails,
            "trash": self.var_trash,
            "firefox": self.var_firefox,
            "chrome": self.var_chrome,
            "flatpak_syscache": self.var_flatpak_syscache,
            "apt": self.var_apt,
            "journal": self.var_journal,
        }

        for key, size in sizes_now.items():
            var = key_to_var.get(key)
            if var is not None and size >= threshold_bytes:
                var.set(True)

    def _apply_autodeselect_zero_or_unknown(self, sizes_now: Dict[str, int]) -> None:
        """
        Auto deselect all items that have size 0 or size unknown.
        Unknown size equals non measurable category or not present in sizes_now.
        """
        key_to_var_measurable = {
            "tmp": self.var_tmp,
            "user_cache": self.var_user_cache,
            "thumbnails": self.var_thumbnails,
            "trash": self.var_trash,
            "firefox": self.var_firefox,
            "chrome": self.var_chrome,
            "flatpak_syscache": self.var_flatpak_syscache,
            "apt": self.var_apt,
            "journal": self.var_journal,
        }
        for key, var in key_to_var_measurable.items():
            size = sizes_now.get(key, None)
            if size is None or size == 0:
                var.set(False)

        # Non measurable entries are always deselected
        self.var_flatpak_user.set(False)
        self.var_flatpak_repair_user.set(False)
        self.var_flatpak_repair_system.set(False)

    # ----------------------------- Size analysis -----------------------------

    def refresh_sizes(self) -> None:
        """
        Recalculate sizes for all measurable categories, auto select those exceeding
        the configured threshold, auto deselect 0 MB or unknown, and update labels.
        """
        measurable = [
            "tmp", "user_cache", "thumbnails", "trash",
            "firefox", "chrome", "flatpak_syscache", "apt", "journal"
        ]
        sizes_now: Dict[str, int] = {}
        for key in measurable:
            patterns = self.patterns.get(key, [])
            sizes_now[key] = size_of_patterns(patterns)

        # Auto select by threshold
        self._apply_autoselect_by_threshold(sizes_now)

        # Auto deselect 0 MB or unknown
        self._apply_autodeselect_zero_or_unknown(sizes_now)

        # Update checkbox texts
        for key, size in sizes_now.items():
            if key in self.widgets and key in self.base_text:
                try:
                    self.widgets[key].configure(text=f"{self.base_text[key]}  [{human_mb(size)}]")
                except tk.TclError:
                    pass

        # Keep non measurable labels as is
        for key in ["flatpak_user_unused", "flatpak_repair_user", "flatpak_repair_system"]:
            if key in self.widgets and key in self.base_text:
                try:
                    self.widgets[key].configure(text=self.base_text[key])
                except tk.TclError:
                    pass

        self.sizes_before = sizes_now
        log_append(self.log, "Sizes refreshed.")

    # ----------------------------- Plan and execution -----------------------------

    def build_plan(self) -> dict:
        """
        Build a plan from selected checkboxes for user deletions, user commands and root actions.

        :return: Dict with user_python_deletes, user_cmds, root_rm_patterns and root_cmds.
        """
        plan = {"user_py_delete": [], "user_cmds": [], "root_rm_patterns": [], "root_cmds": []}

        # User deletions
        if self.var_user_cache.get():
            plan["user_py_delete"].append("~/.cache/*")
        if self.var_thumbnails.get():
            plan["user_py_delete"].append("~/.thumbnails/*")
        if self.var_trash.get():
            plan["user_py_delete"].append("~/.local/share/Trash/*")
        if self.var_firefox.get():
            plan["user_py_delete"] += [
                "~/.mozilla/firefox/*.default*/cache2/*",
                "~/.cache/mozilla/firefox/*.default*/cache2/*",
            ]
        if self.var_chrome.get():
            plan["user_py_delete"] += [
                "~/.config/google-chrome/Default/Cache/*",
                "~/.cache/google-chrome/Default/Cache/*",
                "~/.config/chromium/Default/Cache/*",
                "~/.cache/chromium/Default/Cache/*",
            ]

        # User commands
        if self.var_flatpak_user.get():
            if exists_in_path("flatpak"):
                plan["user_cmds"].append("flatpak uninstall --unused -y")
            else:
                log_append(self.log, "Note: flatpak not found, skipping user flatpak uninstall.")
        if self.var_flatpak_repair_user.get():
            if exists_in_path("flatpak"):
                plan["user_cmds"].append("flatpak repair --user -y")
            else:
                log_append(self.log, "Note: flatpak not found, skipping user flatpak repair.")

        # Root deletions as patterns handled by helper
        if self.var_tmp.get():
            plan["root_rm_patterns"] += ["/tmp/*", "/var/tmp/*"]
        if self.var_flatpak_syscache.get():
            plan["root_rm_patterns"] += ["/var/tmp/flatpak-cache/*"]

        # Root commands
        if self.var_flatpak_repair_system.get():
            plan["root_cmds"].append("flatpak repair --system -y")
        if self.var_apt.get():
            plan["root_cmds"] += ["apt clean", "apt autoclean", "apt autoremove -y"]
        if self.var_journal.get():
            retention = self.journal_retention.get().strip() or "3d"
            plan["root_cmds"].append(f"journalctl --vacuum-time={shlex.quote(retention)}")

        return plan

    def on_preview(self) -> None:
        """
        Show a preview of planned actions.
        """
        plan = self.build_plan()
        mode_txt = "Move to Trash" if self.delete_mode_var.get() == "trash" else "Delete immediately"
        log_append(self.log, f"---- Preview ----\nUser deletion mode: {mode_txt}")
        if plan["user_py_delete"]:
            log_append(self.log, "User deletions, paths:")
            for p in plan["user_py_delete"]:
                log_append(self.log, f"  - {p}")
        if plan["user_cmds"]:
            log_append(self.log, "User commands:")
            for c in plan["user_cmds"]:
                log_append(self.log, f"  - {c}")
        if plan["root_rm_patterns"]:
            log_append(self.log, "Root deletions, patterns:")
            for p in plan["root_rm_patterns"]:
                log_append(self.log, f"  - {p}")
        if plan["root_cmds"]:
            log_append(self.log, "Root commands:")
            for c in plan["root_cmds"]:
                log_append(self.log, f"  - {c}")
        log_append(self.log, "-----------------")

    def on_clean_clicked(self) -> None:
        """
        Execute selected actions using user code and the single helper, then remeasure and log reclaimed sizes.
        No confirmation popup, progress only in log.
        """
        selected_keys = []
        if self.var_tmp.get(): selected_keys.append("tmp")
        if self.var_user_cache.get(): selected_keys.append("user_cache")
        if self.var_thumbnails.get(): selected_keys.append("thumbnails")
        if self.var_trash.get(): selected_keys.append("trash")
        if self.var_firefox.get(): selected_keys.append("firefox")
        if self.var_chrome.get(): selected_keys.append("chrome")
        if self.var_flatpak_syscache.get(): selected_keys.append("flatpak_syscache")
        if self.var_apt.get(): selected_keys.append("apt")
        if self.var_journal.get(): selected_keys.append("journal")

        sizes_before_local = {k: size_of_patterns(self.patterns.get(k, [])) for k in selected_keys}

        plan = self.build_plan()
        if not (plan["user_py_delete"] or plan["user_cmds"] or plan["root_rm_patterns"] or plan["root_cmds"]):
            log_append(self.log, "[INFO] Nothing selected.")
            return

        log_append(self.log, "=== Cleanup started ===")

        to_trash: List[str] = []
        to_delete_user: List[str] = []
        trash_root = os.path.abspath(os.path.expanduser("~/.local/share/Trash/"))

        for pat in plan["user_py_delete"]:
            expanded = os.path.expanduser(pat)
            if os.path.abspath(expanded).startswith(trash_root):
                to_delete_user.append(pat)
            else:
                if self.delete_mode_var.get() == "trash":
                    to_trash.append(pat)
                else:
                    to_delete_user.append(pat)

        if to_trash:
            log_append(self.log, "[User] Moving selected paths to Trash ...")
            moved, logtxt = trash_paths(to_trash)
            if logtxt.strip():
                log_append(self.log, logtxt)
            log_append(self.log, f"[User] Trashed entries: {moved}")
        if to_delete_user:
            log_append(self.log, "[User] Deleting selected paths ...")
            removed, logtxt = rm_paths(to_delete_user)
            if logtxt.strip():
                log_append(self.log, logtxt)
            log_append(self.log, f"[User] Removed entries: {removed}")

        for cmd in plan["user_cmds"]:
            log_append(self.log, f"[User] Running: {cmd}")
            p = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if p.stdout.strip():
                log_append(self.log, p.stdout.strip())
            log_append(self.log, f"[User] Exit code: {p.returncode}")

        if plan["root_rm_patterns"]:
            log_append(self.log, "[Root] Deleting patterns with helper ...")
            rc, out = HELPER.rm_rf_patterns(plan["root_rm_patterns"])
            if out:
                log_append(self.log, out.strip())
            log_append(self.log, f"[Root] rm_rf exit code: {rc}")

        if plan["root_cmds"]:
            results = HELPER.run_root_cmds(plan["root_cmds"])
            for cmd, rc, out in results:
                log_append(self.log, f"[Root] Running: {cmd}")
                if out.strip():
                    log_append(self.log, out.strip())
                log_append(self.log, f"[Root] Exit code: {rc}")

        log_append(self.log, "Recalculating sizes after cleanup ...")
        reclaimed_total = 0
        for key in selected_keys:
            after = size_of_patterns(self.patterns.get(key, []))
            before = sizes_before_local.get(key, 0)
            reclaimed = max(0, before - after)
            reclaimed_total += reclaimed
            log_append(self.log, f"[{key}] before {human_mb(before)}, after {human_mb(after)}, reclaimed {human_mb(reclaimed)}")

        log_append(self.log, f"Total reclaimed: {human_mb(reclaimed_total)}")
        log_append(self.log, "=== Cleanup finished ===")

# ----------------------------- Helper entrypoint (runs as root) -----------------------------

def helper_main() -> None:
    """
    Run the privileged JSON line helper handling a minimal set of safe actions:
    - ping
    - rm_rf_patterns
    - run_root_cmds
    """
    def send_ok(data: Any = True) -> None:
        print(json.dumps({"status": "ok", "data": data}), flush=True)

    def send_err(msg: str) -> None:
        print(json.dumps({"status": "err", "error": msg}), flush=True)

    def _expand_patterns(patterns: List[str]) -> List[str]:
        out: List[str] = []
        for pat in patterns:
            for p in glob.glob(pat, recursive=False):
                out.append(p)
        return out

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
            action = req.get("action")
            args = req.get("args") or {}

            if action == "ping":
                send_ok(True)

            elif action == "rm_rf_patterns":
                pats: List[str] = args.get("patterns") or []
                expanded = _expand_patterns(pats)
                log_lines: List[str] = []
                rc_global = 0
                for p in expanded:
                    try:
                        if os.path.isdir(p) and not os.path.islink(p):
                            shutil.rmtree(p, ignore_errors=True)
                            log_lines.append(f"Removed directory: {p}")
                        elif os.path.isfile(p) or os.path.islink(p):
                            os.remove(p)
                            log_lines.append(f"Removed file: {p}")
                    except Exception as e:
                        rc_global = 1
                        log_lines.append(f"Failed to remove {p}: {e}")
                send_ok((rc_global, "\n".join(log_lines)))

            elif action == "run_root_cmds":
                cmds: List[str] = args.get("cmds") or []
                results: List[Tuple[str, int, str]] = []
                for cmd in cmds:
                    p = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    results.append((cmd, p.returncode, p.stdout or ""))
                send_ok(results)

            else:
                send_err("unknown action")

        except Exception as e:
            send_err(str(e))

# ----------------------------- Main -----------------------------

def main() -> None:
    """
    Application entry point:
    1) Start privileged helper via pkexec BEFORE showing any window.
    2) If authentication fails, exit with error, no GUI shown.
    3) If ok, create and show the Tk GUI.
    """
    ok = False
    try:
        ok = HELPER.start(None)
    except Exception:
        ok = False

    if not ok:
        sys.stderr.write("Authentication failed, could not start privileged helper. Exiting.\n")
        sys.exit(1)

    # Only now create and show the GUI
    app = MintCleanerApp(start_helper=False)
    app.mainloop()


if __name__ == "__main__":
    if "--helper" in sys.argv:
        helper_main()
    else:
        main()
