"""
Lookdev window — engine picker + texture rows + exposed parms.

Opens as a non-modal QDialog so the artist can paint and tweak shading
simultaneously. State persists into the scatter network's userData via
`assign.py`; sliders live-write into the material's VOP nodes via the
engine's `update()`.
"""

import os
import hou

try:
    from PySide2.QtWidgets import (
        QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
        QLabel, QPushButton, QComboBox, QLineEdit, QFileDialog, QCheckBox,
        QGroupBox, QDoubleSpinBox, QSlider, QColorDialog, QFrame, QScrollArea,
        QMessageBox, QListWidget, QListWidgetItem, QAbstractItemView,
    )
    from PySide2.QtCore import Qt, QTimer, Signal
    from PySide2.QtGui import QColor, QPalette, QFont
except ImportError:
    from PySide6.QtWidgets import (
        QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
        QLabel, QPushButton, QComboBox, QLineEdit, QFileDialog, QCheckBox,
        QGroupBox, QDoubleSpinBox, QSlider, QColorDialog, QFrame, QScrollArea,
        QMessageBox, QListWidget, QListWidgetItem, QAbstractItemView,
    )
    from PySide6.QtCore import Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QPalette, QFont

from . import assign, conventions, preview as preview_mod
from .engines import available_engines, get_engine
from .engines import base as eng_base


# ── Tiny widgets ────────────────────────────────────────────────────────────
class _ColorSwatch(QPushButton):
    """A flat color button that opens QColorDialog on click. Emits Qt signal
    `changed` with an (r,g,b) tuple of floats in 0..1 range."""
    changed = Signal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setFixedWidth(60)
        self._rgb = (1.0, 1.0, 1.0)
        self.clicked.connect(self._on_pick)
        self._apply()

    def set_rgb(self, rgb):
        r, g, b = rgb
        self._rgb = (float(r), float(g), float(b))
        self._apply()

    def rgb(self):
        return self._rgb

    def _apply(self):
        r, g, b = [max(0, min(255, int(c * 255))) for c in self._rgb]
        self.setStyleSheet(f"QPushButton {{ background:rgb({r},{g},{b}); border:1px solid #333; }}")

    def _on_pick(self):
        r, g, b = [max(0, min(255, int(c * 255))) for c in self._rgb]
        col = QColorDialog.getColor(QColor(r, g, b), self, "Pick Color")
        if col.isValid():
            self.set_rgb((col.redF(), col.greenF(), col.blueF()))
            self.changed.emit(self._rgb)


