#!/usr/bin/env python3
"""
MintCleaner – selective temp and cache cleanup for Linux Mint.

Features:
- Single privileged helper via pkexec for root tasks, one authentication at startup.
- GUI becomes visible only AFTER authentication succeeded.
- Live size analysis per measurable category, labels show current MB.
- Auto select items above a configured threshold in MB.
- Auto deselect items that are 0 MB or unknown size.
- User deletion mode selectable: Move to Trash (default) or Delete immediately.
  Note: Mode applies only to user scoped paths.
  Trash contents (~/.local/share/Trash/*) are always deleted when selected.
- New options: Flatpak app cache, APT package cache (with size), old kernel removal.

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
from typing import Tuple, List, Dict, Any, Optional

if __name__ == "__main__" and "--helper" not in sys.argv:
    from dependencies import ensure_runtime_dependencies

    ensure_runtime_dependencies()

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from desktop_setup import maybe_prompt_desktop_setup
from nemo_setup import maybe_prompt_nemo_setup
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

    def get_size_of_patterns(self, patterns: List[str]) -> int:
        """
        Get total size (bytes) of root‑owned patterns using the helper.

        :param patterns: List of glob patterns (root accessible).
        :return: Total size in bytes, or 0 on error.
        """
        try:
            return self._rpc({"action": "get_size", "args": {"patterns": patterns}})
        except Exception:
            return 0


HELPER = RootHelper()

# ----------------------------- GUI application -----------------------------

class MintCleanerApp(tk.Tk):
    """
    Tkinter GUI for selective cleanup with dynamic size analysis and a single pkexec helper.
    Modern UI with improved layout and styling.
    """

    def __init__(self, start_helper: bool = False):
        """
        Initialize the MintCleaner application, build UI.
        The helper is expected to be started BEFORE the window is created.
        """
        super().__init__()
        self.title("Mint Cleaner, Selective Temp and Cache Cleanup")
        self.geometry("950x920")
        self.minsize(900, 850)

        # Configure modern style
        self._setup_styles()

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
        # New options
        self.var_flatpak_app_cache = tk.BooleanVar(value=False)   # ~/.var/app/*/cache/*
        self.var_apt_cache = tk.BooleanVar(value=False)           # /var/cache/apt/archives/*
        self.var_old_kernels = tk.BooleanVar(value=False)         # apt autoremove --purge

        self.journal_retention = tk.StringVar(value="3d")
        self.var_select_all = tk.BooleanVar(value=False)

        # Patterns for size analysis (user measurable only)
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
            "flatpak_app_cache": ["~/.var/app/*/cache/*"],
        }

        # Bookkeeping
        self.sizes_before: Dict[str, int] = {}
        self.widgets: Dict[str, ttk.Checkbutton] = {}
        self.base_text: Dict[str, str] = {}

        self._build_ui()

        # Log that helper is ready and authenticated (already done by main())
        log_append(self.log, "[OK] Privileged helper ready, authentication done at startup.")
        self.refresh_sizes()

    def _setup_styles(self) -> None:
        """
        Configure ttk styles for a modern, clean look.
        """
        style = ttk.Style()
        # Try to use 'clam' theme for a more modern appearance (available on most Linux)
        available_themes = style.theme_names()
        if 'clam' in available_themes:
            style.theme_use('clam')
        elif 'vista' in available_themes:
            style.theme_use('vista')
        elif 'alt' in available_themes:
            style.theme_use('alt')
        
        # Configure colors and fonts
        style.configure('TLabel', font=('Segoe UI', 10))
        style.configure('TLabelframe', font=('Segoe UI', 10, 'bold'))
        style.configure('TLabelframe.Label', font=('Segoe UI', 10, 'bold'))
        style.configure('TButton', font=('Segoe UI', 9))
        style.configure('TCheckbutton', font=('Segoe UI', 9))
        style.configure('TEntry', font=('Segoe UI', 9))
        
        # Custom style for the main header
        style.configure('Header.TLabel', font=('Segoe UI', 16, 'bold'))

    def _build_ui(self) -> None:
        """
        Build the complete UI layout with modern structure and new options.
        """
        # Main container with padding
        main_container = ttk.Frame(self, padding=15)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Label(main_container, text="🧹 Mint Cleaner", style='Header.TLabel')
        header.pack(anchor="w", pady=(0, 5))
        subtitle = ttk.Label(main_container, text="Selective cleanup of temporary files and caches")
        subtitle.pack(anchor="w", pady=(0, 15))

        # Top controls row: Select all and deletion mode
        top_frame = ttk.Frame(main_container)
        top_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Checkbutton(top_frame, text="✓ Select all", variable=self.var_select_all, 
                       command=self.on_select_all_toggle).pack(side=tk.LEFT)
        
        # Deletion mode with clear label
        mode_frame = ttk.Frame(top_frame)
        mode_frame.pack(side=tk.RIGHT)
        ttk.Label(mode_frame, text="User deletion mode:").pack(side=tk.LEFT, padx=(0, 6))
        mode_combo = ttk.Combobox(mode_frame, state="readonly",
                                 values=["Move to Trash", "Delete immediately"],
                                 width=18)
        mode_combo.pack(side=tk.LEFT)
        mode_combo.set("Move to Trash")
        
        def on_mode_change(event=None):
            val = mode_combo.get()
            self.delete_mode_var.set("trash" if val == "Move to Trash" else "delete")
        mode_combo.bind("<<ComboboxSelected>>", on_mode_change)

        # Separator
        ttk.Separator(main_container, orient='horizontal').pack(fill=tk.X, pady=8)

        # System tasks group (using LabelFrame)
        sys_frame = ttk.LabelFrame(main_container, text="⚙️ System Tasks (require root privileges)", padding=10)
        sys_frame.pack(fill=tk.X, pady=(0, 15))

        # Use grid for system tasks
        row = 0
        self.widgets["tmp"] = ttk.Checkbutton(sys_frame, text="/tmp and /var/tmp", variable=self.var_tmp)
        self.widgets["tmp"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["tmp"] = "/tmp and /var/tmp"
        row += 1

        self.widgets["apt"] = ttk.Checkbutton(sys_frame, text="APT cleanup (clean, autoclean, autoremove)", variable=self.var_apt)
        self.widgets["apt"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["apt"] = "APT cleanup (clean, autoclean, autoremove)"
        row += 1

        # APT package cache (now with size calculation via root helper)
        self.widgets["apt_cache"] = ttk.Checkbutton(sys_frame, text="APT package cache (/var/cache/apt/archives)", variable=self.var_apt_cache)
        self.widgets["apt_cache"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["apt_cache"] = "APT package cache (/var/cache/apt/archives)"
        row += 1

        # Remove old kernels
        self.widgets["old_kernels"] = ttk.Checkbutton(sys_frame, text="Remove old kernels (apt autoremove --purge) [size unknown]", variable=self.var_old_kernels)
        self.widgets["old_kernels"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["old_kernels"] = "Remove old kernels (apt autoremove --purge) [size unknown]"
        row += 1

        self.widgets["flatpak_syscache"] = ttk.Checkbutton(sys_frame, text="System Flatpak cache", variable=self.var_flatpak_syscache)
        self.widgets["flatpak_syscache"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["flatpak_syscache"] = "System Flatpak cache"
        row += 1

        self.widgets["flatpak_repair_system"] = ttk.Checkbutton(sys_frame, text="Flatpak repair system [size unknown]", variable=self.var_flatpak_repair_system)
        self.widgets["flatpak_repair_system"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["flatpak_repair_system"] = "Flatpak repair system [size unknown]"
        row += 1

        # Journal row with retention entry
        journal_frame = ttk.Frame(sys_frame)
        journal_frame.grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.widgets["journal"] = ttk.Checkbutton(journal_frame, text="Systemd journal vacuum", variable=self.var_journal)
        self.widgets["journal"].pack(side=tk.LEFT)
        self.base_text["journal"] = "Systemd journal vacuum"
        ttk.Label(journal_frame, text="Keep:").pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(journal_frame, width=8, textvariable=self.journal_retention).pack(side=tk.LEFT)
        ttk.Label(journal_frame, text="(e.g., 3d, 7d, 100M)").pack(side=tk.LEFT, padx=(6, 0))

        # User tasks group
        user_frame = ttk.LabelFrame(main_container, text=f"👤 User Caches & Data (running as {self.username})", padding=10)
        user_frame.pack(fill=tk.X, pady=(0, 15))

        row = 0
        self.widgets["user_cache"] = ttk.Checkbutton(user_frame, text="~/.cache/*", variable=self.var_user_cache)
        self.widgets["user_cache"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["user_cache"] = "~/.cache/*"
        row += 1

        self.widgets["thumbnails"] = ttk.Checkbutton(user_frame, text="~/.thumbnails/*", variable=self.var_thumbnails)
        self.widgets["thumbnails"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["thumbnails"] = "~/.thumbnails/*"
        row += 1

        self.widgets["trash"] = ttk.Checkbutton(user_frame, text="~/.local/share/Trash/*", variable=self.var_trash)
        self.widgets["trash"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["trash"] = "~/.local/share/Trash/*"
        row += 1

        # Flatpak app cache (measurable)
        self.widgets["flatpak_app_cache"] = ttk.Checkbutton(user_frame, text="Flatpak application cache (~/.var/app/*/cache/*)", variable=self.var_flatpak_app_cache)
        self.widgets["flatpak_app_cache"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["flatpak_app_cache"] = "Flatpak application cache (~/.var/app/*/cache/*)"
        row += 1

        self.widgets["firefox"] = ttk.Checkbutton(user_frame, text="Firefox cache (all profiles)", variable=self.var_firefox)
        self.widgets["firefox"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["firefox"] = "Firefox cache (all profiles)"
        row += 1

        self.widgets["chrome"] = ttk.Checkbutton(user_frame, text="Chrome/Chromium cache (default profile)", variable=self.var_chrome)
        self.widgets["chrome"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["chrome"] = "Chrome/Chromium cache (default profile)"
        row += 1

        self.widgets["flatpak_user_unused"] = ttk.Checkbutton(user_frame, text="Flatpak user: uninstall unused [size unknown]", variable=self.var_flatpak_user)
        self.widgets["flatpak_user_unused"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["flatpak_user_unused"] = "Flatpak user: uninstall unused [size unknown]"
        row += 1

        self.widgets["flatpak_repair_user"] = ttk.Checkbutton(user_frame, text="Flatpak repair user [size unknown]", variable=self.var_flatpak_repair_user)
        self.widgets["flatpak_repair_user"].grid(row=row, column=0, sticky="w", pady=4, padx=5)
        self.base_text["flatpak_repair_user"] = "Flatpak repair user [size unknown]"
        row += 1

        # Separator
        ttk.Separator(main_container, orient='horizontal').pack(fill=tk.X, pady=8)

        # Action buttons row
        button_frame = ttk.Frame(main_container)
        button_frame.pack(fill=tk.X, pady=(0, 10))

        # Clean button - green tk.Button for better color control
        clean_btn = tk.Button(button_frame, text="🧹 Clean Selected",
                              command=self.on_clean_clicked,
                              bg="#2ecc71", activebackground="#27ae60",
                              fg="white", activeforeground="white",
                              font=('Segoe UI', 10, 'bold'),
                              padx=12, pady=5,
                              relief=tk.FLAT, bd=0)
        clean_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Refresh and Preview as modern ttk buttons
        refresh_btn = ttk.Button(button_frame, text="⟳ Refresh Sizes", command=self.refresh_sizes)
        refresh_btn.pack(side=tk.LEFT, padx=(0, 5))

        preview_btn = ttk.Button(button_frame, text="👁 Preview Commands", command=self.on_preview)
        preview_btn.pack(side=tk.LEFT)

        # Log area with label and frame
        log_label = ttk.Label(main_container, text="📋 Activity Log", font=('Segoe UI', 10, 'bold'))
        log_label.pack(anchor="w", pady=(5, 3))
        
        # ScrolledText with modern look
        self.log = ScrolledText(main_container, height=14, wrap=tk.WORD,
                                font=('Consolas', 9), bg='#f8f9fa', fg='#2c3e50',
                                relief=tk.FLAT, bd=1, highlightthickness=0)
        self.log.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # Initial log message
        log_append(self.log, "Ready. Select items and press 'Clean Selected'.")

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
        # New options
        self.var_flatpak_app_cache.set(state)
        self.var_apt_cache.set(state)
        self.var_old_kernels.set(state)

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
            "flatpak_app_cache": self.var_flatpak_app_cache,
            "apt_cache": self.var_apt_cache,   # Now measurable via root
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
            "flatpak_app_cache": self.var_flatpak_app_cache,
            "apt_cache": self.var_apt_cache,
        }
        for key, var in key_to_var_measurable.items():
            size = sizes_now.get(key, None)
            if size is None or size == 0:
                var.set(False)

        # Non measurable entries are always deselected
        self.var_flatpak_user.set(False)
        self.var_flatpak_repair_user.set(False)
        self.var_flatpak_repair_system.set(False)
        self.var_old_kernels.set(False)

    # ----------------------------- Size analysis -----------------------------

    def refresh_sizes(self) -> None:
        """
        Recalculate sizes for all measurable categories.
        For root‑owned paths (apt_cache) we ask the helper.
        """
        # Standard measurable keys (user accessible)
        measurable = [
            "tmp", "user_cache", "thumbnails", "trash",
            "firefox", "chrome", "flatpak_syscache", "apt", "journal",
            "flatpak_app_cache"
        ]
        sizes_now: Dict[str, int] = {}
        for key in measurable:
            patterns = self.patterns.get(key, [])
            sizes_now[key] = size_of_patterns(patterns)

        # Special root path: APT package cache
        apt_cache_patterns = ["/var/cache/apt/archives/*", "/var/cache/apt/archives/partial/*"]
        try:
            apt_size = HELPER.get_size_of_patterns(apt_cache_patterns)
            sizes_now["apt_cache"] = apt_size
        except Exception:
            sizes_now["apt_cache"] = 0

        # Auto select by threshold
        self._apply_autoselect_by_threshold(sizes_now)

        # Auto deselect 0 MB or unknown
        self._apply_autodeselect_zero_or_unknown(sizes_now)

        # Update checkbox texts for measurable items
        for key, size in sizes_now.items():
            if key in self.widgets and key in self.base_text:
                try:
                    if size == 0:
                        text = f"{self.base_text[key]}  [0 MB]"
                    else:
                        text = f"{self.base_text[key]}  [{human_mb(size)}]"
                    self.widgets[key].configure(text=text)
                except tk.TclError:
                    pass

        # Keep non measurable labels as is (they already have "[size unknown]")
        non_measurable = ["flatpak_user_unused", "flatpak_repair_user", "flatpak_repair_system",
                          "old_kernels"]
        for key in non_measurable:
            if key in self.widgets and key in self.base_text:
                try:
                    self.widgets[key].configure(text=self.base_text[key])
                except tk.TclError:
                    pass

        self.sizes_before = sizes_now
        log_append(self.log, "Sizes refreshed (APT cache size obtained via helper).")

    # ----------------------------- Plan and execution -----------------------------

    def build_plan(self) -> dict:
        """
        Build a plan from selected checkboxes for user deletions, user commands and root actions.

        :return: Dict with user_py_deletes, user_cmds, root_rm_patterns and root_cmds.
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
        # Flatpak app cache
        if self.var_flatpak_app_cache.get():
            plan["user_py_delete"].append("~/.var/app/*/cache/*")

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
        if self.var_apt_cache.get():
            plan["root_rm_patterns"] += ["/var/cache/apt/archives/*", "/var/cache/apt/archives/partial/*"]

        # Root commands
        if self.var_flatpak_repair_system.get():
            plan["root_cmds"].append("flatpak repair --system -y")
        if self.var_apt.get():
            plan["root_cmds"] += ["apt clean", "apt autoclean", "apt autoremove -y"]
        if self.var_journal.get():
            retention = self.journal_retention.get().strip() or "3d"
            plan["root_cmds"].append(f"journalctl --vacuum-time={shlex.quote(retention)}")
        if self.var_old_kernels.get():
            plan["root_cmds"].append("apt autoremove --purge -y")

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
        if self.var_flatpak_app_cache.get(): selected_keys.append("flatpak_app_cache")
        if self.var_apt_cache.get(): selected_keys.append("apt_cache")

        sizes_before_local = {}
        for k in selected_keys:
            if k == "apt_cache":
                # size already obtained via helper, we store it from self.sizes_before
                sizes_before_local[k] = self.sizes_before.get(k, 0)
            else:
                sizes_before_local[k] = size_of_patterns(self.patterns.get(k, []))

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
            if key == "apt_cache":
                after = HELPER.get_size_of_patterns(["/var/cache/apt/archives/*", "/var/cache/apt/archives/partial/*"])
            else:
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
    - get_size (compute total size of root patterns)
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

    def _size_of_path(p: str) -> int:
        """Compute size of a single file/directory (no glob)."""
        if not os.path.exists(p):
            return 0
        if os.path.isdir(p) and not os.path.islink(p):
            total = 0
            for root, _, files in os.walk(p, onerror=lambda e: None):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        if not os.path.islink(fp):
                            total += os.path.getsize(fp)
                    except Exception:
                        pass
            return total
        if os.path.isfile(p) and not os.path.islink(p):
            try:
                return os.path.getsize(p)
            except Exception:
                return 0
        return 0

    def _size_of_patterns(patterns: List[str]) -> int:
        total = 0
        for pat in patterns:
            for p in glob.glob(pat, recursive=False):
                total += _size_of_path(p)
        return total

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

            elif action == "get_size":
                patterns: List[str] = args.get("patterns") or []
                size = _size_of_patterns(patterns)
                send_ok(size)

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
        _root = tk.Tk()
        _root.withdraw()
        maybe_prompt_nemo_setup(_root)
        maybe_prompt_desktop_setup(_root)
        main()
