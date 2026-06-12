#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
First-run setup for Nemo context menu integration.

On the first application start the user is asked once whether a Nemo action
should be installed under ~/.local/share/nemo/actions/. The shared .initialized
marker file in the project directory prevents repeated prompts.
"""

from pathlib import Path

from tkinter import messagebox

SCRIPT_DIR = Path(__file__).resolve().parent
INIT_FILE = SCRIPT_DIR / ".initialized"
NEMO_ACTIONS_DIR = Path.home() / ".local" / "share" / "nemo" / "actions"
ACTION_FILENAME = "mint-cleaner.nemo_action"
MINT_CLEANER_SCRIPT = SCRIPT_DIR / "mint-cleaner.py"


def build_nemo_action_content() -> str:
    """
    Build the contents of the mint-cleaner.nemo_action file.

    @return str Nemo action definition for context menu integration
    """
    return (
        "[Nemo Action]\n"
        "Active=true\n"
        "Name=Mint Cleaner\n"
        "Comment=Starts Mint Cleaner for selective temp and cache cleanup\n"
        f"Exec=python3 {MINT_CLEANER_SCRIPT}\n"
        "Icon=edit-clear-symbolic\n"
        "\n"
        "# Shown on right-click on folders or in an empty window\n"
        "Selection=any\n"
        "Extensions=dir;\n"
    )


def install_nemo_action() -> bool:
    """
    Install the Nemo action file in the user's actions directory.

    @return bool True when the action file was written successfully
    """
    try:
        NEMO_ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
        action_path = NEMO_ACTIONS_DIR / ACTION_FILENAME
        action_path.write_text(build_nemo_action_content(), encoding="utf-8")
        return True
    except OSError:
        return False


def mark_initialization_done() -> None:
    """Create the marker file so the first-run prompt is not shown again."""
    try:
        INIT_FILE.touch()
    except OSError:
        pass


def maybe_prompt_nemo_setup(parent=None) -> None:
    """
    Ask once on first run whether to add a Nemo context menu entry.

    @param parent Optional Tk parent window for message boxes
    """
    if INIT_FILE.exists():
        return

    answer = messagebox.askyesno(
        "Nemo Context Menu",
        "Would you like to add a Mint Cleaner entry to the Nemo context menu "
        "(trash and file system)?",
        parent=parent,
    )

    if answer:
        if not install_nemo_action():
            messagebox.showerror(
                "Nemo Context Menu",
                "Could not create the Nemo context menu entry.",
                parent=parent,
            )
