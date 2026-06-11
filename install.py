"""
Magic Scatter World for Houdini - Installer
======================================

Cross-platform, multi-version installer for Houdini 19.0 / 19.5 / 20.0 / 20.5 / 21.

Usage
-----
  Double-click `install.bat` (Windows) or `install.command` (macOS/Linux),
  or run from a terminal:

      python install.py            # GUI if Tkinter available, else CLI
      python install.py --all      # headless: install to every detected version
      python install.py --versions 20.5 21.0
      python install.py --uninstall
      python install.py --no-gui   # force CLI even if Tkinter is available

It writes a `Magic_Scatter_World.json` package descriptor pointing at *this* folder
into the `packages/` directory of each chosen Houdini user-prefs folder.
No files are copied -- the package is run in place.
"""

from __future__ import print_function

import argparse
import json
import os
import shutil
import sys

PACKAGE_NAME    = "Magic_Scatter_World"
PACKAGE_VERSION = "1.3.0"
SUPPORTED_VERS  = ("19.0", "19.5", "20.0", "20.5", "21.0")

# Resource root: where the Magic_Scatter_World source files (scripts/, toolbar/, icons/)
# live RIGHT NOW, at this moment of execution.
#  - Normal script run: the folder containing install.py.
#  - PyInstaller --onefile exe: the temp extraction dir in sys._MEIPASS.
def _is_frozen():
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

if _is_frozen():
    RESOURCE_DIR = sys._MEIPASS                                     # noqa
else:
    RESOURCE_DIR = (
        os.path.dirname(os.path.abspath(__file__))
        if "__file__" in globals()
        else os.getcwd()
    )

# In script mode, the package JSON points at the same folder Python is
# running from. In frozen mode, that folder is a temp dir that vanishes
# when the exe exits, so we must copy the resources to a persistent
# location first and point the JSON there. PACKAGE_DIR is set per-install
# in frozen mode by _do_install().
PACKAGE_DIR = RESOURCE_DIR


