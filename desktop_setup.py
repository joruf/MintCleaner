#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
First-run setup for desktop shortcut creation.

On the first application start the user is asked once whether a desktop
shortcut should be created on Desktop or its localized equivalent. The shared
.initialized marker file in the project directory prevents repeated prompts.
"""

import stat
from pathlib import Path

from tkinter import messagebox

from nemo_setup import INIT_FILE, mark_initialization_done

SCRIPT_DIR = Path(__file__).resolve().parent
DESKTOP_TEMPLATE = SCRIPT_DIR / "Mint-Cleaner.desktop"
DESKTOP_FILENAME = "Mint Cleaner.desktop"
MINT_CLEANER_SCRIPT = SCRIPT_DIR / "mint-cleaner.py"


def user_desktop_dir() -> Path:
    """
    Return the user's desktop directory.

    Reads XDG user-dirs when available and falls back to Desktop or Schreibtisch.

    @return Path Desktop directory path
    """
    config = Path.home() / ".config" / "user-dirs.dirs"
    if config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("XDG_DESKTOP_DIR="):
                value = line.split("=", 1)[1].strip().strip('"')
                if value.startswith("$HOME/"):
                    return Path.home() / value[len("$HOME/"):]
                if value == "$HOME":
                    return Path.home()
                return Path(value).expanduser()

    for name in ("Desktop", "Schreibtisch"):
        desktop = Path.home() / name
        if desktop.is_dir():
            return desktop

    return Path.home() / "Desktop"


def build_desktop_entry_content() -> str:
    """
    Build the .desktop file contents from the template with the correct Exec path.

    @return str Desktop entry definition
    """
    exec_line = f"Exec=python3 {MINT_CLEANER_SCRIPT}\n"
    if not DESKTOP_TEMPLATE.is_file():
        return (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            "Name=Mint Cleaner\n"
            "Comment=Selective temp and cache cleanup for Linux Mint\n"
            "Icon=edit-clear-symbolic\n"
            f"{exec_line.rstrip()}\n"
            "Terminal=false\n"
            "Categories=Utility;System;\n"
            "StartupNotify=true\n"
        )

    lines: list[str] = []
    for line in DESKTOP_TEMPLATE.read_text(encoding="utf-8").splitlines():
        if line.startswith("Exec="):
            lines.append(exec_line.rstrip())
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def install_desktop_shortcut() -> tuple[bool, Path | None]:
    """
    Install the desktop shortcut on the user's desktop.

    @return tuple[bool, Path | None] Success flag and created shortcut path
    """
    try:
        desktop_dir = user_desktop_dir()
        desktop_dir.mkdir(parents=True, exist_ok=True)
        shortcut_path = desktop_dir / DESKTOP_FILENAME
        shortcut_path.write_text(build_desktop_entry_content(), encoding="utf-8")
        shortcut_path.chmod(
            shortcut_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return True, shortcut_path
    except OSError:
        return False, None


def maybe_prompt_desktop_setup(parent=None) -> None:
    """
    Ask once on first run whether to create a desktop shortcut.

    @param parent Optional Tk parent window for message boxes
    """
    if INIT_FILE.exists():
        return

    answer = messagebox.askyesno(
        "Desktop Shortcut",
        "Would you like to create a desktop shortcut for Mint Cleaner?",
        parent=parent,
    )

    if answer:
        success, _ = install_desktop_shortcut()
        if not success:
            messagebox.showerror(
                "Desktop Shortcut",
                "Could not create the desktop shortcut.",
                parent=parent,
            )

    mark_initialization_done()