class _TextureRow(QWidget):
    """Path field + browse + colorspace badge. Emits `changed` on path edit."""
    changed = Signal(str)

    def __init__(self, label, color_label, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lbl = QLabel(label)
        lbl.setFixedWidth(85)
        lay.addWidget(lbl)
        self.path = QLineEdit()
        self.path.textChanged.connect(self.changed.emit)
        lay.addWidget(self.path, 1)
        browse = QPushButton("…")
        browse.setFixedWidth(26)
        browse.clicked.connect(self._browse)
        lay.addWidget(browse)
        cs = QLabel(color_label)
        cs.setFixedWidth(40)
        cs.setStyleSheet("color:#888; font-size:10px;")
        cs.setAlignment(Qt.AlignCenter)
        lay.addWidget(cs)

    def _browse(self):
        start = self.path.text() or hou.expandString("$HIP")
        f, _ = QFileDialog.getOpenFileName(
            self, "Select texture", start,
            "Images (*.exr *.tx *.tex *.png *.jpg *.jpeg *.tif *.tiff *.hdr);;All Files (*)",
        )
        if f:
            # Auto-detect UDIM and store with <UDIM> token
            self.path.setText(conventions.detect_udim(f.replace("\\", "/")))

    def value(self):
        return self.path.text().strip()

    def set_value(self, v):
        self.path.setText(v or "")


# ── Main window ─────────────────────────────────────────────────────────────
class LookdevWindow(QDialog):

    TEX_LABELS = [
        ("diffuse",      "Diffuse",      "sRGB"),
        ("roughness",    "Roughness",    "Raw"),
        ("metallic",     "Metallic",     "Raw"),
        ("normal",       "Normal",       "Raw"),
        ("opacity",      "Opacity",      "Raw"),
        ("displacement", "Displacement", "Raw"),
    ]

    def __init__(self, paint_node, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lookdev")
        self.setMinimumSize(560, 640)
        self.setWindowFlag(Qt.Window, True)  # standalone, not modal

        self._paint_node = paint_node
        self._building = False  # guards param-changed callbacks during repop
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(120)
        self._live_timer.timeout.connect(self._live_update)

        self._build_ui()
        self._refresh_engines()
        self._refresh_assets()
        self._populate_from_binding()

    # ── UI construction ─────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Header — engine + material name
        hdr = QGridLayout()
        hdr.setHorizontalSpacing(6)
        hdr.setVerticalSpacing(4)
        hdr.addWidget(QLabel("Engine:"), 0, 0)
        self.cb_engine = QComboBox()
        self.cb_engine.currentIndexChanged.connect(self._on_engine_changed)
        hdr.addWidget(self.cb_engine, 0, 1)

        hdr.addWidget(QLabel("Material name:"), 1, 0)
        self.le_matname = QLineEdit()
        self.le_matname.setPlaceholderText("(auto)")
        hdr.addWidget(self.le_matname, 1, 1)

        hdr.setColumnStretch(1, 1)
        root.addLayout(hdr)

        # Asset list — replaces the old Asset combo + groups panel
        asset_box = QGroupBox("Assets")
        asset_lay = QVBoxLayout(asset_box)
        asset_lay.setContentsMargins(8, 6, 8, 6)
        asset_lay.setSpacing(4)
        self.lw_asset = QListWidget()
        self.lw_asset.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lw_asset.setFixedHeight(120)
        self.lw_asset.currentItemChanged.connect(self._on_asset_changed)
        asset_lay.addWidget(self.lw_asset)
        root.addWidget(asset_box)

        # keep cb_asset as a hidden stub so _current_asset() still works simply
        self.cb_asset = QComboBox()
        self._group_checks = []

        # Textures
        tex_box = QGroupBox("Textures")
        tex_lay = QVBoxLayout(tex_box)
        tex_lay.setContentsMargins(8, 6, 8, 6)
        tex_lay.setSpacing(4)
        self._tex_rows = {}
        for key, lbl, cs in self.TEX_LABELS:
            row = _TextureRow(lbl, cs)
            row.changed.connect(self._on_field_changed)
            tex_lay.addWidget(row)
            self._tex_rows[key] = row
        root.addWidget(tex_box)

        # Parameters
        prm_box = QGroupBox("Parameters")
        prm_lay = QGridLayout(prm_box)
        prm_lay.setContentsMargins(8, 6, 8, 6)
        prm_lay.setHorizontalSpacing(8)
        prm_lay.setVerticalSpacing(4)
        self._parm_widgets = {}

        def add_float(row, key, label, default, lo=0.0, hi=2.0):
            prm_lay.addWidget(QLabel(label), row, 0)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 1000)
            sb = QDoubleSpinBox()
            sb.setDecimals(3)
            sb.setRange(lo, hi)
            sb.setSingleStep(0.01)
            sb.setFixedWidth(80)

            def to_slider(v):
                return int(round((v - lo) / (hi - lo) * 1000))

            def from_slider(s):
                return lo + (s / 1000.0) * (hi - lo)

            def on_slider(v, _sb=sb):
                _sb.blockSignals(True)
                _sb.setValue(from_slider(v))
                _sb.blockSignals(False)
                self._on_param_changed()

            def on_spin(v, _sl=sl):
                _sl.blockSignals(True)
                _sl.setValue(to_slider(v))
                _sl.blockSignals(False)
                self._on_param_changed()

            sl.valueChanged.connect(on_slider)
            sb.valueChanged.connect(on_spin)
            sb.setValue(default)
            on_spin(default)
            prm_lay.addWidget(sl, row, 1)
            prm_lay.addWidget(sb, row, 2)
            self._parm_widgets[key] = ("float", sl, sb, lo, hi)

        def add_color(row, key, label, default):
            prm_lay.addWidget(QLabel(label), row, 0)
            sw = _ColorSwatch()
            sw.set_rgb(default)
            sw.changed.connect(lambda _rgb: self._on_param_changed())
            prm_lay.addWidget(sw, row, 1, 1, 2, Qt.AlignLeft)
            self._parm_widgets[key] = ("color", sw)

        add_color(0,  "basecolor_tint",     "Base Color Tint",    (1.0, 1.0, 1.0))
        add_float(1,  "opacity",            "Opacity",            1.0, 0.0, 1.0)
        add_float(2,  "roughness_mult",     "Roughness Mult",     1.0, 0.0, 2.0)
        add_float(3,  "metallic_mult",      "Metallic Mult",      0.0, 0.0, 1.0)
        add_float(4,  "ior",                "IOR",                1.5, 1.0, 3.0)
        add_float(5,  "transmission",       "Transmission",       0.0, 0.0, 1.0)
        add_float(6,  "coat_weight",        "Coat Weight",        0.0, 0.0, 1.0)
        add_float(7,  "coat_roughness",     "Coat Roughness",     0.1, 0.0, 1.0)
        add_float(8,  "sss_weight",         "SSS Weight",         0.0, 0.0, 1.0)
        add_float(9,  "normal_strength",    "Normal Strength",    1.0, 0.0, 2.0)
        add_float(10, "displace_scale",     "Displace Scale",     0.05, 0.0, 1.0)
        add_float(11, "displace_mid",       "Displace Mid",       0.5, 0.0, 1.0)
        add_color(12, "emission_color",     "Emission Color",     (1.0, 1.0, 1.0))
        add_float(13, "emission_intensity", "Emission Intensity", 0.0, 0.0, 10.0)
        prm_lay.setColumnStretch(1, 1)
        root.addWidget(prm_box)

        # Status + buttons
        bar = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#aaa;")
        bar.addWidget(self.lbl_status, 1)

        self.btn_edit = QPushButton("Edit in Houdini")
        self.btn_edit.setToolTip("Focus the material in Houdini's parameter pane "
                                 "to access every shader parm.")
        self.btn_edit.clicked.connect(self._on_edit_in_houdini)
        bar.addWidget(self.btn_edit)

        self.btn_preview = QPushButton("Show Preview")
        self.btn_preview.setToolTip("Open a floating viewport with a sphere "
                                    "that has this material assigned.")
        self.btn_preview.clicked.connect(self._on_show_preview)
        bar.addWidget(self.btn_preview)

        self.btn_clear = QPushButton("Clear Binding")
        self.btn_clear.clicked.connect(self._on_clear)
        bar.addWidget(self.btn_clear)

        self.btn_apply = QPushButton("Build && Apply")
        self.btn_apply.setStyleSheet(
            "QPushButton { background:#1a5c1a; color:#cffccf; }"
            "QPushButton:hover { background:#236b23; }"
        )
        self.btn_apply.clicked.connect(self._on_apply)
        bar.addWidget(self.btn_apply)
        root.addLayout(bar)

    # ── Population ──────────────────────────────────────────────────────────
    def _refresh_engines(self):
        self.cb_engine.blockSignals(True)
        self.cb_engine.clear()
        engines = available_engines()
        if not engines:
            self.cb_engine.addItem("(no render engine installed)")
            self.cb_engine.setEnabled(False)
            self.btn_apply.setEnabled(False)
        else:
            self.cb_engine.setEnabled(True)
            self.btn_apply.setEnabled(True)
            for e in engines:
                self.cb_engine.addItem(e.NAME)
        self.cb_engine.blockSignals(False)

    def _refresh_assets(self):
        from scatter_tool import logic
        self.lw_asset.blockSignals(True)
        self.lw_asset.clear()
        paths = []
        try:
            if self._paint_node is None:
                paths = []
            elif hasattr(logic, "get_lookdev_asset_paths"):
                paths = logic.get_lookdev_asset_paths(self._paint_node)
            else:
                # Old logic.py — append wire SOP inline so it still shows up here.
                paths = list(logic.get_asset_node_paths(self._paint_node))
                geo = self._paint_node.parent()
                wire = geo.node("crawl_OUT") or geo.node("OUT_wires")
                if wire is not None and wire.path() not in paths:
                    paths.append(wire.path())
        except Exception:
            paths = []
        if not paths:
            placeholder = QListWidgetItem("(no assets — add one to the scatter list first)")
            placeholder.setFlags(Qt.NoItemFlags)
            placeholder.setForeground(QColor("#777"))
            self.lw_asset.addItem(placeholder)
            self.btn_apply.setEnabled(False)
        else:
            self.btn_apply.setEnabled(True)
            for p in paths:
                has_binding = bool(assign.get_binding(self._paint_node, p)) if self._paint_node else False
                _n = hou.node(p)
                display = "Wires Geometry" if (_n is not None and _n.name() in ("crawl_OUT", "OUT_wires")) else p
                label = ("● " if has_binding else "  ") + display
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, p)
                if has_binding:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.lw_asset.addItem(item)
            self.lw_asset.setCurrentRow(0)
        self.lw_asset.blockSignals(False)

    def _refresh_groups(self):
        self._group_checks = []

    def _current_asset(self):
        item = self.lw_asset.currentItem()
        if item is None:
            return ""
        path = item.data(Qt.UserRole)
        return (path or "").strip()

    def _current_engine(self):
        return get_engine(self.cb_engine.currentText())

    # ── Populate from saved binding ─────────────────────────────────────────
    def _populate_from_binding(self):
        self._refresh_groups()
        if self._paint_node is None:
            return
        asset = self._current_asset()
        if not asset:
            return
        b = assign.get_binding(self._paint_node, asset)
        self._building = True
        try:
            if b:
                eng_name = b.get("engine", "")
                idx = self.cb_engine.findText(eng_name)
                if idx >= 0:
                    self.cb_engine.setCurrentIndex(idx)
                self.le_matname.setText(b.get("mat_name", ""))
                tx = b.get("textures") or {}
                for k, row in self._tex_rows.items():
                    row.set_value(tx.get(k, ""))
                pm = b.get("params") or {}
                self._set_params(pm)
                # Restore group selection
                want = set(b.get("groups") or [])
                for cb in self._group_checks:
                    cb.setChecked(cb.text() in want)
            else:
                # Auto-name material from asset
                self.le_matname.setText(self._auto_mat_name(asset))
                for row in self._tex_rows.values():
                    row.set_value("")
                self._set_params({})
                for cb in self._group_checks:
                    cb.setChecked(False)
        finally:
            self._building = False
        self._set_status("")

    def _set_params(self, pm):
        defaults = conventions.DEFAULT_PARMS
        for key, w in self._parm_widgets.items():
            kind = w[0]
            if kind == "float":
                _, sl, sb, lo, hi = w
                val = pm.get(key, defaults.get(key, sb.value()))
                sb.blockSignals(True)
                sl.blockSignals(True)
                sb.setValue(float(val))
                sl.setValue(int(round((float(val) - lo) / (hi - lo) * 1000)))
                sb.blockSignals(False)
                sl.blockSignals(False)
            else:
                _, sw = w
                rgb = pm.get(key, defaults.get(key, (1.0, 1.0, 1.0)))
                if isinstance(rgb, list):
                    rgb = tuple(rgb)
                sw.blockSignals(True)
                sw.set_rgb(rgb)
                sw.blockSignals(False)

    def _collect_params(self):
        out = {}
        for key, w in self._parm_widgets.items():
            if w[0] == "float":
                out[key] = float(w[2].value())
            else:
                out[key] = list(w[1].rgb())
        return out

    def _collect_textures(self):
        return {k: r.value() for k, r in self._tex_rows.items()}

    def _collect_groups(self):
        return [cb.text() for cb in self._group_checks if cb.isChecked()]

    def _auto_mat_name(self, asset_path):
        leaf = (asset_path.rsplit("/", 1)[-1] or "asset").strip()
        return f"{leaf}_mat"

    # ── Callbacks ───────────────────────────────────────────────────────────
    def _on_engine_changed(self, *_):
        if self._building:
            return
        # Engine change is structural — clear material name suggestion if blank
        if not self.le_matname.text().strip():
            self.le_matname.setText(self._auto_mat_name(self._current_asset()))

    def _on_asset_changed(self, current, previous=None):
        if self._building:
            return
        self._populate_from_binding()

    def _on_field_changed(self, *_):
        # Texture-path / group edits → try live update too. If topology
        # changed (slot added/removed), _live_update will auto-rebuild.
        if self._building:
            return
        self._live_timer.start()

    def _on_param_changed(self, *_):
        if self._building:
            return
        self._live_timer.start()

    def _live_update(self):
        """Apply changes to the existing material without rebuilding when
        possible. Auto-rebuilds if the engine reports the texture topology
        has changed (a slot was added or removed)."""
        eng = self._current_engine()
        asset = self._current_asset()
        if eng is None or not asset or self._paint_node is None:
            return
        b = assign.get_binding(self._paint_node, asset)
        if not b:
            return
        mat = hou.node(b.get("mat_path", ""))
        if mat is None:
            return
        params = self._collect_params()
        textures = self._collect_textures()
        groups = self._collect_groups()
        try:
            ok = eng.update(mat, params, textures)
        except Exception as e:
            self._set_status(f"Update error: {e}", error=True)
            return

        if ok is False:
            # Texture slot added/removed — rebuild the graph
            self._set_status("Rebuilding (texture topology changed)…")
            try:
                matnet = eng_base.ensure_matnet("/mat/scatter_lookdev")
                name = b.get("mat_name") or self._auto_mat_name(asset)
                mat = eng.build(matnet, name, textures, params)
            except Exception as e:
                self._set_status(f"Rebuild failed: {e}", error=True)
                return
            b["mat_path"] = mat.path()
            self._update_preview(mat.path())

        b["params"] = params
        b["textures"] = textures
        if b.get("groups") != groups:
            b["groups"] = groups
            assign.set_binding(self._paint_node, asset, b)
            try:
                assign.apply_bindings(self._paint_node)
            except Exception:
                pass
        else:
            assign.set_binding(self._paint_node, asset, b)
        self._set_status("Live-updated.")

    def _on_apply(self):
        eng = self._current_engine()
        if eng is None:
            self._set_status("No engine available.", error=True)
            return
        asset = self._current_asset()
        if not asset or hou.node(asset) is None:
            self._set_status("Pick a valid asset.", error=True)
            return
        if self._paint_node is None:
            self._set_status("No scatter network active.", error=True)
            return

        # Aggressively re-load every lookdev module from disk so any stale
        # cached code (e.g. window left open before a code update) is purged.
        import sys, importlib
        for k in [m for m in sys.modules
                  if m.startswith("scatter_tool.lookdev")
                  and m != __name__]:
            try:
                importlib.reload(sys.modules[k])
            except Exception as ex:
                print(f"[Lookdev] reload({k}) failed: {ex}")
        # Re-resolve engine + base from the freshly-reloaded namespace
        import scatter_tool.lookdev.engines as _eng_pkg
        import scatter_tool.lookdev.engines.base as _eng_base_fresh
        eng = _eng_pkg.get_engine(self.cb_engine.currentText()) or eng
        eng_base_local = _eng_base_fresh
        print(f"[Lookdev] engine module: {eng.__file__ if eng else None}, "
              f"has T_BUILDER: {hasattr(eng, 'T_BUILDER')}")

        name = self.le_matname.text().strip() or self._auto_mat_name(asset)
        textures = self._collect_textures()
        params = self._collect_params()
        groups = self._collect_groups()

        try:
            matnet = eng_base.ensure_matnet("/mat/scatter_lookdev")
            mat = eng.build(matnet, name, textures, params)
        except Exception as e:
            self._set_status(f"Build failed: {e}", error=True)
            return

        binding = {
            "engine":    eng.NAME,
            "mat_name":  name,
            "mat_path":  mat.path(),
            "textures":  textures,
            "params":    params,
            "groups":    groups,
        }
        assign.set_binding(self._paint_node, asset, binding)
        try:
            assign.apply_bindings(self._paint_node)
        except Exception as e:
            self._set_status(f"Material built, but binding failed: {e}", error=True)
            return
        self._update_preview(mat.path())
        self._refresh_asset_indicators()
        self._set_status(f"Built {eng.NAME} shader '{name}' and assigned to '{asset}'.")

    # ── Preview / edit-in-houdini ───────────────────────────────────────────
    def _update_preview(self, mat_path):
        """Keep /obj/scatter_lookdev_preview pointed at the active material."""
        try:
            preview_mod.ensure_preview(mat_path)
        except Exception as e:
            print(f"[Lookdev] preview update failed: {e}")

    def _on_show_preview(self):
        asset = self._current_asset()
        if not asset or self._paint_node is None:
            self._set_status("Pick an asset first.", warn=True)
            return
        b = assign.get_binding(self._paint_node, asset)
        if not b:
            self._set_status("Click Build & Apply first.", warn=True)
            return
        mat_path = b.get("mat_path", "")
        if not hou.node(mat_path):
            self._set_status("Material no longer exists — rebuild.", warn=True)
            return
        try:
            preview_mod.ensure_preview(mat_path)
            preview_mod.show_preview_viewer()
            self._set_status("Preview viewport opened.")
        except Exception as e:
            self._set_status(f"Preview error: {e}", error=True)

    def _on_edit_in_houdini(self):
        asset = self._current_asset()
        if not asset or self._paint_node is None:
            self._set_status("Pick an asset first.", warn=True)
            return
        b = assign.get_binding(self._paint_node, asset)
        if not b:
            self._set_status("Click Build & Apply first.", warn=True)
            return
        mat = hou.node(b.get("mat_path", ""))
        if mat is None:
            self._set_status("Material no longer exists — rebuild.", warn=True)
            return
        # Select the material and reveal it in the parm pane + network editor.
        # The Material is the surface VOP inside the container, which is what
        # the artist usually wants to tweak.
        target = mat.node("Material") or mat.node("standard_surface") or mat
        try:
            target.setSelected(True, clear_all_selected=True)
            for pane in hou.ui.paneTabs():
                if pane.type() == hou.paneTabType.Parm:
                    pane.setCurrentNode(target)
                elif pane.type() == hou.paneTabType.NetworkEditor:
                    pane.cd(mat.path())
            self._set_status(f"Opened {target.path()} in Houdini.")
        except Exception as e:
            self._set_status(f"Could not focus material: {e}", error=True)

    def _on_clear(self):
        asset = self._current_asset()
        if not asset or self._paint_node is None:
            return
        b = assign.get_binding(self._paint_node, asset)
        if b:
            mat = hou.node(b.get("mat_path", ""))
            if mat is not None:
                try:
                    mat.destroy()
                except Exception:
                    pass
        assign.set_binding(self._paint_node, asset, None)
        try:
            assign.apply_bindings(self._paint_node)
        except Exception as e:
            self._set_status(f"Binding clear error: {e}", error=True)
        self._refresh_asset_indicators()
        self._populate_from_binding()
        self._set_status("Cleared binding.")

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _refresh_asset_indicators(self):
        """Update the ● indicator and bold font on list items to reflect
        which assets currently have a binding saved."""
        for i in range(self.lw_asset.count()):
            item = self.lw_asset.item(i)
            path = item.data(Qt.UserRole)
            if not path:
                continue
            has_binding = bool(assign.get_binding(self._paint_node, path)) if self._paint_node else False
            _n = hou.node(path)
            display = "Wires Geometry" if (_n is not None and _n.name() in ("crawl_OUT", "OUT_wires")) else path
            item.setText(("● " if has_binding else "  ") + display)
            f = item.font()
            f.setBold(has_binding)
            item.setFont(f)

    # ── Status helper ───────────────────────────────────────────────────────
    def _set_status(self, msg, warn=False, error=False):
        col = "#aaa"
        if warn:
            col = "#d9a44d"
        if error:
            col = "#d96666"
        self.lbl_status.setStyleSheet(f"color:{col};")
        self.lbl_status.setText(msg)


# ── Module entry ────────────────────────────────────────────────────────────
def open_window(paint_node, parent=None):
    """Open (or reuse) the Lookdev window for the given scatter paint_node."""
    win = LookdevWindow(paint_node, parent=parent)
    win.show()
    win.raise_()
    return win