def _default_install_dest():
    """Where to copy bundled resources when running as a frozen exe."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Magic_Scatter_World")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Magic_Scatter_World")
    return os.path.expanduser("~/.local/share/Magic_Scatter_World")


def _copy_bundled_resources(dest):
    """Copy scripts/, toolbar/, icons/, package.json from RESOURCE_DIR to dest."""
    os.makedirs(dest, exist_ok=True)
    for item in ("scripts", "toolbar", "icons", "package.json", "README.md"):
        src = os.path.join(RESOURCE_DIR, item)
        dst = os.path.join(dest, item)
        if not os.path.exists(src):
            continue
        if os.path.isdir(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    return dest


# --------------------------------------------------------------------------
# Houdini prefs-dir discovery
# --------------------------------------------------------------------------

def _windows_documents_dir():
    """Resolve the real Documents folder on Windows (handles OneDrive redirect)."""
    try:
        import ctypes
        from ctypes import wintypes
        CSIDL_PERSONAL = 5
        SHGFP_TYPE_CURRENT = 0
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(
            None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf
        )
        if buf.value and os.path.isdir(buf.value):
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def _platform_houdini_root():
    """Root directory under which `houdiniXX.X` folders live."""
    if sys.platform.startswith("win"):
        return _windows_documents_dir()
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Preferences/houdini")
    return os.path.expanduser("~")  # Linux


def _houdini_dirname(ver):
    """Folder name for a given Houdini version on the current OS."""
    if sys.platform == "darwin":
        return ver                  # ~/Library/Preferences/houdini/20.5
    return "houdini" + ver          # ~/Documents/houdini20.5  or  ~/houdini20.5


def discover_houdini_versions():
    """
    Return [(version, prefs_dir), ...] for every supported Houdini install
    found on disk.  Includes any extra `houdini*` dirs that aren't in the
    supported list, so the user can opt-in to nightlies / future versions.
    """
    root = _platform_houdini_root()
    found = []

    if not os.path.isdir(root):
        return found

    seen = set()
    # Pass 1: known supported versions
    for ver in SUPPORTED_VERS:
        path = os.path.join(root, _houdini_dirname(ver))
        if os.path.isdir(path):
            found.append((ver, path))
            seen.add(path)

    # Pass 2: any other houdiniX.Y the user may have
    try:
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if not os.path.isdir(full) or full in seen:
                continue
            ver = None
            if sys.platform == "darwin":
                # Folders here look like "20.5", "21.0"
                if entry[:1].isdigit() and "." in entry:
                    ver = entry
            else:
                if entry.lower().startswith("houdini"):
                    tail = entry[len("houdini"):]
                    if tail and tail[:1].isdigit():
                        ver = tail
            if ver:
                found.append((ver, full))
    except OSError:
        pass

    return found


# --------------------------------------------------------------------------
# Package JSON authoring
# --------------------------------------------------------------------------

def _build_package_json(package_dir):
    pd = package_dir.replace("\\", "/")
    return {
        "name":        PACKAGE_NAME,
        "version":     PACKAGE_VERSION,
        "description": "Magic Scatter World - brush-based surface scattering for Houdini.",
        # 'path' makes Houdini add this folder to HOUDINI_PATH, which is
        # what causes <path>/toolbar/*.shelf to auto-load as a shelf tab,
        # <path>/icons/ to be picked up, etc.
        "path":        pd,
        "variables": {
            "MAGIC_SCATTER_WORLD_ROOT": pd,
        },
        "env": [
            {"PYTHONPATH":           {"method": "prepend", "value": pd + "/scripts"}},
            {"HOUDINI_TOOLBAR_PATH": {"method": "prepend", "value": pd + "/toolbar"}},
            {"HOUDINI_UI_ICON_PATH": {"method": "prepend", "value": pd + "/icons"}},
        ],
    }


def install_to(prefs_dir, package_dir, log=print):
    """Write Magic_Scatter_World.json into prefs_dir/packages/. Returns the JSON path."""
    packages_dir = os.path.join(prefs_dir, "packages")
    os.makedirs(packages_dir, exist_ok=True)

    json_path = os.path.join(packages_dir, PACKAGE_NAME + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_build_package_json(package_dir), f, indent=4)

    log("  + " + json_path)
    return json_path


def uninstall_from(prefs_dir, log=print):
    """Remove Magic_Scatter_World.json from prefs_dir/packages/. Returns True if removed."""
    json_path = os.path.join(prefs_dir, "packages", PACKAGE_NAME + ".json")
    if os.path.isfile(json_path):
        try:
            os.remove(json_path)
            log("  - " + json_path)
            return True
        except OSError as e:
            log("  ! could not remove " + json_path + ": " + str(e))
            return False
    log("  . not installed: " + json_path)
    return False


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print_header(action, package_dir):
    print("")
    print("[Magic Scatter World Installer]")
    print("  Action       : " + action)
    print("  Package root : " + package_dir)
    print("  Platform     : " + sys.platform)
    print("")


def run_cli(args, found):
    # In frozen mode, decide where to copy bundled resources to.
    if _is_frozen() and not args.uninstall:
        package_dir = (args.dest or _default_install_dest()).strip()
    else:
        package_dir = RESOURCE_DIR

    if not found:
        print("No Houdini user-prefs folders found under:")
        print("  " + _platform_houdini_root())
        print("Run Houdini at least once, or set HOUDINI_USER_PREF_DIR, then retry.")
        return 2

    _print_header("Uninstall" if args.uninstall else "Install", package_dir)

    # Pick which versions to act on
    if args.all:
        targets = found
    elif args.versions:
        wanted = set(args.versions)
        targets = [(v, p) for v, p in found if v in wanted]
        missing = wanted - {v for v, _ in targets}
        if missing:
            print("WARN: requested versions not found on disk: "
                  + ", ".join(sorted(missing)))
        if not targets:
            print("No matching Houdini versions found.")
            return 2
    else:
        # Interactive prompt
        print("Detected Houdini installs:")
        for i, (v, p) in enumerate(found, 1):
            print("  [{0}] {1:<5}  {2}".format(i, v, p))
        print("  [a] all")
        print("  [q] quit")
        choice = ""
        try:
            choice = input("Select (e.g. 1 3, or 'a'): ").strip().lower()
        except EOFError:
            choice = "a"
        if choice in ("q", "quit", "exit"):
            return 0
        if choice in ("", "a", "all"):
            targets = found
        else:
            picks = []
            for tok in choice.replace(",", " ").split():
                if tok.isdigit() and 1 <= int(tok) <= len(found):
                    picks.append(found[int(tok) - 1])
            if not picks:
                print("No valid selection. Aborting.")
                return 2
            targets = picks

    # Frozen mode: copy bundled files to package_dir before pointing JSONs at it.
    if _is_frozen() and not args.uninstall and targets:
        print("Copying files to: " + package_dir)
        try:
            _copy_bundled_resources(package_dir)
        except Exception as e:
            print("  ! failed to copy files: " + str(e))
            return 1

    print("")
    ok = 0
    for ver, prefs in targets:
        print("Houdini " + ver + " -> " + prefs)
        if args.uninstall:
            if uninstall_from(prefs):
                ok += 1
        else:
            try:
                install_to(prefs, package_dir)
                ok += 1
            except OSError as e:
                print("  ! failed: " + str(e))

    print("")
    verb = "Uninstalled from" if args.uninstall else "Installed to"
    print("{0} {1}/{2} Houdini version(s).".format(verb, ok, len(targets)))
    if not args.uninstall and ok:
        print("Restart Houdini -- look for the 'Magic Scatter World' shelf tab.")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# Optional Tkinter GUI
# --------------------------------------------------------------------------

def _try_run_gui(found):
    """Return True if GUI ran to completion (success or user cancel)."""
    try:
        if sys.version_info[0] >= 3:
            import tkinter as tk
            from tkinter import messagebox, filedialog
        else:
            import Tkinter as tk            # noqa
            import tkMessageBox as messagebox  # noqa
            import tkFileDialog as filedialog  # noqa
    except Exception:
        return False

    frozen = _is_frozen()

    root = tk.Tk()
    root.title("Magic Scatter World Installer")
    try:
        root.minsize(620, 360 if frozen else 320)
    except Exception:
        pass

    tk.Label(
        root,
        text="Magic Scatter World for Houdini",
        font=("Segoe UI", 14, "bold"),
    ).pack(pady=(14, 2))

    if frozen:
        # Frozen exe: bundled resources will be COPIED to a chosen folder,
        # and the package JSON will point at that folder.
        tk.Label(
            root,
            text="Files will be copied to:",
            anchor="w",
        ).pack(fill="x", padx=14, pady=(8, 0))

        dest_row = tk.Frame(root)
        dest_row.pack(fill="x", padx=14, pady=(2, 10))
        dest_var = tk.StringVar(value=_default_install_dest())
        dest_entry = tk.Entry(dest_row, textvariable=dest_var)
        dest_entry.pack(side="left", fill="x", expand=True)

        def _browse():
            path = filedialog.askdirectory(
                title="Choose installation folder",
                initialdir=os.path.dirname(dest_var.get()) or None,
            )
            if path:
                dest_var.set(os.path.join(path, "Magic_Scatter_World")
                             if not path.lower().endswith("sp_scatter")
                             else path)

        tk.Button(dest_row, text="Browse...", command=_browse).pack(
            side="left", padx=(6, 0))
    else:
        dest_var = None
        tk.Label(
            root,
            text="Source folder:  " + RESOURCE_DIR,
            anchor="w",
            justify="left",
            wraplength=580,
        ).pack(fill="x", padx=14, pady=(0, 10))

    if not found:
        tk.Label(
            root,
            text=(
                "No Houdini user-prefs folders found under:\n  "
                + _platform_houdini_root()
                + "\n\nRun Houdini once so it creates its prefs folder, then re-run this installer."
            ),
            justify="left",
            fg="#aa3333",
        ).pack(padx=14, pady=14)
        tk.Button(root, text="Close", width=12, command=root.destroy).pack(pady=10)
        root.mainloop()
        return True

    tk.Label(
        root,
        text="Select Houdini versions to install for:",
        anchor="w",
    ).pack(fill="x", padx=14)

    box = tk.Frame(root)
    box.pack(fill="both", expand=True, padx=14, pady=6)

    vars_ = []
    for ver, prefs in found:
        v = tk.IntVar(value=1)
        tk.Checkbutton(
            box,
            text="Houdini {0}    ({1})".format(ver, prefs),
            variable=v,
            anchor="w",
            justify="left",
        ).pack(fill="x", anchor="w")
        vars_.append((v, ver, prefs))

    status = tk.StringVar(value="")
    tk.Label(root, textvariable=status, fg="#226622",
             justify="left", anchor="w", wraplength=580).pack(
        fill="x", padx=14, pady=(4, 0))

    btn_row = tk.Frame(root)
    btn_row.pack(fill="x", padx=14, pady=12)

    def do_action(uninstall):
        picked = [(ver, prefs) for v, ver, prefs in vars_ if v.get()]
        if not picked:
            messagebox.showwarning(
                "Magic Scatter World",
                "Select at least one Houdini version.",
            )
            return

        # Determine where the JSON should point. In frozen mode, copy
        # bundled resources to the chosen dest first.
        if frozen and not uninstall:
            dest = (dest_var.get() if dest_var else "").strip()
            if not dest:
                messagebox.showwarning(
                    "Magic Scatter World", "Pick an installation folder.")
                return
            try:
                _copy_bundled_resources(dest)
            except Exception as e:
                messagebox.showerror(
                    "Magic Scatter World",
                    "Failed to copy files to:\n  {0}\n\n{1}".format(dest, e),
                )
                return
            target_dir = dest
        else:
            target_dir = RESOURCE_DIR

        lines = []
        ok = 0
        for ver, prefs in picked:
            try:
                if uninstall:
                    if uninstall_from(prefs, log=lambda *_: None):
                        ok += 1
                        lines.append("Removed from Houdini " + ver)
                    else:
                        lines.append("Not installed for Houdini " + ver)
                else:
                    install_to(prefs, target_dir, log=lambda *_: None)
                    ok += 1
                    lines.append("Installed for Houdini " + ver)
            except Exception as e:
                lines.append("FAILED Houdini " + ver + ": " + str(e))
        status.set("\n".join(lines))

        title = "Uninstall complete" if uninstall else "Install complete"
        tail  = ("" if uninstall else
                 "\n\nFiles copied to:\n  " + target_dir + "\n\n"
                 if frozen else "")
        if not uninstall and not frozen:
            tail = ""
        if not uninstall:
            tail += "\nRestart Houdini -- look for the 'Magic Scatter World' shelf tab."
        messagebox.showinfo(
            title,
            "{0} {1}/{2} Houdini version(s).{3}".format(
                "Removed from" if uninstall else "Installed to",
                ok, len(picked), tail,
            ),
        )

    tk.Button(btn_row, text="Install",   width=14,
              command=lambda: do_action(False)).pack(side="left")
    tk.Button(btn_row, text="Uninstall", width=14,
              command=lambda: do_action(True)).pack(side="left", padx=(8, 0))
    tk.Button(btn_row, text="Close",     width=10,
              command=root.destroy).pack(side="right")

    root.mainloop()
    return True


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _parse_args(argv):
    p = argparse.ArgumentParser(
        prog="install.py",
        description="Install / uninstall Magic Scatter World for Houdini.",
    )
    p.add_argument("--all", action="store_true",
                   help="install/uninstall to every detected Houdini version")
    p.add_argument("--versions", nargs="+", metavar="VER",
                   help="explicit version list, e.g. --versions 20.5 21.0")
    p.add_argument("--uninstall", action="store_true",
                   help="remove Magic_Scatter_World.json from selected Houdini versions")
    p.add_argument("--no-gui", action="store_true",
                   help="force CLI even if Tkinter is available")
    p.add_argument("--dest", metavar="DIR",
                   help="(frozen exe only) install destination folder")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    found = discover_houdini_versions()

    headless = args.all or args.versions or args.uninstall or args.no_gui
    if not headless and _try_run_gui(found):
        return 0

    return run_cli(args, found)


if __name__ == "__main__":
    sys.exit(main())
