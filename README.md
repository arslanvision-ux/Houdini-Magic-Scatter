# Magic Scatter World for Houdini

**Version:** 1.3.0 — Houdini port of the Maya Magic Scatter World brush-based surface scattering tool.

---

**Demonstration:** [Watch on Google Drive](https://drive.google.com/file/d/1XBM2NiO13Ed2wULodtJtUxfXL6xUl877/view?usp=drive_link)

**Video Tutorials:** [Visit my YouTube Channel](https://www.youtube.com/@mamgicscatterworld)

---

## Features

| Feature | Details |
|---|---|
| Python Panel | Dockable panel — lives inside any Houdini pane tab |
| Brush Settings | Radius, Falloff Amount/Softness |
| Density / Spacing | Density, Min Spacing, Min Distance, Relax Iterations, Max Points |
| Brush Stamp | Grayscale mask, rotation, X/Y flip, random flip |
| Rotation | Normal Align, Cone Angle, Full Random, Min/Max (0–1 normalised) |
| Scale | Global Scale + Per-axis Min/Max with Uniform XYZ link |
| Assets | Multiple source objects with independent weight per asset |
| Thumbnails | Per-asset preview icons (viewport screenshot + disk cache) |
| Paint / Erase / Clear | Toggle brush modes directly from the panel |
| Resume | Dropdown lists all scatter setups in the current scene |
| Persistence | All data stored as node userData inside the .hip file |

---

## Installation

Supports **Houdini 19.0, 19.5, 20.0, 20.5, 21.0** on Windows / macOS / Linux.

### Option A – One-click `.exe` installer *(Windows artists, no Python required)*

Download `Magic_Scatter_World_Installer.exe` from the release zip. Double-click it.

A window appears asking where to install the Magic_Scatter_World files (default
`%LOCALAPPDATA%\Magic_Scatter_World`) and lists every Houdini version it found.
Tick versions, click **Install**, restart Houdini → **Magic Scatter World** shelf tab
appears. Bundled, self-contained — no Python install needed on the artist's
machine.

### Option A2 – Double-click script installer (cross-platform)

If you prefer the source-folder layout (or you're on macOS/Linux):

| Platform | Double-click |
|---|---|
| Windows | `install.bat` |
| macOS   | `install.command` |
| Linux   | `install.command` (or `python3 install.py` from a terminal) |

Same Tkinter window, but installs *in place* — the package JSON points at the
Magic_Scatter_World folder you ran the script from. If Tkinter isn't available the
installer falls back to an interactive text prompt.

### Option B – Drag-into-Houdini installer

For machines that don't have Python on the PATH at all. Pick **one** of:

**B1. Drag into the Network Editor**
1. Open Houdini.
2. Drag `houdini_install.py` from your file browser into Houdini's
   **Network Editor** pane (the node graph view, *not* the main window —
   dropping on the main window will fail with *"Invalid .hip file header"*).
3. Houdini opens it in the Python Source Editor. Press **Ctrl+Enter** (Apply).
4. A folder picker appears → select the unzipped `Magic_Scatter_World` folder.
5. A version checklist appears → tick the Houdini versions you want.
6. Restart Houdini.

**B2. Python Shell one-liner** *(quickest if Houdini is already open)*
1. **Windows → Python Shell** (or press the Python Shell pane tab).
2. Paste, replacing the path with your unzip location:
   ```python
   exec(open(r"C:/PATH TO YOU FOLDER/houdini_install.py").read())
   ```
3. Folder picker → version checklist → restart Houdini.

**B3. Python Source Editor**
1. **Windows → Python Source Editor**.
2. **File → Open...** → pick `houdini_install.py`.
3. **Apply** (Ctrl+Enter). Same folder picker / checklist flow.

### Option C – Headless / scripted

```
python install.py --all                  # register for every Houdini version on this machine
python install.py --versions 20.5 21.0   # only specific versions
python install.py --uninstall --all      # remove from all
python install.py --no-gui               # force CLI even with Tkinter installed
```



## Quick Start

1. In the **Magic Scatter World** panel click **Set Surface** after selecting a Grid / mesh in the scene.
2. Select one or more geometry nodes → **Add Asset(s)**.
3. Click **Create Network** and give it a name.
4. Click **▶ PAINT**, then drag across the surface in the 3D viewport.
5. Tweak parameters on the **Brush / Stamp / Rotation / Scale** tabs in real time.
6. Use **⌦ ERASE** to remove instances locally, **✕ CLEAR ALL** to start over.

---

## File Structure

```
Magic_Scatter_World_Houdini/
├── package.json                  ← Houdini package descriptor (template)
├── install.py                    ← Cross-platform installer (GUI + CLI)
├── install.bat                   ← Windows double-click launcher
├── install.command               ← macOS / Linux double-click launcher
├── houdini_install.py            ← Drag-into-Houdini one-time installer (no Python needed)
├── toolbar/
│   └── Magic_Scatter_World.shelf          ← Shelf definition (floating window + panel focus)
└── scripts/
    └── scatter_tool/
        ├── __init__.py
        ├── logic.py              ← SOP network builder, scatter engine, metadata
        ├── raycast.py            ← Python Viewer State (brush overlay)
        ├── thumbnail.py          ← Asset preview generation / disk cache
        ├── ui.py                 ← ScatterWindow widget + createInterface() factory
        └── launcher.py           ← launch() for shelf; createInterface() for panel
```

---

## Python Panel vs Floating Window

| | Python Panel | Floating Window |
|---|---|---|
| Docked in Houdini layout | ✓ | ✗ |
| Survives scene reload | ✓ (pane persists) | ✗ (must re-launch) |
| Shelf button | Focus existing tab | Always opens new window |
| Entry point | `createInterface()` | `launch()` / `show()` |

---

## Building distributables (maintainers only)

```
python build_installer.py            # builds Magic_Scatter_World_Installer.exe + release zip
python build_installer.py --exe-only
python build_installer.py --zip-only
```

Outputs land in `dist/`:

| File | Size | Use |
|---|---|---|
| `Magic_Scatter_World_Installer.exe` | ~40 MB | Single-file Windows installer (Python runtime bundled) |
| `Magic_Scatter_World_v1.2.0.zip`    | ~70 MB | Full release: source + the .exe + install scripts for every OS |

PyInstaller is auto-installed on first run; no other build tools required.
The zip is filtered to exclude `backup/`, `__pycache__/`, `.hip` files, and
other local clutter.

---

## Notes

- **No C++ plugin required.** Everything is pure Python + Houdini SOPs.
- The viewer state (`scatter_tool.paint`) is registered automatically when the panel opens.
- Direct API usage: `import scatter_tool.launcher; scatter_tool.launcher.launch()`
- Compatible with **Houdini 19.0 → 21.0** (Python 3.7+, PySide2 or PySide6 — auto-detected).
