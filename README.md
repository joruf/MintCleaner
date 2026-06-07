# Mint Cleaner – Selective Temp & Cache Cleanup for Linux Mint

A modern GUI tool to clean temporary files, caches, and system leftovers on Linux Mint (and other Debian‑based distributions).  
Uses a single `pkexec` authentication at startup – no repeated password prompts.

## Features

- **Single authentication** – privileged helper runs with `pkexec`, one‑time password entry.
- **Live size analysis** – shows current MB usage for all measurable categories.
- **Auto‑select by threshold** – automatically ticks items larger than 100 MB (configurable).
- **Auto‑deselect** – untick items that are 0 MB or have unknown size.
- **User deletion mode** – choose **Move to Trash** (default) or **Delete immediately**.
- **Modern UI** – grouped categories (System / User), clear icons, and a detailed log area.
- **No confirmation popups** – all progress is shown directly in the log.

## Requirements

- Linux with `pkexec` (part of `policykit-1`)
- Python 3.6+ with `tkinter` (usually pre‑installed)
- Tested on Linux Mint, but works on Ubuntu, Debian, and similar distributions.

## What gets deleted?
System tasks (require root privileges)
- /tmp/* and /var/tmp/* – temporary files (safe to delete)
- APT cleanup – runs apt clean, apt autoclean, apt autoremove
(removes downloaded .deb packages, obsolete dependencies)
- APT package cache – /var/cache/apt/archives/* (all cached .deb files)
- Remove old kernels – apt autoremove --purge
(uninstalls older Linux kernels and headers, keeps the current one)
- System Flatpak cache – /var/tmp/flatpak-cache/*
- Flatpak repair system – flatpak repair --system -y
(repairs system Flatpak installations, removes broken references)
- Systemd journal vacuum – journalctl --vacuum-time=…
(configurable retention, e.g., 3d / 100M)

User tasks (run as your user)
- ~/.cache/* – application caches (web browser caches, thumbnails, etc.)
- ~/.thumbnails/* – thumbnail cache of the file manager
- ~/.local/share/Trash/* – your Trash folder (files you already deleted once)
- Flatpak application cache – ~/.var/app/*/cache/* (caches of Flatpak apps)
- Firefox cache – all profiles: ~/.mozilla/firefox/*.default*/cache2/* and ~/.cache/mozilla/firefox/*.default*/cache2/*
- Chrome / Chromium cache – default profile:
~/.config/google-chrome/Default/Cache/*, ~/.cache/google-chrome/Default/Cache/*,
~/.config/chromium/Default/Cache/*, ~/.cache/chromium/Default/Cache/*
- Flatpak user: uninstall unused – flatpak uninstall --unused -y
(removes unused Flatpak runtimes and extensions)
- Flatpak repair user – flatpak repair --user -y
(repairs user‑level Flatpak installations)
    
## Usage

```bash
git clone https://github.com/joruf/mint-cleaner.git
cd mint-cleaner
chmod +x mint-cleaner.py
./mint-cleaner.py
