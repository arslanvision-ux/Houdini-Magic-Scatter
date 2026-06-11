"""
Magic Scatter World for Houdini - In-Houdini installer
================================================

Run this from inside a running Houdini session. No external Python required.

Three ways to invoke it:

  1) Drag this file into the NETWORK EDITOR (not the main window).
     Houdini opens it in the Python Source Editor. Press Ctrl+Enter (Apply).

  2) Windows -> Python Shell, paste:
         exec(open(r"PATH/TO/Magic_Scatter_World_Houdini/houdini_install.py").read())

  3) Windows -> Python Source Editor -> File -> Open this file -> Apply.

A folder picker appears asking for the Magic_Scatter_World source folder, then a
multi-select list of detected Houdini versions. Pick one or more, click OK.
The installer writes Magic_Scatter_World.json into each chosen Houdini's packages/
folder. Restart Houdini -- the Magic Scatter World shelf tab appears.
"""

import os
import sys
import json

import hou


PACKAGE_NAME    = "Magic_Scatter_World"
PACKAGE_VERSION = "1.2.0"
SUPPORTED_VERS  = ("19.0", "19.5", "20.0", "20.5", "21.0")


# --------------------------------------------------------------------------
# Houdini prefs-dir discovery (same logic as install.py, copied for
# self-containment so this single file is everything the artist needs).
# --------------------------------------------------------------------------

def _platform_houdini_root():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            if buf.value and os.path.isdir(buf.value):
                return buf.value
        except Exception:
            pass
        return os.path.join(os.path.expanduser("~"), "Documents")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Preferences/houdini")
    return os.path.expanduser("~")


def _houdini_dirname(ver):
    return ver if sys.platform == "darwin" else "houdini" + ver


def _discover():
    root = _platform_houdini_root()
    found = []
    if not os.path.isdir(root):
        return found
    seen = set()
    for ver in SUPPORTED_VERS:
        p = os.path.join(root, _houdini_dirname(ver))
        if os.path.isdir(p):
            found.append((ver, p))
            seen.add(p)
    try:
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if not os.path.isdir(full) or full in seen:
                continue
            ver = None
            if sys.platform == "darwin":
                if entry[:1].isdigit() and "." in entry:
                    ver = entry
            elif entry.lower().startswith("houdini"):
                tail = entry[len("houdini"):]
                if tail and tail[:1].isdigit():
                    ver = tail
            if ver:
                found.append((ver, full))
    except OSError:
        pass
    return found


def _build_pkg_json(package_dir):
    pd = package_dir.replace("\\", "/")
    return {
        "name":        PACKAGE_NAME,
        "version":     PACKAGE_VERSION,
        "description": "Magic Scatter World - brush-based surface scattering for Houdini.",
        "path":        pd,
        "variables": {"MAGIC_SCATTER_WORLD_ROOT": pd},
        "env": [
            {"PYTHONPATH":           {"method": "prepend", "value": pd + "/scripts"}},
            {"HOUDINI_TOOLBAR_PATH": {"method": "prepend", "value": pd + "/toolbar"}},
            {"HOUDINI_UI_ICON_PATH": {"method": "prepend", "value": pd + "/icons"}},
        ],
    }


def _install_to(prefs_dir, package_dir):
    pkg_dir = os.path.join(prefs_dir, "packages")
    os.makedirs(pkg_dir, exist_ok=True)
    json_path = os.path.join(pkg_dir, PACKAGE_NAME + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_build_pkg_json(package_dir), f, indent=4)
    return json_path


# --------------------------------------------------------------------------
# Main flow
# --------------------------------------------------------------------------

def install_in_houdini():
    # 1) Source folder. Default to this script's own folder if known.
    default_dir = ""
    if "__file__" in globals():
        try:
            default_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            default_dir = ""

    chosen = hou.ui.selectFile(
        start_directory=default_dir or None,
        title="Select the Magic_Scatter_World folder (must contain install.py)",
        file_type=hou.fileType.Directory,
        chooser_mode=hou.fileChooserMode.Read,
    )
    if not chosen:
        hou.ui.displayMessage("Install cancelled.", title="Magic Scatter World Installer")
        return

    src = hou.expandString(chosen).rstrip("/\\")
    if not os.path.isdir(src) or not os.path.isfile(os.path.join(src, "install.py")):
        hou.ui.displayMessage(
            "That folder does not look like the Magic_Scatter_World source.\n"
            "Expected to find install.py at:\n  " + src,
            severity=hou.severityType.Error,
            title="Magic Scatter World Installer",
        )
        return

    # 2) Detect installed Houdini versions
    found = _discover()
    if not found:
        hou.ui.displayMessage(
            "No Houdini user-prefs folders found under:\n  "
            + _platform_houdini_root()
            + "\n\nRun Houdini once so it creates a prefs folder, then retry.",
            severity=hou.severityType.Error,
            title="Magic Scatter World Installer",
        )
        return

    # 3) Multi-select
    labels = ["Houdini {0}    ({1})".format(v, p) for v, p in found]
    picked_idx = hou.ui.selectFromList(
        labels,
        default_choices=tuple(range(len(found))),
        title="Magic Scatter World Installer",
        message="Install Magic Scatter World for which Houdini version(s)?",
        column_header="Detected installs",
        clear_on_cancel=True,
    )
    if not picked_idx:
        hou.ui.displayMessage("Install cancelled.", title="Magic Scatter World Installer")
        return

    # 4) Write JSONs
    results = []
    ok = 0
    for i in picked_idx:
        ver, prefs = found[i]
        try:
            path = _install_to(prefs, src)
            results.append("OK   Houdini {0}\n      -> {1}".format(ver, path))
            ok += 1
        except Exception as e:
            results.append("FAIL Houdini {0}: {1}".format(ver, e))

    hou.ui.displayMessage(
        "Installed for {0}/{1} Houdini version(s).\n\n".format(ok, len(picked_idx))
        + "\n".join(results)
        + "\n\nRestart Houdini -- look for the 'Magic Scatter World' shelf tab.",
        title="Magic Scatter World Installer",
    )


# Execute immediately when this file is dragged into the network editor /
# pasted into the Python Shell / Apply'd in Python Source Editor.
install_in_houdini()
