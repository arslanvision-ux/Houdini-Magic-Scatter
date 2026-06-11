"""
SP Scatter for Houdini – Main UI  (Python Panel edition)
=========================================================
Designed to live inside a Houdini Python Panel pane tab.

Entry points
------------
  createInterface(kwargs)   ← called by Houdini when the panel opens
  show()                    ← legacy helper; opens a floating window as fallback
  get_window()              ← returns the active ScatterWindow instance

All scatter data is stored as Houdini node userData inside the .hip file,
so nothing is lost on save/load.
"""

import os
import json
import random
import math
from string import Template

import hou

try:
    from PySide2.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
        QSlider, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QScrollArea,
        QLineEdit, QFileDialog, QInputDialog, QMessageBox, QFrame,
        QGridLayout, QAbstractSpinBox, QLayout, QSizePolicy, QApplication,
        QTabWidget, QToolButton, QDialog, QDialogButtonBox,
        QColorDialog, QRadioButton, QButtonGroup, QSplitter, QMenu,
    )
    from PySide2.QtCore import Qt, QRect, QPoint, QPointF, QSize, Signal, QTimer
    from PySide2.QtGui import QPixmap, QColor, QIcon, QFont, QImage, QPainter, QRadialGradient
except ImportError:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
        QSlider, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QScrollArea,
        QLineEdit, QFileDialog, QInputDialog, QMessageBox, QFrame,
        QGridLayout, QAbstractSpinBox, QLayout, QSizePolicy, QApplication,
        QTabWidget, QToolButton, QDialog, QDialogButtonBox,
        QColorDialog, QRadioButton, QButtonGroup, QSplitter, QMenu,
    )
    from PySide6.QtCore import Qt, QRect, QPoint, QPointF, QSize, Signal, QTimer
    from PySide6.QtGui import QPixmap, QColor, QIcon, QFont, QImage, QPainter, QRadialGradient

from scatter_tool import logic, thumbnail
from scatter_tool import raycast as rc

# ---------------------------------------------------------------------------
# Constants / slider ranges  (kept in one place so they're easy to tune)
# ---------------------------------------------------------------------------
TOOL_VERSION = logic.TOOL_VERSION

RADIUS_MIN,  RADIUS_MAX,  RADIUS_DEF   =    0.1,   10.0,    1.0
DENS_MIN,    DENS_MAX,    DENS_DEF     =  0.001,    1.0,    2.5
SPC_MIN,     SPC_MAX,     SPC_DEF      =  0.001,    1.0,    0.5
FAL_AMT_MIN, FAL_AMT_MAX, FAL_AMT_DEF =    0.0,    1.0,    1.0
FAL_SFT_MIN, FAL_SFT_MAX, FAL_SFT_DEF =   -1.0,    1.0,    0.5
RELAX_MIN,   RELAX_MAX,   RELAX_DEF   =      0,    100,     10

# Asset thumbnail size presets: (card_w, card_h, thumb_px)
_ASSET_SIZE_PRESETS = {
    "small":  ( 80, 118,  50),
    "medium": (110, 158, 100),
    "large":  (150, 205, 130),
    "huge":   (200, 265, 180),
}

def debounce(wait_ms):
    """Decorator that postpones function execution until after wait_ms have elapsed
       since the last time it was invoked. Reduces network cook overhead during dragging."""
    def decorator(fn):
        def debounced(self, *args, **kwargs):
            timer_name = f"_debounce_timer_{fn.__name__}"
            if not hasattr(self, timer_name):
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda: fn(self, *getattr(self, f"_debounce_args_{fn.__name__}", ()), **getattr(self, f"_debounce_kwargs_{fn.__name__}", {})))
                setattr(self, timer_name, timer)
            else:
                timer = getattr(self, timer_name)
            setattr(self, f"_debounce_args_{fn.__name__}", args)
            setattr(self, f"_debounce_kwargs_{fn.__name__}", kwargs)
            timer.start(wait_ms)
        return debounced
    return decorator



MAX_PTS_MIN, MAX_PTS_MAX, MAX_PTS_DEF =      1, 1000000, 1000000
OVLP_TOL_MIN, OVLP_TOL_MAX, OVLP_TOL_DEF = 0.1,    50.0,    1.0
ROT_MIN_DEF, ROT_MAX_DEF             =    0.0,    1.0
CONE_DEF                             =    0.0
SCL_MIN_DEF, SCL_MAX_DEF            =    0.0,    1.0
PSCALE_RAND_DEF                     =    1.0
ROT_RAND_DEF                        =    1.0
GS_MIN,      GS_MAX,      GS_DEF     =    0.0,  100.0,    0.5
IVY_GS_MAX                           =    10.0
WT_MIN,      WT_MAX,      WT_DEF     =    0.0,    1.0,    1.0
MDIST_MIN,   MDIST_MAX,   MDIST_DEF  =    0.0,  100.0,    0.0

# Ivy parameter defaults (mirrors logic.IVY_PARM_SPECS)
IVY_DEFAULTS = {
    "ivy_seed":            2789,
    "ivy_max_strands":     333,
    "ivy_mask_threshold":  0.504,
    "ivy_strand_length":   9.182,
    "ivy_step_size":       0.888,
    "ivy_gravity":         0.0,
    "ivy_droop_bias":      0.0,
    "ivy_inertia":         0.0,
    "ivy_curl":            0.0,
    "ivy_randomness":      0.25,
    # Point jitter
    "ivy_jitter_scale":    0.0,
    "ivy_jitter_seed":     0,
    # Wire appearance
    "ivy_wire_radius":     0.008,
    "ivy_wire_segs":       5,
    "ivy_wire_divisions":  5,
}
IVY_SIM_DEFAULTS = {
    "ivy_sim_gravity":     -9.8,
    "ivy_sim_substeps":     2,
    "ivy_sim_stiffness":    0.5,
    "ivy_sim_bend":         0.3,
    "ivy_sim_damping":      0.1,
    "ivy_sim_start_frame":  1,
    "ivy_sim_end_frame":    100,
}
# Crawling Ivy defaults — mirror logic.CRAWL_PARM_SPECS
CRAWL_DEFAULTS = {
    "crawl_seed":            7,
    "crawl_n_seeds":         60,
    "crawl_strand_length":   8.0,
    "crawl_step_size":       0.1,
    "crawl_adherence":       0.25,
    "crawl_gravity":         0.5,
    "crawl_upward_bias":     0.6,
    "crawl_lag":             6,
    "crawl_gain":            0.25,
    "crawl_noise":           0.05,
    "crawl_branch_prob":     0.015,
    "crawl_branch_angle":    45.0,
    "crawl_max_depth":       3,
    "crawl_min_strands":     0.3,
    "crawl_wire_radius":     0.01,
    "crawl_wire_segs":       1,
    "crawl_wire_divisions":  5,
}

# Float parameters that use an integer QSlider internally (value * scale = slider int).
# crawl_wire_radius is no longer here — it now uses a QDoubleSpinBox with no upper limit.
_CRAWL_FLOAT_SLIDER_SCALES = {
}

STAMP_BLEND_MODES = [
    "Multiply", "Add", "Screen", "Overlay",
    "Subtract", "Divide", "Average", "Max", "Min",
]
STAMP_BLEND_MODE_KEYS = [
    "multiply", "add", "screen", "overlay",
    "subtract", "divide", "average", "over", "min",
]

IVY_PRESETS = {
    "Sparse": dict(ivy_max_strands=40,  ivy_strand_length=1.8, ivy_gravity=0.3,  ivy_droop_bias=0.5, ivy_curl=0.15, ivy_randomness=0.1),
    "Dense":  dict(ivy_max_strands=400, ivy_strand_length=3.5, ivy_gravity=0.5,  ivy_droop_bias=1.0, ivy_curl=0.4,  ivy_randomness=0.25),
    "Drape":  dict(ivy_max_strands=150, ivy_strand_length=4.5, ivy_gravity=0.9,  ivy_droop_bias=2.0, ivy_curl=0.1,  ivy_inertia=0.6),
    "Wild":   dict(ivy_max_strands=200, ivy_strand_length=2.5, ivy_gravity=0.25, ivy_droop_bias=0.4, ivy_curl=1.2,  ivy_randomness=0.6),
}

CRAWL_PRESETS = {
    "Sparse":   dict(crawl_n_seeds=25,  crawl_strand_length=5.0,  crawl_branch_prob=0.005, crawl_max_depth=2,
                     crawl_gravity=0.4, crawl_upward_bias=0.6, crawl_noise=0.04),
    "Dense":    dict(crawl_n_seeds=200, crawl_strand_length=10.0, crawl_branch_prob=0.03,  crawl_max_depth=4,
                     crawl_gravity=0.4, crawl_upward_bias=0.6, crawl_noise=0.05),
    "Climbing": dict(crawl_n_seeds=80,  crawl_strand_length=12.0, crawl_gravity=0.1, crawl_upward_bias=0.95,
                     crawl_gain=0.35, crawl_lag=4,  crawl_noise=0.03, crawl_branch_prob=0.01),
    "Hanging":  dict(crawl_n_seeds=80,  crawl_strand_length=8.0,  crawl_gravity=1.5, crawl_upward_bias=0.1,
                     crawl_gain=0.15, crawl_lag=10, crawl_noise=0.04, crawl_branch_prob=0.012),
    "Wild":     dict(crawl_n_seeds=120, crawl_strand_length=9.0,  crawl_branch_prob=0.06, crawl_branch_angle=70.0,
                     crawl_max_depth=5, crawl_noise=0.18, crawl_gain=0.4),
    # Directional, lightly-branched long runners — vines reaching out across a wall.
    "Tendrils": dict(crawl_n_seeds=40,  crawl_strand_length=18.0, crawl_branch_prob=0.003, crawl_max_depth=2,
                     crawl_gain=0.15, crawl_lag=12, crawl_noise=0.02,
                     crawl_upward_bias=0.7, crawl_gravity=0.3),
    # Many short, near-horizontal strands — flat ground/floor coverage.
    "Carpet":   dict(crawl_n_seeds=400, crawl_strand_length=2.5,  crawl_step_size=0.08,
                     crawl_branch_prob=0.005, crawl_max_depth=1,
                     crawl_upward_bias=0.3, crawl_gravity=0.2, crawl_noise=0.06),
    # Few seeds with explosive recursive branching — radial web look.
    "Spider":   dict(crawl_n_seeds=20,  crawl_strand_length=6.0,  crawl_branch_prob=0.08,
                     crawl_branch_angle=60.0, crawl_max_depth=6, crawl_noise=0.07,
                     crawl_gain=0.3),
    # Low-noise responsive controller — clean elegant curves.
    "Smooth":   dict(crawl_n_seeds=80,  crawl_strand_length=7.0,
                     crawl_gain=0.45, crawl_lag=2,  crawl_noise=0.005,
                     crawl_branch_prob=0.008, crawl_branch_angle=30.0,
                     crawl_upward_bias=0.7),
    # Maximum coverage — full overgrowth, expensive to cook.
    "Overgrown":dict(crawl_n_seeds=500, crawl_strand_length=14.0, crawl_branch_prob=0.05,
                     crawl_max_depth=5, crawl_branch_angle=55.0, crawl_noise=0.08),
    # Mid density with delicate wire + extra divisions for hero shots.
    "Fine Mesh":dict(crawl_n_seeds=150, crawl_strand_length=6.0,
                     crawl_branch_prob=0.02, crawl_max_depth=3,
                     crawl_wire_radius=0.005, crawl_wire_segs=6, crawl_wire_divisions=12),
}

# Path for user-saved ivy presets (persisted across sessions)
def _ivy_user_presets_path():
    try:
        base = hou.homeHoudiniDirectory()
    except Exception:
        base = os.path.expanduser("~")
    return os.path.join(base, "sp_scatter_ivy_presets.json")


def _crawl_user_presets_path():
    try:
        base = hou.homeHoudiniDirectory()
    except Exception:
        base = os.path.expanduser("~")
    return os.path.join(base, "sp_scatter_crawl_presets.json")


# Magic Scatter biome presets — distribution + scale + rotation + noise
# values calibrated to mimic real-world biome character. Density/distance values
# assume a roughly 10×10 unit surface; users can tweak after applying. Combo
# values are stored as the exact display strings shown in their dropdowns.
BIOME_PARAM_KEYS = (
    # distribution
    "dens", "spacing", "min_distance", "relax_iter",
    "f_amt", "f_soft", "max_pts",
    # rotation
    "cone_angle", "full_rand",
    # scale
    "gs", "uniform_xyz", "scale_min", "scale_max",
    # altitude (elevation-as-temperature mask, 0..1 of terrain Y range)
    "altitude_enabled", "elev_min", "elev_max", "elev_falloff",
    # slope mask (0=flat, 1=vertical cliff)
    "slope_max", "slope_falloff",
    # noise (subset that defines ecological pattern)
    "scatter_noise_enabled", "scatter_noise_type",
    "scatter_noise_element_size", "scatter_noise_amplitude",
    "scatter_noise_fractal_type", "scatter_noise_max_octaves",
    "scatter_noise_lacunarity", "scatter_noise_roughness",
    "scatter_noise_operation", "scatter_noise_range",
)

def _biome(dens, spacing, mdist, relax, soft, maxpts, cone, gs, smin, smax,
           emin=0.0, emax=1.0, efall=0.10,
           slmax=0.55, slfall=0.10,
           ntype="Perlin", namp=0.5, nsize=4.0, nfract="Standard (fBm)",
           noct=3, nlac=2.0, nrough=0.5):
    return dict(
        dens=dens, spacing=spacing, min_distance=mdist, relax_iter=relax,
        f_amt=1.0, f_soft=soft, max_pts=maxpts,
        cone_angle=cone, full_rand=True,
        gs=gs, uniform_xyz=True, scale_min=smin, scale_max=smax,
        altitude_enabled=True,
        elev_min=emin, elev_max=emax, elev_falloff=efall,
        slope_max=slmax, slope_falloff=slfall,
        scatter_noise_enabled=True,
        scatter_noise_type=ntype,
        scatter_noise_amplitude=namp,
        scatter_noise_element_size=nsize,
        scatter_noise_fractal_type=nfract,
        scatter_noise_max_octaves=noct,
        scatter_noise_lacunarity=nlac,
        scatter_noise_roughness=nrough,
        scatter_noise_operation="Multiply",
        scatter_noise_range="Positive",
    )

BIOME_PRESETS = {
    # ── Tropical Rainforest ──────────────────────────────────────────────
    "Tropical Rainforest: Lowland":   _biome(2.5, 0.20, 0.15, 4, 0.40, 200000, 12, 1.00, 0.5, 1.8,
                                             emin=0.00, emax=0.30, efall=0.12,
                                             slmax=0.50, slfall=0.10,
                                             namp=0.4, nsize=4.0),
    "Tropical Rainforest: Montane":   _biome(1.8, 0.30, 0.22, 5, 0.50, 150000, 18, 0.85, 0.6, 1.4,
                                             emin=0.30, emax=0.70, efall=0.10,
                                             slmax=0.55, slfall=0.10,
                                             namp=0.5, nsize=3.0, noct=3, nrough=0.6),
    "Tropical Rainforest: Mangrove":  _biome(1.5, 0.40, 0.35, 10, 0.30, 100000, 8, 1.00, 0.8, 1.3,
                                             emin=0.00, emax=0.05, efall=0.04,
                                             slmax=0.12, slfall=0.06,
                                             ntype="Worley Cellular F1", namp=0.3, nsize=2.0,
                                             nfract="None", noct=1),
    # ── Temperate Forest ────────────────────────────────────────────────
    "Temperate Forest: Deciduous":    _biome(1.0, 0.60, 0.50, 8, 0.50, 80000, 18, 1.00, 0.8, 1.4,
                                             emin=0.00, emax=0.60, efall=0.15,
                                             slmax=0.45, slfall=0.10,
                                             namp=0.5, nsize=5.0),
    "Temperate Forest: Mixed":        _biome(0.85, 0.65, 0.55, 7, 0.55, 80000, 18, 1.00, 0.7, 1.5,
                                             emin=0.10, emax=0.70, efall=0.15,
                                             slmax=0.50, slfall=0.10,
                                             namp=0.6, nsize=6.0, noct=4, nrough=0.55),
    "Temperate Forest: Coniferous":   _biome(0.8, 0.70, 0.65, 12, 0.55, 80000, 12, 1.10, 0.9, 1.2,
                                             emin=0.20, emax=0.80, efall=0.12,
                                             slmax=0.55, slfall=0.10,
                                             ntype="Worley Cellular F1", namp=0.3, nsize=4.0,
                                             nfract="None", noct=1),
    "Temperate Forest: Mediterranean":_biome(0.5, 1.00, 0.85, 4, 0.45, 60000, 20, 0.90, 0.6, 1.3,
                                             emin=0.00, emax=0.55, efall=0.15,
                                             slmax=0.40, slfall=0.10,
                                             namp=0.7, nsize=8.0, noct=4, nlac=2.2, nrough=0.6),
    # ── Boreal Forest ────────────────────────────────────────────────────
    "Boreal Forest: Conifer Stand":   _biome(0.6, 0.85, 0.80, 14, 0.50, 50000, 10, 1.20, 0.9, 1.15,
                                             emin=0.30, emax=0.80, efall=0.10,
                                             slmax=0.45, slfall=0.10,
                                             ntype="Worley Cellular F1", namp=0.35, nsize=5.0,
                                             nfract="None", noct=1),
    "Boreal Forest: Lichen Woodland": _biome(0.3, 1.50, 1.20, 8, 0.60, 40000, 12, 1.00, 0.85, 1.2,
                                             emin=0.40, emax=0.85, efall=0.10,
                                             slmax=0.50, slfall=0.10,
                                             ntype="Worley Cellular F2-F1", namp=0.5, nsize=8.0,
                                             nfract="None", noct=1),
    # ── Savanna ──────────────────────────────────────────────────────────
    "Savanna: Tree":                  _biome(0.18, 2.00, 1.50, 2, 0.35, 20000, 18, 1.00, 0.7, 1.5,
                                             emin=0.00, emax=0.45, efall=0.15,
                                             slmax=0.25, slfall=0.10,
                                             ntype="Worley Cellular F1", namp=0.8, nsize=10.0,
                                             nfract="None", noct=1),
    "Savanna: Grass":                 _biome(2.5, 0.20, 0.15, 4, 0.45, 200000, 22, 0.80, 0.7, 1.3,
                                             emin=0.00, emax=0.50, efall=0.15,
                                             slmax=0.20, slfall=0.08,
                                             namp=0.4, nsize=4.0),
    "Savanna: Acacia":                _biome(0.10, 2.50, 2.00, 1, 0.30, 10000, 14, 1.10, 0.8, 1.4,
                                             emin=0.00, emax=0.40, efall=0.12,
                                             slmax=0.30, slfall=0.10,
                                             ntype="Worley Cellular F1", namp=1.0, nsize=14.0,
                                             nfract="None", noct=1),
    # ── Temperate Grassland ──────────────────────────────────────────────
    "Temperate Grassland: Prairie":   _biome(3.0, 0.15, 0.10, 3, 0.50, 250000, 24, 0.85, 0.85, 1.15,
                                             emin=0.00, emax=0.55, efall=0.15,
                                             slmax=0.18, slfall=0.08,
                                             namp=0.2, nsize=3.0, noct=2),
    "Temperate Grassland: Steppe":    _biome(1.5, 0.30, 0.25, 4, 0.40, 150000, 20, 0.70, 0.7, 1.2,
                                             emin=0.00, emax=0.55, efall=0.15,
                                             slmax=0.25, slfall=0.10,
                                             namp=0.5, nsize=6.0, noct=3, nrough=0.6),
    "Temperate Grassland: Meadow":    _biome(2.2, 0.20, 0.15, 4, 0.55, 200000, 22, 0.90, 0.6, 1.5,
                                             emin=0.05, emax=0.55, efall=0.15,
                                             slmax=0.22, slfall=0.08,
                                             namp=0.4, nsize=2.5, noct=3, nlac=2.2),
    # ── Desert ───────────────────────────────────────────────────────────
    "Desert: Cover":                  _biome(0.08, 3.00, 2.50, 0, 0.30, 8000, 10, 0.70, 0.4, 1.2,
                                             emin=0.00, emax=0.50, efall=0.12,
                                             slmax=0.65, slfall=0.12,
                                             ntype="Worley Cellular F1", namp=1.0, nsize=12.0,
                                             nfract="None", noct=1),
    "Desert: Sandy":                  _biome(0.03, 5.00, 4.00, 0, 0.25, 3000, 8, 0.60, 0.5, 1.1,
                                             emin=0.00, emax=0.45, efall=0.10,
                                             slmax=0.12, slfall=0.06,
                                             ntype="Worley Cellular F2-F1", namp=1.5, nsize=20.0,
                                             nfract="None", noct=1),
    "Desert: Rocky":                  _biome(0.10, 2.50, 2.00, 1, 0.35, 10000, 15, 0.80, 0.5, 1.4,
                                             emin=0.10, emax=0.65, efall=0.12,
                                             slmax=0.75, slfall=0.12,
                                             ntype="Worley Cellular F1", namp=0.9, nsize=8.0,
                                             nfract="None", noct=1),
    "Desert: Coastal":                _biome(0.15, 2.00, 1.60, 2, 0.40, 15000, 12, 0.75, 0.5, 1.2,
                                             emin=0.00, emax=0.10, efall=0.05,
                                             slmax=0.15, slfall=0.06,
                                             namp=0.7, nsize=8.0, noct=3, nrough=0.55),
    # ── Tundra ───────────────────────────────────────────────────────────
    "Tundra: Arctic":                 _biome(0.20, 1.50, 1.20, 6, 0.60, 20000, 28, 0.50, 0.7, 1.0,
                                             emin=0.65, emax=1.00, efall=0.10,
                                             slmax=0.35, slfall=0.10,
                                             namp=0.5, nsize=3.0, noct=3, nrough=0.6),
    "Tundra: Alpine":                 _biome(0.12, 2.00, 1.60, 3, 0.40, 12000, 32, 0.45, 0.5, 1.3,
                                             emin=0.75, emax=1.00, efall=0.08,
                                             slmax=0.65, slfall=0.12,
                                             ntype="Worley Cellular F1", namp=0.7, nsize=6.0,
                                             nfract="None", noct=1),
}


def _biome_user_presets_path():
    try:
        base = hou.homeHoudiniDirectory()
    except Exception:
        base = os.path.expanduser("~")
    return os.path.join(base, "sp_scatter_biome_presets.json")


def _global_preset_path(mode="scatter"):
    try:
        base = hou.homeHoudiniDirectory()
    except Exception:
        base = os.path.expanduser("~")
    suffix = {"ivy": "ivy", "crawling_ivy": "crawl"}.get(mode, "scatter")
    return os.path.join(base, f"sp_scatter_global_presets_{suffix}.json")


def _set_preset_widget(widget, value):
    """Set a single widget's value from a preset dict, handling all widget types.

    Spinboxes intentionally do NOT block signals so that their linked slider
    (_sb_to_sl callback from _link_slider_spinbox) fires and the slider moves
    visually.  All other widget types block signals to avoid cascade side-effects.
    _prevent_sync=True in _apply_global_preset gates any actual Houdini syncs.
    """
    if widget is None:
        return
    if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
        widget.setValue(value)
    elif isinstance(widget, QCheckBox):
        widget.blockSignals(True)
        try:
            widget.setChecked(bool(value))
        finally:
            widget.blockSignals(False)
    elif isinstance(widget, QComboBox):
        widget.blockSignals(True)
        try:
            if isinstance(value, str):
                idx = widget.findText(value)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            else:
                widget.setCurrentIndex(int(value))
        finally:
            widget.blockSignals(False)
    elif isinstance(widget, QLineEdit):
        widget.blockSignals(True)
        try:
            widget.setText(str(value))
        finally:
            widget.blockSignals(False)
    elif hasattr(widget, "setValue"):
        widget.setValue(value)


# ---------------------------------------------------------------------------
# Module-level window references (viewer state callbacks use these)
# ---------------------------------------------------------------------------
# `_window` is the SP Scatter (paint) window — raycast/viewer-state callbacks
# resolve through it. `_window_ivy` is the independent Ivy Scatter window
# (no paint, no raycast). Both can be open simultaneously; each owns its
# own state and target network.
_window = None
_window_ivy = None
_window_crawling_ivy = None
_last_scatter_sop_path = None  # Track last active scatter network for auto-resume


def get_window():
    return _window


def get_ivy_window():
    return _window_ivy


def get_active_painter():
    """
    Return whichever ScatterWindow currently has paint or erase toggled on.
    Used by the raycast viewer state so hits and state-exit callbacks route
    to the window that started the paint session — not always the SP
    Scatter window. Falls back to `_window` (then `_window_ivy`) if neither
    is actively painting.
    """
    for win in (_window, _window_ivy):
        if win is None:
            continue
        try:
            if win.p_btn.isChecked() or win.e_btn.isChecked():
                return win
        except (AttributeError, RuntimeError):
            # Widget destroyed or paint widgets not present on this window.
            pass
    return _window if _window is not None else _window_ivy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _h_sep():
    """Thin horizontal separator line."""
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #444;")
    return f


# ---------------------------------------------------------------------------
# Themes & Stylesheet
# ---------------------------------------------------------------------------
# Stylesheet is built from a Template — each theme provides a dict of color
# tokens, and _build_stylesheet(theme) substitutes them.  Adding a new theme
# means adding an entry to THEMES with the same keys.
# Note: a few semantic colors (paint=blue, erase=orange, clear=red, Sim/Ivy
# tab tints) are intentionally NOT themed — they signal action type.

STYLE_TEMPLATE = Template("""
QWidget {
    background-color: ${bg};
    color: ${text};
    font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
    font-size: 11px;
}
QGroupBox {
    font-weight: bold;
    border: 1px solid ${border};
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 14px;
    background-color: ${panel_bg};
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: ${accent};
}
QPushButton {
    background-color: ${btn_bg};
    border: 1px solid ${btn_border};
    border-radius: 4px;
    padding: 5px 8px;
    font-weight: bold;
    color: ${text};
}
QPushButton:hover  { background-color: ${btn_border}; border-color: ${accent}; }
QPushButton:pressed { background-color: ${btn_pressed}; }
QPushButton:checked { background-color: ${success_bg}; color: ${success}; border-color: ${success}; }
QPushButton:disabled { color: ${text_disabled}; border-color: ${border_disabled}; }

QPushButton#paint_btn { color: #7ab0ff; border-color: #3a5a8a; }
QPushButton#paint_btn:checked { background-color: #1a3a6a; color: #9fd0ff; border-color: #7ab0ff; }
QPushButton#erase_btn { color: #ff9a7a; border-color: #8a4a3a; }
QPushButton#erase_btn:checked { background-color: #6a2a1a; color: #ffb090; border-color: #ff7050; }
QPushButton#clear_btn { color: ${danger}; border-color: #6a2020; }
QPushButton#clear_btn:hover { background-color: ${danger_bg}; }

QTabWidget::pane { border: 1px solid ${border_dim}; background: ${bg}; }
QTabBar::tab {
    background: ${tab_inactive_bg}; color: ${text_dim}; padding: 5px 14px;
    border: 1px solid ${border_dim}; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
}
/* Selected tab → green highlight across every QTabBar.
   Per-widget stylesheets (e.g. Sim tab brown tint) keep their override. */
QTabBar::tab:selected { background: #1e4a30; color: #7fff9a; border-color: #2d6644; border-bottom: 1px solid #1e4a30; }
QTabBar::tab:hover { background: #245c3a; color: #7fff9a; }

QComboBox {
    background-color: ${input_bg}; border: 1px solid ${border};
    border-radius: 3px; padding: 3px 8px; color: ${accent};
}
QComboBox QAbstractItemView { background: ${input_bg}; color: ${text}; selection-background-color: ${accent_dim}; }

QDoubleSpinBox, QSpinBox {
    background-color: ${input_bg}; border: 1px solid ${border};
    border-radius: 3px; padding: 2px 4px; color: ${text};
}
QDoubleSpinBox:focus, QSpinBox:focus { border-color: ${accent}; }

QSlider::groove:horizontal {
    border: 1px solid ${border_dim}; height: 4px;
    background: ${input_bg}; margin: 2px 0; border-radius: 2px;
}
QSlider::handle:horizontal {
    background: ${accent}; border: 1px solid ${accent_dim};
    width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
}
QSlider::sub-page:horizontal { background: ${accent_dim}; border-radius: 2px; }

QScrollArea { border: 1px solid ${border}; border-radius: 4px; background: ${input_bg}; }
QScrollBar:vertical { background: ${panel_bg}; width: 10px; }
QScrollBar::handle:vertical { background: ${border}; border-radius: 4px; min-height: 20px; }

QCheckBox::indicator { width: 14px; height: 14px; border-radius: 3px; border: 1px solid ${border_dim}; background: ${input_bg}; }
QCheckBox::indicator:checked { background: ${accent_dim}; border-color: ${accent}; }

QLineEdit {
    background: ${input_bg}; border: 1px solid ${border};
    border-radius: 3px; padding: 2px 6px; color: ${text};
}
QLineEdit:focus { border-color: ${accent}; }

QLabel#section_header { color: ${accent}; font-weight: bold; font-size: 12px; }
QLabel#info_label { color: ${accent}; font-size: 10px; }
QLabel#count_label { color: ${success}; font-weight: bold; font-size: 12px; }
""")

# Theme dictionaries — each must define every token used by STYLE_TEMPLATE.
THEMES = {
    "Dark Blue": {
        "bg": "#2c2c2c", "panel_bg": "#272727", "input_bg": "#1e1e1e",
        "text": "#dddddd", "text_dim": "#aaaaaa", "text_disabled": "#666666",
        "border": "#484848", "border_dim": "#444444", "border_disabled": "#3a3a3a",
        "accent": "#7ab0ff", "accent_dim": "#3a5a8a",
        "success": "#5fdb5f", "success_bg": "#1e4a1e",
        "danger": "#ff6060", "danger_bg": "#5a1a1a",
        "btn_bg": "#3c3c3c", "btn_border": "#505050", "btn_pressed": "#252525",
        "tab_inactive_bg": "#333333",
    },
    "Dark Green": {
        "bg": "#222a22", "panel_bg": "#1d251d", "input_bg": "#161d16",
        "text": "#dddddd", "text_dim": "#a8b8a8", "text_disabled": "#5a6a5a",
        "border": "#3e4a3e", "border_dim": "#384238", "border_disabled": "#2e352e",
        "accent": "#7fdf7f", "accent_dim": "#2d6634",
        "success": "#5fdb5f", "success_bg": "#1e4a1e",
        "danger": "#ff6060", "danger_bg": "#5a1a1a",
        "btn_bg": "#2f3a2f", "btn_border": "#46544a", "btn_pressed": "#1a221a",
        "tab_inactive_bg": "#283028",
    },
    "Dark Orange": {
        "bg": "#2c2620", "panel_bg": "#27211b", "input_bg": "#1d1814",
        "text": "#e8dcc8", "text_dim": "#b8a890", "text_disabled": "#6e604e",
        "border": "#4a3e30", "border_dim": "#42382c", "border_disabled": "#352d24",
        "accent": "#ffb86c", "accent_dim": "#8b5a2b",
        "success": "#a8d860", "success_bg": "#3a4a18",
        "danger": "#ff6060", "danger_bg": "#5a1a1a",
        "btn_bg": "#3c3528", "btn_border": "#544738", "btn_pressed": "#251f18",
        "tab_inactive_bg": "#332b22",
    },
    "Dark Purple": {
        "bg": "#272430", "panel_bg": "#221f2a", "input_bg": "#1a1722",
        "text": "#e0dceb", "text_dim": "#a89fc0", "text_disabled": "#605870",
        "border": "#463e58", "border_dim": "#3e3850", "border_disabled": "#2d2838",
        "accent": "#c08aff", "accent_dim": "#5a3a8a",
        "success": "#5fdb5f", "success_bg": "#1e4a1e",
        "danger": "#ff6080", "danger_bg": "#5a1a30",
        "btn_bg": "#36304a", "btn_border": "#4a4060", "btn_pressed": "#221c30",
        "tab_inactive_bg": "#2d2838",
    },
    "Midnight": {
        "bg": "#181c28", "panel_bg": "#13172a", "input_bg": "#0d1020",
        "text": "#d8e0f0", "text_dim": "#8898b8", "text_disabled": "#4a5870",
        "border": "#2c3550", "border_dim": "#252e44", "border_disabled": "#1c2238",
        "accent": "#7ab0ff", "accent_dim": "#1f3a6a",
        "success": "#5fdb9f", "success_bg": "#0e3a2a",
        "danger": "#ff6080", "danger_bg": "#3a1024",
        "btn_bg": "#1f2a40", "btn_border": "#2e3a55", "btn_pressed": "#10162a",
        "tab_inactive_bg": "#1a2030",
    },
    "Light": {
        "bg": "#ececec", "panel_bg": "#f4f4f4", "input_bg": "#ffffff",
        "text": "#202020", "text_dim": "#606060", "text_disabled": "#a0a0a0",
        "border": "#b0b0b0", "border_dim": "#c4c4c4", "border_disabled": "#d4d4d4",
        "accent": "#1f6fdc", "accent_dim": "#a8c8ec",
        "success": "#1f8a32", "success_bg": "#cfeacf",
        "danger": "#c63030", "danger_bg": "#f3d4d4",
        "btn_bg": "#dadada", "btn_border": "#b8b8b8", "btn_pressed": "#c0c0c0",
        "tab_inactive_bg": "#d8d8d8",
    },
}

DEFAULT_THEME = "Dark Blue"


def _build_stylesheet(theme_name):
    """Resolve a theme name to its full qss string, falling back to default."""
    tokens = THEMES.get(theme_name) or THEMES[DEFAULT_THEME]
    return STYLE_TEMPLATE.substitute(**tokens)


def _theme_pref_path():
    """Path to the JSON file storing the user's last-selected theme."""
    try:
        base = hou.homeHoudiniDirectory()
    except Exception:
        base = os.path.expanduser("~")
    return os.path.join(base, "sp_scatter_theme.json")


def _user_themes_path():
    """Path to the JSON file holding user-defined themes/skins.

    Format (a JSON object mapping theme name -> token dict):
        {
          "My Theme": {
            "bg": "#1a1a22", "panel_bg": "#15151c", "input_bg": "#0e0e14",
            "text": "#e0e0f0", "accent": "#ff80c0", ...
          }
        }
    Any tokens you omit are filled from the Dark Blue defaults.
    Names matching a built-in theme are ignored.
    """
    try:
        base = hou.homeHoudiniDirectory()
    except Exception:
        base = os.path.expanduser("~")
    return os.path.join(base, "sp_scatter_themes.json")


def _load_user_themes():
    """Load + validate user themes, filling missing tokens from defaults."""
    path = _user_themes_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Magic Scatter World] Failed to load user themes from {path}: {e}")
        return {}
    if not isinstance(data, dict):
        return {}
    base = THEMES[DEFAULT_THEME]
    out = {}
    for name, tokens in data.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if name in THEMES:
            print(f"[Magic Scatter World] Skipping user theme '{name}' (reserved built-in name).")
            continue
        if not isinstance(tokens, dict):
            print(f"[Magic Scatter World] Skipping user theme '{name}' (must be an object).")
            continue
        merged = dict(base)
        for k, v in tokens.items():
            if k in base and isinstance(v, str):
                merged[k] = v
        out[name] = merged
    return out


# Snapshot built-in names BEFORE merging in user themes — so the editor can
# tell them apart and protect built-ins from being edited or deleted.
BUILTIN_THEMES = frozenset(THEMES.keys())

# Merge user themes into the built-in set so they appear in the dropdown.
THEMES.update(_load_user_themes())


# Token groupings for the skin editor dialog (label, [token, …]).
SKIN_TOKEN_GROUPS = [
    ("Surface",      ["bg", "panel_bg", "input_bg"]),
    ("Text",         ["text", "text_dim", "text_disabled"]),
    ("Borders",      ["border", "border_dim", "border_disabled"]),
    ("Accent",       ["accent", "accent_dim"]),
    ("Status",       ["success", "success_bg", "danger", "danger_bg"]),
    ("Buttons/Tabs", ["btn_bg", "btn_border", "btn_pressed", "tab_inactive_bg"]),
]

# Hint text shown below each token in the editor (kept terse).
SKIN_TOKEN_HINTS = {
    "bg":               "Window background",
    "panel_bg":         "Group/panel background",
    "input_bg":         "Combo/spin/line input bg",
    "text":             "Primary text color",
    "text_dim":         "Secondary / inactive text",
    "text_disabled":    "Disabled text",
    "border":           "Primary border color",
    "border_dim":       "Subtle border / separator",
    "border_disabled":  "Disabled border",
    "accent":           "Titles, focus, slider handle",
    "accent_dim":       "Slider track, subtle accent",
    "success":          "Success text / checked btn",
    "success_bg":       "Checked button background",
    "danger":           "Error / danger color",
    "danger_bg":        "Danger button hover bg",
    "btn_bg":           "Default button background",
    "btn_border":       "Button border / hover bg",
    "btn_pressed":      "Button pressed bg",
    "tab_inactive_bg":  "Inactive tab background",
}


def _save_user_theme(name, tokens):
    """Persist a single user theme into sp_scatter_themes.json (create / update)."""
    path = _user_themes_path()
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception as e:
            print(f"[Magic Scatter World] Warning: existing user themes file unreadable, will rewrite: {e}")
    data[name] = dict(tokens)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _delete_user_theme(name):
    """Remove a user theme from the JSON file. No-op if it isn't there."""
    path = _user_themes_path()
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return
    if not isinstance(data, dict) or name not in data:
        return
    del data[name]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class _SkinEditorDialog(QDialog):
    """Modal editor for creating / editing a user skin via color swatches."""

    def __init__(self, parent, initial_name="", initial_tokens=None, locked_name=False):
        super().__init__(parent)
        self.setWindowTitle("Skin Editor")
        self.setMinimumWidth(420)

        base = dict(THEMES[DEFAULT_THEME])
        if initial_tokens:
            for k, v in initial_tokens.items():
                if k in base and isinstance(v, str):
                    base[k] = v
        self._tokens = base
        self._swatches = {}     # token name -> QPushButton
        self._hex_labels = {}   # token name -> QLabel

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # Name row
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(initial_name)
        if locked_name:
            self.name_edit.setReadOnly(True)
        name_row.addWidget(self.name_edit, 1)
        outer.addLayout(name_row)

        # Token grid (scrollable so the dialog stays compact)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(4, 4, 4, 4)
        body_lay.setSpacing(8)

        for group_label, token_names in SKIN_TOKEN_GROUPS:
            grp = QGroupBox(group_label)
            grid = QGridLayout(grp)
            grid.setContentsMargins(8, 8, 8, 8)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(4)
            for row, token in enumerate(token_names):
                lbl = QLabel(token)
                lbl.setMinimumWidth(120)
                grid.addWidget(lbl, row, 0)

                swatch = QPushButton()
                swatch.setFixedSize(36, 22)
                swatch.setCursor(Qt.PointingHandCursor)
                swatch.clicked.connect(lambda _=False, t=token: self._pick_color(t))
                grid.addWidget(swatch, row, 1)
                self._swatches[token] = swatch

                hex_lbl = QLabel()
                hex_lbl.setMinimumWidth(70)
                grid.addWidget(hex_lbl, row, 2)
                self._hex_labels[token] = hex_lbl

                hint = QLabel(SKIN_TOKEN_HINTS.get(token, ""))
                hint.setStyleSheet("color:#888; font-size:10px;")
                grid.addWidget(hint, row, 3)

                self._refresh_token(token)
            body_lay.addWidget(grp)

        body_lay.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # OK / Cancel
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        outer.addWidget(btn_box)

    def _refresh_token(self, token):
        col = self._tokens.get(token, "#000000")
        sw = self._swatches[token]
        sw.setStyleSheet(
            f"QPushButton {{ background-color: {col}; "
            f"border: 1px solid #555; border-radius: 3px; }}"
        )
        self._hex_labels[token].setText(col)

    def _pick_color(self, token):
        cur = QColor(self._tokens.get(token, "#000000"))
        chosen = QColorDialog.getColor(cur, self, f"Pick color — {token}")
        if not chosen.isValid():
            return
        self._tokens[token] = chosen.name()
        self._refresh_token(token)

    def get_name(self):
        return self.name_edit.text().strip()

    def get_tokens(self):
        return dict(self._tokens)


# ---------------------------------------------------------------------------
# FlowLayout  (wrapping tile layout — same as original)
# ---------------------------------------------------------------------------
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=4, spacing=6):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def __del__(self):
        while self.takeAt(0):
            pass

    def addItem(self, item):             self._items.append(item)
    def count(self):                     return len(self._items)
    def itemAt(self, i):                 return self._items[i] if 0 <= i < len(self._items) else None
    def takeAt(self, i):                 return self._items.pop(i) if 0 <= i < len(self._items) else None
    def expandingDirections(self):       return Qt.Orientations(0)
    def hasHeightForWidth(self):         return True
    def heightForWidth(self, w):         return self._layout(QRect(0, 0, w, 0), dry=True)
    def setGeometry(self, rect):         super().setGeometry(rect); self._layout(rect, dry=False)
    def sizeHint(self):                  return self.minimumSize()
    def minimumSize(self):
        sz = QSize()
        for item in self._items:
            sz = sz.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return sz + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, dry):
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            nx = x + w + sp
            if nx - sp > rect.right() and line_h > 0:
                x = rect.x(); y += line_h + sp; nx = x + w + sp; line_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = nx
            line_h = max(line_h, h)
        return y + line_h - rect.y()


# ---------------------------------------------------------------------------
# AssetWidget
# ---------------------------------------------------------------------------
class AssetWidget(QWidget):
    """Thumbnail card for a single scatter asset."""

    CARD_W, CARD_H = 80, 118

    def __init__(self, node_path, window, parent=None):
        super().__init__(parent)
        self.node_path = node_path
        self.window    = window
        self.selected  = False

        self.setFixedSize(self.CARD_W, self.CARD_H)
        self._set_normal_style()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(3)

        # ── thumbnail ──────────────────────────────────────────────────
        self.thumb_l = QLabel()
        self.thumb_l.setFixedSize(50, 50)
        self.thumb_l.setAlignment(Qt.AlignCenter)
        self.thumb_l.setScaledContents(True)
        self.thumb_l.setStyleSheet("background:#111; border:1px solid #333; border-radius:3px;")
        self._load_thumb()
        lay.addWidget(self.thumb_l, 0, Qt.AlignHCenter)

        # ── name ───────────────────────────────────────────────────────
        short = node_path.split("/")[-1]
        if len(short) > 13:
            short = short[:12] + "…"
        name_l = QLabel(short)
        name_l.setAlignment(Qt.AlignCenter)
        name_l.setStyleSheet("color:#7ab0ff; font-size:10px; font-weight:bold;")
        name_l.setWordWrap(False)
        lay.addWidget(name_l)

        # ── weight ─────────────────────────────────────────────────────
        wt_row = QHBoxLayout()
        wt_row.setContentsMargins(0, 0, 0, 0)
        wt_row.setSpacing(2)
        wt_lbl = QLabel("Wt:")
        wt_lbl.setStyleSheet("font-size:10px; color:#aaa;")
        wt_lbl.setToolTip(
            "Asset density weight (0-1). 1.0 = full density; lower values "
            "drop a fraction of points assigned to this asset, thinning the "
            "scatter."
        )
        wt_row.addWidget(wt_lbl)
        self.weight_sl = QSlider(Qt.Horizontal)
        self.weight_sl.setRange(0, 100)
        self.weight_sl.setValue(int(WT_DEF * 100))
        self.weight_sl.setFixedHeight(16)
        self.weight_sl.setToolTip(
            "Drop probability per asset. 1.0 keeps every point; 0.5 keeps "
            "~half; 0.0 drops all points assigned to this asset."
        )
        self._wt_val_l = QLabel(f"{WT_DEF:.2f}")
        self._wt_val_l.setFixedWidth(26)
        self._wt_val_l.setStyleSheet("font-size:9px; color:#aaa;")
        self.weight_sl.valueChanged.connect(
            lambda v: self._wt_val_l.setText(f"{v / 100:.2f}")
        )
        wt_row.addWidget(self.weight_sl, 1)
        wt_row.addWidget(self._wt_val_l)
        lay.addLayout(wt_row)

        # ── buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(3)
        self.upd_btn = QPushButton("⟳")
        self.upd_btn.setFixedSize(24, 20)
        self.upd_btn.setToolTip("Refresh thumbnail")
        self.upd_btn.setStyleSheet("background:#33a; border-radius:3px; color:white; font-size:11px; padding:0;")
        self.rem_btn = QPushButton("✕")
        self.rem_btn.setFixedSize(24, 20)
        self.rem_btn.setToolTip("Remove asset")
        self.rem_btn.setStyleSheet("background:#a33; border-radius:3px; color:white; font-size:10px; padding:0;")
        btn_row.addWidget(self.upd_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.rem_btn)
        lay.addLayout(btn_row)

        # Signals
        self.weight_sl.valueChanged.connect(lambda _: self.window._on_weight_changed())
        self.upd_btn.clicked.connect(self._refresh_thumb)

    # ── helpers ────────────────────────────────────────────────────────
    def _load_thumb(self):
        try:
            pix = thumbnail.get_thumbnail(self.node_path, 50, 50,
                                          session_id=self.window.session_id)
            if pix and not pix.isNull():
                self.thumb_l.setPixmap(pix)
                return
        except Exception:
            pass
        self.thumb_l.setText("?")

    def _refresh_thumb(self):
        try:
            pix = thumbnail.get_thumbnail(self.node_path, 50, 50,
                                          session_id=self.window.session_id,
                                          force=True)
            if pix and not pix.isNull():
                self.thumb_l.setPixmap(pix)
        except Exception:
            pass

    def _set_normal_style(self):
        self.setStyleSheet("background:#232323; border:1px solid #404040; border-radius:5px;")

    def setSelected(self, state):
        self.selected = state
        if state:
            self.setStyleSheet("background:#1a2d45; border:2px solid #7ab0ff; border-radius:5px;")
        else:
            self._set_normal_style()

    def set_size(self, card_w, card_h, thumb_size):
        self.setFixedSize(card_w, card_h)
        self.thumb_l.setFixedSize(thumb_size, thumb_size)
        try:
            pix = thumbnail.get_thumbnail(self.node_path, thumb_size, thumb_size,
                                          session_id=self.window.session_id)
            if pix and not pix.isNull():
                self.thumb_l.setPixmap(pix)
        except Exception:
            pass

    def contextMenuEvent(self, e):
        self.window._show_asset_context_menu(e.globalPos())

    def mousePressEvent(self, e):
        self.window._on_asset_clicked(self, e.modifiers())
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        dlg = AssetDetailDialog(self, self.window)
        self._detail_dlg = dlg  # prevent GC while open
        dlg.show()
        super().mouseDoubleClickEvent(e)


# ---------------------------------------------------------------------------
# AssetDetailDialog – popup on double-click
# ---------------------------------------------------------------------------
class AssetDetailDialog(QDialog):
    """Large thumbnail + weight editor that opens on double-clicking an AssetWidget."""

    def __init__(self, asset_widget, window, parent=None):
        super().__init__(parent or window)
        self.asset_widget = asset_widget
        self.window = window
        self._original_val = asset_widget.weight_sl.value()

        self.setWindowTitle(asset_widget.node_path.split("/")[-1])
        self.setMinimumWidth(280)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(14, 14, 14, 14)

        # Large thumbnail
        thumb = QLabel()
        thumb.setFixedSize(240, 240)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setScaledContents(True)
        thumb.setStyleSheet("background:#111; border:1px solid #444; border-radius:4px;")
        try:
            pix = thumbnail.get_thumbnail(asset_widget.node_path, 240, 240,
                                          session_id=window.session_id)
            if pix and not pix.isNull():
                thumb.setPixmap(pix)
            else:
                thumb.setText("?")
        except Exception:
            thumb.setText("?")
        lay.addWidget(thumb, 0, Qt.AlignHCenter)

        # Node path label
        path_l = QLabel(asset_widget.node_path)
        path_l.setStyleSheet("color:#7ab0ff; font-size:10px;")
        path_l.setAlignment(Qt.AlignCenter)
        path_l.setWordWrap(True)
        lay.addWidget(path_l)

        # Weight row
        wt_row = QHBoxLayout()
        wt_lbl = QLabel("Weight:")
        wt_lbl.setStyleSheet("color:#ccc; font-size:12px;")
        wt_lbl.setToolTip(
            "Asset density weight (0–1). 1.0 = full density; lower values "
            "thin the scatter for this asset."
        )
        self._spin = QSpinBox()
        self._spin.setRange(0, 100)
        self._spin.setSingleStep(5)
        self._spin.setSuffix(" %")
        self._spin.setFixedWidth(80)
        self._spin.setValue(asset_widget.weight_sl.value())
        self._spin.setStyleSheet("font-size:13px;")
        wt_row.addWidget(wt_lbl)
        wt_row.addStretch()
        wt_row.addWidget(self._spin)
        lay.addLayout(wt_row)

        # Slider (mirrors the card slider)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(asset_widget.weight_sl.value())
        lay.addWidget(self._slider)

        # Keep spin and slider in sync, and live-update the asset
        self._slider.valueChanged.connect(self._spin.setValue)
        self._spin.valueChanged.connect(self._slider.setValue)
        self._spin.valueChanged.connect(self._live_update)

        # OK / Cancel
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self._cancel)
        lay.addWidget(btns)

    def _live_update(self, val):
        self.asset_widget.weight_sl.blockSignals(True)
        self.asset_widget.weight_sl.setValue(val)
        self.asset_widget._wt_val_l.setText(f"{val / 100:.2f}")
        self.asset_widget.weight_sl.blockSignals(False)
        self.window._on_weight_changed()

    def _apply(self):
        self._live_update(self._spin.value())
        self.accept()

    def _cancel(self):
        self._live_update(self._original_val)
        self.reject()


# ---------------------------------------------------------------------------
# Row-builder helpers (used throughout _build_* methods)
# ---------------------------------------------------------------------------

def _make_spinbox(min_v, max_v, def_v, dec=2, step=0.1, width=72):
    sb = QDoubleSpinBox()
    sb.setRange(min_v, max_v)
    sb.setValue(def_v)
    sb.setDecimals(dec)
    sb.setSingleStep(step)
    sb.setFixedWidth(width)
    return sb


def _make_int_spinbox(min_v, max_v, def_v, width=72):
    sb = QSpinBox()
    sb.setRange(min_v, max_v)
    sb.setValue(def_v)
    sb.setFixedWidth(width)
    return sb


def _make_slider(min_v, max_v, def_v, expo_mid=None):
    sl = QSlider(Qt.Horizontal)
    if expo_mid is not None:
        sl.setRange(0, 1000)
        # init position
        if def_v <= expo_mid:
            sl.setValue(int((def_v - min_v) / (expo_mid - min_v) * 500) if expo_mid != min_v else 0)
        else:
            sl.setValue(int(500 + (def_v - expo_mid) / (max_v - expo_mid) * 500))
    else:
        sl.setRange(int(min_v * 1000), int(max_v * 1000))
        sl.setValue(int(def_v * 1000))
    return sl


def _link_slider_spinbox(sl, sb, min_v, max_v, expo_mid=None, on_change=None):
    """
    Wire bidirectional sync between a QSlider and a QDoubleSpinBox.

    on_change: optional callable fired whenever the slider is dragged
               (spinbox changes already trigger their own valueChanged).
    """
    if expo_mid is not None:
        def _sb_to_sl(v):
            sl.blockSignals(True)
            if v <= expo_mid:
                s = int((v - min_v) / (expo_mid - min_v) * 500) if expo_mid != min_v else 0
            else:
                s = int(500 + (v - expo_mid) / (max_v - expo_mid) * 500)
            sl.setValue(max(0, min(1000, s)))
            sl.blockSignals(False)

        def _sl_to_sb(s):
            sb.blockSignals(True)
            v = (min_v + (expo_mid - min_v) * s / 500.0) if s <= 500 else \
                (expo_mid + (max_v - expo_mid) * (s - 500) / 500.0)
            sb.setValue(v)
            sb.blockSignals(False)
            if on_change:
                on_change()
    else:
        def _sb_to_sl(v):
            sl.blockSignals(True)
            sl.setValue(int(v * 1000))
            sl.blockSignals(False)

        def _sl_to_sb(s):
            sb.blockSignals(True)
            sb.setValue(s / 1000.0)
            sb.blockSignals(False)
            if on_change:
                on_change()

    sb.valueChanged.connect(_sb_to_sl)
    sl.valueChanged.connect(_sl_to_sb)


def _param_row(label_text, sl, sb, layout, label_width=90):
    """Add a label + slider + spinbox row to a QVBoxLayout."""
    row = QHBoxLayout()
    row.setSpacing(6)
    lbl = QLabel(label_text)
    lbl.setFixedWidth(label_width)
    lbl.setStyleSheet("color:#bbb;")
    row.addWidget(lbl)
    row.addWidget(sl, 1)
    row.addWidget(sb)
    layout.addLayout(row)


class _CollapsibleGroup(QWidget):
    """
    Collapsible container with a clickable arrow header.

    Usage mirrors the QGroupBox pattern, but layouts attach to ``.body``:

        grp = _CollapsibleGroup("Title")
        gl  = QVBoxLayout(grp.body)
        gl.addWidget(...)
        parent_layout.addWidget(grp)
    """
    def __init__(self, title, expanded=True, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._toggle = QToolButton(self)
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toggle.setAutoRaise(True)
        self._toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._toggle.setStyleSheet(
            "QToolButton { border: none; background: transparent;"
            " color: #ddd; font-weight: bold; padding: 4px; text-align: left; }"
            "QToolButton:hover { background: #3a3a3a; }"
        )
        self._toggle.clicked.connect(self._on_toggle)
        outer.addWidget(self._toggle)

        # Content body — user attaches their own layout here.
        self.body = QWidget(self)
        self.body.setVisible(expanded)
        outer.addWidget(self.body)

    def _on_toggle(self):
        expanded = self._toggle.isChecked()
        self._toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body.setVisible(expanded)


class _RefreshingComboBox(QComboBox):
    """ComboBox that re-queries its items right before the dropdown opens."""
    def __init__(self, refresh_callback, parent=None):
        super().__init__(parent)
        self._refresh_callback = refresh_callback

    def showPopup(self):
        try:
            self._refresh_callback(self)
        except Exception:
            pass
        super().showPopup()


# ---------------------------------------------------------------------------
# Image editor — helper functions
# ---------------------------------------------------------------------------

def _build_levels_lut(brightness, contrast, gamma):
    """256-entry byte LUT: brightness in [-100,100], contrast in [-100,100], gamma > 0."""
    import math
    factor = (259.0 * (contrast + 255)) / (255.0 * (259 - contrast)) if contrast != 0 else 1.0
    lut = []
    for i in range(256):
        v = factor * (i - 128.0) + 128.0 + brightness * 2.55
        v = max(0.0, min(255.0, v))
        if gamma != 1.0 and v > 0.0:
            v = 255.0 * math.pow(v / 255.0, 1.0 / gamma)
        lut.append(int(round(max(0.0, min(255.0, v)))))
    return lut


def _img_apply_lut(image, lut):
    """Apply a 256-entry byte LUT to the R, G, B channels. Returns a new QImage."""
    img32 = image.convertToFormat(QImage.Format_ARGB32)
    try:
        import numpy as np
        ptr = img32.bits()
        try:
            ptr.setsize(img32.byteCount())   # PySide2 needs explicit size
        except AttributeError:
            pass                              # PySide6: bits() is already a memoryview
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
            (img32.height(), img32.width(), 4)
        ).copy()
        lut_a = np.array(lut, dtype=np.uint8)
        arr[:, :, 0] = lut_a[arr[:, :, 0]]  # B
        arr[:, :, 1] = lut_a[arr[:, :, 1]]  # G
        arr[:, :, 2] = lut_a[arr[:, :, 2]]  # R  (alpha left intact)
        return QImage(arr.tobytes(), img32.width(), img32.height(),
                      img32.bytesPerLine(), QImage.Format_ARGB32)
    except ImportError:
        result = img32.copy()
        for y in range(img32.height()):
            for x in range(img32.width()):
                c = img32.pixel(x, y)
                r = lut[(c >> 16) & 0xFF]
                g = lut[(c >> 8) & 0xFF]
                b = lut[c & 0xFF]
                a = (c >> 24) & 0xFF
                result.setPixel(x, y, (a << 24) | (r << 16) | (g << 8) | b)
        return result


def _qimage_to_rgba_uint8(qimage):
    """Return an (H, W, 4) uint8 numpy RGBA copy of *qimage*. Requires numpy."""
    import numpy as np
    img32 = qimage.convertToFormat(QImage.Format_ARGB32)
    ptr = img32.bits()
    try:
        ptr.setsize(img32.byteCount())   # PySide2
    except AttributeError:
        pass                             # PySide6
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
        (img32.height(), img32.width(), 4)
    ).copy()
    # Qt stores ARGB32 as BGRA in memory; swap to RGBA.
    return arr[:, :, [2, 1, 0, 3]]


def _try_import_oiio():
    """Return the OpenImageIO module if available, else None."""
    for mod in ("PyOpenImageIO", "OpenImageIO"):
        try:
            return __import__(mod)
        except ImportError:
            continue
    return None


def _save_exr_oiio(rgba8, path, oiio):
    """Write a 32-bit float EXR via OpenImageIO. Returns (ok, msg)."""
    rgba32 = rgba8.astype("float32") / 255.0
    h, w = rgba32.shape[:2]
    spec = oiio.ImageSpec(w, h, 4, oiio.FLOAT)
    out = oiio.ImageOutput.create(path)
    if out is None:
        return False, "OpenImageIO can't create writer for this path."
    if not out.open(path, spec):
        return False, out.geterror()
    if not out.write_image(rgba32):
        return False, out.geterror()
    out.close()
    return True, None


def _write_exr_uncompressed(rgba_float32, path):
    """Pure-Python writer: single-part scanline OpenEXR, NO_COMPRESSION,
    32-bit float RGBA. *rgba_float32* must be (H, W, 4) float32 numpy array.
    No dependencies beyond numpy (always available in Houdini)."""
    import struct
    import numpy as np

    h, w = rgba_float32.shape[:2]

    def _attr(name, type_name, value_bytes):
        return (name.encode("ascii") + b"\x00"
                + type_name.encode("ascii") + b"\x00"
                + struct.pack("<i", len(value_bytes))
                + value_bytes)

    # chlist: channels are listed in ASCII alphabetical order (A, B, G, R).
    chlist = b""
    for ch in ("A", "B", "G", "R"):
        chlist += (ch.encode("ascii") + b"\x00"
                   + struct.pack("<i", 2)        # pixelType FLOAT
                   + struct.pack("<B", 0)        # pLinear
                   + b"\x00\x00\x00"             # reserved
                   + struct.pack("<i", 1)        # xSampling
                   + struct.pack("<i", 1))       # ySampling
    chlist += b"\x00"  # end of chlist

    box = struct.pack("<iiii", 0, 0, w - 1, h - 1)
    header = (
        _attr("channels",           "chlist",      chlist)
        + _attr("compression",      "compression", struct.pack("<B", 0))    # NO_COMPRESSION
        + _attr("dataWindow",       "box2i",       box)
        + _attr("displayWindow",    "box2i",       box)
        + _attr("lineOrder",        "lineOrder",   struct.pack("<B", 0))    # INCREASING_Y
        + _attr("pixelAspectRatio", "float",       struct.pack("<f", 1.0))
        + _attr("screenWindowCenter", "v2f",       struct.pack("<ff", 0.0, 0.0))
        + _attr("screenWindowWidth",  "float",     struct.pack("<f", 1.0))
        + b"\x00"  # end-of-header marker
    )
    magic_version = struct.pack("<ii", 20000630, 2)

    scanline_pixel_bytes = w * 4 * 4               # 4 channels × float32
    scanline_block_bytes = 8 + scanline_pixel_bytes  # plus y(4) + size(4)

    first_scanline_offset = len(magic_version) + len(header) + 8 * h
    line_offsets = b"".join(
        struct.pack("<Q", first_scanline_offset + y * scanline_block_bytes)
        for y in range(h)
    )

    # Reorder RGBA → ABGR (alphabetical), then channel-major per row → (h, 4, w).
    abgr = rgba_float32[..., [3, 2, 1, 0]].astype("<f4", copy=False)
    rows_data = np.ascontiguousarray(abgr.transpose(0, 2, 1)).tobytes()

    buf = bytearray(h * scanline_block_bytes)
    for y in range(h):
        base = y * scanline_block_bytes
        buf[base : base + 8] = struct.pack("<ii", y, scanline_pixel_bytes)
        buf[base + 8 : base + scanline_block_bytes] = (
            rows_data[y * scanline_pixel_bytes : (y + 1) * scanline_pixel_bytes]
        )

    with open(path, "wb") as f:
        f.write(magic_version)
        f.write(header)
        f.write(line_offsets)
        f.write(bytes(buf))


def _save_qimage_as(qimage, path, fmt):
    """Save *qimage* to *path* in one of three formats:
       'jpg_8'   — JPEG, 8-bit RGB (Qt native)
       'png_16'  — PNG, 16-bit per channel (OpenImageIO; falls back to PIL
                    16-bit grayscale, then Qt 8-bit RGBA)
       'exr_32'  — OpenEXR, 32-bit float RGBA (OpenImageIO; falls back to a
                    pure-Python uncompressed writer that needs only numpy)
    Returns (success: bool, message: str|None). The message is a non-fatal
    note when a fallback caused some loss (e.g. 16-bit RGB → 16-bit gray).
    """
    try:
        if fmt == "jpg_8":
            rgb = qimage.convertToFormat(QImage.Format_RGB32)
            if rgb.save(path, "JPG", 95):
                return True, None
            return False, "Qt JPEG writer failed."

        if fmt == "png_16":
            # 1) OpenImageIO if available — full 16-bit RGBA.
            oiio = _try_import_oiio()
            if oiio is not None:
                try:
                    rgba8 = _qimage_to_rgba_uint8(qimage)
                    rgba16 = (rgba8.astype("uint16") * 257)
                    h, w = rgba16.shape[:2]
                    spec = oiio.ImageSpec(w, h, 4, oiio.UINT16)
                    out = oiio.ImageOutput.create(path)
                    if out is None:
                        raise RuntimeError("OpenImageIO can't create writer.")
                    if not out.open(path, spec):
                        raise RuntimeError(out.geterror())
                    if not out.write_image(rgba16):
                        raise RuntimeError(out.geterror())
                    out.close()
                    return True, None
                except Exception:
                    pass  # fall through

            # 2) PIL — write 16-bit grayscale PNG (paint is grayscale anyway).
            try:
                from PIL import Image as PILImage
                rgba8 = _qimage_to_rgba_uint8(qimage)
                # Use luminance from the R channel (paint is R==G==B).
                gray16 = (rgba8[:, :, 0].astype("uint16") * 257)
                PILImage.fromarray(gray16, mode="I;16").save(path, "PNG")
                return True, ("Saved as 16-bit grayscale PNG (no OpenImageIO; "
                              "alpha and color channels were dropped).")
            except Exception:
                pass

            # 3) Last resort — Qt 8-bit RGBA.
            if qimage.save(path, "PNG"):
                return True, "Saved as 8-bit PNG (no 16-bit writer available)."
            return False, "Qt PNG writer failed."

        if fmt == "exr_32":
            rgba8 = _qimage_to_rgba_uint8(qimage)

            # 1) OpenImageIO if available.
            oiio = _try_import_oiio()
            if oiio is not None:
                try:
                    return _save_exr_oiio(rgba8, path, oiio)
                except Exception:
                    pass  # fall through to pure-Python writer

            # 2) Pure-Python uncompressed EXR — needs only numpy.
            try:
                rgba32 = rgba8.astype("float32") / 255.0
                _write_exr_uncompressed(rgba32, path)
                return True, None
            except Exception as e:
                return False, f"EXR save failed: {e}"

        return False, f"Unknown format key: {fmt!r}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Image editor — widgets
# ---------------------------------------------------------------------------

def _render_brush_thumbnail(brush, w=180, h=36, bg=QColor(50, 50, 50)):
    """Render a tapered preview stroke of *brush* into a QImage."""
    import math, random
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(bg)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)

    r = h * 0.32
    hardness = brush.get("hardness", 100) / 100.0
    spacing_frac = max(0.05, brush.get("spacing", 0.25))
    scatter = brush.get("scatter", 0.0)
    jitter_size = brush.get("jitter_size", 0.0)
    jitter_opacity = brush.get("jitter_opacity", 0.0)
    hard = hardness >= 0.999

    rng = random.Random(brush.get("name", "x"))
    step = max(1.0, r * spacing_frac)
    n = max(1, int((w - 16) / step))
    for i in range(n + 1):
        t = i / n
        x = 8 + t * (w - 16)
        # Tapered envelope: thin at the ends, full in the middle.
        size_factor = math.sin(t * math.pi) * 0.85 + 0.18
        rad = max(1.0, r * size_factor * (1.0 + rng.uniform(-jitter_size, jitter_size)))
        cy = h * 0.5 + rng.uniform(-1, 1) * r * scatter
        cx = x + rng.uniform(-1, 1) * r * scatter
        alpha = int(round(255 * (1.0 - rng.uniform(0.0, jitter_opacity))))
        if hard:
            p.setBrush(QColor(235, 235, 235, alpha))
        else:
            grad = QRadialGradient(QPointF(cx, cy), float(rad))
            grad.setColorAt(0.0, QColor(235, 235, 235, alpha))
            grad.setColorAt(hardness, QColor(235, 235, 235, alpha))
            grad.setColorAt(1.0, QColor(235, 235, 235, 0))
            p.setBrush(grad)
        p.drawEllipse(QPointF(cx, cy), rad, rad)
    p.end()
    return img


class _ClickableLabel(QLabel):
    """QLabel that emits doubleClicked so thumbnails can be double-clicked."""
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(e)


class _ImageDrawCanvas(QWidget):
    """Displays the composite image and handles brush painting directly on it."""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor
        self._drawing = False
        self._last_img_pos = None
        self.setMinimumSize(380, 380)
        self.setCursor(Qt.CrossCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(40, 40, 40))
        composite = self._editor._get_composite()
        if composite and not composite.isNull():
            p.drawImage(self._fit_rect(composite.width(), composite.height()), composite)
        p.end()

    def _fit_rect(self, iw, ih):
        """Centered rect: fit-to-canvas (preserve aspect), then apply user X/Y zoom."""
        ww, wh = max(1, self.width()), max(1, self.height())
        if iw <= 0 or ih <= 0:
            return QRect(0, 0, ww, wh)
        img_aspect    = iw / ih
        widget_aspect = ww / wh
        if img_aspect >= widget_aspect:
            base_w = ww
            base_h = max(1, int(round(ww / img_aspect)))
        else:
            base_h = wh
            base_w = max(1, int(round(wh * img_aspect)))
        zx = self._editor._scale_x_sl.value() / 100.0
        zy = self._editor._scale_y_sl.value() / 100.0
        w = max(1, int(round(base_w * zx)))
        h = max(1, int(round(base_h * zy)))
        return QRect((ww - w) // 2, (wh - h) // 2, w, h)

    def _to_img(self, wpos):
        ed = self._editor
        iw, ih = ed._working.width(), ed._working.height()
        target = self._fit_rect(iw, ih)
        if target.width() <= 0 or target.height() <= 0:
            return 0, 0
        return ((wpos.x() - target.x()) * iw / target.width(),
                (wpos.y() - target.y()) * ih / target.height())

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drawing = True
            ix, iy = self._to_img(e.pos())
            self._last_img_pos = (ix, iy)
            self._do_stroke(ix, iy, ix, iy)

    def mouseMoveEvent(self, e):
        if self._drawing and (e.buttons() & Qt.LeftButton):
            ix, iy = self._to_img(e.pos())
            px, py = self._last_img_pos or (ix, iy)
            self._do_stroke(px, py, ix, iy)
            self._last_img_pos = (ix, iy)
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drawing = False
            self._last_img_pos = None

    def _do_stroke(self, x0, y0, x1, y1):
        import math, random
        ed = self._editor
        layer = ed._active_paint_layer()
        if layer is None:
            return
        target = layer["image"]
        brush = getattr(ed, "_current_brush", None) or {}
        p = QPainter(target)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        r = max(1, ed._brush_size_sl.value() // 2)
        hardness = ed._brush_hardness_sl.value() / 100.0
        is_eraser = ed._eraser_cb.isChecked()
        color = ed._brush_color
        cr, cg, cb = color.red(), color.green(), color.blue()
        opacity = ed._brush_opacity_sl.value()
        hard = hardness >= 0.999

        spacing_frac   = max(0.05, brush.get("spacing", 0.4))
        scatter        = brush.get("scatter", 0.0)
        jitter_size    = brush.get("jitter_size", 0.0)
        jitter_opacity = brush.get("jitter_opacity", 0.0)
        has_variation  = bool(scatter or jitter_size or jitter_opacity)

        if is_eraser:
            if hard and not has_variation:
                p.setCompositionMode(QPainter.CompositionMode_Clear)
                p.setBrush(Qt.transparent)
            else:
                p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        else:
            # Source = uniform single-stroke opacity (fast path for plain hard brush).
            # SourceOver is required when stamps vary (gradient/scatter/jitter),
            # so individual stamps can accumulate / blend correctly.
            uniform_hard = hard and not has_variation
            p.setCompositionMode(QPainter.CompositionMode_Source if uniform_hard
                                 else QPainter.CompositionMode_SourceOver)
            if uniform_hard:
                p.setBrush(QColor(cr, cg, cb, opacity))

        dist = math.hypot(x1 - x0, y1 - y0)
        step = max(1.0, r * spacing_frac)
        steps = max(1, int(dist / step))
        for i in range(steps + 1):
            t = i / steps if steps else 0.0
            cx = x0 + (x1 - x0) * t
            cy = y0 + (y1 - y0) * t
            if scatter:
                cx += random.uniform(-1, 1) * r * scatter
                cy += random.uniform(-1, 1) * r * scatter
            rad = r
            if jitter_size:
                rad = max(1.0, r * (1.0 + random.uniform(-jitter_size, jitter_size)))
            alpha = opacity
            if jitter_opacity:
                alpha = max(0, int(round(opacity * (1.0 - random.uniform(0.0, jitter_opacity)))))

            if hard:
                if has_variation and not is_eraser:
                    p.setBrush(QColor(cr, cg, cb, alpha))
                # else: brush already set above (uniform_hard path) or eraser uses Clear/DestOut.
                if is_eraser and has_variation:
                    # Soft-ish eraser stamp with per-stamp alpha (DestinationOut).
                    p.setBrush(QColor(0, 0, 0, alpha))
            else:
                grad = QRadialGradient(QPointF(cx, cy), float(rad))
                if is_eraser:
                    grad.setColorAt(0.0, QColor(0, 0, 0, alpha))
                    grad.setColorAt(hardness, QColor(0, 0, 0, alpha))
                    grad.setColorAt(1.0, QColor(0, 0, 0, 0))
                else:
                    grad.setColorAt(0.0, QColor(cr, cg, cb, alpha))
                    grad.setColorAt(hardness, QColor(cr, cg, cb, alpha))
                    grad.setColorAt(1.0, QColor(cr, cg, cb, 0))
                p.setBrush(grad)
            p.drawEllipse(QPointF(cx, cy), float(rad), float(rad))
        p.end()
        self.update()


class _BrushPickerDialog(QDialog):
    """Photoshop-style brush picker. Brushes are grouped by category and shown
    as a clickable thumbnail + name. A single click selects + closes."""

    THUMB_W = 168
    THUMB_H = 36

    def __init__(self, brushes, current_brush, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Brush Picker")
        self.setMinimumSize(560, 480)
        self._brushes = brushes
        self._current_name = current_brush.get("name") if current_brush else None
        self._picked = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Filter / search
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search_le = QLineEdit()
        self._search_le.setPlaceholderText("Filter brushes by name…")
        self._search_le.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search_le, 1)
        root.addLayout(search_row)

        # Scrollable list of categories
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.StyledPanel)
        self._content = QWidget()
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(6, 6, 6, 6)
        self._content_lay.setSpacing(4)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        # _brush_buttons: list of (brush_dict, QToolButton) for filtering.
        self._brush_buttons = []
        self._category_widgets = []  # list of (category_label, container_widget)
        self._build_brush_list()

    def selected_brush(self):
        return self._picked

    def _build_brush_list(self):
        # Group by category, preserving the source order.
        cats = {}
        order = []
        for b in self._brushes:
            cat = b.get("category", "Other")
            if cat not in cats:
                cats[cat] = []
                order.append(cat)
            cats[cat].append(b)

        for cat in order:
            hdr = QLabel(cat)
            hdr.setStyleSheet(
                "background:#2d2d2d; color:#ccc; font-weight:bold;"
                " padding:4px 6px; border:1px solid #444;"
            )
            self._content_lay.addWidget(hdr)

            grid_wrap = QWidget()
            grid = QGridLayout(grid_wrap)
            grid.setContentsMargins(2, 2, 2, 2)
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(4)
            for i, brush in enumerate(cats[cat]):
                btn = self._make_brush_button(brush)
                grid.addWidget(btn, i // 3, i % 3)
                self._brush_buttons.append((brush, btn))
            self._content_lay.addWidget(grid_wrap)
            self._category_widgets.append((hdr, grid_wrap))

        self._content_lay.addStretch()

    def _make_brush_button(self, brush):
        thumb = _render_brush_thumbnail(brush, self.THUMB_W, self.THUMB_H,
                                        bg=QColor(45, 45, 45))
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setIcon(QIcon(QPixmap.fromImage(thumb)))
        btn.setIconSize(QSize(self.THUMB_W, self.THUMB_H))
        btn.setText(brush["name"])
        is_current = (brush.get("name") == self._current_name)
        border = "#6a8acc" if is_current else "#444"
        bg = "#3a4a5a" if is_current else "#2a2a2a"
        btn.setStyleSheet(
            f"QToolButton {{ background:{bg}; border:1px solid {border};"
            f" border-radius:3px; padding:4px; color:#eee; }}"
            "QToolButton:hover { border-color:#6a8acc; background:#3a3a3a; }"
        )
        btn.setFixedSize(self.THUMB_W + 14, self.THUMB_H + 32)
        btn.clicked.connect(lambda _=False, b=brush: self._on_pick(b))
        return btn

    def _on_pick(self, brush):
        self._picked = brush
        self.accept()

    def _apply_filter(self, text):
        needle = (text or "").strip().lower()
        # Show/hide each button + each category header if all its brushes hidden.
        for brush, btn in self._brush_buttons:
            visible = (not needle) or (needle in brush["name"].lower())
            btn.setVisible(visible)
        # Hide category headers whose brushes are all hidden.
        for hdr, container in self._category_widgets:
            any_visible = any(
                btn.isVisible() for b, btn in self._brush_buttons
                if b.get("category", "Other") == hdr.text()
            )
            hdr.setVisible(any_visible)
            container.setVisible(any_visible)


class ImageEditorDialog(QDialog):
    """
    Opens on double-click of a stamp layer thumbnail.
    Provides brightness/contrast/gamma adjustments and a brush drawing tool.
    Save overwrites the source file and refreshes the layer preview.
    """

    # Blend mode display names → QPainter.CompositionMode_*
    BLEND_MODES = [
        ("Normal",     QPainter.CompositionMode_SourceOver),
        ("Multiply",   QPainter.CompositionMode_Multiply),
        ("Screen",     QPainter.CompositionMode_Screen),
        ("Overlay",    QPainter.CompositionMode_Overlay),
        ("Darken",     QPainter.CompositionMode_Darken),
        ("Lighten",    QPainter.CompositionMode_Lighten),
        ("Difference", QPainter.CompositionMode_Difference),
        ("Add",        QPainter.CompositionMode_Plus),
    ]

    # Brush presets — picking sets hardness slider; spacing/scatter/jitter
    # are consumed by _do_stroke. Categories appear as headers in the picker.
    BRUSH_PRESETS = [
        # General
        {"name": "Hard Round",      "category": "General",   "hardness": 100, "spacing": 0.20},
        {"name": "Soft Round",      "category": "General",   "hardness":   0, "spacing": 0.25},
        {"name": "Medium Round",    "category": "General",   "hardness":  50, "spacing": 0.25},
        {"name": "Hard Round Wide", "category": "General",   "hardness": 100, "spacing": 0.55},
        # Dry Media
        {"name": "Pencil",          "category": "Dry Media", "hardness":  95, "spacing": 0.10, "scatter": 0.05, "jitter_size": 0.10},
        {"name": "Charcoal",        "category": "Dry Media", "hardness":  40, "spacing": 0.30, "scatter": 0.40, "jitter_opacity": 0.40},
        {"name": "Chalk",           "category": "Dry Media", "hardness":  60, "spacing": 0.35, "scatter": 0.30, "jitter_size": 0.40},
        # Wet Media
        {"name": "Wet Brush",       "category": "Wet Media", "hardness":  25, "spacing": 0.15},
        {"name": "Ink Pen",         "category": "Wet Media", "hardness": 100, "spacing": 0.08},
        # Special
        {"name": "Spray",           "category": "Special",   "hardness":   0, "spacing": 0.10, "scatter": 0.80, "jitter_opacity": 0.70},
        {"name": "Dots",            "category": "Special",   "hardness": 100, "spacing": 1.50, "scatter": 0.20},
        {"name": "Splatter",        "category": "Special",   "hardness":  60, "spacing": 0.45, "scatter": 0.90, "jitter_size": 0.60, "jitter_opacity": 0.50},
    ]

    def __init__(self, image_path, on_save=None, parent=None,
                 new_image_size=(1024, 1024)):
        """If *image_path* is None, opens in 'new image' mode with a blank
        black canvas of *new_image_size*. On Save, the user is prompted for
        filename + format (jpg/png/exr) and self._image_path is filled in."""
        super().__init__(parent)
        self._image_path = image_path        # may be None until save-as
        self._on_save = on_save

        if image_path is None:
            fname = "New Image"
            nw, nh = new_image_size
            raw = QImage(max(1, int(nw)), max(1, int(nh)), QImage.Format_ARGB32)
            raw.fill(QColor(0, 0, 0))
        else:
            fname = image_path.replace("\\", "/").split("/")[-1]
            raw = QImage(image_path)
            if raw.isNull():
                raw = QImage(256, 256, QImage.Format_ARGB32)
                raw.fill(QColor(0, 0, 0))

        self.setWindowTitle(f"Image Editor — {fname}")
        self.setMinimumSize(820, 600)
        self._working = raw.convertToFormat(QImage.Format_ARGB32)

        # Photoshop-style paint layers. _paint_layers[0] = bottom; last = top.
        self._paint_layers = []
        self._active_paint_layer_idx = 0
        self._layers_vlay = None       # set in _build_ui
        self._layer_card_widgets = []  # parallel list of card widgets
        self._next_layer_num = 1
        self._add_paint_layer()        # initial empty Layer 1

        self._current_brush = self.BRUSH_PRESETS[0]   # default: Hard Round
        self._brush_color = QColor(255, 255, 255)     # default: white

        self._resize_undo_working = None
        self._resize_undo_layers = None
        self._build_ui()
        self._update_color_swatch()
        self._update_tile_size_label()
        self._rebuild_layers_ui()
        self._update_brush_picker_btn()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._canvas = _ImageDrawCanvas(self)
        root.addWidget(self._canvas, 1)

        # Right-side panel is scrollable so collapsibles + layers can grow.
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFixedWidth(255)
        panel_scroll.setFrameShape(QFrame.NoFrame)
        panel = QWidget()
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(0, 0, 0, 0)
        panel_lay.setSpacing(4)
        panel_scroll.setWidget(panel)

        def _sl_row(label, lo, hi, val, fmt_fn=str):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            lbl = QLabel(label)
            lbl.setFixedWidth(72)
            lbl.setStyleSheet("font-size:10px; color:#aaa;")
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            sl.setValue(val)
            vl = QLabel(fmt_fn(val))
            vl.setFixedWidth(38)
            vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            vl.setStyleSheet("font-size:10px; color:#ddd;")
            h.addWidget(lbl)
            h.addWidget(sl, 1)
            h.addWidget(vl)
            return w, sl, vl

        # ── Adjustments ──────────────────────────────────────────────────
        adj_grp = _CollapsibleGroup("Adjustments")
        adj_lay = QVBoxLayout(adj_grp.body)
        adj_lay.setContentsMargins(4, 2, 4, 4)
        adj_lay.setSpacing(3)

        br_w, self._brightness_sl, self._brightness_vl = _sl_row(
            "Brightness", -100, 100, 0, lambda v: f"{v:+d}")
        ct_w, self._contrast_sl, self._contrast_vl = _sl_row(
            "Contrast",   -100, 100, 0, lambda v: f"{v:+d}")
        gm_w, self._gamma_sl,    self._gamma_vl    = _sl_row(
            "Gamma",        10, 300, 100, lambda v: f"{v/100:.2f}")

        self._brightness_sl.valueChanged.connect(
            lambda v: (self._brightness_vl.setText(f"{v:+d}"), self._canvas.update()))
        self._contrast_sl.valueChanged.connect(
            lambda v: (self._contrast_vl.setText(f"{v:+d}"), self._canvas.update()))
        self._gamma_sl.valueChanged.connect(
            lambda v: (self._gamma_vl.setText(f"{v/100:.2f}"), self._canvas.update()))

        for w in (br_w, ct_w, gm_w):
            adj_lay.addWidget(w)

        apply_adj_btn = QPushButton("Apply Adjustments")
        apply_adj_btn.setToolTip("Bake adjustments into the image and reset sliders to neutral.")
        apply_adj_btn.clicked.connect(self._apply_adjustments)
        reset_adj_btn = QPushButton("Reset Sliders")
        reset_adj_btn.clicked.connect(self._reset_adj_sliders)
        adj_lay.addWidget(apply_adj_btn)
        adj_lay.addWidget(reset_adj_btn)
        panel_lay.addWidget(adj_grp)

        # ── Draw (brush + Photoshop-style paint layers) ──────────────────
        draw_grp = _CollapsibleGroup("Draw")
        draw_lay = QVBoxLayout(draw_grp.body)
        draw_lay.setContentsMargins(4, 2, 4, 4)
        draw_lay.setSpacing(3)

        sz_w, self._brush_size_sl,     self._brush_size_vl     = _sl_row("Size",     1, 300, 20,  str)
        hd_w, self._brush_hardness_sl, self._brush_hardness_vl = _sl_row("Hardness", 0, 100, 100, lambda v: f"{v}%")
        op_w, self._brush_opacity_sl,  self._brush_opacity_vl  = _sl_row("Opacity",  1, 255, 255, str)

        self._brush_size_sl.valueChanged.connect(
            lambda v: self._brush_size_vl.setText(str(v)))
        self._brush_hardness_sl.valueChanged.connect(
            lambda v: self._brush_hardness_vl.setText(f"{v}%"))
        self._brush_opacity_sl.valueChanged.connect(
            lambda v: self._brush_opacity_vl.setText(str(v)))

        # Brush picker button — opens a dialog with brush thumbnails.
        self._brush_picker_btn = QToolButton()
        self._brush_picker_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._brush_picker_btn.setIconSize(QSize(64, 22))
        self._brush_picker_btn.setMinimumHeight(32)
        self._brush_picker_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._brush_picker_btn.setStyleSheet(
            "QToolButton { background:#333; border:1px solid #555; padding:2px 6px;"
            " color:#ddd; text-align:left; }"
            "QToolButton:hover { background:#3a3a3a; border-color:#6a8acc; }"
        )
        self._brush_picker_btn.setToolTip("Click to choose a brush preset.")
        self._brush_picker_btn.clicked.connect(self._open_brush_picker)
        preset_row = QWidget()
        pr = QHBoxLayout(preset_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(4)
        pr.addWidget(QLabel("Brush:"))
        pr.addWidget(self._brush_picker_btn, 1)

        # Color swatch — double-click opens a full color picker.
        color_row = QWidget()
        cr = QHBoxLayout(color_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(4)
        color_lbl = QLabel("Color:")
        color_lbl.setFixedWidth(72)
        color_lbl.setStyleSheet("font-size:10px; color:#aaa;")
        self._color_swatch = _ClickableLabel()
        self._color_swatch.setFixedHeight(22)
        self._color_swatch.setCursor(Qt.PointingHandCursor)
        self._color_swatch.setToolTip("Double-click to pick a brush color.")
        self._color_swatch.doubleClicked.connect(self._pick_brush_color)
        cr.addWidget(color_lbl)
        cr.addWidget(self._color_swatch, 1)

        self._eraser_cb = QCheckBox("Eraser mode")

        for w in (sz_w, hd_w, op_w):
            draw_lay.addWidget(w)
        draw_lay.addWidget(preset_row)
        draw_lay.addWidget(color_row)
        draw_lay.addWidget(self._eraser_cb)

        # Layers sub-section.
        layers_hdr = QHBoxLayout()
        layers_hdr.setContentsMargins(0, 4, 0, 0)
        layers_lbl = QLabel("Layers")
        layers_lbl.setStyleSheet("font-size:10px; color:#aaa; font-weight:bold;")
        add_layer_btn = QPushButton("+ Add Layer")
        add_layer_btn.setToolTip("Add a new paint layer on top of the active layer.")
        add_layer_btn.clicked.connect(self._on_add_paint_layer)
        layers_hdr.addWidget(layers_lbl)
        layers_hdr.addStretch()
        layers_hdr.addWidget(add_layer_btn)
        draw_lay.addLayout(layers_hdr)

        self._layers_container = QWidget()
        self._layers_vlay = QVBoxLayout(self._layers_container)
        self._layers_vlay.setContentsMargins(0, 0, 0, 0)
        self._layers_vlay.setSpacing(3)
        draw_lay.addWidget(self._layers_container)

        layer_btn_row = QHBoxLayout()
        clr_btn  = QPushButton("Clear Active")
        clr_btn.setToolTip("Clear the active paint layer.")
        bake_btn = QPushButton("Bake All")
        bake_btn.setToolTip("Flatten all visible paint layers into the base image.")
        clr_btn.clicked.connect(self._clear_drawing)
        bake_btn.clicked.connect(self._bake_drawing)
        layer_btn_row.addWidget(clr_btn)
        layer_btn_row.addWidget(bake_btn)
        draw_lay.addLayout(layer_btn_row)

        panel_lay.addWidget(draw_grp)

        # ── Tile / Repeat ────────────────────────────────────────────────
        tile_grp = _CollapsibleGroup("Tile / Repeat")
        tile_lay = QVBoxLayout(tile_grp.body)
        tile_lay.setContentsMargins(4, 2, 4, 4)
        tile_lay.setSpacing(3)

        tx_w, self._tile_x_sl, self._tile_x_vl = _sl_row("Tile X", 1, 10, 1, str)
        ty_w, self._tile_y_sl, self._tile_y_vl = _sl_row("Tile Y", 1, 10, 1, str)
        self._tile_x_sl.valueChanged.connect(
            lambda v: (self._tile_x_vl.setText(str(v)), self._update_tile_size_label()))
        self._tile_y_sl.valueChanged.connect(
            lambda v: (self._tile_y_vl.setText(str(v)), self._update_tile_size_label()))

        self._tile_size_lbl = QLabel()
        self._tile_size_lbl.setStyleSheet("font-size:10px; color:#888;")
        self._tile_size_lbl.setAlignment(Qt.AlignCenter)

        tile_btn = QPushButton("Apply Tile")
        tile_btn.setToolTip(
            "Repeat the image N×M times to make a larger texture.\n"
            "Bakes any pending adjustments/drawing first; clears paint layers."
        )
        tile_btn.clicked.connect(self._apply_tile)

        self._undo_resize_btn = QPushButton("Undo Tile")
        self._undo_resize_btn.setToolTip("Revert to the image state before the last Tile was applied.")
        self._undo_resize_btn.clicked.connect(self._undo_resize)
        self._undo_resize_btn.setEnabled(False)

        tile_lay.addWidget(tx_w)
        tile_lay.addWidget(ty_w)
        tile_lay.addWidget(self._tile_size_lbl)
        tile_lay.addWidget(tile_btn)
        tile_lay.addWidget(self._undo_resize_btn)
        panel_lay.addWidget(tile_grp)

        # ── View Zoom (non-destructive — display only) ───────────────────
        zoom_grp = _CollapsibleGroup("View Zoom", expanded=False)
        zoom_lay = QVBoxLayout(zoom_grp.body)
        zoom_lay.setContentsMargins(4, 2, 4, 4)
        zoom_lay.setSpacing(3)

        zx_w, self._scale_x_sl, self._scale_x_vl = _sl_row("Zoom X", 10, 400, 100, lambda v: f"{v}%")
        zy_w, self._scale_y_sl, self._scale_y_vl = _sl_row("Zoom Y", 10, 400, 100, lambda v: f"{v}%")
        self._scale_uniform_cb = QCheckBox("Uniform (proportional)")
        self._scale_uniform_cb.setChecked(True)

        def _on_sx(v):
            self._scale_x_vl.setText(f"{v}%")
            if self._scale_uniform_cb.isChecked() and self._scale_y_sl.value() != v:
                self._scale_y_sl.blockSignals(True)
                self._scale_y_sl.setValue(v)
                self._scale_y_sl.blockSignals(False)
                self._scale_y_vl.setText(f"{v}%")
            self._canvas.update()

        def _on_sy(v):
            self._scale_y_vl.setText(f"{v}%")
            if self._scale_uniform_cb.isChecked() and self._scale_x_sl.value() != v:
                self._scale_x_sl.blockSignals(True)
                self._scale_x_sl.setValue(v)
                self._scale_x_sl.blockSignals(False)
                self._scale_x_vl.setText(f"{v}%")
            self._canvas.update()

        self._scale_x_sl.valueChanged.connect(_on_sx)
        self._scale_y_sl.valueChanged.connect(_on_sy)

        reset_zoom_btn = QPushButton("Reset Zoom (100%)")
        reset_zoom_btn.setToolTip("Reset both zoom sliders to 100%.")
        reset_zoom_btn.clicked.connect(self._reset_zoom)

        zoom_lay.addWidget(zx_w)
        zoom_lay.addWidget(zy_w)
        zoom_lay.addWidget(self._scale_uniform_cb)
        zoom_lay.addWidget(reset_zoom_btn)
        panel_lay.addWidget(zoom_grp)

        panel_lay.addStretch()

        save_btn = QPushButton("Save (overwrite file)")
        save_btn.setStyleSheet(
            "background:#1a5c1a; color:white; font-weight:bold; padding:5px;")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        panel_lay.addWidget(save_btn)
        panel_lay.addWidget(cancel_btn)

        root.addWidget(panel_scroll)

    # ── logic ────────────────────────────────────────────────────────────

    # ── paint layer helpers ──────────────────────────────────────────────

    def _blend_mode_to_qt(self, name):
        for n, mode in self.BLEND_MODES:
            if n == name:
                return mode
        return QPainter.CompositionMode_SourceOver

    def _active_paint_layer(self):
        if not self._paint_layers:
            return None
        idx = max(0, min(self._active_paint_layer_idx, len(self._paint_layers) - 1))
        return self._paint_layers[idx]

    def _new_empty_layer_image(self):
        img = QImage(self._working.width(), self._working.height(),
                     QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        return img

    def _add_paint_layer(self, name=None, blend="Normal", opacity=100, visible=True):
        if name is None:
            name = f"Layer {self._next_layer_num}"
        self._next_layer_num += 1
        self._paint_layers.append({
            "image":   self._new_empty_layer_image(),
            "name":    name,
            "blend":   blend,
            "opacity": opacity,
            "visible": visible,
        })
        self._active_paint_layer_idx = len(self._paint_layers) - 1

    def _on_add_paint_layer(self):
        self._add_paint_layer()
        self._rebuild_layers_ui()
        self._canvas.update()

    def _on_remove_paint_layer(self, idx):
        if len(self._paint_layers) <= 1:
            return
        del self._paint_layers[idx]
        if self._active_paint_layer_idx >= len(self._paint_layers):
            self._active_paint_layer_idx = len(self._paint_layers) - 1
        self._rebuild_layers_ui()
        self._canvas.update()

    def _set_active_layer(self, idx):
        if 0 <= idx < len(self._paint_layers):
            self._active_paint_layer_idx = idx
            self._rebuild_layers_ui()

    def _rebuild_layers_ui(self):
        if self._layers_vlay is None:
            return
        # Clear existing rows.
        while self._layers_vlay.count():
            item = self._layers_vlay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._layer_card_widgets = []
        # Render top→bottom (Photoshop convention: top of list = top of stack).
        for i in range(len(self._paint_layers) - 1, -1, -1):
            card = self._make_paint_layer_card(i)
            self._layers_vlay.addWidget(card)
            self._layer_card_widgets.append(card)

    def _make_paint_layer_card(self, idx):
        layer = self._paint_layers[idx]
        is_active = (idx == self._active_paint_layer_idx)
        can_remove = len(self._paint_layers) > 1

        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        bg = "#3a4a5a" if is_active else "#2a2a2a"
        border = "#5a8ad0" if is_active else "#444"
        card.setStyleSheet(
            f"QFrame {{ background:{bg}; border:1px solid {border};"
            f" border-radius:3px; }} QLabel {{ background:transparent; }}"
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(4, 3, 4, 3)
        v.setSpacing(2)

        # Row 1: visibility | name | remove
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        vis_cb = QCheckBox()
        vis_cb.setChecked(layer["visible"])
        vis_cb.setToolTip("Toggle layer visibility")
        vis_cb.setFixedWidth(18)
        def _on_vis(_state, i=idx):
            self._paint_layers[i]["visible"] = bool(vis_cb.isChecked())
            self._canvas.update()
        vis_cb.stateChanged.connect(_on_vis)

        name_btn = QPushButton(layer["name"])
        name_btn.setFlat(True)
        name_btn.setStyleSheet(
            "QPushButton { color:#eee; text-align:left; padding:1px 4px;"
            " border:none; background:transparent; }"
            "QPushButton:hover { color:#fff; }"
        )
        name_btn.setToolTip("Click to make this the active paint layer.")
        name_btn.clicked.connect(lambda _=False, i=idx: self._set_active_layer(i))

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(20, 20)
        remove_btn.setEnabled(can_remove)
        remove_btn.setToolTip("Remove this layer" if can_remove
                              else "Cannot remove the last layer")
        remove_btn.clicked.connect(lambda _=False, i=idx: self._on_remove_paint_layer(i))

        row1.addWidget(vis_cb)
        row1.addWidget(name_btn, 1)
        row1.addWidget(remove_btn)
        v.addLayout(row1)

        # Row 2: blend mode | opacity slider
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        blend_cb = QComboBox()
        for name, _ in self.BLEND_MODES:
            blend_cb.addItem(name)
        bi = blend_cb.findText(layer["blend"])
        blend_cb.setCurrentIndex(max(0, bi))
        blend_cb.setToolTip("Blend mode of this layer over those below it.")
        def _on_blend(_=None, i=idx):
            self._paint_layers[i]["blend"] = blend_cb.currentText()
            self._canvas.update()
        blend_cb.currentIndexChanged.connect(_on_blend)

        op_sl = QSlider(Qt.Horizontal)
        op_sl.setRange(0, 100)
        op_sl.setValue(int(layer["opacity"]))
        op_sl.setToolTip("Layer opacity")
        op_vl = QLabel(f"{int(layer['opacity'])}%")
        op_vl.setFixedWidth(34)
        op_vl.setStyleSheet("font-size:10px; color:#ddd;")
        op_vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        def _on_op(v, i=idx):
            self._paint_layers[i]["opacity"] = v
            op_vl.setText(f"{v}%")
            self._canvas.update()
        op_sl.valueChanged.connect(_on_op)

        row2.addWidget(blend_cb)
        row2.addWidget(op_sl, 1)
        row2.addWidget(op_vl)
        v.addLayout(row2)

        return card

    # ── compositing ──────────────────────────────────────────────────────

    def _get_composite(self):
        br = self._brightness_sl.value()
        ct = self._contrast_sl.value()
        gm = self._gamma_sl.value() / 100.0
        if br != 0 or ct != 0 or gm != 1.0:
            lut = _build_levels_lut(br, ct, gm)
            base = _img_apply_lut(self._working, lut)
        else:
            base = self._working
        result = base.copy()
        p = QPainter(result)
        for layer in self._paint_layers:
            if not layer["visible"]:
                continue
            p.setOpacity(layer["opacity"] / 100.0)
            p.setCompositionMode(self._blend_mode_to_qt(layer["blend"]))
            p.drawImage(0, 0, layer["image"])
        p.end()
        return result

    def _apply_adjustments(self):
        br = self._brightness_sl.value()
        ct = self._contrast_sl.value()
        gm = self._gamma_sl.value() / 100.0
        if br != 0 or ct != 0 or gm != 1.0:
            lut = _build_levels_lut(br, ct, gm)
            self._working = _img_apply_lut(self._working, lut)
        self._reset_adj_sliders()

    def _reset_adj_sliders(self):
        for sl, v in ((self._brightness_sl, 0), (self._contrast_sl, 0), (self._gamma_sl, 100)):
            sl.blockSignals(True)
            sl.setValue(v)
            sl.blockSignals(False)
        self._brightness_vl.setText("+0")
        self._contrast_vl.setText("+0")
        self._gamma_vl.setText("1.00")
        self._canvas.update()

    def _clear_drawing(self):
        layer = self._active_paint_layer()
        if layer is None:
            return
        layer["image"].fill(Qt.transparent)
        self._canvas.update()

    def _bake_drawing(self):
        """Flatten all visible paint layers into the base image; reset to one empty layer."""
        p = QPainter(self._working)
        for layer in self._paint_layers:
            if not layer["visible"]:
                continue
            p.setOpacity(layer["opacity"] / 100.0)
            p.setCompositionMode(self._blend_mode_to_qt(layer["blend"]))
            p.drawImage(0, 0, layer["image"])
        p.end()
        # Reset to a single empty Layer 1.
        self._paint_layers = []
        self._next_layer_num = 1
        self._active_paint_layer_idx = 0
        self._add_paint_layer()
        self._rebuild_layers_ui()
        self._canvas.update()

    def _update_color_swatch(self):
        c = self._brush_color
        self._color_swatch.setStyleSheet(
            f"background:rgb({c.red()},{c.green()},{c.blue()});"
            " border:1px solid #555;")

    def _pick_brush_color(self):
        picked = QColorDialog.getColor(
            self._brush_color, self, "Pick Brush Color"
        )
        if picked.isValid():
            self._brush_color = picked
            self._update_color_swatch()

    # ── brush picker ─────────────────────────────────────────────────────

    def _update_brush_picker_btn(self):
        """Refresh the brush picker button's preview thumbnail + label."""
        brush = self._current_brush
        thumb = _render_brush_thumbnail(brush, 64, 22, bg=QColor(30, 30, 30))
        self._brush_picker_btn.setIcon(QIcon(QPixmap.fromImage(thumb)))
        self._brush_picker_btn.setText(f"  {brush['name']}")

    def _set_current_brush(self, brush):
        self._current_brush = brush
        # Sync hardness slider to the picked brush.
        self._brush_hardness_sl.blockSignals(True)
        self._brush_hardness_sl.setValue(int(brush.get("hardness", 100)))
        self._brush_hardness_sl.blockSignals(False)
        self._brush_hardness_vl.setText(f"{int(brush.get('hardness', 100))}%")
        self._update_brush_picker_btn()

    def _open_brush_picker(self):
        dlg = _BrushPickerDialog(self.BRUSH_PRESETS, self._current_brush, self)
        if dlg.exec_():
            picked = dlg.selected_brush()
            if picked is not None:
                self._set_current_brush(picked)

    def _update_tile_size_label(self):
        tx = self._tile_x_sl.value()
        ty = self._tile_y_sl.value()
        w = self._working.width() * tx
        h = self._working.height() * ty
        self._tile_size_lbl.setText(f"Result: {w} × {h} px")

    def _snapshot_for_resize_undo(self):
        self._resize_undo_working = self._working.copy()
        self._resize_undo_layers = [
            {**lyr, "image": lyr["image"].copy()} for lyr in self._paint_layers
        ]
        self._resize_undo_active_idx = self._active_paint_layer_idx
        self._resize_undo_next_num = self._next_layer_num
        self._undo_resize_btn.setEnabled(True)

    def _apply_tile(self):
        tx = self._tile_x_sl.value()
        ty = self._tile_y_sl.value()
        if tx <= 1 and ty <= 1:
            return
        self._apply_adjustments()
        self._bake_drawing()
        self._snapshot_for_resize_undo()

        src = self._working
        sw, sh = src.width(), src.height()
        new_w, new_h = sw * tx, sh * ty
        tiled = QImage(new_w, new_h, QImage.Format_ARGB32)
        tiled.fill(Qt.transparent)
        p = QPainter(tiled)
        for j in range(ty):
            for i in range(tx):
                p.drawImage(i * sw, j * sh, src)
        p.end()

        self._working = tiled
        # Reset paint layers to a single empty layer at the new size.
        self._paint_layers = []
        self._next_layer_num = 1
        self._active_paint_layer_idx = 0
        self._add_paint_layer()
        self._rebuild_layers_ui()

        for sl in (self._tile_x_sl, self._tile_y_sl):
            sl.blockSignals(True)
            sl.setValue(1)
            sl.blockSignals(False)
        self._tile_x_vl.setText("1")
        self._tile_y_vl.setText("1")
        self._update_tile_size_label()
        self._canvas.update()

    def _reset_zoom(self):
        for sl, vl in ((self._scale_x_sl, self._scale_x_vl),
                       (self._scale_y_sl, self._scale_y_vl)):
            sl.blockSignals(True)
            sl.setValue(100)
            sl.blockSignals(False)
            vl.setText("100%")
        self._canvas.update()

    def _undo_resize(self):
        if self._resize_undo_working is None:
            return
        self._working = self._resize_undo_working
        self._paint_layers = self._resize_undo_layers or []
        self._active_paint_layer_idx = getattr(self, "_resize_undo_active_idx", 0)
        self._next_layer_num = getattr(self, "_resize_undo_next_num", len(self._paint_layers) + 1)
        if not self._paint_layers:
            self._add_paint_layer()
        self._resize_undo_working = None
        self._resize_undo_layers = None
        self._undo_resize_btn.setEnabled(False)
        self._rebuild_layers_ui()
        self._update_tile_size_label()
        self._canvas.update()

    def _save(self):
        self._apply_adjustments()
        self._bake_drawing()

        if not self._image_path:
            # New-image flow — prompt for filename + format. If the user
            # cancels, leave the dialog open instead of closing.
            if not self._save_as_new():
                return
        else:
            # Existing file — overwrite using Qt's native writer with
            # whatever extension the file already has.
            ext = self._image_path.rsplit(".", 1)[-1].lower() if "." in self._image_path else "png"
            fmt_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG",
                       "bmp": "BMP", "tif": "TIFF", "tiff": "TIFF"}
            qt_fmt = fmt_map.get(ext, "PNG")
            quality = 90 if qt_fmt == "JPEG" else -1
            self._working.save(self._image_path, qt_fmt, quality)

        if self._on_save:
            self._on_save()
        self.accept()

    def _save_as_new(self):
        """Prompt for filename + format, then write the file. Returns True on
        successful save; False if the user cancelled or the write failed."""
        # Default to $HIP so the file lands next to the .hip by default.
        default_dir = ""
        try:
            default_dir = hou.expandString("$HIP") or ""
        except Exception:
            default_dir = ""
        if not default_dir or not os.path.isdir(default_dir):
            default_dir = os.path.expanduser("~")
        default_path = os.path.join(default_dir, "stamp_layer.png")

        filters = ("PNG 16-bit (*.png);;"
                   "JPEG 8-bit (*.jpg);;"
                   "OpenEXR 32-bit (*.exr)")
        path, selected = QFileDialog.getSaveFileName(
            self, "Save Image As", default_path, filters,
            "PNG 16-bit (*.png)"
        )
        if not path:
            return False

        if "JPEG" in selected:
            fmt = "jpg_8"
            if not path.lower().endswith((".jpg", ".jpeg")):
                path += ".jpg"
        elif "EXR" in selected:
            fmt = "exr_32"
            if not path.lower().endswith(".exr"):
                path += ".exr"
        else:
            fmt = "png_16"
            if not path.lower().endswith(".png"):
                path += ".png"

        ok, msg = _save_qimage_as(self._working, path, fmt)
        if not ok:
            QMessageBox.warning(self, "Save failed",
                                msg or "Could not save image.")
            return False
        if msg:
            # Non-fatal note (e.g. 16-bit downgraded to 8-bit).
            QMessageBox.information(self, "Saved with note", msg)

        self._image_path = path
        self.setWindowTitle(f"Image Editor — {os.path.basename(path)}")
        return True


# ---------------------------------------------------------------------------
# Main ScatterWindow widget
# ---------------------------------------------------------------------------
class ScatterWindow(QWidget):
    """
    The SP Scatter control panel.  Works as:
      • A Houdini Python Panel widget (returned from createInterface)
      • A standalone floating window (show() fallback)
    """

    def __init__(self, parent=None, mode="scatter"):
        super().__init__(parent)
        # mode: "scatter"      → Set Dressing + Transformation + paint row.
        #       "ivy"          → Transformation + Ivy Generation, no paint row.
        #       "crawling_ivy" → Crawling Ivy focused tabs only.
        self._is_crawling_ivy = (mode == "crawling_ivy")
        self._mode = "ivy" if self._is_crawling_ivy else mode
        if self._is_crawling_ivy:
            self.setObjectName("CrawlingIvyPanel")
        elif mode == "ivy":
            self.setObjectName("IvyScatterPanel")
        else:
            self.setObjectName("SPScatterPanel")
        self._current_theme = self._load_theme_pref()
        self.setStyleSheet(_build_stylesheet(self._current_theme))

        if self._is_crawling_ivy:
            global _window_crawling_ivy
            _window_crawling_ivy = self
        elif mode == "ivy":
            global _window_ivy
            _window_ivy = self
        else:
            global _window
            _window = self

        # Internal bookkeeping
        self.session_id          = str(random.random())[2:8]
        self.asset_rows          = []
        self._asset_size_preset  = "small"
        self._prevent_sync       = False
        self._ivy_widgets        = {}   # name -> QSpinBox / QDoubleSpinBox
        self._ivy_sliders        = {}
        self._crawl_widgets      = {}   # name -> QSpinBox / QDoubleSpinBox
        self._scatter_noise_widgets = {}
        self._ivy_sim_widgets    = {}
        self._ivy_sim_sliders    = {}
        self._ivy_noise_widgets  = {}
        self._ivy_noise_sliders  = {}

        # Houdini nodes
        self.surface_paths       = []     # ordered list of surface SOP paths
        self.scatter_sop_node    = None   # the attribpaint SOP
        self.geo_node            = None

        # Placement rules state
        self._placement_rules    = []
        self._rule_cards         = []   # parallel list of QFrame cards in _rules_layout

        # Full parameter state dict (mirrors what logic.sync_scatter_params expects)
        self.state = {
            "radius":           RADIUS_DEF,
            "density":          DENS_DEF,
            "spacing":          SPC_DEF,
            "falloff_amount":   FAL_AMT_DEF,
            "falloff_softness": FAL_SFT_DEF,
            "relax_iter":       RELAX_DEF,
            "max_points":       MAX_PTS_DEF,
            "min_distance":     MDIST_DEF,
            "global_scale":     GS_DEF,
            "rot_min":          ROT_MIN_DEF,
            "rot_max":          ROT_MAX_DEF,
            "rot_randomize":    ROT_RAND_DEF,
            "cone_angle":       CONE_DEF,
            "uniform_xyz":      True,
            "scl_min":          [SCL_MIN_DEF] * 3,
            "scl_max":          [SCL_MAX_DEF] * 3,
            "pscale_randomize":  PSCALE_RAND_DEF,
            "stamp_layers":     [],
            "mode":             "paint",
            "real_time":        True,
        }
        self.state.update(IVY_DEFAULTS)
        self.state.update(CRAWL_DEFAULTS)
        self.state.update(logic.SCATTER_NOISE_DEFAULTS)
        self.state.update(logic.SCATTER_CACHE_DEFAULTS)
        self.state.update(logic.CLUMP_DEFAULTS)
        self.state.update(logic.COLOR_VARIATION_DEFAULTS)
        self.state.update(logic.PROXIMITY_DEFAULTS)
        self.state.update(logic.LOD_DEFAULTS)

        # Register viewer state once
        try:
            rc.register()
        except Exception as e:
            print(f"[Magic Scatter World] Viewer state: {e}")

        self._build_ui()
        self._refresh_resume_dropdown()
        self._setup_hip_callbacks()

        # Auto-resume to the last active scatter network if it still exists
        self._auto_resume_last()

    # ======================================================================
    # UI construction
    # ======================================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── header bar ────────────────────────────────────────────────────
        root.addLayout(self._build_header())
        root.addWidget(_h_sep(), 0)

        # ── scene / asset area ────────────────────────────────────────────
        root.addWidget(self._build_scene_row(), 0)

        # ── parameter tabs ────────────────────────────────────────────────
        # Tab subset depends on mode. Both modes share the Transformation
        # tab; each window instance owns its own state, so the Rotation/
        # Scale values in one window do not affect the other.
        self._tabs = QTabWidget()

        if self._mode == "scatter":
            self._tabs.addTab(self._build_brush_tab(), "Paint")
            self._tabs.addTab(self._build_stamp_tab(), "Stamp")
            self._tabs.addTab(self._build_curve_tab(), "Curve")
            self._tabs.addTab(self._build_transformation_unified_tab(), "Transform")
            self._tabs.addTab(self._build_scatter_appearance_tab(), "Appearance")
            self._tabs.addTab(self._build_noises_tab(), "Noises")
            self._tabs.addTab(self._build_lod_tab(), "LOD")
            self._tabs.addTab(self._build_scatter_cache_tab(), "Cache")
        elif self._is_crawling_ivy:
            self._tabs.addTab(self._build_paint_mask_tab(), "Paint Mask")
            self._tabs.addTab(self._build_cy_appearance_tab(), "Appearance")
            self._tabs.addTab(self._build_transformation_unified_tab(), "Transformation")
            self._tabs.addTab(self._build_cy_crawl_tab(), "Crawling Ivy")
            self._tabs.addTab(self._build_cy_output_bake_tab(), "Output/Bake")
            # Build ivy/sim tabs silently so their self.* attrs exist for shared handlers.
            # Must be stored on self — otherwise GC deletes them and their child widgets.
            self._ivy_tab_hidden = self._build_ivy_tab()
            self._sim_tab_hidden = self._build_simulation_tab()
        else:  # ivy
            self._tabs.addTab(self._build_paint_mask_tab(), "Paint Mask")
            self._tabs.addTab(self._build_appearance_tab(), "Appearance")
            self._tabs.addTab(self._build_transformation_unified_tab(), "Transformation")
            self._tabs.addTab(self._build_ivy_tab(),       "Ivy Generation")
            simulation_tab = self._build_simulation_tab()
            self._tabs.addTab(simulation_tab, "Simulation")
            self._tabs.addTab(self._build_output_bake_tab(), "Output/Bake")
            # Build crawl tab silently so self.crawl_* widgets exist for shared handlers.
            self._ivy_crawl_tab_hidden = self._build_ivy_crawl_tab()

            # Apply simulation tab tint without depending on the tab order.
            self._tabs.tabBar().setTabTextColor(self._tabs.indexOf(simulation_tab), QColor("#ffee00"))

        # ── splitter: resizable asset panel above [resume + sep + tabs] ───
        tabs_w = QWidget()
        tabs_w_lay = QVBoxLayout(tabs_w)
        tabs_w_lay.setContentsMargins(0, 0, 0, 0)
        tabs_w_lay.setSpacing(6)
        tabs_w_lay.addLayout(self._build_resume_row())
        tabs_w_lay.addLayout(self._build_global_preset_row())
        if self._mode == "scatter":
            tabs_w_lay.addLayout(self._build_biome_row())
            tabs_w_lay.addWidget(self._build_altitude_mask_group())
        tabs_w_lay.addWidget(_h_sep())
        tabs_w_lay.addWidget(self._tabs, 1)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._build_asset_area())
        splitter.addWidget(tabs_w)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        if self._mode == "ivy":
            # ── ivy persistent footer ─────────────────────────────────────────────
            self.ivy_rt_cb = QCheckBox("Real-time update")
            self.ivy_rt_cb.setChecked(True)
            self.ivy_rt_cb.hide()
            self.ivy_status_l = QLabel("No ivy network.")
            self.ivy_status_l.setStyleSheet("color:#888; font-size:10px; padding:2px;")
            self.ivy_status_l.setWordWrap(True)
            if not self._is_crawling_ivy:
                footer_lay = QVBoxLayout()
                footer_lay.setContentsMargins(8, 0, 8, 4)
                rt_row = QHBoxLayout()
                rt_row.addWidget(self.ivy_rt_cb)
                rt_row.addStretch()
                footer_lay.addLayout(rt_row)
                footer_lay.addWidget(self.ivy_status_l)
                root.addLayout(footer_lay)

        # ── Paint / Erase / Clear All buttons above status bar (scatter only) ───
        if self._mode == "scatter":
            root.addLayout(self._build_paint_row(), 0)

        # ── status bar pinned at the very bottom ──────────────────────────
        status_widget = QWidget()
        status_lay = self._build_status_bar()
        status_widget.setLayout(status_lay)
        root.addWidget(status_widget, 0)

    # ── header ────────────────────────────────────────────────────────────
    def _build_header(self):
        lay = QHBoxLayout()
        if self._is_crawling_ivy:
            title_text = "CRAWLING IVY"
        elif self._mode == "ivy":
            title_text = "IVY SCATTER"
        else:
            title_text = "MAGIC SCATTER WORLD"
        title = QLabel(f"{title_text}  ·  v{TOOL_VERSION}")
        title.setObjectName("section_header")
        title.setStyleSheet("font-size:14px; font-weight:bold; letter-spacing:1px;")
        lay.addWidget(title)
        lay.addStretch()

        self.lookdev_btn = QPushButton("Lookdev")
        self.lookdev_btn.setFixedHeight(22)
        self.lookdev_btn.setToolTip(
            "Open the Lookdev window — build PBR shaders for your assets\n"
            "in Arnold or Redshift, with textures and live parameter tweaks."
        )
        self.lookdev_btn.setStyleSheet(
            "QPushButton { background-color:#3a1a5c; color:#d0b0ff; border-color:#5f2b8b; padding:0 10px; }"
            "QPushButton:hover { background-color:#4f2480; border-color:#8f3cc8; }"
            "QPushButton:pressed { background-color:#241038; }"
        )
        self.lookdev_btn.clicked.connect(self._open_lookdev)
        lay.addWidget(self.lookdev_btn)

        theme_l = QLabel("Theme:")
        theme_l.setObjectName("info_label")
        lay.addWidget(theme_l)

        self.theme_cb = QComboBox()
        self.theme_cb.setToolTip(
            "Switch the panel color theme.\n"
            "Custom skins are stored in:\n"
            f"{_user_themes_path()}"
        )
        self._refresh_theme_combo()
        self.theme_cb.activated.connect(self._on_theme_changed)
        lay.addWidget(self.theme_cb)

        self.skin_new_btn = QPushButton("+ New")
        self.skin_new_btn.setFixedHeight(22)
        self.skin_new_btn.setToolTip("Create a new custom skin from scratch (starts from the current theme)")
        self.skin_new_btn.clicked.connect(self._on_skin_new)
        lay.addWidget(self.skin_new_btn)

        self.skin_edit_btn = QPushButton("Edit")
        self.skin_edit_btn.setFixedHeight(22)
        self.skin_edit_btn.setToolTip("Edit the selected user skin (built-in skins are read-only)")
        self.skin_edit_btn.clicked.connect(self._on_skin_edit)
        lay.addWidget(self.skin_edit_btn)

        self.skin_delete_btn = QPushButton("✕")
        self.skin_delete_btn.setFixedSize(22, 22)
        self.skin_delete_btn.setToolTip("Delete the selected user skin")
        self.skin_delete_btn.clicked.connect(self._on_skin_delete)
        lay.addWidget(self.skin_delete_btn)

        about_btn = QPushButton("?")
        about_btn.setFixedSize(22, 22)
        about_btn.setToolTip("About Magic Scatter World")
        about_btn.clicked.connect(self._show_about)
        lay.addWidget(about_btn)
        return lay

    @property
    def surface_node_path(self):
        """Primary surface path — backward-compat read accessor."""
        return self.surface_paths[0] if self.surface_paths else ""

    # ── scene controls ────────────────────────────────────────────────────
    def _build_scene_row(self):
        outer = QVBoxLayout()
        outer.setSpacing(2)

        # ── row 1: labels + buttons ──────────────────────────────────────
        lay = QHBoxLayout()
        lay.setSpacing(4)

        self.surf_l = QLabel("Surface: —")
        self.surf_l.setObjectName("info_label")
        self.surf_l.setToolTip("Currently selected scatter surface(s)")
        lay.addWidget(self.surf_l, 1)

        self.node_l = QLabel("Node: —")
        self.node_l.setObjectName("info_label")
        self.node_l.setToolTip("Active scatter SOP node")
        lay.addWidget(self.node_l, 1)

        _surf_style = (
            "QPushButton { background-color: #5c3a1a; color: #e0c09a; border-color: #8b5a2b; }"
            "QPushButton:hover { background-color: #7a4e24; border-color: #c8823c; }"
            "QPushButton:pressed { background-color: #3b2410; }"
        )
        b_surf = QPushButton("Set Surface")
        b_surf.setToolTip("Select geometry node(s) in viewport — replaces current surface list")
        b_surf.setStyleSheet(_surf_style)
        b_surf.clicked.connect(self._set_surface)

        b_add_surf = QPushButton("+ Surface")
        b_add_surf.setToolTip("Select geometry node(s) in viewport — adds to current surface list")
        b_add_surf.setStyleSheet(_surf_style)
        b_add_surf.clicked.connect(self._add_surface)

        b_on_scatter = QPushButton("↳ On Scatter")
        b_on_scatter.setToolTip(
            "Select a Magic Scatter geo node — scatter on top of its instanced geometry"
        )
        b_on_scatter.setStyleSheet(
            "QPushButton { background-color: #3a1a5c; color: #c09ae0; border-color: #6b2b8b; }"
            "QPushButton:hover { background-color: #4e2480; border-color: #a83cc8; }"
            "QPushButton:pressed { background-color: #240f3b; }"
        )
        b_on_scatter.clicked.connect(self._on_scatter_on_scatter)

        # Dropdown toggle — only visible when there are multiple surfaces
        self._surf_toggle_btn = QPushButton("▼ surfaces")
        self._surf_toggle_btn.setToolTip("Show / hide surface list")
        self._surf_toggle_btn.setCheckable(True)
        self._surf_toggle_btn.setVisible(False)
        self._surf_toggle_btn.setStyleSheet(
            "QPushButton { background-color: #2a2a2a; color: #a0b0c0; border-color: #444;"
            "  padding: 2px 6px; }"
            "QPushButton:checked { background-color: #333; color: #c0d8f0; }"
            "QPushButton:hover { border-color: #888; }"
        )
        self._surf_toggle_btn.toggled.connect(self._on_surf_toggle)

        b_add = QPushButton("Add Asset(s)")
        b_add.setToolTip("Select geometry nodes to scatter, then click")
        b_add.setStyleSheet(
            "QPushButton { background-color: #1a3a5c; color: #9ac0e0; border-color: #2b5f8b; }"
            "QPushButton:hover { background-color: #245080; border-color: #3c8fc8; }"
            "QPushButton:pressed { background-color: #102438; }"
        )
        b_add.clicked.connect(self._add_objects)

        b_new = QPushButton("New Setup")
        b_new.setToolTip("Reset to a blank scatter session")
        b_new.setStyleSheet(
            "QPushButton { background-color: #4a4a4a; color: #cccccc; border-color: #6a6a6a; }"
            "QPushButton:hover { background-color: #5a5a5a; border-color: #909090; }"
            "QPushButton:pressed { background-color: #333333; }"
        )
        b_new.clicked.connect(self._on_new_setup)

        b_cre = QPushButton("Create Network")
        b_cre.setToolTip("Build the Houdini SOP network for this setup")
        b_cre.setStyleSheet(
            "QPushButton { background-color: #1a5c1a; color: #7fff7f; border-color: #3a9a3a; }"
            "QPushButton:hover { background-color: #236b23; border-color: #5fdb5f; }"
            "QPushButton:pressed { background-color: #0f3a0f; }"
        )
        b_cre.clicked.connect(self._on_create)

        for b in (b_surf, b_add_surf, b_on_scatter, self._surf_toggle_btn, b_add, b_new, b_cre):
            lay.addWidget(b)
        outer.addLayout(lay)

        # ── row 2: collapsible surface list (hidden by default) ──────────
        self._surf_list_w = QWidget()
        self._surf_list_w.setStyleSheet(
            "QWidget { background-color: #1e1e1e; border: 1px solid #333; border-radius: 3px; }"
        )
        self._surf_list_layout = QVBoxLayout(self._surf_list_w)
        self._surf_list_layout.setContentsMargins(4, 3, 4, 3)
        self._surf_list_layout.setSpacing(2)
        self._surf_list_w.setVisible(False)
        outer.addWidget(self._surf_list_w)

        container = QWidget()
        container.setLayout(outer)
        return container

    def _on_surf_toggle(self, checked):
        n = len(self.surface_paths)
        arrow = "▲" if checked else "▼"
        self._surf_toggle_btn.setText(f"{arrow} {n} surfaces")
        self._surf_list_w.setVisible(checked)

    # ── asset scroll area ─────────────────────────────────────────────────
    def _build_asset_area(self):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setMinimumHeight(60)
        sc.setContextMenuPolicy(Qt.CustomContextMenu)
        sc.customContextMenuRequested.connect(
            lambda pos: self._show_asset_context_menu(sc.mapToGlobal(pos))
        )
        self._asset_container = QWidget()
        self._asset_container.setContextMenuPolicy(Qt.CustomContextMenu)
        self._asset_container.customContextMenuRequested.connect(
            lambda pos: self._show_asset_context_menu(self._asset_container.mapToGlobal(pos))
        )
        self._asset_layout    = FlowLayout(self._asset_container, margin=4, spacing=6)
        sc.setWidget(self._asset_container)
        return sc

    # ── resume dropdown ───────────────────────────────────────────────────
    def _build_resume_row(self):
        lay = QHBoxLayout()
        lay.addWidget(QLabel("Resume session:"))
        self.resume_cb = QComboBox()
        self.resume_cb.setToolTip("Resume a previously created scatter or ivy session from this .hip file.")
        self.resume_cb.currentIndexChanged.connect(self._on_resume_dropdown)
        lay.addWidget(self.resume_cb, 1)
        return lay

    # ── Biome preset row (scatter mode only) ─────────────────────────────
    def _build_biome_row(self):
        """Returns a QHBoxLayout with: Biome combo + Apply / Save / Delete buttons.
        Built-in presets first, then a separator, then user presets."""
        self._biome_user_presets = self._load_biome_user_presets()
        lay = QHBoxLayout()
        lbl = QLabel("Biome:")
        lbl.setToolTip("Apply a real-world biome distribution preset.\n"
                       "Affects density, spacing, scale, rotation and noise — "
                       "your assets, surface, and paint masks are not changed.")
        lay.addWidget(lbl)

        self.biome_cb = QComboBox()
        self.biome_cb.setToolTip(
            "Built-in biomes calibrated from real-world ecological "
            "characteristics. User presets appear below the separator."
        )
        lay.addWidget(self.biome_cb, 1)

        apply_btn = QPushButton("Apply")
        apply_btn.setToolTip("Overwrite distribution / scale / rotation / noise "
                             "with the selected biome preset.")
        apply_btn.clicked.connect(self._on_biome_apply)
        lay.addWidget(apply_btn)

        save_btn = QPushButton("Save…")
        save_btn.setToolTip("Save the current settings as a custom biome preset.")
        save_btn.clicked.connect(self._on_biome_save)
        lay.addWidget(save_btn)

        del_btn = QPushButton("Delete")
        del_btn.setToolTip("Delete the selected user preset (built-ins are protected).")
        del_btn.clicked.connect(self._on_biome_delete)
        lay.addWidget(del_btn)

        self._refresh_biome_combo()
        return lay

    # ── Biome preset persistence ─────────────────────────────────────────
    def _load_biome_user_presets(self):
        path = _biome_user_presets_path()
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}
        except Exception as e:
            print(f"[Magic Scatter World] Failed to load user biome presets: {e}")
        return {}

    def _save_biome_user_presets(self):
        path = _biome_user_presets_path()
        try:
            with open(path, "w") as f:
                json.dump(self._biome_user_presets, f, indent=2)
        except Exception as e:
            print(f"[Magic Scatter World] Failed to save user biome presets: {e}")

    def _refresh_biome_combo(self, select_name=None):
        cb = self.biome_cb
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("— Select biome preset —")
        for name in BIOME_PRESETS.keys():
            cb.addItem(name)
        if self._biome_user_presets:
            cb.insertSeparator(cb.count())
            for name in sorted(self._biome_user_presets.keys()):
                cb.addItem(name)
        if select_name:
            idx = cb.findText(select_name)
            if idx >= 0:
                cb.setCurrentIndex(idx)
        else:
            cb.setCurrentIndex(0)
        cb.blockSignals(False)

    def _selected_biome_name(self):
        idx = self.biome_cb.currentIndex()
        if idx <= 0:
            return None
        name = self.biome_cb.itemText(idx)
        if not name or name.startswith("—"):
            return None
        return name

    def _on_biome_apply(self):
        name = self._selected_biome_name()
        if not name:
            self._set_status("Select a biome preset first.", error=True)
            return
        vals = BIOME_PRESETS.get(name) or self._biome_user_presets.get(name)
        if not vals:
            return
        self._apply_biome_preset(vals)
        self._set_status(f"Applied biome preset '{name}'.")

    def _on_biome_save(self):
        name, ok = QInputDialog.getText(self, "Save Biome Preset", "Preset name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            self._set_status("Preset name cannot be empty.", error=True)
            return
        if name in BIOME_PRESETS:
            QMessageBox.warning(self, "Reserved name",
                                f"'{name}' is a built-in biome preset name. "
                                "Choose a different name.")
            return
        if name in self._biome_user_presets:
            reply = QMessageBox.question(
                self, "Overwrite preset?",
                f"A biome preset named '{name}' already exists. Overwrite it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        vals = self._collect_biome_state()
        if not vals:
            self._set_status("Could not snapshot scatter state.", error=True)
            return
        self._biome_user_presets[name] = vals
        self._save_biome_user_presets()
        self._refresh_biome_combo(select_name=name)
        self._set_status(f"Saved biome preset '{name}'.")

    def _on_biome_delete(self):
        name = self._selected_biome_name()
        if not name:
            self._set_status("Select a user preset to delete.", error=True)
            return
        if name in BIOME_PRESETS:
            QMessageBox.information(self, "Built-in preset",
                                    f"'{name}' is a built-in biome preset and cannot be deleted.")
            return
        if name not in self._biome_user_presets:
            return
        reply = QMessageBox.question(
            self, "Delete preset?",
            f"Delete biome preset '{name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        del self._biome_user_presets[name]
        self._save_biome_user_presets()
        self._refresh_biome_combo()
        self._set_status(f"Deleted biome preset '{name}'.")

    # ── Global Preset row (all modes) ───────────────────────────────────
    def _build_global_preset_row(self):
        """Preset: combo + Apply / Save / Delete / Export / Import buttons."""
        self._global_presets = self._load_global_presets()
        lay = QHBoxLayout()
        lbl = QLabel("Preset:")
        lbl.setToolTip("Save or load a full snapshot of all UI parameters.")
        lay.addWidget(lbl)

        self.global_preset_cb = QComboBox()
        self.global_preset_cb.setToolTip(
            "Click a preset to apply it immediately.\n"
            "Presets capture all distribution, transformation, noise, "
            "ivy/crawl, and cache settings."
        )
        # activated fires on user click/Enter but not on programmatic changes,
        # so scrolling through the list won't spam apply calls.
        self.global_preset_cb.activated.connect(self._on_global_preset_apply)
        lay.addWidget(self.global_preset_cb, 1)

        save_btn = QPushButton("Save…")
        save_btn.setToolTip("Save current settings as a new global preset.")
        save_btn.clicked.connect(self._on_global_preset_save)
        lay.addWidget(save_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setToolTip("Overwrite the selected preset with the current settings.")
        edit_btn.clicked.connect(self._on_global_preset_edit)
        lay.addWidget(edit_btn)

        del_btn = QPushButton("Delete")
        del_btn.setToolTip("Delete the selected preset.")
        del_btn.clicked.connect(self._on_global_preset_delete)
        lay.addWidget(del_btn)

        export_btn = QPushButton("Export…")
        export_btn.setToolTip("Export the selected preset to a standalone JSON file.")
        export_btn.clicked.connect(self._on_global_preset_export)
        lay.addWidget(export_btn)

        import_btn = QPushButton("Import…")
        import_btn.setToolTip("Import a preset from a JSON file.")
        import_btn.clicked.connect(self._on_global_preset_import)
        lay.addWidget(import_btn)

        self._refresh_global_preset_combo()
        return lay

    # ── Global preset persistence ────────────────────────────────────────
    _GLOBAL_PRESET_EXCLUDE = frozenset({
        "mode", "real_time", "stamp_layers", "stamp_mask_layer",
        "weights", "cam_frustum_path",
        "ivy_sim", "ivy_glue", "ivy_collision", "ivy_sim_length",
        "scatter_active_mask_layer", "scatter_mask_layers",
        "scatter_noise_mask_gating", "assets",
    })

    def _load_global_presets(self):
        mode_key = "crawling_ivy" if self._is_crawling_ivy else self._mode
        path = _global_preset_path(mode_key)
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}
        except Exception as e:
            print(f"[Magic Scatter World] Failed to load global presets: {e}")
        return {}

    def _save_global_presets(self):
        mode_key = "crawling_ivy" if self._is_crawling_ivy else self._mode
        path = _global_preset_path(mode_key)
        try:
            with open(path, "w") as f:
                json.dump(self._global_presets, f, indent=2)
        except Exception as e:
            print(f"[Magic Scatter World] Failed to save global presets: {e}")

    def _refresh_global_preset_combo(self, select_name=None):
        cb = self.global_preset_cb
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("— Select preset —")
        for name in sorted(self._global_presets.keys()):
            cb.addItem(name)
        if select_name:
            idx = cb.findText(select_name)
            if idx >= 0:
                cb.setCurrentIndex(idx)
        else:
            cb.setCurrentIndex(0)
        cb.blockSignals(False)

    def _selected_global_preset_name(self):
        idx = self.global_preset_cb.currentIndex()
        if idx <= 0:
            return None
        name = self.global_preset_cb.itemText(idx)
        return name if name and not name.startswith("—") else None

    def _collect_global_preset(self):
        """Snapshot self.state into a portable preset dict."""
        self.sync_state(save=False)
        return {
            k: v for k, v in self.state.items()
            if k not in self._GLOBAL_PRESET_EXCLUDE
        }

    def _apply_global_preset(self, data):
        """Push preset data onto all UI widgets, then sync to Houdini."""
        self._prevent_sync = True
        try:
            # ── Brush / density ──────────────────────────────────────────
            for key, attr in (
                ("radius",           "r_sb"),
                ("density",          "d_sb"),
                ("spacing",          "s_sb"),
                ("falloff_amount",   "fa_sb"),
                ("falloff_softness", "fs_sb"),
                ("relax_iter",       "relax_sb"),
                ("max_points",       "max_pts_sb"),
                ("min_distance",     "mdist_sb"),
                ("overlap_tolerance","overlap_tol_sb"),
                ("curve_scale",      "curve_scale_sb"),
                ("stamp_scale",      "stamp_scale_sb"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])

            for key, attr in (
                ("remove_overlapping", "remove_overlap_cb"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])

            # ── Transformation ───────────────────────────────────────────
            for key, attr in (
                ("rot_min",         "rot_min_sb"),
                ("rot_max",         "rot_max_sb"),
                ("rot_randomize",   "rot_rand_sb"),
                ("cone_angle",      "cone_sb"),
                ("global_scale",    "gs_sb"),
                ("pscale_randomize","pscale_rand_sb"),
                ("blend_amount",    "blend_amount_sb"),
                ("geo_offset",      "geo_offset_sb"),
                ("cam_fov_padding", "_cam_fov_pad_sb"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])

            for key, attr in (
                ("full_rand",        "full_rand_cb"),
                ("uniform_xyz",      "uni_cb"),
                ("normal_align",     "normal_align_cb"),
                ("cam_frustum_enabled", "_cam_frustum_cb"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])

            for key, attr in (
                ("blend_axis", "blend_axis_cb"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])

            # scl_min / scl_max are lists
            if "scl_min" in data:
                v = data["scl_min"]
                for w, val in zip([getattr(self, "smn_x", None),
                                   getattr(self, "smn_y", None),
                                   getattr(self, "smn_z", None)], v):
                    _set_preset_widget(w, val)
            if "scl_max" in data:
                v = data["scl_max"]
                for w, val in zip([getattr(self, "smx_x", None),
                                   getattr(self, "smx_y", None),
                                   getattr(self, "smx_z", None)], v):
                    _set_preset_widget(w, val)

            # ── Scatter noise widgets ─────────────────────────────────────
            for key, widget in self._scatter_noise_widgets.items():
                if key in data:
                    _set_preset_widget(widget, data[key])

            # ── Cache widgets ─────────────────────────────────────────────
            for key, attr in (
                ("scatter_cache_basedir",  "scatter_cache_folder_le"),
                ("scatter_cache_basename", "scatter_cache_name_le"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])
            for key, attr in (
                ("scatter_cache_version",        "scatter_cache_version_sb"),
                ("scatter_cache_start",          "scatter_cache_start_sb"),
                ("scatter_cache_end",            "scatter_cache_end_sb"),
                ("scatter_cache_inc",            "scatter_cache_inc_sb"),
                ("scatter_cache_substeps",       "scatter_cache_substeps_sb"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])
            for key, attr in (
                ("scatter_cache_loadfromdisk",   "scatter_cache_load_cb"),
                ("scatter_cache_timedependent",  "scatter_cache_timedependent_cb"),
                ("scatter_cache_simulation",     "scatter_cache_simulation_cb"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])
            if "scatter_cache_trange" in data:
                _set_preset_widget(getattr(self, "scatter_cache_trange_cb", None),
                                   data["scatter_cache_trange"])

            # ── Clumping widgets ─────────────────────────────────────────
            for key, attr in (
                ("clump_enabled",   "clump_enabled_cb"),
                ("clump_min_count", "clump_min_count_sb"),
                ("clump_seed",      "clump_seed_sb"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])
            for key, attr in (
                ("clump_radius",   "clump_radius_sb"),
                ("clump_strength", "clump_strength_sb"),
            ):
                if key in data:
                    _set_preset_widget(getattr(self, attr, None), data[key])

            # ── Color variation widgets ───────────────────────────────────
            if "color_variation_enabled" in data:
                _set_preset_widget(getattr(self, "color_var_enabled_cb", None),
                                   data["color_variation_enabled"])
            if "color_variation_seed" in data:
                _set_preset_widget(getattr(self, "color_var_seed_sb", None),
                                   data["color_variation_seed"])
            for key, attr in (
                ("color_variation_a", "color_var_a_btn"),
                ("color_variation_b", "color_var_b_btn"),
            ):
                if key in data:
                    btn = getattr(self, attr, None)
                    if btn is not None:
                        rgb = data[key]
                        c = QColor(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
                        btn._color = c
                        btn.setStyleSheet(
                            f"background:rgb({c.red()},{c.green()},{c.blue()});"
                            " border:1px solid #555;")

            # ── Ivy widgets ───────────────────────────────────────────────
            for name in IVY_DEFAULTS:
                if name in data:
                    _set_preset_widget(self._ivy_widgets.get(name), data[name])

            # ── Crawl widgets ─────────────────────────────────────────────
            for name in CRAWL_DEFAULTS:
                if name in data:
                    _set_preset_widget(self._crawl_widgets.get(name), data[name])

            # ── Altitude mask ─────────────────────────────────────────────
            if hasattr(self, "_alt_enabled_cb") and "altitude_enabled" in data:
                self._push_altitude_to_ui(
                    bool(data.get("altitude_enabled", False)),
                    float(data.get("elev_min", 0.0)),
                    float(data.get("elev_max", 1.0)),
                    float(data.get("elev_falloff", 0.10)),
                    float(data.get("slope_max", 0.55)),
                    float(data.get("slope_falloff", 0.10)),
                )

        finally:
            self._prevent_sync = False

        self.sync_state(save=self.scatter_sop_node is not None)
        if self.scatter_sop_node is not None and self.geo_node is not None:
            if "altitude_enabled" in data:
                try:
                    logic.set_altitude_mask_params(
                        self.geo_node,
                        bool(data.get("altitude_enabled", False)),
                        float(data.get("elev_min", 0.0)),
                        float(data.get("elev_max", 1.0)),
                        float(data.get("elev_falloff", 0.10)),
                        float(data.get("slope_max", 0.55)),
                        float(data.get("slope_falloff", 0.10)),
                    )
                except Exception as e:
                    print(f"[Magic Scatter World] preset altitude apply: {e}")

    def _on_global_preset_apply(self, *_):
        name = self._selected_global_preset_name()
        if not name:
            return
        data = self._global_presets.get(name)
        if not data:
            return
        self._apply_global_preset(data)
        self._set_status(f"Applied preset '{name}'.")

    def _on_global_preset_save(self):
        name, ok = QInputDialog.getText(self, "Save Global Preset", "Preset name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            self._set_status("Preset name cannot be empty.", error=True)
            return
        if name in self._global_presets:
            reply = QMessageBox.question(
                self, "Overwrite preset?",
                f"A preset named '{name}' already exists. Overwrite it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self._global_presets[name] = self._collect_global_preset()
        self._save_global_presets()
        self._refresh_global_preset_combo(select_name=name)
        self._set_status(f"Saved preset '{name}'.")

    def _on_global_preset_edit(self):
        name = self._selected_global_preset_name()
        if not name:
            self._set_status("Select a preset to overwrite.", error=True)
            return
        reply = QMessageBox.question(
            self, "Overwrite preset?",
            f"Overwrite '{name}' with the current settings?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._global_presets[name] = self._collect_global_preset()
        self._save_global_presets()
        self._refresh_global_preset_combo(select_name=name)
        self._set_status(f"Updated preset '{name}'.")

    def _on_global_preset_delete(self):
        name = self._selected_global_preset_name()
        if not name:
            self._set_status("Select a preset to delete.", error=True)
            return
        reply = QMessageBox.question(
            self, "Delete preset?",
            f"Delete preset '{name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._global_presets.pop(name, None)
        self._save_global_presets()
        self._refresh_global_preset_combo()
        self._set_status(f"Deleted preset '{name}'.")

    def _on_global_preset_export(self):
        name = self._selected_global_preset_name()
        if not name:
            self._set_status("Select a preset to export.", error=True)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Preset", f"{name}.json", "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump({name: self._global_presets[name]}, f, indent=2)
            self._set_status(f"Exported preset '{name}' to {os.path.basename(path)}.")
        except Exception as e:
            self._set_status(f"Export failed: {e}", error=True)

    def _on_global_preset_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Preset", "", "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as e:
            self._set_status(f"Import failed: {e}", error=True)
            return
        if not isinstance(data, dict):
            self._set_status("Invalid preset file.", error=True)
            return
        # File may be {name: {params}} or a flat {params} (single preset)
        imported = 0
        last_name = None
        if all(isinstance(v, dict) for v in data.values()):
            for name, vals in data.items():
                self._global_presets[name] = vals
                last_name = name
                imported += 1
        else:
            # Flat dict — use filename as preset name
            name = os.path.splitext(os.path.basename(path))[0]
            self._global_presets[name] = data
            last_name = name
            imported = 1
        self._save_global_presets()
        self._refresh_global_preset_combo(select_name=last_name)
        self._set_status(f"Imported {imported} preset(s) from {os.path.basename(path)}.")

    # ── Altitude mask (elevation-as-temperature) ────────────────────────
    def _build_altitude_mask_group(self):
        """Collapsible group with altitude-mask sliders, preview toggle and a
        re-measure button. Shown only in scatter mode."""
        grp = _CollapsibleGroup("Altitude Mask (elevation = temperature)",
                                expanded=False)
        outer = QVBoxLayout(grp.body)
        outer.setContentsMargins(6, 4, 6, 6)
        outer.setSpacing(4)

        self._alt_enabled_cb = QCheckBox("Use altitude mask")
        self._alt_enabled_cb.setToolTip(
            "When on, scatter density is multiplied by an altitude band — "
            "biomes only grow inside their preferred elevation range."
        )
        self._alt_enabled_cb.toggled.connect(self._on_altitude_changed)
        outer.addWidget(self._alt_enabled_cb)

        def _slider_pct(label, default_pct):
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label)
            lbl.setFixedWidth(60)
            lbl.setStyleSheet("font-size:10px; color:#aaa;")
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(default_pct)
            vl = QLabel(f"{default_pct}%")
            vl.setFixedWidth(36)
            vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            vl.setStyleSheet("font-size:10px; color:#ddd;")
            row.addWidget(lbl)
            row.addWidget(sl, 1)
            row.addWidget(vl)
            return row, sl, vl

        row1, self._alt_min_sl, self._alt_min_vl = _slider_pct("Elev. min", 0)
        row2, self._alt_max_sl, self._alt_max_vl = _slider_pct("Elev. max", 100)
        row3, self._alt_fall_sl, self._alt_fall_vl = _slider_pct("Falloff", 10)
        row4, self._alt_slope_sl, self._alt_slope_vl = _slider_pct("Max slope", 55)
        row5, self._alt_sfall_sl, self._alt_sfall_vl = _slider_pct("Slope fall", 10)
        outer.addLayout(row1)
        outer.addLayout(row2)
        outer.addLayout(row3)
        outer.addLayout(row4)
        outer.addLayout(row5)

        for sl, vl in ((self._alt_min_sl,   self._alt_min_vl),
                       (self._alt_max_sl,   self._alt_max_vl),
                       (self._alt_fall_sl,  self._alt_fall_vl),
                       (self._alt_slope_sl, self._alt_slope_vl),
                       (self._alt_sfall_sl, self._alt_sfall_vl)):
            sl.valueChanged.connect(
                lambda v, lbl=vl: lbl.setText(f"{v}%"))
            sl.valueChanged.connect(self._on_altitude_changed)

        # Keep min ≤ max automatically.
        self._alt_min_sl.valueChanged.connect(
            lambda v: self._alt_max_sl.setValue(max(v, self._alt_max_sl.value())))
        self._alt_max_sl.valueChanged.connect(
            lambda v: self._alt_min_sl.setValue(min(v, self._alt_min_sl.value())))

        bottom = QHBoxLayout()
        self._alt_preview_cb = QCheckBox("Show preview")
        self._alt_preview_cb.setToolTip(
            "Overlay a colored heatmap on the terrain showing where this "
            "altitude band scatters (green) versus excludes (red).")
        self._alt_preview_cb.toggled.connect(self._on_altitude_preview_toggled)
        bottom.addWidget(self._alt_preview_cb)

        self._alt_y_range_lbl = QLabel("Y: —")
        self._alt_y_range_lbl.setStyleSheet("font-size:10px; color:#888;")
        self._alt_y_range_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self._alt_y_range_lbl, 1)

        remeasure_btn = QPushButton("Re-measure")
        remeasure_btn.setToolTip("Re-read the surface bounding box (use after "
                                 "editing the terrain).")
        remeasure_btn.clicked.connect(self._on_altitude_remeasure)
        bottom.addWidget(remeasure_btn)
        outer.addLayout(bottom)

        return grp

    def _altitude_state(self):
        """Return (enabled, emin, emax, falloff, slope_max, slope_falloff)."""
        enabled   = self._alt_enabled_cb.isChecked()
        emin      = self._alt_min_sl.value()   / 100.0
        emax      = self._alt_max_sl.value()   / 100.0
        fall      = self._alt_fall_sl.value()  / 100.0
        slope_max = self._alt_slope_sl.value() / 100.0
        slope_fall = self._alt_sfall_sl.value() / 100.0
        return enabled, emin, emax, fall, slope_max, slope_fall

    def _on_altitude_changed(self, *_):
        if self.scatter_sop_node is None:
            return
        try:
            geo_node = self.scatter_sop_node.parent()
            enabled, emin, emax, fall, slope_max, slope_fall = self._altitude_state()
            logic.set_altitude_mask_params(geo_node, enabled, emin, emax, fall,
                                           slope_max, slope_fall)
        except Exception as e:
            print(f"[Magic Scatter World] altitude apply failed: {e}")

    def _on_altitude_preview_toggled(self, on):
        if self.scatter_sop_node is None:
            return
        try:
            geo_node = self.scatter_sop_node.parent()
            logic.set_altitude_vis_visible(geo_node, bool(on))
        except Exception as e:
            print(f"[Magic Scatter World] altitude preview toggle failed: {e}")

    def _on_altitude_remeasure(self):
        self._measure_surface()
        self._set_status("Surface re-measured.")

    def _push_altitude_to_ui(self, enabled, emin, emax, fall,
                             slope_max=0.55, slope_fall=0.10):
        """Sync the altitude widgets without firing change handlers."""
        pairs = (
            (self._alt_min_sl,   self._alt_min_vl,   emin),
            (self._alt_max_sl,   self._alt_max_vl,   emax),
            (self._alt_fall_sl,  self._alt_fall_vl,  fall),
            (self._alt_slope_sl, self._alt_slope_vl, slope_max),
            (self._alt_sfall_sl, self._alt_sfall_vl, slope_fall),
        )
        for sl, vl, v in pairs:
            pct = int(round(v * 100))
            sl.blockSignals(True)
            sl.setValue(max(0, min(100, pct)))
            sl.blockSignals(False)
            vl.setText(f"{pct}%")
        self._alt_enabled_cb.blockSignals(True)
        self._alt_enabled_cb.setChecked(bool(enabled))
        self._alt_enabled_cb.blockSignals(False)

    # ── Biome preset apply / snapshot ────────────────────────────────────
    # Mapping: preset key → ScatterWindow attribute (non-noise scalars).
    _BIOME_NON_NOISE_ATTRS = {
        "dens":         "d_sb",
        "spacing":      "s_sb",
        "min_distance": "mdist_sb",
        "relax_iter":   "relax_sb",
        "f_amt":        "fa_sb",
        "f_soft":       "fs_sb",
        "max_pts":      "max_pts_sb",
        "cone_angle":   "cone_sb",
        "gs":           "gs_sb",
        "full_rand":    "full_rand_cb",
        "uniform_xyz":  "uni_cb",
    }

    def _apply_biome_preset(self, vals):
        """Full-overwrite apply: walk preset keys, set widget values, sync."""
        # Non-noise scalars / checkboxes
        for key, attr in self._BIOME_NON_NOISE_ATTRS.items():
            if key not in vals:
                continue
            w = getattr(self, attr, None)
            if w is None:
                continue
            v = vals[key]
            w.blockSignals(True)
            try:
                if isinstance(w, QCheckBox):
                    w.setChecked(bool(v))
                elif hasattr(w, "setValue"):
                    w.setValue(v)
            finally:
                w.blockSignals(False)

        # Scale range — preset stores uniform min/max; push to all axes.
        smin = vals.get("scale_min")
        smax = vals.get("scale_max")
        if smin is not None or smax is not None:
            for axis in ("x", "y", "z"):
                if smin is not None:
                    w = getattr(self, f"smn_{axis}", None)
                    if w is not None:
                        w.blockSignals(True)
                        w.setValue(smin)
                        w.blockSignals(False)
                if smax is not None:
                    w = getattr(self, f"smx_{axis}", None)
                    if w is not None:
                        w.blockSignals(True)
                        w.setValue(smax)
                        w.blockSignals(False)

        # Noise widgets
        noise_widgets = getattr(self, "_scatter_noise_widgets", {}) or {}
        for key, w in noise_widgets.items():
            if key not in vals:
                continue
            v = vals[key]
            w.blockSignals(True)
            try:
                if isinstance(w, QComboBox):
                    if isinstance(v, str):
                        idx = w.findText(v)
                        if idx >= 0:
                            w.setCurrentIndex(idx)
                    else:
                        w.setCurrentIndex(int(v))
                elif isinstance(w, QCheckBox):
                    w.setChecked(bool(v))
                elif isinstance(w, QLineEdit):
                    w.setText(str(v))
                elif hasattr(w, "setValue"):
                    w.setValue(v)
            finally:
                w.blockSignals(False)

        # Altitude mask — push to wrangle, sync UI sliders.
        if hasattr(self, "_alt_enabled_cb"):
            enabled    = bool(vals.get("altitude_enabled", False))
            emin       = float(vals.get("elev_min", 0.0))
            emax       = float(vals.get("elev_max", 1.0))
            fall       = float(vals.get("elev_falloff", 0.10))
            slope_max  = float(vals.get("slope_max", 0.55))
            slope_fall = float(vals.get("slope_falloff", 0.10))
            self._push_altitude_to_ui(enabled, emin, emax, fall, slope_max, slope_fall)
            if self.scatter_sop_node is not None:
                try:
                    geo_node = self.scatter_sop_node.parent()
                    logic.set_altitude_mask_params(geo_node, enabled, emin, emax, fall,
                                                   slope_max, slope_fall)
                except Exception as e:
                    print(f"[Magic Scatter World] biome altitude apply failed: {e}")

        # Push to the running scatter network in one shot.
        try:
            self._sync_rt()
        except Exception as e:
            print(f"[Magic Scatter World] Biome apply: _sync_rt failed: {e}")

    def _collect_biome_state(self):
        """Snapshot the current widget values into a biome preset dict.
        Combo widgets are saved as their display strings (portable)."""
        out = {}
        for key, attr in self._BIOME_NON_NOISE_ATTRS.items():
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if isinstance(w, QCheckBox):
                    out[key] = bool(w.isChecked())
                elif hasattr(w, "value"):
                    out[key] = w.value()
            except Exception:
                pass

        # Scale range — read X axis as the canonical value (uniform mode).
        for key, attr in (("scale_min", "smn_x"), ("scale_max", "smx_x")):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    out[key] = w.value()
                except Exception:
                    pass

        # Altitude mask state.
        if hasattr(self, "_alt_enabled_cb"):
            enabled, emin, emax, fall, slope_max, slope_fall = self._altitude_state()
            out["altitude_enabled"] = enabled
            out["elev_min"] = emin
            out["elev_max"] = emax
            out["elev_falloff"] = fall
            out["slope_max"] = slope_max
            out["slope_falloff"] = slope_fall

        noise_widgets = getattr(self, "_scatter_noise_widgets", {}) or {}
        noise_keys = {k for k in BIOME_PARAM_KEYS if k.startswith("scatter_noise_")}
        for key in noise_keys:
            w = noise_widgets.get(key)
            if w is None:
                continue
            try:
                if isinstance(w, QComboBox):
                    out[key] = w.currentText()
                elif isinstance(w, QCheckBox):
                    out[key] = bool(w.isChecked())
                elif isinstance(w, QLineEdit):
                    out[key] = w.text()
                elif hasattr(w, "value"):
                    out[key] = w.value()
            except Exception:
                pass
        return out

    # ── BRUSH tab ─────────────────────────────────────────────────────────
    def _build_brush_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        # Brush shape group
        grp = QGroupBox("Brush Shape")
        gl  = QVBoxLayout(grp)

        self.r_sb   = _make_spinbox(RADIUS_MIN, RADIUS_MAX, RADIUS_DEF, dec=3)
        self.r_sl   = _make_slider(RADIUS_MIN, RADIUS_MAX, RADIUS_DEF)
        self.r_sb.setToolTip("Radius of the paint brush in world units.")
        _link_slider_spinbox(self.r_sl, self.r_sb, RADIUS_MIN, RADIUS_MAX, on_change=self._on_paint_changed)
        _param_row("Radius:", self.r_sl, self.r_sb, gl)

        self.fa_sb  = _make_spinbox(FAL_AMT_MIN, FAL_AMT_MAX, FAL_AMT_DEF, dec=3)
        self.fa_sl  = _make_slider(FAL_AMT_MIN, FAL_AMT_MAX, FAL_AMT_DEF)
        self.fa_sb.setToolTip("Opacity / intensity of the brush stroke (0 = no paint, 1 = full paint).")
        _link_slider_spinbox(self.fa_sl, self.fa_sb, FAL_AMT_MIN, FAL_AMT_MAX, on_change=self._on_paint_changed)
        _param_row("Opacity:", self.fa_sl, self.fa_sb, gl)

        self.fs_sb  = _make_spinbox(FAL_SFT_MIN, FAL_SFT_MAX, FAL_SFT_DEF, dec=3)
        self.fs_sl  = _make_slider(FAL_SFT_MIN, FAL_SFT_MAX, FAL_SFT_DEF)
        self.fs_sb.setToolTip("Softness of the brush falloff. Negative values sharpen the edge; positive values soften it.")
        _link_slider_spinbox(self.fs_sl, self.fs_sb, FAL_SFT_MIN, FAL_SFT_MAX, on_change=self._on_paint_changed)
        _param_row("Falloff Soft:", self.fs_sl, self.fs_sb, gl)

        lay.addWidget(grp)

        # Scatter density group
        grp2 = QGroupBox("Scatter Density")
        gl2  = QVBoxLayout(grp2)

        self.d_sb   = _make_spinbox(DENS_MIN, DENS_MAX, DENS_DEF, dec=3)
        self.d_sb.setMaximum(99999.0)   # slider caps at 100; spinbox is unlimited
        self.d_sl   = _make_slider(DENS_MIN, 100.0, DENS_DEF)
        self.d_sb.setToolTip("Number of scatter points generated per unit area. Higher values produce denser results.")
        _link_slider_spinbox(self.d_sl, self.d_sb, DENS_MIN, 100.0, on_change=self._sync_rt)
        _param_row("Density:", self.d_sl, self.d_sb, gl2)

        self.s_sb   = _make_spinbox(SPC_MIN, SPC_MAX, SPC_DEF, dec=3)
        self.s_sb.setMaximum(99999.0)   # slider caps at 100; spinbox is unlimited
        self.s_sl   = _make_slider(SPC_MIN, 100.0, SPC_DEF)
        self.s_sb.setToolTip("Minimum allowed distance between any two scattered points. Prevents overlap.")
        _link_slider_spinbox(self.s_sl, self.s_sb, SPC_MIN, 100.0, on_change=self._sync_rt)
        _param_row("Min Spacing:", self.s_sl, self.s_sb, gl2)

        self.mdist_sb = _make_spinbox(MDIST_MIN, MDIST_MAX, MDIST_DEF, dec=3)
        self.mdist_sl = _make_slider(MDIST_MIN, MDIST_MAX, MDIST_DEF)
        self.mdist_sb.setToolTip("Minimum distance between scatter points and the surface boundary or obstacle geometry.")
        _link_slider_spinbox(self.mdist_sl, self.mdist_sb, MDIST_MIN, MDIST_MAX, on_change=self._sync_rt)
        _mdist_w = QWidget()
        _mdist_lay = QVBoxLayout(_mdist_w)
        _mdist_lay.setContentsMargins(0, 0, 0, 0)
        _param_row("Min Distance:", self.mdist_sl, self.mdist_sb, _mdist_lay)
        gl2.addWidget(_mdist_w)
        _mdist_w.hide()

        self.relax_sb = _make_int_spinbox(RELAX_MIN, RELAX_MAX, RELAX_DEF)
        self.relax_sb.setToolTip("Number of relaxation iterations applied to even out point distribution. Higher values improve spacing but cost more to compute.")
        self.relax_sl = QSlider(Qt.Horizontal)
        self.relax_sl.setRange(RELAX_MIN, RELAX_MAX)
        self.relax_sl.setValue(RELAX_DEF)
        self.relax_sl.valueChanged.connect(lambda v: (self.relax_sb.blockSignals(True),
                                                       self.relax_sb.setValue(v),
                                                       self.relax_sb.blockSignals(False),
                                                       self._sync_rt()))
        self.relax_sb.valueChanged.connect(lambda v: (self.relax_sl.blockSignals(True),
                                                       self.relax_sl.setValue(v),
                                                       self.relax_sl.blockSignals(False)))
        r_row = QHBoxLayout()
        r_row.setSpacing(6)
        rl = QLabel("Relax Iter:")
        rl.setFixedWidth(90)
        rl.setStyleSheet("color:#bbb;")
        r_row.addWidget(rl)
        r_row.addWidget(self.relax_sl, 1)
        r_row.addWidget(self.relax_sb)
        gl2.addLayout(r_row)

        self.max_pts_sb = _make_int_spinbox(MAX_PTS_MIN, MAX_PTS_MAX, MAX_PTS_DEF, width=88)
        self.max_pts_sb.setToolTip("Hard upper limit on the total number of scatter points. Prevents accidental runaway counts.")
        mp_row = QHBoxLayout()
        mp_row.setSpacing(6)
        ml = QLabel("Emergency Limit:")
        ml.setFixedWidth(90)
        ml.setStyleSheet("color:#bbb;")
        mp_row.addWidget(ml)
        mp_row.addStretch(1)
        mp_row.addWidget(self.max_pts_sb)
        gl2.addLayout(mp_row)

        self.rt_cb = QCheckBox("Real-time update")
        self.rt_cb.setChecked(True)
        gl2.addWidget(self.rt_cb)
        self.rt_cb.hide()

        # Remove Overlapping Points
        self.remove_overlap_cb = QCheckBox("Remove Overlapping Points")
        self.remove_overlap_cb.setToolTip(
            "Post-process pass that removes scatter points whose bounding spheres "
            "intersect. Eliminates geometry collision without changing density settings."
        )
        gl2.addWidget(self.remove_overlap_cb)

        self.overlap_tol_sb = _make_spinbox(OVLP_TOL_MIN, OVLP_TOL_MAX, OVLP_TOL_DEF, dec=2)
        self.overlap_tol_sl = _make_slider(OVLP_TOL_MIN, OVLP_TOL_MAX, OVLP_TOL_DEF)
        self.overlap_tol_sb.setToolTip(
            "Multiplier on each point's bounding radius used when testing for overlaps. "
            "< 1.0 = allow some interpenetration; > 1.0 = add extra clearance."
        )
        _link_slider_spinbox(self.overlap_tol_sl, self.overlap_tol_sb,
                             OVLP_TOL_MIN, OVLP_TOL_MAX, on_change=self._sync_rt)
        self._overlap_tol_row = QWidget()
        _ot_lay = QVBoxLayout(self._overlap_tol_row)
        _ot_lay.setContentsMargins(0, 0, 0, 0)
        _param_row("Overlap Tol.:", self.overlap_tol_sl, self.overlap_tol_sb, _ot_lay)
        gl2.addWidget(self._overlap_tol_row)
        self._overlap_tol_row.setVisible(False)

        def _on_remove_overlap_toggled(checked):
            self._overlap_tol_row.setVisible(checked)
            self._sync_rt()

        self.remove_overlap_cb.toggled.connect(_on_remove_overlap_toggled)

        # Recache Strokes button
        self.recache_btn = QPushButton("Recache Strokes")
        self.recache_btn.setMinimumHeight(30)
        self.recache_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        self.recache_btn.setToolTip("Re-bake all existing brush strokes into the scatter cache. Use this after changing density or spacing on a finished paint.")
        self.recache_btn.clicked.connect(self._on_recache_strokes)
        gl2.addWidget(self.recache_btn)

        lay.addWidget(grp2)
        if self._mode != "scatter":
            grp2.hide()

        # ── Manual Scatter ────────────────────────────────────────────────
        manual_grp = _CollapsibleGroup("Manual Scatter", expanded=True)
        mg = QVBoxLayout(manual_grp.body)
        mg.setContentsMargins(6, 4, 6, 6)
        mg.setSpacing(4)

        manual_ctrl = QHBoxLayout()
        manual_ctrl.setSpacing(6)
        lbl_piece = QLabel("Asset index:")
        lbl_piece.setStyleSheet("color:#bbb;")
        manual_ctrl.addWidget(lbl_piece)
        self._manual_piece_sb = _make_int_spinbox(0, 99, 0)
        self._manual_piece_sb.setFixedWidth(60)
        self._manual_piece_sb.setToolTip("Which asset slot (0 = first asset) to place")
        manual_ctrl.addWidget(self._manual_piece_sb)
        manual_ctrl.addStretch()
        b_place = QPushButton("Place")
        b_place.setFixedWidth(60)
        b_place.setStyleSheet(
            "QPushButton { background:#3a5a3a; color:#cfc; border:1px solid #5a7a5a; border-radius:3px; }"
            "QPushButton:hover { background:#4a6a4a; }"
        )
        b_place.clicked.connect(self._on_place_mode)
        manual_ctrl.addWidget(b_place)
        b_clear_manual = QPushButton("Clear")
        b_clear_manual.setFixedWidth(50)
        b_clear_manual.setStyleSheet(
            "QPushButton { background:#553333; color:#f88; border:1px solid #774444; border-radius:3px; }"
            "QPushButton:hover { background:#664444; }"
        )
        b_clear_manual.clicked.connect(self._on_clear_manual)
        manual_ctrl.addWidget(b_clear_manual)
        mg.addLayout(manual_ctrl)
        lay.addWidget(manual_grp)
        if self._mode != "scatter":
            manual_grp.hide()

        # ── Mask Layers group (scatter mode only) ─────────────────────────────
        mask_grp = QGroupBox("Mask Layers")
        mask_gl = QVBoxLayout(mask_grp)
        mask_gl.setSpacing(4)

        self._mask_layers_container = QWidget()
        self._mask_layers_vlay = QVBoxLayout(self._mask_layers_container)
        self._mask_layers_vlay.setSpacing(2)
        self._mask_layers_vlay.setContentsMargins(0, 0, 0, 0)
        mask_gl.addWidget(self._mask_layers_container)

        self._mask_layer_rows = []
        self._mask_layer_radio_group = QButtonGroup(w)
        self._mask_layer_radio_group.setExclusive(True)
        self._active_mask_layer = "mask"
        self._add_mask_layer_row("mask")

        add_layer_btn = QPushButton("+ Add Layer")
        add_layer_btn.setMinimumHeight(30)
        add_layer_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        add_layer_btn.setToolTip("Add a new named mask attribute layer for selective painting.")
        add_layer_btn.clicked.connect(self._on_add_mask_layer)
        mask_gl.addWidget(add_layer_btn)

        lay.addWidget(mask_grp)
        if self._mode != "scatter":
            mask_grp.hide()

        lay.addStretch()

        # Connect brush tab signals — Radius/Opacity/Falloff Soft use _on_paint_changed
        # so they always push paint_mask parms in ivy mode without the rt_cb gate.
        for w_ in (self.r_sb, self.fa_sb, self.fs_sb):
            w_.valueChanged.connect(self._on_paint_changed)
        for w_ in (self.d_sb, self.s_sb, self.mdist_sb):
            w_.valueChanged.connect(self._sync_rt)
        self.relax_sb.valueChanged.connect(self._sync_rt)
        self.max_pts_sb.valueChanged.connect(self._sync_rt)

        return w

    # ── STAMP tab ─────────────────────────────────────────────────────────
    def _build_stamp_tab(self):
        self._stamp_layers = []

        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # ── Stamp global controls ─────────────────────────────────────────
        stamp_ctrl_grp = QGroupBox("Stamp Settings")
        sc_lay = QVBoxLayout(stamp_ctrl_grp)
        sc_lay.setSpacing(4)
        sc_lay.setContentsMargins(8, 8, 8, 8)

        self.stamp_scale_sb = _make_spinbox(0.01, 20.0, 1.0, dec=3)
        self.stamp_scale_sl = _make_slider(0.01, 20.0, 1.0)
        self.stamp_scale_sb.setToolTip(
            "Scale multiplier applied to instances scattered in stamp-masked areas (@mask > 0). "
            "1.0 = no change; 2.0 = twice the global scale."
        )
        _link_slider_spinbox(self.stamp_scale_sl, self.stamp_scale_sb, 0.01, 20.0,
                             on_change=self._on_stamp_layer_changed)
        _param_row("Scale:", self.stamp_scale_sl, self.stamp_scale_sb, sc_lay)
        self.stamp_scale_sb.valueChanged.connect(self._on_stamp_layer_changed)

        mask_row_w = QWidget()
        mask_row_h = QHBoxLayout(mask_row_w)
        mask_row_h.setContentsMargins(0, 0, 0, 0)
        mask_row_h.setSpacing(6)
        mask_row_h.addWidget(QLabel("Restrict to Mask:"))
        self.stamp_mask_layer_cb = QComboBox()
        self.stamp_mask_layer_cb.addItem("None")
        self.stamp_mask_layer_cb.setToolTip(
            "Restrict stamp scatter to areas painted in the selected mask layer.\n"
            "Set to 'None' to apply stamp over the full surface."
        )
        self.stamp_mask_layer_cb.currentIndexChanged.connect(self._on_stamp_layer_changed)
        mask_row_h.addWidget(self.stamp_mask_layer_cb)
        mask_row_h.addStretch()
        sc_lay.addWidget(mask_row_w)

        outer.addWidget(stamp_ctrl_grp)

        # ── Stamp layers ──────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._stamp_scroll_w = QWidget()
        self._stamp_scroll_lay = QVBoxLayout(self._stamp_scroll_w)
        self._stamp_scroll_lay.setSpacing(6)
        self._stamp_scroll_lay.setContentsMargins(0, 0, 0, 0)
        self._stamp_scroll_lay.addStretch()
        scroll.setWidget(self._stamp_scroll_w)
        outer.addWidget(scroll, 1)

        add_btn = QPushButton("+ Add Layer")
        add_btn.setMinimumHeight(30)
        add_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        add_btn.setToolTip("Add another stamp mask layer that blends on top of the base layer.")
        add_btn.clicked.connect(self._on_stamp_add_layer)
        outer.addWidget(add_btn)

        self._stamp_add_layer_card()
        return w

    def _stamp_add_layer_card(self, data=None):
        is_base = len(self._stamp_layers) == 0
        title = "Layer 1  (Base)" if is_base else f"Layer {len(self._stamp_layers) + 1}"

        card = QGroupBox(title)
        card_lay = QVBoxLayout(card)
        card_lay.setSpacing(4)
        card_lay.setContentsMargins(8, 8, 8, 8)

        # Row 1: enable + path + browse + remove
        r1 = QHBoxLayout()
        enabled_cb = QCheckBox()
        enabled_cb.setChecked(data.get("enabled", True) if data else True)
        enabled_cb.setToolTip("Enable / disable this layer")
        r1.addWidget(enabled_cb)
        path_le = QLineEdit(data.get("path", "") if data else "")
        path_le.setPlaceholderText("Path to grayscale image…")
        path_le.setToolTip("File path to a grayscale image used as a stamp mask (white = full density, black = no scatter).")
        r1.addWidget(path_le, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedHeight(22)
        browse_btn.setToolTip("Browse for a grayscale stamp image file.")
        r1.addWidget(browse_btn)
        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(22, 22)
        remove_btn.setEnabled(not is_base)
        remove_btn.setToolTip("Base layer cannot be removed" if is_base else "Remove this layer")
        r1.addWidget(remove_btn)
        card_lay.addLayout(r1)

        # Row 2: thumbnail + rotation + flip
        r2 = QHBoxLayout()
        preview = _ClickableLabel("No Image")
        preview.setFixedSize(72, 72)
        preview.setAlignment(Qt.AlignCenter)
        preview.setScaledContents(True)
        preview.setStyleSheet("background:#111; border:1px solid #444;")
        preview.setCursor(Qt.PointingHandCursor)
        r2.addWidget(preview)
        ctrl = QVBoxLayout()
        ctrl.setSpacing(2)
        rot_sb = _make_spinbox(0.0, 360.0, data.get("rot", 0.0) if data else 0.0, dec=1)
        rot_sl = _make_slider(0.0, 360.0, data.get("rot", 0.0) if data else 0.0)
        rot_sb.setToolTip("Rotation angle of the stamp image in degrees.")
        _link_slider_spinbox(rot_sl, rot_sb, 0.0, 360.0, on_change=self._on_stamp_layer_changed)
        _param_row("Rotation:", rot_sl, rot_sb, ctrl)
        flip_r = QHBoxLayout()
        fx_cb = QCheckBox("Flip X")
        fy_cb = QCheckBox("Flip Y")
        invert_cb = QCheckBox("Invert")
        fx_cb.setChecked(data.get("fx", False) if data else False)
        fx_cb.setToolTip("Flip the stamp image horizontally.")
        fy_cb.setChecked(data.get("fy", False) if data else False)
        fy_cb.setToolTip("Flip the stamp image vertically.")
        invert_cb.setChecked(data.get("invert", False) if data else False)
        invert_cb.setToolTip("Invert the stamp image so dark areas become dense scatter and light areas become sparse.")
        flip_r.addWidget(fx_cb)
        flip_r.addWidget(fy_cb)
        flip_r.addWidget(invert_cb)
        flip_r.addStretch()
        ctrl.addLayout(flip_r)
        r2.addLayout(ctrl, 1)
        card_lay.addLayout(r2)

        # Row 3: blend mode + amount (hidden for base layer)
        blend_w = QWidget()
        bl = QHBoxLayout(blend_w)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet("color:#bbb;")
        bl.addWidget(mode_lbl)
        mode_cb = QComboBox()
        mode_cb.addItems(STAMP_BLEND_MODES)
        saved_mode = data.get("mode", "multiply") if data else "multiply"
        if saved_mode in STAMP_BLEND_MODE_KEYS:
            mode_cb.setCurrentIndex(STAMP_BLEND_MODE_KEYS.index(saved_mode))
        mode_cb.setToolTip("How this layer's mask is blended with the layer below it (e.g. Multiply darkens, Add brightens).")
        bl.addWidget(mode_cb)
        amt_lbl = QLabel("Amt:")
        amt_lbl.setStyleSheet("color:#bbb;")
        bl.addWidget(amt_lbl)
        amt_sb = _make_spinbox(0.0, 1.0, data.get("amount", 1.0) if data else 1.0, dec=3)
        amt_sl = _make_slider(0.0, 1.0, data.get("amount", 1.0) if data else 1.0)
        amt_sb.setToolTip("Blend strength of this layer (0 = no effect, 1 = full effect).")
        _link_slider_spinbox(amt_sl, amt_sb, 0.0, 1.0, on_change=self._on_stamp_layer_changed)
        bl.addWidget(amt_sl, 1)
        bl.addWidget(amt_sb)
        card_lay.addWidget(blend_w)
        if is_base:
            blend_w.hide()

        # Per-layer mask restriction
        lmask_row = QWidget()
        lmask_h = QHBoxLayout(lmask_row)
        lmask_h.setContentsMargins(0, 0, 0, 0)
        lmask_h.setSpacing(6)
        lmask_lbl = QLabel("Mask:")
        lmask_lbl.setStyleSheet("color:#bbb;")
        lmask_h.addWidget(lmask_lbl)
        layer_mask_cb = QComboBox()
        layer_mask_cb.addItem("None")
        layer_mask_cb.setToolTip("Restrict this layer's contribution to areas painted in the selected mask.")
        if hasattr(self, "_mask_layer_rows"):
            seen = set()
            for le, _, _, _, _ in self._mask_layer_rows:
                n = le.currentText().strip()
                if n and n not in seen:
                    layer_mask_cb.addItem(n)
                    seen.add(n)
        saved_lmask = data.get("layer_mask", "") if data else ""
        idx = layer_mask_cb.findText(saved_lmask if saved_lmask else "None")
        layer_mask_cb.setCurrentIndex(max(0, idx))
        lmask_h.addWidget(layer_mask_cb)
        lmask_h.addStretch()
        card_lay.addWidget(lmask_row)

        layer_dict = {
            "card": card, "enabled_cb": enabled_cb, "path_le": path_le,
            "preview": preview, "rot_sl": rot_sl, "rot_sb": rot_sb,
            "fx_cb": fx_cb, "fy_cb": fy_cb, "invert_cb": invert_cb,
            "mode_cb": mode_cb, "amt_sl": amt_sl, "amt_sb": amt_sb,
            "blend_w": blend_w, "layer_mask_cb": layer_mask_cb, "is_base": is_base,
        }
        self._stamp_layers.append(layer_dict)

        preview.doubleClicked.connect(lambda: self._open_stamp_image_editor(layer_dict))
        preview.setToolTip("Double-click to open Image Editor")
        enabled_cb.stateChanged.connect(lambda _: self._on_stamp_layer_changed())
        path_le.textChanged.connect(lambda pth: self._stamp_path_changed(layer_dict, pth))
        browse_btn.clicked.connect(lambda: self._stamp_browse(layer_dict))
        remove_btn.clicked.connect(lambda: self._on_stamp_remove_layer(layer_dict))
        rot_sb.valueChanged.connect(lambda _: self._on_stamp_layer_changed())
        fx_cb.stateChanged.connect(lambda _: self._on_stamp_layer_changed())
        fy_cb.stateChanged.connect(lambda _: self._on_stamp_layer_changed())
        invert_cb.stateChanged.connect(lambda _: self._on_stamp_layer_changed())
        mode_cb.currentIndexChanged.connect(lambda _: self._on_stamp_layer_changed())
        amt_sb.valueChanged.connect(lambda _: self._on_stamp_layer_changed())
        layer_mask_cb.currentIndexChanged.connect(lambda _: self._on_stamp_layer_changed())

        self._stamp_scroll_lay.insertWidget(self._stamp_scroll_lay.count() - 1, card)
        if data and data.get("path"):
            self._stamp_path_changed(layer_dict, data["path"])

    def _on_stamp_add_layer(self):
        self._stamp_add_layer_card()
        self._on_stamp_layer_changed()

    def _on_stamp_remove_layer(self, layer_dict):
        if layer_dict["is_base"]:
            return
        self._stamp_layers.remove(layer_dict)
        layer_dict["card"].setParent(None)
        layer_dict["card"].deleteLater()
        for i, ld in enumerate(self._stamp_layers):
            ld["card"].setTitle(f"Layer {i + 1}" + ("  (Base)" if i == 0 else ""))
        self._on_stamp_layer_changed()

    def _open_stamp_image_editor(self, layer_dict):
        pth = layer_dict["path_le"].text().strip()
        if not pth:
            # No image yet — open the editor on a blank canvas so the user can
            # paint a new texture and save it to disk with a chosen format.
            self._create_new_stamp_image(layer_dict)
            return
        if not os.path.isfile(pth):
            self._set_status(f"Image not found: {pth}", error=True)
            return

        def _after_save():
            # Houdini caches texture-map data; the file on disk changed but
            # attribfrommap won't see it until its Reload Texture button is
            # pressed. Also flush the global texture cache as a belt-and-suspenders.
            try:
                hou.hscriptCommand("texcache -c")
            except Exception:
                pass
            self._stamp_path_changed(layer_dict, pth)
            if self.geo_node:
                for child in self.geo_node.children():
                    if not (child.name().startswith("stamp_layer_")
                            or child.name() == "stamp_map"):
                        continue
                    # Press whichever "reload" button this attribfrommap exposes
                    for parm_name in ("reload", "reloadtexture", "reloadtex"):
                        p = child.parm(parm_name)
                        if p is not None:
                            try:
                                p.pressButton()
                            except Exception:
                                pass
                            break
                    try:
                        child.cook(force=True)
                    except Exception:
                        pass

        try:
            dlg = ImageEditorDialog(pth, on_save=_after_save, parent=self)
            dlg.exec_()
        except Exception as e:
            hou.ui.displayMessage(
                f"Could not open Image Editor:\n{e}",
                severity=hou.severityType.Error,
            )

    def _create_new_stamp_image(self, layer_dict):
        """Open the editor on a blank canvas; on save, set the layer path to
        the file the user wrote (filename + format chosen inside the dialog)."""
        # Ask for canvas size up front. Square dimensions keep the prompt simple;
        # users can change aspect later via the Tile/Repeat tool.
        size, ok = QInputDialog.getInt(
            self, "New Image", "Canvas size (px, square):",
            value=1024, minValue=16, maxValue=8192, step=64,
        )
        if not ok:
            return
        try:
            dlg = ImageEditorDialog(None, parent=self, new_image_size=(size, size))
            if dlg.exec_() == QDialog.Accepted and dlg._image_path:
                # path_le.textChanged → _stamp_path_changed → preview + sync.
                layer_dict["path_le"].setText(dlg._image_path)
        except Exception as e:
            hou.ui.displayMessage(
                f"Could not open Image Editor:\n{e}",
                severity=hou.severityType.Error,
            )

    def _stamp_browse(self, layer_dict):
        pth, _ = QFileDialog.getOpenFileName(
            self, "Select Stamp Layer Image", "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.exr)"
        )
        if pth:
            layer_dict["path_le"].setText(pth)

    def _stamp_path_changed(self, layer_dict, pth):
        if pth and os.path.isfile(pth):
            pix = QPixmap(pth)
            if not pix.isNull():
                layer_dict["preview"].setPixmap(
                    pix.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self._on_stamp_layer_changed()
                return
        layer_dict["preview"].clear()
        layer_dict["preview"].setText("No Image")
        self._on_stamp_layer_changed()

    def _on_stamp_layer_changed(self):
        self._sync_rt()

    def _get_stamp_layers_state(self):
        result = []
        for ld in self._stamp_layers:
            txt = ld["layer_mask_cb"].currentText()
            entry = {
                "enabled":    ld["enabled_cb"].isChecked(),
                "path":       ld["path_le"].text().strip(),
                "rot":        ld["rot_sb"].value(),
                "fx":         ld["fx_cb"].isChecked(),
                "fy":         ld["fy_cb"].isChecked(),
                "invert":     ld["invert_cb"].isChecked(),
                "layer_mask": "" if txt == "None" else txt,
            }
            if not ld["is_base"]:
                mode_idx = ld["mode_cb"].currentIndex()
                entry["mode"]   = STAMP_BLEND_MODE_KEYS[mode_idx]
                entry["amount"] = ld["amt_sb"].value()
            result.append(entry)
        return result

    def _restore_stamp_layers(self, layers_data):
        for ld in list(self._stamp_layers):
            ld["card"].setParent(None)
            ld["card"].deleteLater()
        self._stamp_layers = []
        for layer_data in layers_data:
            self._stamp_add_layer_card(layer_data)
        if not self._stamp_layers:
            self._stamp_add_layer_card()

    # ── ROTATION tab ──────────────────────────────────────────────────────
    def _build_rotation_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        # Normal Alignment group — scatter mode only
        if self._mode == "scatter":
            align_grp = QGroupBox("Normal Alignment")
            al = QVBoxLayout(align_grp)

            blend_row = QHBoxLayout()
            self.normal_align_cb = QCheckBox("Blend normal with")
            self.normal_align_cb.stateChanged.connect(self._sync_rt)
            blend_row.addWidget(self.normal_align_cb)

            self.blend_axis_cb = QComboBox()
            self.blend_axis_cb.addItems(["X", "Y", "Z"])
            self.blend_axis_cb.setCurrentIndex(1)
            self.blend_axis_cb.currentIndexChanged.connect(self._sync_rt)
            blend_row.addWidget(self.blend_axis_cb)
            blend_row.addStretch()
            al.addLayout(blend_row)

            self.blend_amount_sb = _make_spinbox(0.0, 1.0, 1.0, dec=3)
            self.blend_amount_sl = _make_slider(0.0, 1.0, 1.0)
            _link_slider_spinbox(self.blend_amount_sl, self.blend_amount_sb, 0.0, 1.0, on_change=self._sync_rt)
            _param_row("Amount:", self.blend_amount_sl, self.blend_amount_sb, al)
            self.blend_amount_sb.valueChanged.connect(self._sync_rt)

            self.cone_sb = _make_spinbox(0.0, 180.0, CONE_DEF, dec=1)
            self.cone_sl = _make_slider(0.0, 180.0, CONE_DEF)
            _link_slider_spinbox(self.cone_sl, self.cone_sb, 0.0, 180.0, on_change=self._sync_rt)
            _param_row("Cone Angle:", self.cone_sl, self.cone_sb, al)
            self.cone_sb.valueChanged.connect(self._sync_rt)
            self.cone_sb.valueChanged.connect(self._sync_cone_orient)

            lay.addWidget(align_grp)

        # Rotation range per axis
        rand_grp = QGroupBox("Random Rotation Range")
        rl = QVBoxLayout(rand_grp)

        self.full_rand_cb = QCheckBox("Full Random (0–360° all axes)")
        self.full_rand_cb.stateChanged.connect(self._on_full_rand_toggled)
        # Hidden but kept unchecked - checkbox exists in code but not displayed in UI

        self.rot_min_sb = _make_spinbox(0.0, 1.0, ROT_MIN_DEF, dec=3)
        self.rot_min_sl = _make_slider(0.0, 1.0, ROT_MIN_DEF)
        _link_slider_spinbox(self.rot_min_sl, self.rot_min_sb, 0.0, 1.0, on_change=self._on_rot_changed)
        _param_row("Rot Min (0–1):", self.rot_min_sl, self.rot_min_sb, rl)
        self.rot_min_sb.valueChanged.connect(self._on_rot_changed)

        self.rot_max_sb = _make_spinbox(0.0, 1.0, ROT_MAX_DEF, dec=3)
        self.rot_max_sl = _make_slider(0.0, 1.0, ROT_MAX_DEF)
        _link_slider_spinbox(self.rot_max_sl, self.rot_max_sb, 0.0, 1.0, on_change=self._on_rot_changed)
        _param_row("Rot Max (0–1):", self.rot_max_sl, self.rot_max_sb, rl)
        self.rot_max_sb.valueChanged.connect(self._on_rot_changed)

        self.rot_rand_sb = _make_spinbox(0.0, 1.0, ROT_RAND_DEF, dec=3)
        self.rot_rand_sl = _make_slider(0.0, 1.0, ROT_RAND_DEF)
        _link_slider_spinbox(self.rot_rand_sl, self.rot_rand_sb, 0.0, 1.0, on_change=self._on_rot_changed)
        # Randomize control - only shown in Ivy, hidden in SP Scatter
        if self._mode == "ivy":
            _param_row("Randomize:", self.rot_rand_sl, self.rot_rand_sb, rl)
        self.rot_rand_sb.valueChanged.connect(self._on_rot_changed)

        lay.addWidget(rand_grp)
        lay.addStretch()
        return w

    # ── SCALE tab ─────────────────────────────────────────────────────────
    def _build_scale_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        glob_grp = QGroupBox("Global Scale")
        gg = QVBoxLayout(glob_grp)
        self.gs_sb = _make_spinbox(GS_MIN, IVY_GS_MAX, GS_DEF, dec=3)
        self.gs_sl = _make_slider(GS_MIN, IVY_GS_MAX, GS_DEF)
        _link_slider_spinbox(self.gs_sl, self.gs_sb, GS_MIN, IVY_GS_MAX, on_change=self._sync_rt)
        _param_row("Global:", self.gs_sl, self.gs_sb, gg)
        self.gs_sb.valueChanged.connect(self._sync_rt)
        lay.addWidget(glob_grp)

        axis_grp = QGroupBox("Per-Axis Scale Range")
        ag = QVBoxLayout(axis_grp)

        self.uni_cb = QCheckBox("Uniform XYZ  (links X to Y and Z)")
        self.uni_cb.setChecked(True)
        self.uni_cb.stateChanged.connect(self._on_uniform_toggled)
        # Hidden but kept checked - checkbox exists in code but not displayed in UI

        # ── Uniform sliders (shown when Uniform XYZ is checked) ───────────
        self._uni_slider_widget = QWidget()
        usl = QVBoxLayout(self._uni_slider_widget)
        usl.setContentsMargins(0, 0, 0, 0)
        usl.setSpacing(2)

        self.smn_x = _make_spinbox(0.0, 10.0, SCL_MIN_DEF, dec=3, width=64)
        self.smn_y = _make_spinbox(0.0, 10.0, SCL_MIN_DEF, dec=3, width=64)
        self.smn_z = _make_spinbox(0.0, 10.0, SCL_MIN_DEF, dec=3, width=64)
        self.smx_x = _make_spinbox(0.0, 10.0, SCL_MAX_DEF, dec=3, width=64)
        self.smx_y = _make_spinbox(0.0, 10.0, SCL_MAX_DEF, dec=3, width=64)
        self.smx_z = _make_spinbox(0.0, 10.0, SCL_MAX_DEF, dec=3, width=64)

        self.uni_mn_sl = _make_slider(0.0, 10.0, SCL_MIN_DEF)
        _link_slider_spinbox(self.uni_mn_sl, self.smn_x, 0.0, 10.0, on_change=self._sync_rt)
        _param_row("Scale Min:", self.uni_mn_sl, self.smn_x, usl)

        self.uni_mx_sl = _make_slider(0.0, 10.0, SCL_MAX_DEF)
        _link_slider_spinbox(self.uni_mx_sl, self.smx_x, 0.0, 10.0, on_change=self._sync_rt)
        _param_row("Scale Max:", self.uni_mx_sl, self.smx_x, usl)

        # Randomize control - only shown in SP Scatter, hidden in Ivy Scatter
        self.pscale_rand_sb = _make_spinbox(0.0, 1.0, PSCALE_RAND_DEF, dec=3, width=64)
        self.pscale_rand_sl = _make_slider(0.0, 1.0, PSCALE_RAND_DEF)
        _link_slider_spinbox(self.pscale_rand_sl, self.pscale_rand_sb, 0.0, 1.0, on_change=self._sync_rt)
        if self._mode == "scatter":
            _param_row("Randomize:", self.pscale_rand_sl, self.pscale_rand_sb, usl)

        ag.addWidget(self._uni_slider_widget)

        # ── Per-axis grid (shown when Uniform XYZ is unchecked) ───────────
        self._axis_grid_widget = QWidget()
        gw = QVBoxLayout(self._axis_grid_widget)
        gw.setContentsMargins(0, 0, 0, 0)
        gw.setSpacing(2)

        grid = QGridLayout()
        grid.setSpacing(4)
        for col, txt in enumerate(("", "X", "Y", "Z"), 0):
            lbl = QLabel(txt)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color:#7ab0ff; font-weight:bold;")
            grid.addWidget(lbl, 0, col)
        for row, txt in enumerate(("Min", "Max"), 1):
            lbl = QLabel(txt)
            lbl.setStyleSheet("color:#bbb;")
            grid.addWidget(lbl, row, 0)

        for col, sb in enumerate((self.smn_x, self.smn_y, self.smn_z), 1):
            grid.addWidget(sb, 1, col)
        for col, sb in enumerate((self.smx_x, self.smx_y, self.smx_z), 1):
            grid.addWidget(sb, 2, col)

        gw.addLayout(grid)
        self._axis_grid_widget.setVisible(False)
        ag.addWidget(self._axis_grid_widget)

        lay.addWidget(axis_grp)

        for sb in (self.smn_x, self.smn_y, self.smn_z, self.smx_x, self.smx_y, self.smx_z,
                   self.pscale_rand_sb):
            sb.valueChanged.connect(self._sync_rt)
        self.uni_cb.stateChanged.connect(self._sync_rt)

        # Uniform linking
        self.smn_x.valueChanged.connect(self._propagate_uniform_min)
        self.smx_x.valueChanged.connect(self._propagate_uniform_max)

        lay.addStretch()
        return w

    def _build_transformation_unified_tab(self):
        """Combined Rotation and Scale in one unified Transformation view."""
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        # ── ROTATION SECTION ──────────────────────────────────────────────
        # Normal Alignment group — scatter mode only
        if self._mode == "scatter":
            align_grp = QGroupBox("Normal Alignment")
            al = QVBoxLayout(align_grp)

            blend_row = QHBoxLayout()
            self.normal_align_cb = QCheckBox("Blend normal with")
            self.normal_align_cb.setToolTip("When checked, the instance up-axis is blended toward the chosen world axis, reducing full surface-normal alignment.")
            self.normal_align_cb.stateChanged.connect(self._sync_rt)
            blend_row.addWidget(self.normal_align_cb)

            self.blend_axis_cb = QComboBox()
            self.blend_axis_cb.addItems(["X", "Y", "Z"])
            self.blend_axis_cb.setCurrentIndex(1)
            self.blend_axis_cb.setToolTip("World axis to blend the surface normal toward (typically Y = up).")
            self.blend_axis_cb.currentIndexChanged.connect(self._sync_rt)
            blend_row.addWidget(self.blend_axis_cb)
            blend_row.addStretch()
            al.addLayout(blend_row)

            self.blend_amount_sb = _make_spinbox(0.0, 1.0, 1.0, dec=3)
            self.blend_amount_sl = _make_slider(0.0, 1.0, 1.0)
            self.blend_amount_sb.setToolTip("How much to blend the instance normal toward the chosen world axis (0 = full surface normal, 1 = full world axis).")
            _link_slider_spinbox(self.blend_amount_sl, self.blend_amount_sb, 0.0, 1.0, on_change=self._sync_rt)
            _param_row("Amount:", self.blend_amount_sl, self.blend_amount_sb, al)
            self.blend_amount_sb.valueChanged.connect(self._sync_rt)

            self.cone_sb = _make_spinbox(0.0, 180.0, CONE_DEF, dec=1)
            self.cone_sl = _make_slider(0.0, 180.0, CONE_DEF)
            self.cone_sb.setToolTip("Random angular offset from the surface normal in degrees. 0° = aligned to normal, 180° = fully random hemisphere.")
            _link_slider_spinbox(self.cone_sl, self.cone_sb, 0.0, 180.0, on_change=self._sync_rt)
            _param_row("Cone Angle:", self.cone_sl, self.cone_sb, al)
            self.cone_sb.valueChanged.connect(self._sync_rt)
            self.cone_sb.valueChanged.connect(self._sync_cone_orient)

            lay.addWidget(align_grp)

        # Rotation range per axis
        rand_grp = QGroupBox("Random Rotation Range")
        rl = QVBoxLayout(rand_grp)

        self.full_rand_cb = QCheckBox("Full Random (0–360° all axes)")
        self.full_rand_cb.setToolTip("When checked, instances are rotated randomly on all three axes over the full 0–360° range.")
        self.full_rand_cb.stateChanged.connect(self._on_full_rand_toggled)

        self.rot_min_sb = _make_spinbox(0.0, 1.0, ROT_MIN_DEF, dec=3)
        self.rot_min_sl = _make_slider(0.0, 1.0, ROT_MIN_DEF)
        self.rot_min_sb.setToolTip("Minimum random rotation on the Y axis, expressed as a fraction of 360° (0 = 0°, 1 = 360°).")
        _link_slider_spinbox(self.rot_min_sl, self.rot_min_sb, 0.0, 1.0, on_change=self._on_rot_changed)
        _param_row("Rot Min (0–1):", self.rot_min_sl, self.rot_min_sb, rl)
        self.rot_min_sb.valueChanged.connect(self._on_rot_changed)

        self.rot_max_sb = _make_spinbox(0.0, 1.0, ROT_MAX_DEF, dec=3)
        self.rot_max_sl = _make_slider(0.0, 1.0, ROT_MAX_DEF)
        self.rot_max_sb.setToolTip("Maximum random rotation on the Y axis, expressed as a fraction of 360° (0 = 0°, 1 = 360°).")
        _link_slider_spinbox(self.rot_max_sl, self.rot_max_sb, 0.0, 1.0, on_change=self._on_rot_changed)
        _param_row("Rot Max (0–1):", self.rot_max_sl, self.rot_max_sb, rl)
        self.rot_max_sb.valueChanged.connect(self._on_rot_changed)

        self.rot_rand_sb = _make_spinbox(0.0, 1.0, ROT_RAND_DEF, dec=3)
        self.rot_rand_sl = _make_slider(0.0, 1.0, ROT_RAND_DEF)
        self.rot_rand_sb.setToolTip("Amount of rotation randomization applied per instance (0 = no randomization, 1 = full range).")
        _link_slider_spinbox(self.rot_rand_sl, self.rot_rand_sb, 0.0, 1.0, on_change=self._on_rot_changed)
        if self._mode == "ivy":
            _param_row("Randomize:", self.rot_rand_sl, self.rot_rand_sb, rl)
        self.rot_rand_sb.valueChanged.connect(self._on_rot_changed)

        lay.addWidget(rand_grp)

        # ── SCALE SECTION ─────────────────────────────────────────────────
        glob_grp = QGroupBox("Global Scale")
        gg = QVBoxLayout(glob_grp)
        self.gs_sb = _make_spinbox(GS_MIN, IVY_GS_MAX, GS_DEF, dec=3)
        self.gs_sl = _make_slider(GS_MIN, IVY_GS_MAX, GS_DEF, expo_mid=1.0)
        self.gs_sb.setToolTip("Uniform scale multiplier applied to all instances. Scales all axes equally.")
        _link_slider_spinbox(self.gs_sl, self.gs_sb, GS_MIN, IVY_GS_MAX, expo_mid=1.0, on_change=self._sync_rt)
        _param_row("Global:", self.gs_sl, self.gs_sb, gg)
        self.gs_sb.valueChanged.connect(self._sync_rt)
        lay.addWidget(glob_grp)

        axis_grp = QGroupBox("Per-Axis Scale Range")
        ag = QVBoxLayout(axis_grp)

        self.uni_cb = QCheckBox("Uniform XYZ  (links X to Y and Z)")
        self.uni_cb.setToolTip("When checked, Scale Min/Max apply to all three axes uniformly. Uncheck to set each axis independently.")
        self.uni_cb.setChecked(True)
        self.uni_cb.stateChanged.connect(self._on_uniform_toggled)

        self._uni_slider_widget = QWidget()
        usl = QVBoxLayout(self._uni_slider_widget)
        usl.setContentsMargins(0, 0, 0, 0)
        usl.setSpacing(2)

        self.smn_x = _make_spinbox(0.0, 10.0, SCL_MIN_DEF, dec=3, width=64)
        self.smn_y = _make_spinbox(0.0, 10.0, SCL_MIN_DEF, dec=3, width=64)
        self.smn_z = _make_spinbox(0.0, 10.0, SCL_MIN_DEF, dec=3, width=64)
        self.smx_x = _make_spinbox(0.0, 10.0, SCL_MAX_DEF, dec=3, width=64)
        self.smx_y = _make_spinbox(0.0, 10.0, SCL_MAX_DEF, dec=3, width=64)
        self.smx_z = _make_spinbox(0.0, 10.0, SCL_MAX_DEF, dec=3, width=64)
        self.smn_x.setToolTip("Minimum scale multiplier for scattered instances (lower bound of random scale range).")
        self.smx_x.setToolTip("Maximum scale multiplier for scattered instances (upper bound of random scale range).")

        self.uni_mn_sl = _make_slider(0.0, 10.0, SCL_MIN_DEF)
        _link_slider_spinbox(self.uni_mn_sl, self.smn_x, 0.0, 10.0, on_change=self._sync_rt)
        _param_row("Scale Min:", self.uni_mn_sl, self.smn_x, usl)

        self.uni_mx_sl = _make_slider(0.0, 10.0, SCL_MAX_DEF)
        _link_slider_spinbox(self.uni_mx_sl, self.smx_x, 0.0, 10.0, on_change=self._sync_rt)
        _param_row("Scale Max:", self.uni_mx_sl, self.smx_x, usl)

        self.pscale_rand_sb = _make_spinbox(0.0, 1.0, PSCALE_RAND_DEF, dec=3, width=64)
        self.pscale_rand_sl = _make_slider(0.0, 1.0, PSCALE_RAND_DEF)
        self.pscale_rand_sb.setToolTip("How much random variation to apply to the pscale attribute per instance (0 = uniform scale, 1 = full random range).")
        _link_slider_spinbox(self.pscale_rand_sl, self.pscale_rand_sb, 0.0, 1.0, on_change=self._sync_rt)
        if self._mode == "scatter":
            _param_row("Randomize:", self.pscale_rand_sl, self.pscale_rand_sb, usl)

        ag.addWidget(self._uni_slider_widget)

        self._axis_grid_widget = QWidget()
        gw = QVBoxLayout(self._axis_grid_widget)
        gw.setContentsMargins(0, 0, 0, 0)
        gw.setSpacing(2)

        grid = QGridLayout()
        grid.setSpacing(4)
        for col, txt in enumerate(("", "X", "Y", "Z"), 0):
            lbl = QLabel(txt)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color:#7ab0ff; font-weight:bold;")
            grid.addWidget(lbl, 0, col)
        for row, txt in enumerate(("Min", "Max"), 1):
            lbl = QLabel(txt)
            lbl.setStyleSheet("color:#bbb;")
            grid.addWidget(lbl, row, 0)

        for col, sb in enumerate((self.smn_x, self.smn_y, self.smn_z), 1):
            grid.addWidget(sb, 1, col)
        for col, sb in enumerate((self.smx_x, self.smx_y, self.smx_z), 1):
            grid.addWidget(sb, 2, col)

        gw.addLayout(grid)
        self._axis_grid_widget.setVisible(False)
        ag.addWidget(self._axis_grid_widget)

        lay.addWidget(axis_grp)

        for sb in (self.smn_x, self.smn_y, self.smn_z, self.smx_x, self.smx_y, self.smx_z,
                   self.pscale_rand_sb):
            sb.valueChanged.connect(self._sync_rt)
        self.uni_cb.stateChanged.connect(self._sync_rt)

        self.smn_x.valueChanged.connect(self._propagate_uniform_min)
        self.smx_x.valueChanged.connect(self._propagate_uniform_max)

        # ── OFFSET SECTION ────────────────────────────────────────────────
        if self._mode == "scatter":
            offset_grp = QGroupBox("Offset Geometry")
            og = QVBoxLayout(offset_grp)
            self.geo_offset_sb = _make_spinbox(-5.0, 5.0, 0.0, dec=3)
            self.geo_offset_sl = _make_slider(-5.0, 5.0, 0.0)
            self.geo_offset_sb.setToolTip("Offset each instance along its local up axis. Useful to lift or sink geometry relative to the surface.")
            _link_slider_spinbox(self.geo_offset_sl, self.geo_offset_sb, -5.0, 5.0, on_change=self._sync_rt)
            _param_row("Offset:", self.geo_offset_sl, self.geo_offset_sb, og)
            self.geo_offset_sb.valueChanged.connect(self._sync_rt)
            lay.addWidget(offset_grp)
        elif self._mode == "ivy":
            offset_grp = QGroupBox("Offset Geometry")
            og = QVBoxLayout(offset_grp)
            self.ivy_geo_offset_sb = _make_spinbox(-5.0, 5.0, 0.0, dec=3)
            self.ivy_geo_offset_sl = _make_slider(-5.0, 5.0, 0.0)
            self.ivy_geo_offset_sb.setToolTip("Offset ivy leaf instances along their local up axis. Use to push leaves off the wire surface.")
            _link_slider_spinbox(self.ivy_geo_offset_sl, self.ivy_geo_offset_sb, -5.0, 5.0,
                                 on_change=self._on_ivy_geo_offset_changed)
            _param_row("Offset:", self.ivy_geo_offset_sl, self.ivy_geo_offset_sb, og)
            self.ivy_geo_offset_sb.valueChanged.connect(self._on_ivy_geo_offset_changed)
            lay.addWidget(offset_grp)

        lay.addStretch()
        scroll.setWidget(w)
        outer_lay.addWidget(scroll, 1)
        return outer

    # ── APPEARANCE tab (scatter mode) ─────────────────────────────────────
    def _build_scatter_appearance_tab(self):
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # ── CLUMPING ──────────────────────────────────────────────────────
        clump_grp = _CollapsibleGroup("Clumping", expanded=True)
        clump_gl  = QVBoxLayout(clump_grp.body)
        clump_gl.setContentsMargins(6, 4, 6, 6)
        clump_gl.setSpacing(4)

        self.clump_enabled_cb = QCheckBox("Enable Clumping")
        self.clump_enabled_cb.setToolTip(
            "Pull scatter points toward their neighbours, creating natural species clusters.\n"
            "Points with too few neighbours within the radius are removed."
        )
        self.clump_enabled_cb.stateChanged.connect(self._sync_rt)
        clump_gl.addWidget(self.clump_enabled_cb)

        self.clump_radius_sb = _make_spinbox(0.1, 9999.0, 2.0, dec=2)
        self.clump_radius_sl = _make_slider(0.1, 20.0, 2.0)
        self.clump_radius_sb.setToolTip("Search radius in world units. Points within this distance form a cluster.")
        _link_slider_spinbox(self.clump_radius_sl, self.clump_radius_sb, 0.1, 20.0, on_change=self._sync_rt)
        _param_row("Radius:", self.clump_radius_sl, self.clump_radius_sb, clump_gl)

        self.clump_strength_sb = _make_spinbox(0.0, 1.0, 0.7, dec=3)
        self.clump_strength_sl = _make_slider(0.0, 1.0, 0.7)
        self.clump_strength_sb.setToolTip("How strongly points are pulled toward the cluster centroid (0 = no pull, 1 = full snap).")
        _link_slider_spinbox(self.clump_strength_sl, self.clump_strength_sb, 0.0, 1.0, on_change=self._sync_rt)
        _param_row("Strength:", self.clump_strength_sl, self.clump_strength_sb, clump_gl)

        mn_row = QHBoxLayout()
        mn_row.setSpacing(6)
        mn_lbl = QLabel("Min Neighbors:")
        mn_lbl.setFixedWidth(90)
        mn_lbl.setStyleSheet("color:#bbb;")
        mn_row.addWidget(mn_lbl)
        mn_row.addStretch(1)
        self.clump_min_count_sb = _make_int_spinbox(0, 100, 2)
        self.clump_min_count_sb.setToolTip("Minimum number of neighbours a point must have to survive. Isolated points are removed.")
        self.clump_min_count_sb.valueChanged.connect(self._sync_rt)
        mn_row.addWidget(self.clump_min_count_sb)
        clump_gl.addLayout(mn_row)

        seed_row = QHBoxLayout()
        seed_row.setSpacing(6)
        seed_lbl = QLabel("Seed:")
        seed_lbl.setFixedWidth(90)
        seed_lbl.setStyleSheet("color:#bbb;")
        seed_row.addWidget(seed_lbl)
        seed_row.addStretch(1)
        self.clump_seed_sb = _make_int_spinbox(0, 999999, 42)
        self.clump_seed_sb.setToolTip("Random seed for per-point pull variation.")
        self.clump_seed_sb.valueChanged.connect(self._sync_rt)
        seed_row.addWidget(self.clump_seed_sb)
        clump_gl.addLayout(seed_row)

        lay.addWidget(clump_grp)

        # ── CAMERA FRUSTUM CULLING ────────────────────────────────────────
        cam_grp = _CollapsibleGroup("Camera Frustum Culling", expanded=True)
        cam_gl = QVBoxLayout(cam_grp.body)
        cam_gl.setContentsMargins(6, 4, 6, 6)
        cam_gl.setSpacing(4)

        self._cam_frustum_cb = QCheckBox("Enable")
        self._cam_frustum_cb.setToolTip("When checked, scatter points outside the camera frustum are culled from the instancer.")
        cam_gl.addWidget(self._cam_frustum_cb)

        cam_row = QHBoxLayout()
        cam_lbl = QLabel("Camera:")
        cam_lbl.setFixedWidth(90)
        cam_lbl.setStyleSheet("color:#bbb;")
        cam_row.addWidget(cam_lbl)
        self._cam_combo = QComboBox()
        self._cam_combo.setToolTip("Choose the Houdini camera used for frustum culling.")
        self._cam_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        cam_row.addWidget(self._cam_combo, 1)
        self._cam_refresh_btn = QPushButton("↺")
        self._cam_refresh_btn.setFixedWidth(28)
        self._cam_refresh_btn.setToolTip("Refresh camera list")
        self._cam_refresh_btn.clicked.connect(self._populate_camera_combo)
        cam_row.addWidget(self._cam_refresh_btn)
        cam_gl.addLayout(cam_row)

        self._cam_fov_pad_sb = _make_spinbox(0.0, 2.0, 0.0, dec=3)
        self._cam_fov_pad_sl = _make_slider(0.0, 2.0, 0.0)
        self._cam_fov_pad_sb.setToolTip("Extra padding added around the frustum edges before culling. Useful to keep nearby off-screen objects ready.")
        _link_slider_spinbox(self._cam_fov_pad_sl, self._cam_fov_pad_sb, 0.0, 2.0,
                             on_change=self._on_camera_frustum_changed)
        _param_row("FOV Padding:", self._cam_fov_pad_sl, self._cam_fov_pad_sb, cam_gl)

        self._cam_frustum_cb.toggled.connect(self._on_camera_frustum_changed)
        self._cam_combo.currentIndexChanged.connect(self._on_camera_frustum_changed)

        lay.addWidget(cam_grp)
        self._populate_camera_combo()

        # ── COLOR VARIATION ───────────────────────────────────────────────
        color_grp = _CollapsibleGroup("Color Variation", expanded=True)
        cg = QVBoxLayout(color_grp.body)
        cg.setContentsMargins(6, 4, 6, 6)
        cg.setSpacing(4)

        self.color_var_enabled_cb = QCheckBox("Enable Color Variation")
        self.color_var_enabled_cb.setChecked(True)
        self.color_var_enabled_cb.setToolTip(
            "Assign a random v@Cd color to each instance by lerping between\n"
            "Color A and Color B.  Renderers that read Cd (e.g. Redshift, Arnold)\n"
            "will tint instances individually, breaking up visual repetition."
        )
        self.color_var_enabled_cb.stateChanged.connect(self._sync_rt)
        cg.addWidget(self.color_var_enabled_cb)

        def _make_color_btn(default_rgb, tip):
            btn = QPushButton()
            btn.setFixedSize(60, 22)
            btn.setToolTip(tip)
            r, g, b = [int(v * 255) for v in default_rgb]
            btn.setStyleSheet(
                f"background:rgb({r},{g},{b}); border:1px solid #555;")
            btn._color = QColor(r, g, b)
            return btn

        def _on_color_btn_clicked(btn):
            picked = QColorDialog.getColor(btn._color, self, "Pick Color")
            if picked.isValid():
                btn._color = picked
                btn.setStyleSheet(
                    f"background:rgb({picked.red()},{picked.green()},{picked.blue()});"
                    " border:1px solid #555;")
                self._sync_rt()

        ca_row = QHBoxLayout()
        ca_row.setSpacing(6)
        ca_lbl = QLabel("Color A:")
        ca_lbl.setFixedWidth(90)
        ca_lbl.setStyleSheet("color:#bbb;")
        ca_row.addWidget(ca_lbl)
        self.color_var_a_btn = _make_color_btn(
            logic.COLOR_VARIATION_DEFAULTS["color_variation_a"],
            "Darker/cooler colour — instances lerp from here to Color B.")
        self.color_var_a_btn.clicked.connect(
            lambda: _on_color_btn_clicked(self.color_var_a_btn))
        ca_row.addWidget(self.color_var_a_btn)
        ca_row.addStretch()
        cg.addLayout(ca_row)

        cb_row = QHBoxLayout()
        cb_row.setSpacing(6)
        cb_lbl = QLabel("Color B:")
        cb_lbl.setFixedWidth(90)
        cb_lbl.setStyleSheet("color:#bbb;")
        cb_row.addWidget(cb_lbl)
        self.color_var_b_btn = _make_color_btn(
            logic.COLOR_VARIATION_DEFAULTS["color_variation_b"],
            "Lighter/warmer colour — instances lerp up to here from Color A.")
        self.color_var_b_btn.clicked.connect(
            lambda: _on_color_btn_clicked(self.color_var_b_btn))
        cb_row.addWidget(self.color_var_b_btn)
        cb_row.addStretch()
        cg.addLayout(cb_row)

        cv_seed_row = QHBoxLayout()
        cv_seed_row.setSpacing(6)
        cv_seed_lbl = QLabel("Seed:")
        cv_seed_lbl.setFixedWidth(90)
        cv_seed_lbl.setStyleSheet("color:#bbb;")
        cv_seed_row.addWidget(cv_seed_lbl)
        cv_seed_row.addStretch(1)
        self.color_var_seed_sb = _make_int_spinbox(0, 999999, 0)
        self.color_var_seed_sb.setToolTip("Random seed for per-instance colour assignment.")
        self.color_var_seed_sb.valueChanged.connect(self._sync_rt)
        cv_seed_row.addWidget(self.color_var_seed_sb)
        cg.addLayout(cv_seed_row)

        lay.addWidget(color_grp)

        # ── PROXIMITY EXCLUSION ───────────────────────────────────────────
        prox_grp = _CollapsibleGroup("Proximity Exclusion", expanded=True)
        pg = QVBoxLayout(prox_grp.body)
        pg.setContentsMargins(6, 4, 6, 6)
        pg.setSpacing(4)

        self._prox_enabled_cb = QCheckBox("Enable Proximity Exclusion")
        self._prox_enabled_cb.setToolTip(
            "Delete scatter points that fall within Radius of any point\n"
            "in the specified SOP node. Useful for keeping clear zones\n"
            "around hero props, doors, paths, etc.")
        self._prox_enabled_cb.stateChanged.connect(self._sync_rt)
        pg.addWidget(self._prox_enabled_cb)

        self._prox_radius_sb = _make_spinbox(0.01, 500.0, 2.0, dec=2)
        self._prox_radius_sl = _make_slider(0.01, 50.0, 2.0)
        self._prox_radius_sb.setToolTip("Points within this world-space radius of any exclusion point are removed.")
        _link_slider_spinbox(self._prox_radius_sl, self._prox_radius_sb, 0.01, 50.0, on_change=self._sync_rt)
        _param_row("Radius:", self._prox_radius_sl, self._prox_radius_sb, pg)

        prox_path_row = QHBoxLayout()
        prox_path_lbl = QLabel("Exclusion SOP:")
        prox_path_lbl.setFixedWidth(90)
        prox_path_lbl.setStyleSheet("color:#bbb;")
        self._prox_sop_le = QLineEdit()
        self._prox_sop_le.setPlaceholderText("/obj/geo1/null1")
        self._prox_sop_le.setToolTip(
            "Path to a SOP node whose points act as exclusion centres.\n"
            "Can be any SOP — null, scatter, packed geometry, etc.")
        self._prox_sop_le.textChanged.connect(self._sync_rt)
        prox_pick_btn = QPushButton("…")
        prox_pick_btn.setFixedWidth(26)
        prox_pick_btn.setToolTip("Pick a SOP node from the scene.")
        prox_pick_btn.clicked.connect(self._pick_prox_sop)
        prox_path_row.addWidget(prox_path_lbl)
        prox_path_row.addWidget(self._prox_sop_le, 1)
        prox_path_row.addWidget(prox_pick_btn)
        pg.addLayout(prox_path_row)

        lay.addWidget(prox_grp)

        # ── PLACEMENT RULES ───────────────────────────────────────────────
        rules_grp = _CollapsibleGroup("Placement Rules", expanded=True)
        rg = QVBoxLayout(rules_grp.body)
        rg.setContentsMargins(6, 4, 6, 6)
        rg.setSpacing(4)

        rules_hdr = QHBoxLayout()
        rules_hdr.addStretch()
        _rule_type_cb = QComboBox()
        for key, label in logic.RULE_TYPES.items():
            _rule_type_cb.addItem(label, key)
        rules_hdr.addWidget(_rule_type_cb)
        b_add_rule = QPushButton("Add Rule")
        b_add_rule.setFixedWidth(70)
        b_add_rule.clicked.connect(lambda: self._add_placement_rule(_rule_type_cb.currentData()))
        rules_hdr.addWidget(b_add_rule)
        rg.addLayout(rules_hdr)

        # Resizable rules area: outer_wrap holds _rules_container + drag handle.
        # The user drags the handle bar to set the visible height; the outer
        # Appearance tab scroll handles page-level navigation.
        outer_wrap = QWidget()
        outer_wrap.setMinimumHeight(60)
        outer_wrap_lay = QVBoxLayout(outer_wrap)
        outer_wrap_lay.setContentsMargins(0, 0, 0, 0)
        outer_wrap_lay.setSpacing(0)

        self._rules_container = QWidget()
        self._rules_layout    = QVBoxLayout(self._rules_container)
        self._rules_layout.setContentsMargins(0, 0, 0, 0)
        self._rules_layout.setSpacing(3)
        self._rules_layout.addStretch()
        outer_wrap_lay.addWidget(self._rules_container, 1)

        # Drag handle — user grabs it to resize the rules area
        _drag_handle = QFrame()
        _drag_handle.setFixedHeight(6)
        _drag_handle.setStyleSheet(
            "QFrame { background: #333; border-top: 1px solid #555; }"
            "QFrame:hover { background: #4a6a4a; border-top: 1px solid #5a8a5a; }"
        )
        _drag_handle.setCursor(Qt.SizeVerCursor)
        outer_wrap_lay.addWidget(_drag_handle)

        _drag_state = {"y": None, "h": None}

        def _handle_press(ev, s=_drag_state, w=outer_wrap):
            if ev.button() == Qt.LeftButton:
                s["y"] = ev.globalY()
                s["h"] = w.height()
        def _handle_move(ev, s=_drag_state, w=outer_wrap):
            if s["y"] is not None:
                delta = ev.globalY() - s["y"]
                new_h = max(60, s["h"] + delta)
                w.setFixedHeight(new_h)
        def _handle_release(ev, s=_drag_state):
            s["y"] = None

        _drag_handle.mousePressEvent   = _handle_press
        _drag_handle.mouseMoveEvent    = _handle_move
        _drag_handle.mouseReleaseEvent = _handle_release

        rg.addWidget(outer_wrap)
        lay.addWidget(rules_grp)

        lay.addStretch()
        scroll.setWidget(w)
        outer_lay.addWidget(scroll, 1)
        self._populate_lod_cam_combo()
        return outer

    # ── NOISES tab ────────────────────────────────────────────────────────
    def _build_noises_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self._scatter_noise_widgets = {}

        def add_combo(layout, key, label, items, default=0):
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(label + ":")
            lbl.setFixedWidth(110)
            lbl.setStyleSheet("color:#bbb;")
            cb = QComboBox()
            cb.addItems(items)
            cb.setCurrentIndex(int(default))
            cb.currentIndexChanged.connect(self._on_scatter_noise_changed)
            row.addWidget(lbl)
            row.addWidget(cb, 1)
            layout.addLayout(row)
            self._scatter_noise_widgets[key] = cb
            return cb

        def add_line(layout, key, label, default=""):
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(label + ":")
            lbl.setFixedWidth(110)
            lbl.setStyleSheet("color:#bbb;")
            le = QLineEdit(default)
            le.editingFinished.connect(self._on_scatter_noise_changed)
            row.addWidget(lbl)
            row.addWidget(le, 1)
            layout.addLayout(row)
            self._scatter_noise_widgets[key] = le
            return le

        def add_check(layout, key, label, default=False):
            cb = QCheckBox(label)
            cb.setChecked(bool(default))
            cb.toggled.connect(self._on_scatter_noise_changed)
            layout.addWidget(cb)
            self._scatter_noise_widgets[key] = cb
            return cb

        def add_float(layout, key, label, mn, mx, default, step=0.01, dec=3):
            sb = _make_spinbox(mn, mx, default, dec=dec, step=step)
            sl = _make_slider(mn, mx, default)
            _link_slider_spinbox(sl, sb, mn, mx, on_change=self._on_scatter_noise_changed)
            sb.valueChanged.connect(self._on_scatter_noise_changed)
            _param_row(label + ":", sl, sb, layout, label_width=110)
            self._scatter_noise_widgets[key] = sb
            return sb

        def add_int(layout, key, label, mn, mx, default):
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(label + ":")
            lbl.setFixedWidth(110)
            lbl.setStyleSheet("color:#bbb;")
            sb = _make_int_spinbox(mn, mx, default)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(mn, mx)
            sl.setValue(default)
            sl.valueChanged.connect(
                lambda v, _sb=sb: (
                    _sb.blockSignals(True),
                    _sb.setValue(v),
                    _sb.blockSignals(False),
                    self._on_scatter_noise_changed(),
                )
            )
            sb.valueChanged.connect(
                lambda v, _sl=sl: (
                    _sl.blockSignals(True),
                    _sl.setValue(int(v)),
                    _sl.blockSignals(False),
                    self._on_scatter_noise_changed(),
                )
            )
            row.addWidget(lbl)
            row.addWidget(sl, 1)
            row.addWidget(sb)
            layout.addLayout(row)
            self._scatter_noise_widgets[key] = sb
            return sb

        defaults = logic.SCATTER_NOISE_DEFAULTS

        general_grp = _CollapsibleGroup("General")
        general_lay = QVBoxLayout(general_grp.body)
        add_check(general_lay, "scatter_noise_enabled", "Enable Noise",
                  defaults["scatter_noise_enabled"])
        add_check(general_lay, "scatter_noise_enable_blend", "Enable Blend",
                  defaults["scatter_noise_enable_blend"])
        add_float(general_lay, "scatter_noise_blend", "Blend",
                  0.0, 1.0, defaults["scatter_noise_blend"], step=0.01)
        add_combo(general_lay, "scatter_noise_attrib_type", "Attribute Type",
                  ["Float", "Vector"],
                  defaults["scatter_noise_attrib_type"])
        add_line(general_lay, "scatter_noise_attrib", "Attribute Names", defaults["scatter_noise_attrib"])

        # Mask Gating — dynamic list of (mask layer, blending op) entries.
        # Each entry applies sequentially: gating[i+1] sees the result of gating[i].
        general_lay.addWidget(QLabel("Mask Gating:"))
        self._mask_gating_entries = []  # list of (layer_cb, op_cb, blend_sb, rem_btn, row_w)
        self._mask_gating_container = QWidget()
        self._mask_gating_vlay = QVBoxLayout(self._mask_gating_container)
        self._mask_gating_vlay.setSpacing(2)
        self._mask_gating_vlay.setContentsMargins(0, 0, 0, 0)
        general_lay.addWidget(self._mask_gating_container)

        self._add_mask_gating_btn = QPushButton("+ Add Mask Layer")
        self._add_mask_gating_btn.setMinimumHeight(30)
        self._add_mask_gating_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        self._add_mask_gating_btn.setToolTip("Add another mask layer entry to the noise gating chain.")
        self._add_mask_gating_btn.clicked.connect(self._on_add_mask_gating)
        general_lay.addWidget(self._add_mask_gating_btn)

        # Seed with one default entry (layer = "None", op = Subtract)
        self._add_mask_gating_row("", 0)
        self._refresh_mask_layer_combo()

        lay.addWidget(general_grp)

        value_grp = _CollapsibleGroup("Noise Value")
        value_lay = QVBoxLayout(value_grp.body)
        add_combo(value_lay, "scatter_noise_operation", "Operation",
                  ["Set", "Add", "Subtract", "Multiply", "Minimum", "Maximum"], defaults["scatter_noise_operation"])
        add_combo(value_lay, "scatter_noise_range", "Range Values",
                  ["Positive", "Zero Centered", "Min/Max", "Negative",
                   "Min + Range Length", "Middle ± Range Length"],
                  defaults["scatter_noise_range"])
        add_float(value_lay, "scatter_noise_amplitude", "Amplitude",
                  0.0, 10.0, defaults["scatter_noise_amplitude"], step=0.01)
        lay.addWidget(value_grp)

        pattern_grp = _CollapsibleGroup("Noise Pattern", expanded=False)
        pattern_lay = QVBoxLayout(pattern_grp.body)
        add_combo(pattern_lay, "scatter_noise_type", "Noise Type",
                  ["Fast", "Sparse Convolution", "Alligator", "Perlin", "Perlin Flow",
                   "Simplex", "Worley Cellular F1", "Worley Cellular F2-F1",
                   "Manhattan Cellular F1", "Manhattan Cellular F2-F1",
                   "Chebyshev Cellular F1", "Chebyshev Cellular F2-F1"],
                  defaults["scatter_noise_type"])
        add_line(pattern_lay, "scatter_noise_location_attr", "Location Attribute",
                 defaults["scatter_noise_location_attr"])
        add_float(pattern_lay, "scatter_noise_element_size", "Element Size",
                  0.001, 50.0, defaults["scatter_noise_element_size"], step=0.01)
        add_float(pattern_lay, "scatter_noise_offset", "Offset",
                  -100.0, 100.0, defaults["scatter_noise_offset"], step=0.01)
        lay.addWidget(pattern_grp)

        animation_grp = _CollapsibleGroup("Animation", expanded=False)
        animation_lay = QVBoxLayout(animation_grp.body)
        add_check(animation_lay, "scatter_noise_animate", "Animate Noise",
                  defaults["scatter_noise_animate"])
        add_float(animation_lay, "scatter_noise_pulse_duration", "Pulse Duration",
                  0.0, 100.0, defaults["scatter_noise_pulse_duration"], step=0.01)
        lay.addWidget(animation_grp)

        fractal_grp = _CollapsibleGroup("Fractal", expanded=False)
        fractal_lay = QVBoxLayout(fractal_grp.body)
        add_combo(fractal_lay, "scatter_noise_fractal_type", "Fractal Type",
                  ["None", "Standard (fBm)", "Terrain", "Hybrid Terrain"],
                  defaults["scatter_noise_fractal_type"])
        add_int(fractal_lay, "scatter_noise_max_octaves", "Max Octaves",
                1, 16, defaults["scatter_noise_max_octaves"])
        add_float(fractal_lay, "scatter_noise_lacunarity", "Lacunarity",
                  0.0, 10.0, defaults["scatter_noise_lacunarity"], step=0.01)
        add_float(fractal_lay, "scatter_noise_roughness", "Roughness",
                  0.0, 1.0, defaults["scatter_noise_roughness"], step=0.01)
        lay.addWidget(fractal_grp)

        post_grp = _CollapsibleGroup("Post-Process", expanded=False)
        post_lay = QVBoxLayout(post_grp.body)
        add_check(post_lay, "scatter_noise_enable_min", "Minimum",
                  defaults["scatter_noise_enable_min"])
        add_float(post_lay, "scatter_noise_min", "Minimum",
                  0.0, 10.0, defaults["scatter_noise_min"], step=0.01)
        add_check(post_lay, "scatter_noise_enable_max", "Maximum",
                  defaults["scatter_noise_enable_max"])
        add_float(post_lay, "scatter_noise_max", "Maximum",
                  0.0, 10.0, defaults["scatter_noise_max"], step=0.01)
        lay.addWidget(post_grp)

        lay.addStretch()
        return w

    # ── LOD tab ───────────────────────────────────────────────────────────
    def _build_lod_tab(self):
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lod_grp = _CollapsibleGroup("LOD / Distance Culling", expanded=True)
        lg = QVBoxLayout(lod_grp.body)
        lg.setContentsMargins(6, 4, 6, 6)
        lg.setSpacing(4)

        self._lod_enabled_cb = QCheckBox("Enable LOD")
        self._lod_enabled_cb.setToolTip(
            "Beyond set distances, swap instances to lighter LOD variants\n"
            "or remove them entirely.  LOD paths are set per-asset below.")
        self._lod_enabled_cb.stateChanged.connect(self._on_lod_toggled)
        lg.addWidget(self._lod_enabled_cb)

        lod_cam_row = QHBoxLayout()
        lod_cam_lbl = QLabel("Camera:")
        lod_cam_lbl.setFixedWidth(90)
        lod_cam_lbl.setStyleSheet("color:#bbb;")
        lod_cam_row.addWidget(lod_cam_lbl)
        self._lod_cam_combo = QComboBox()
        self._lod_cam_combo.setToolTip("Camera used to measure distance from each scatter point.")
        self._lod_cam_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lod_cam_row.addWidget(self._lod_cam_combo, 1)
        lod_cam_refresh = QPushButton("↺")
        lod_cam_refresh.setFixedWidth(28)
        lod_cam_refresh.setToolTip("Refresh camera list")
        lod_cam_refresh.clicked.connect(self._populate_lod_cam_combo)
        lod_cam_row.addWidget(lod_cam_refresh)
        lg.addLayout(lod_cam_row)

        self._lod1_dist_sb = _make_spinbox(0.0, 9999.0, 20.0, dec=1)
        self._lod1_dist_sl = _make_slider(0.0, 500.0, 20.0)
        self._lod1_dist_sb.setToolTip("Distance at which LOD 1 (medium) variants start.")
        _link_slider_spinbox(self._lod1_dist_sl, self._lod1_dist_sb, 0.0, 500.0, on_change=self._sync_rt)
        _param_row("LOD 1 Dist:", self._lod1_dist_sl, self._lod1_dist_sb, lg)

        self._lod2_dist_sb = _make_spinbox(0.0, 9999.0, 50.0, dec=1)
        self._lod2_dist_sl = _make_slider(0.0, 500.0, 50.0)
        self._lod2_dist_sb.setToolTip("Distance at which LOD 2 (low) variants start.")
        _link_slider_spinbox(self._lod2_dist_sl, self._lod2_dist_sb, 0.0, 500.0, on_change=self._sync_rt)
        _param_row("LOD 2 Dist:", self._lod2_dist_sl, self._lod2_dist_sb, lg)

        self._lod_cull_sb = _make_spinbox(0.0, 9999.0, 100.0, dec=1)
        self._lod_cull_sl = _make_slider(0.0, 500.0, 100.0)
        self._lod_cull_sb.setToolTip("Points beyond this distance are removed entirely. Set 0 to disable culling.")
        _link_slider_spinbox(self._lod_cull_sl, self._lod_cull_sb, 0.0, 500.0, on_change=self._sync_rt)
        _param_row("Cull Dist:", self._lod_cull_sl, self._lod_cull_sb, lg)

        # Per-asset LOD path table (shown only when LOD is enabled)
        self._lod_assets_widget = QWidget()
        lod_assets_lay = QVBoxLayout(self._lod_assets_widget)
        lod_assets_lay.setContentsMargins(0, 4, 0, 0)
        lod_assets_lay.setSpacing(2)
        hdr = QHBoxLayout()
        for txt, stretch in (("Asset", 1), ("LOD 1 (medium)", 2), ("LOD 2 (low)", 2)):
            lbl = QLabel(txt)
            lbl.setStyleSheet("color:#aaa; font-size:10px;")
            hdr.addWidget(lbl, stretch)
        lod_assets_lay.addLayout(hdr)
        self._lod_table_lay = QVBoxLayout()
        self._lod_table_lay.setSpacing(2)
        lod_assets_lay.addLayout(self._lod_table_lay)
        self._lod_assets_widget.setVisible(False)
        lg.addWidget(self._lod_assets_widget)

        self._lod_cam_combo.currentIndexChanged.connect(self._sync_rt)
        lay.addWidget(lod_grp)
        lay.addStretch()
        scroll.setWidget(w)
        outer_lay.addWidget(scroll, 1)
        self._populate_lod_cam_combo()
        return outer

    # ── CURVE tab ─────────────────────────────────────────────────────────
    def _build_scatter_cache_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 20, 8)
        lay.setSpacing(6)

        cache_grp = QGroupBox("File Cache")
        cv = QVBoxLayout(cache_grp)
        cv.setContentsMargins(8, 10, 8, 8)
        cv.setSpacing(5)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Base Folder:"))
        self.scatter_cache_folder_le = QLineEdit("$HIP/geo")
        self.scatter_cache_folder_le.setToolTip("Base folder path for the scatter cache file. Houdini variables such as $HIP are supported.")
        self.scatter_cache_folder_le.editingFinished.connect(self._on_scatter_cache_folder_changed)
        folder_row.addWidget(self.scatter_cache_folder_le, 1)
        self.scatter_cache_browse_btn = QPushButton("...")
        self.scatter_cache_browse_btn.setFixedWidth(28)
        self.scatter_cache_browse_btn.setToolTip("Browse for the cache output folder.")
        self.scatter_cache_browse_btn.clicked.connect(self._on_scatter_cache_folder_browse)
        folder_row.addWidget(self.scatter_cache_browse_btn)
        cv.addLayout(folder_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Base Name:"))
        self.scatter_cache_name_le = QLineEdit("$HIPNAME.$OS")
        self.scatter_cache_name_le.setToolTip("Base name for the cache file. $HIPNAME = scene name, $OS = scatter node name.")
        self.scatter_cache_name_le.editingFinished.connect(self._on_scatter_cache_name_changed)
        name_row.addWidget(self.scatter_cache_name_le, 1)
        name_row.addWidget(QLabel("Version:"))
        self.scatter_cache_version_sb = QSpinBox()
        self.scatter_cache_version_sb.setRange(1, 9999)
        self.scatter_cache_version_sb.setValue(1)
        self.scatter_cache_version_sb.setToolTip("Cache version number appended to the filename. Increment to write a new version without overwriting the previous.")
        self.scatter_cache_version_sb.valueChanged.connect(self._on_scatter_cache_version_changed)
        name_row.addWidget(self.scatter_cache_version_sb)
        cv.addLayout(name_row)

        option_row = QHBoxLayout()
        self.scatter_cache_timedependent_cb = QCheckBox("Time Dependent Cache")
        self.scatter_cache_timedependent_cb.setChecked(True)
        self.scatter_cache_timedependent_cb.setToolTip("When checked, the cache writes a separate file per frame. Uncheck for a static single-frame cache.")
        self.scatter_cache_timedependent_cb.toggled.connect(self._on_scatter_cache_timedependent_changed)
        option_row.addWidget(self.scatter_cache_timedependent_cb)
        self.scatter_cache_simulation_cb = QCheckBox("Simulation")
        self.scatter_cache_simulation_cb.setChecked(True)
        self.scatter_cache_simulation_cb.setToolTip("Enable the simulation flag on the file cache node so Houdini treats it as a simulation cache.")
        self.scatter_cache_simulation_cb.toggled.connect(self._on_scatter_cache_simulation_changed)
        option_row.addWidget(self.scatter_cache_simulation_cb)
        option_row.addStretch()
        cv.addLayout(option_row)

        eval_row = QHBoxLayout()
        eval_row.addWidget(QLabel("Evaluate As:"))
        self.scatter_cache_trange_cb = QComboBox()
        self.scatter_cache_trange_cb.addItems(["Single Frame", "Frame Range"])
        self.scatter_cache_trange_cb.setCurrentIndex(0)
        self.scatter_cache_trange_cb.setToolTip("Choose whether to cache only the current frame or a range of frames.")
        self.scatter_cache_trange_cb.currentIndexChanged.connect(self._on_scatter_cache_trange_changed)
        eval_row.addWidget(self.scatter_cache_trange_cb, 1)
        cv.addLayout(eval_row)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Start:"))
        self.scatter_cache_start_sb = QSpinBox()
        self.scatter_cache_start_sb.setRange(-99999, 999999)
        self.scatter_cache_start_sb.setValue(1)
        self.scatter_cache_start_sb.setToolTip("First frame of the cache range.")
        self.scatter_cache_start_sb.valueChanged.connect(self._on_scatter_cache_range_changed)
        range_row.addWidget(self.scatter_cache_start_sb)
        range_row.addWidget(QLabel("End:"))
        self.scatter_cache_end_sb = QSpinBox()
        self.scatter_cache_end_sb.setRange(-99999, 999999)
        self.scatter_cache_end_sb.setValue(50)
        self.scatter_cache_end_sb.setToolTip("Last frame of the cache range.")
        self.scatter_cache_end_sb.valueChanged.connect(self._on_scatter_cache_range_changed)
        range_row.addWidget(self.scatter_cache_end_sb)
        range_row.addWidget(QLabel("Inc:"))
        self.scatter_cache_inc_sb = QSpinBox()
        self.scatter_cache_inc_sb.setRange(1, 9999)
        self.scatter_cache_inc_sb.setValue(1)
        self.scatter_cache_inc_sb.setToolTip("Frame step increment — 1 = every frame, 2 = every other frame, etc.")
        self.scatter_cache_inc_sb.valueChanged.connect(self._on_scatter_cache_range_changed)
        range_row.addWidget(self.scatter_cache_inc_sb)
        cv.addLayout(range_row)

        sub_row = QHBoxLayout()
        sub_row.addWidget(QLabel("Substeps:"))
        self.scatter_cache_substeps_sb = QSpinBox()
        self.scatter_cache_substeps_sb.setRange(1, 100)
        self.scatter_cache_substeps_sb.setValue(1)
        self.scatter_cache_substeps_sb.setToolTip("Number of sub-frame samples per frame cached. Increase for motion-blur accuracy.")
        self.scatter_cache_substeps_sb.valueChanged.connect(self._on_scatter_cache_range_changed)
        sub_row.addWidget(self.scatter_cache_substeps_sb)
        sub_row.addStretch()
        cv.addLayout(sub_row)

        lay.addWidget(cache_grp)

        # ── Pack and Instance (proxy warning) ─────────────────────────────
        proxy_frame = QFrame()
        proxy_frame.setStyleSheet(
            "QFrame { background: #2e2200; border: 2px solid #c08000; border-radius: 5px; }"
        )
        pf_lay = QVBoxLayout(proxy_frame)
        pf_lay.setContentsMargins(10, 7, 10, 7)
        pf_lay.setSpacing(5)
        self.msw_pack_instance_cb = QCheckBox("  Pack and Instance  —  Uncheck this if you're using proxy assets")
        self.msw_pack_instance_cb.setChecked(True)
        self.msw_pack_instance_cb.setStyleSheet(
            "QCheckBox { font-weight: bold; color: #ffcc44; font-size: 12px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
        )
        self.msw_pack_instance_cb.setToolTip(
            "Checked (default): Pack and Instance is ON — geometry is packed.\n"
            "Unchecked: Pack and Instance is OFF — required when using Proxy workflows."
        )
        self.msw_pack_instance_cb.toggled.connect(self._on_msw_pack_instance_changed)
        pf_lay.addWidget(self.msw_pack_instance_cb)
        disp_row = QHBoxLayout()
        disp_lbl = QLabel("Display As:")
        disp_lbl.setStyleSheet("color: #ffcc44; font-size: 11px;")
        disp_row.addWidget(disp_lbl)
        self.msw_display_as_cb = QComboBox()
        self.msw_display_as_cb.addItems(["Full Geometry", "Point Cloud", "Bounding Box", "Centroid", "Hidden"])
        self.msw_display_as_cb.setCurrentText("Bounding Box")
        self.msw_display_as_cb.setToolTip("Controls how packed instances appear in the viewport.")
        self.msw_display_as_cb.currentTextChanged.connect(self._on_msw_display_as_changed)
        disp_row.addWidget(self.msw_display_as_cb)
        disp_row.addStretch()
        pf_lay.addLayout(disp_row)
        lay.addWidget(proxy_frame)

        self.scatter_cache_load_cb = QCheckBox("Load from Disk")
        self.scatter_cache_load_cb.setToolTip("When checked, the scatter network reads the cached .bgeo file from disk instead of recomputing scatter points.")
        self.scatter_cache_load_cb.setStyleSheet("QCheckBox { font-weight: bold; color: #7ec8e3; font-size: 11px; }")
        self.scatter_cache_load_cb.toggled.connect(self._on_scatter_cache_load_changed)
        lay.addWidget(self.scatter_cache_load_cb)
        self.scatter_cache_save_btn = QPushButton("💾 Bake Geometry ")
        self.scatter_cache_save_btn.setMinimumHeight(40)
        self.scatter_cache_save_btn.setStyleSheet(
            "QPushButton { background:#2c5a8c; color:#e8f2ff; font-weight:bold; padding: 0 10px; }"
            "QPushButton:hover { background:#3870a8; }"
            "QPushButton:pressed { background:#1e3e66; }"
        )
        self.scatter_cache_save_btn.setToolTip("Bake the current scatter geometry to disk using the file cache settings above.")
        self.scatter_cache_save_btn.clicked.connect(self._on_scatter_cache_bake)
        lay.addWidget(self.scatter_cache_save_btn)

        # ── Solaris ──────────────────────────────────────────────────────────
        solaris_grp = QGroupBox("Solaris")
        sl_lay = QVBoxLayout(solaris_grp)
        sl_lay.setContentsMargins(8, 10, 8, 8)
        self.send_to_solaris_btn = QPushButton("⬡  Send to Solaris")
        self.send_to_solaris_btn.setMinimumHeight(36)
        self.send_to_solaris_btn.setStyleSheet(
            "QPushButton { background-color:#1a4a5c; color:#a0e8ff; border:1px solid #2a7a9c; font-weight:bold; }"
            "QPushButton:hover { background-color:#1f5f78; border-color:#3ab0d8; }"
            "QPushButton:pressed { background-color:#0f2f3c; }"
        )
        self.send_to_solaris_btn.setToolTip(
            "Create a sopimport LOP in /stage that imports this scatter into Solaris."
        )
        self.send_to_solaris_btn.clicked.connect(self._on_send_to_solaris)
        sl_lay.addWidget(self.send_to_solaris_btn)

        # ── Lookdev ───────────────────────────────────────────────────────────
        msw_ld_grp = QGroupBox("Lookdev")
        msw_ld_lay = QVBoxLayout(msw_ld_grp)
        msw_ld_lay.setContentsMargins(8, 10, 8, 8)
        msw_lookdev_btn = QPushButton("Lookdev")
        msw_lookdev_btn.setMinimumHeight(36)
        msw_lookdev_btn.setToolTip(
            "Open the Lookdev window — build PBR shaders for your scatter assets\n"
            "in Arnold or Redshift, with textures and live parameter tweaks."
        )
        msw_lookdev_btn.setStyleSheet(
            "QPushButton { background-color:#3a1a5c; color:#d0b0ff; border-color:#5f2b8b; }"
            "QPushButton:hover { background-color:#4f2480; border-color:#8f3cc8; }"
            "QPushButton:pressed { background-color:#241038; }"
        )
        msw_lookdev_btn.clicked.connect(self._open_lookdev)
        msw_ld_lay.addWidget(msw_lookdev_btn)
        lay.addWidget(msw_ld_grp)
        lay.addWidget(solaris_grp)

        lay.addStretch()
        return w

    def _build_curve_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # ── info ──────────────────────────────────────────────────────────
        info = QLabel(
            "Scatter assets along a curve drawn on the surface.\n"
            "1. Click  Draw Curve  to enter the curve draw state.\n"
            "2. Draw on the surface — points are projected onto it.\n"
            "3. Adjust spacing and click  Apply Curve Scatter.\n"
            "4. Use  Clear Curve  to remove the curve branch."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa; font-size:10px; padding:4px;")
        lay.addWidget(info)

        lay.addWidget(_h_sep())

        # ── resample spacing ──────────────────────────────────────────────
        grp = QGroupBox("Curve Settings")
        gl  = QVBoxLayout(grp)

        self.curve_spacing_sb = _make_spinbox(0.01, 1.0, 0.02, dec=3)
        self.curve_spacing_sb.setMaximum(99999.0)   # slider caps at 100; spinbox is unlimited
        self.curve_spacing_sl = _make_slider(0.01, 1.0, 0.02)
        _link_slider_spinbox(self.curve_spacing_sl, self.curve_spacing_sb,
                             0.01, 100.0, on_change=self._on_curve_spacing_changed)
        self.curve_spacing_sb.valueChanged.connect(self._on_curve_spacing_changed)
        _param_row("Point Spacing:", self.curve_spacing_sl, self.curve_spacing_sb, gl)

        # Jitter along curve
        self.curve_jitter_sb = _make_spinbox(0.0, 10.0, 0.0, dec=3)
        self.curve_jitter_sl = _make_slider(0.0, 10.0, 0.0)
        _link_slider_spinbox(self.curve_jitter_sl, self.curve_jitter_sb,
                             0.0, 10.0, on_change=self._on_curve_jitter_changed)
        self.curve_jitter_sb.valueChanged.connect(self._on_curve_jitter_changed)
        _param_row("Jitter:", self.curve_jitter_sl, self.curve_jitter_sb, gl)

        # Random Y rotation
        self.curve_rand_rot_sb = _make_spinbox(0.0, 360.0, 0.0, dec=1)
        self.curve_rand_rot_sl = _make_slider(0.0, 360.0, 0.0)
        _link_slider_spinbox(self.curve_rand_rot_sl, self.curve_rand_rot_sb,
                             0.0, 360.0, on_change=self._on_curve_rand_rot_changed)
        self.curve_rand_rot_sb.valueChanged.connect(self._on_curve_rand_rot_changed)
        _param_row("Rand Rot:", self.curve_rand_rot_sl, self.curve_rand_rot_sb, gl)

        # Curve Scale
        self.curve_scale_sb = _make_spinbox(0.01, 10.0, 1.0, dec=3)
        self.curve_scale_sl = _make_slider(0.01, 10.0, 1.0)
        _link_slider_spinbox(self.curve_scale_sl, self.curve_scale_sb,
                             0.01, 10.0, on_change=self._on_curve_scale_changed)
        self.curve_scale_sb.valueChanged.connect(self._on_curve_scale_changed)
        _param_row("Scale:", self.curve_scale_sl, self.curve_scale_sb, gl)

        # Subdivide — wires to resample node's treatpolysas (option 1)
        self.curve_subdivide_cb = QCheckBox("Subdivide")
        self.curve_subdivide_cb.setToolTip(
            "Sets Resample 'Treat Polygons As' to Subdivision Curves (treatpolysas = 1)"
        )
        self.curve_subdivide_cb.stateChanged.connect(self._on_curve_subdivide_changed)
        gl.addWidget(self.curve_subdivide_cb)

        lay.addWidget(grp)

        # ── curve selector ────────────────────────────────────────────────
        sel_grp = QGroupBox("Curve Selection")
        sl_lay  = QVBoxLayout(sel_grp)

        sel_top = QHBoxLayout()
        sel_top.addWidget(QLabel("Active curve:"))
        self.curve_selector_cb = QComboBox()
        self.curve_selector_cb.setToolTip(
            "Select a curve to act on (rename / delete)"
        )
        self.curve_selector_cb.currentIndexChanged.connect(self._on_curve_selected)
        sel_top.addWidget(self.curve_selector_cb, 1)

        self.refresh_curves_btn = QPushButton("↻")
        self.refresh_curves_btn.setFixedSize(26, 26)
        self.refresh_curves_btn.setToolTip("Refresh the curve list")
        self.refresh_curves_btn.clicked.connect(self._refresh_curve_selector)
        sel_top.addWidget(self.refresh_curves_btn)
        sl_lay.addLayout(sel_top)

        sel_btns = QHBoxLayout()
        self.select_curve_btn = QPushButton("⬡  Select in Network")
        self.select_curve_btn.setToolTip(
            "Select the chosen curve node in the Houdini network editor"
        )
        self.select_curve_btn.setEnabled(False)
        self.select_curve_btn.clicked.connect(self._on_select_curve_in_network)
        sel_btns.addWidget(self.select_curve_btn)

        self.rename_curve_btn = QPushButton("✎  Rename")
        self.rename_curve_btn.setToolTip("Rename the selected curve node")
        self.rename_curve_btn.setEnabled(False)
        self.rename_curve_btn.clicked.connect(self._on_rename_curve)
        sel_btns.addWidget(self.rename_curve_btn)

        self.delete_curve_btn = QPushButton("✕  Delete")
        self.delete_curve_btn.setToolTip("Delete the selected curve and rewire the network")
        self.delete_curve_btn.setEnabled(False)
        self.delete_curve_btn.setStyleSheet(
            "QPushButton { color:#ff6060; } QPushButton:hover { background:#5a1a1a; }"
        )
        self.delete_curve_btn.clicked.connect(self._on_delete_selected_curve)
        sel_btns.addWidget(self.delete_curve_btn)
        sl_lay.addLayout(sel_btns)

        lay.addWidget(sel_grp)

        # ── buttons ───────────────────────────────────────────────────────
        btn_grp = QGroupBox("Actions")
        bl = QVBoxLayout(btn_grp)

        self.draw_curve_btn = QPushButton("✏  Draw Curve on Surface")
        self.draw_curve_btn.setMinimumHeight(36)
        self.draw_curve_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        self.draw_curve_btn.setToolTip(
            "Activates Houdini's curve draw state — draw on the surface geometry"
        )
        self.draw_curve_btn.clicked.connect(self._on_draw_curve)
        bl.addWidget(self.draw_curve_btn)

        self.add_curve_btn = QPushButton("➕  Add Another Curve")
        self.add_curve_btn.setMinimumHeight(36)
        self.add_curve_btn.setToolTip(
            "Draw a second (or further) curve that will be merged with the existing one(s)"
        )
        self.add_curve_btn.clicked.connect(self._on_add_curve)
        bl.addWidget(self.add_curve_btn)
        self.add_curve_btn.hide()

        self.apply_curve_btn = QPushButton("⟳  Apply Curve Scatter")
        self.apply_curve_btn.setMinimumHeight(36)
        self.apply_curve_btn.setToolTip(
            "Build / rebuild the curve scatter network with current settings"
        )
        self.apply_curve_btn.clicked.connect(self._on_apply_curve)
        bl.addWidget(self.apply_curve_btn)
        self.apply_curve_btn.hide()

        self.clear_curve_btn = QPushButton("✕  Clear Curve")
        self.clear_curve_btn.setMinimumHeight(36)
        self.clear_curve_btn.setStyleSheet(
            "QPushButton { color:#ff6060; } QPushButton:hover { background:#5a1a1a; }"
        )
        self.clear_curve_btn.setToolTip("Remove the curve scatter branch from the network")
        self.clear_curve_btn.clicked.connect(self._on_clear_curve)
        bl.addWidget(self.clear_curve_btn)

        lay.addWidget(btn_grp)

        # ── status ────────────────────────────────────────────────────────
        self.curve_status_l = QLabel("No curve active.")
        self.curve_status_l.setStyleSheet("color:#888; font-size:10px; padding:2px;")
        self.curve_status_l.setWordWrap(True)
        lay.addWidget(self.curve_status_l)

        lay.addStretch()
        return w

    # ── paint / erase / clear bar ─────────────────────────────────────────
    def _build_paint_row(self):
        lay = QHBoxLayout()
        lay.setSpacing(6)

        self.p_btn = QPushButton("▶  PAINT")
        self.p_btn.setObjectName("paint_btn")
        self.p_btn.setCheckable(True)
        self.p_btn.setMinimumHeight(42)
        self.p_btn.setToolTip("LMB drag in the viewport to scatter instances")

        self.e_btn = QPushButton("⌦  ERASE")
        self.e_btn.setObjectName("erase_btn")
        self.e_btn.setCheckable(True)
        self.e_btn.setMinimumHeight(42)
        self.e_btn.setToolTip("LMB drag in the viewport to erase instances")

        self.c_btn = QPushButton("✕  CLEAR ALL")
        self.c_btn.setObjectName("clear_btn")
        self.c_btn.setMinimumHeight(42)
        self.c_btn.setToolTip("Delete every scattered point in this setup")

        self.p_btn.clicked.connect(lambda: self._toggle_mode("paint",  self.p_btn.isChecked()))
        self.e_btn.clicked.connect(lambda: self._toggle_mode("erase",  self.e_btn.isChecked()))
        self.c_btn.clicked.connect(self._on_clear_all)

        lay.addWidget(self.p_btn, 2)
        lay.addWidget(self.e_btn, 2)
        lay.addWidget(self.c_btn, 1)
        return lay

    # ── PAINT MASK tab (ivy mode) ─────────────────────────────────────────
    def _build_paint_mask_tab(self):
        """
        Ivy-mode tab that combines the brush parameter group with the
        Paint / Erase / Clear-All action row, so an Ivy Scatter window can
        paint the same mask the ivy chain reads via ivy_mask_threshold.
        """
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        recache_btn = QPushButton("Recache Strokes")
        recache_btn.setMinimumHeight(30)
        recache_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        recache_btn.setToolTip("Re-bake all existing brush strokes into the paint cache. Use after changing density or spacing on a finished paint.")
        recache_btn.clicked.connect(self._on_recache_strokes)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setWidget(self._build_brush_tab())
        lay.addWidget(scroll, 1)
        lay.addWidget(recache_btn)

        lay.addWidget(_h_sep())
        lay.addLayout(self._build_paint_row())
        return w

    # ── IVY tab ───────────────────────────────────────────────────────────
    def _build_ivy_tab(self):
        """
        Main Ivy Generation tab (Strands & Presets).
        """
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        info = QLabel(
            "Paint a mask on your surface (Brush tab → PAINT), then switch here.\n"
            "Strands grow from every painted point using its surface normal as the\n"
            "initial direction. Gravity bends each strand downward over its length.\n"
            "Click  Create Ivy Network  once, then paint and  Regenerate  freely."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa; font-size:10px; padding:4px;")
        lay.addWidget(info)
        lay.addWidget(_h_sep())

        strand_scroll = QScrollArea()
        strand_scroll.setWidgetResizable(True)
        strand_scroll_w = QWidget()
        strand_scroll_lay = QVBoxLayout(strand_scroll_w)
        strand_scroll_lay.setSpacing(4)
        strand_scroll.setWidget(strand_scroll_w)
        lay.addWidget(strand_scroll, 1)

        STRAND_GROUPS = [
            ("Mask & Seed",
             [("ivy_seed",           "Seed",             0,    9999, 2789,  1,    True),
              ("ivy_max_strands",    "Max Strands",      1,    2000, 333,   1,    True),
              ("ivy_mask_threshold", "Mask Threshold",   0.0,  1.0,  0.504, 0.01, False)]),
            ("Shape",
             [("ivy_strand_length",  "Strand Length",    0.1,  100.0, 9.182, 0.05, False),
              ("ivy_step_size",      "Step Size",        0.01, 10.0, 0.888, 0.01, False),
              ("ivy_curl",           "Curl Amount",      0.0,  2.0,  0.0, 0.05, False)]),
            ("Gravity & Motion",
             [("ivy_gravity",        "Gravity Strength", 0.0,  2.0,  0.0,  0.05, False),
              ("ivy_droop_bias",     "Droop Bias",       0.0,  3.0,  0.0,  0.05, False),
              ("ivy_inertia",        "Inertia",          0.0,  1.0,  0.0,  0.01, False),
              ("ivy_randomness",     "Randomness",       0.0,  1.0,  0.25, 0.01, False)]),
            ("Point Jitter",
             [("ivy_jitter_scale",   "Jitter Scale",     0.0, 10.0,  0.0,  0.1,  False),
              ("ivy_jitter_seed",    "Jitter Seed",      0,    9999, 0,    1,    True)]),
        ]

        for group_title, specs in STRAND_GROUPS:
            grp = _CollapsibleGroup(group_title)
            gl  = QVBoxLayout(grp.body)
            for name, label, mn, mx, default, step, is_int in specs:
                if is_int:
                    sb = _make_int_spinbox(int(mn), int(mx), int(default))
                    sl = QSlider(Qt.Horizontal)
                    sl.setRange(int(mn), int(mx))
                    sl.setValue(int(default))
                    sl.valueChanged.connect(
                        lambda v, _sb=sb: (
                            _sb.blockSignals(True),
                            _sb.setValue(v),
                            _sb.blockSignals(False),
                            self._sync_ivy_rt(),
                        )
                    )
                    sb.valueChanged.connect(
                        lambda v, _sl=sl: (
                            _sl.blockSignals(True),
                            _sl.setValue(int(v)),
                            _sl.blockSignals(False),
                        )
                    )
                else:
                    sb = _make_spinbox(mn, mx, default, dec=3, step=step)
                    sl = _make_slider(mn, mx, default)
                    _link_slider_spinbox(sl, sb, mn, mx, on_change=self._sync_ivy_rt)
                sb.valueChanged.connect(self._sync_ivy_rt)
                _param_row(label + ":", sl, sb, gl)
                self._ivy_widgets[name] = sb
            strand_scroll_lay.addWidget(grp)

        len_grp = _CollapsibleGroup("Strand Length Scale")
        len_vl = QVBoxLayout(len_grp.body)
        len_vl.setSpacing(3)
        self._ivy_sim_min_len_sb = _make_spinbox(0.01, 10.0, 0.1, dec=3, step=0.1)
        self._ivy_sim_min_len_sl = _make_slider(0.01, 10.0, 0.1)
        self._ivy_sim_min_len_sb.setToolTip("Minimum scale multiplier applied to ivy strand length. Strands shorter than this ratio are culled.")
        _link_slider_spinbox(self._ivy_sim_min_len_sl, self._ivy_sim_min_len_sb,
                             0.01, 10.0, on_change=self._on_ivy_sim_length_changed)
        self._ivy_sim_min_len_sb.valueChanged.connect(self._on_ivy_sim_length_changed)
        _param_row("Min Length:", self._ivy_sim_min_len_sl, self._ivy_sim_min_len_sb, len_vl)
        self._ivy_sim_max_len_sb = _make_spinbox(1.0, 10.0, 1.0, dec=3, step=0.1)
        self._ivy_sim_max_len_sl = _make_slider(1.0, 10.0, 1.0)
        self._ivy_sim_max_len_sb.setToolTip("Maximum scale multiplier applied to ivy strand length. Controls how long the longest strands can grow.")
        _link_slider_spinbox(self._ivy_sim_max_len_sl, self._ivy_sim_max_len_sb,
                             1.0, 10.0, on_change=self._on_ivy_sim_length_changed)
        self._ivy_sim_max_len_sb.valueChanged.connect(self._on_ivy_sim_length_changed)
        _param_row("Max Length:", self._ivy_sim_max_len_sl, self._ivy_sim_max_len_sb, len_vl)
        strand_scroll_lay.addWidget(len_grp)

        strand_scroll_lay.addStretch()

        # Presets
        preset_grp = _CollapsibleGroup("Presets")
        pr_outer = QVBoxLayout(preset_grp.body)
        pr_outer.setContentsMargins(2, 2, 2, 2)
        pr_outer.setSpacing(4)
        self._user_presets = self._load_user_presets()
        pr_row = QHBoxLayout()
        pr_row.setSpacing(4)
        self.ivy_preset_cb = QComboBox()
        self.ivy_preset_cb.setToolTip("Select a built-in or user-saved ivy preset to apply its parameter values.")
        self._refresh_preset_combo()
        self.ivy_preset_cb.activated.connect(self._on_ivy_preset_selected)
        pr_row.addWidget(self.ivy_preset_cb, 1)
        self.ivy_preset_save_btn = QPushButton("Save")
        self.ivy_preset_save_btn.setToolTip("Save the current ivy parameters as a new named user preset.")
        self.ivy_preset_save_btn.clicked.connect(self._on_ivy_preset_save)
        pr_row.addWidget(self.ivy_preset_save_btn)
        self.ivy_preset_delete_btn = QPushButton("Delete")
        self.ivy_preset_delete_btn.setToolTip("Delete the selected user preset (built-in presets cannot be deleted).")
        self.ivy_preset_delete_btn.clicked.connect(self._on_ivy_preset_delete)
        pr_row.addWidget(self.ivy_preset_delete_btn)
        self.ivy_preset_update_btn = QPushButton("Update")
        self.ivy_preset_update_btn.setToolTip("Overwrite the selected user preset with the current parameter values.")
        self.ivy_preset_update_btn.clicked.connect(self._on_ivy_preset_update)
        pr_row.addWidget(self.ivy_preset_update_btn)
        pr_outer.addLayout(pr_row)
        lay.addWidget(preset_grp)

        lay.addWidget(_h_sep())

        # Main Ivy Actions
        self.ivy_create_btn = QPushButton("🌿  Create Ivy Network ")
        self.ivy_create_btn.setMinimumHeight(36)
        self.ivy_create_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        self.ivy_create_btn.setToolTip("Build the ivy SOP network inside the selected geo node. Do this once before painting and regenerating.")
        self.ivy_create_btn.clicked.connect(self._on_ivy_create)
        lay.addWidget(self.ivy_create_btn)

        self.ivy_regen_btn = QPushButton("⟳  Regenerate")
        self.ivy_regen_btn.setMinimumHeight(36)
        self.ivy_regen_btn.setToolTip("Re-cook the ivy network with the current parameters. Use after painting new mask areas or changing settings.")
        self.ivy_regen_btn.clicked.connect(self._on_ivy_regen)
        lay.addWidget(self.ivy_regen_btn)
        self.ivy_regen_btn.hide()

        self.ivy_remove_btn = QPushButton("✕  Remove Ivy Network")
        self.ivy_remove_btn.setMinimumHeight(36)
        self.ivy_remove_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #ff6060; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #5a1a1a; border-color: #b03030; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        self.ivy_remove_btn.setToolTip("Delete the ivy SOP chain from this geo node and restore the original scatter network.")
        self.ivy_remove_btn.clicked.connect(self._on_ivy_remove)
        lay.addWidget(self.ivy_remove_btn)

        return w

    def _build_simulation_tab(self):
        """
        Tab for Vellum Simulation settings.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        sim_scroll = QScrollArea()
        sim_scroll.setWidgetResizable(True)
        sim_scroll_w = QWidget()
        sim_scroll_lay = QVBoxLayout(sim_scroll_w)
        sim_scroll_lay.setSpacing(4)
        sim_scroll.setWidget(sim_scroll_w)
        lay.addWidget(sim_scroll, 1)

        SIM_SPECS = [
            ("ivy_sim_gravity",     "Gravity",       -30.0,  30.0,  -9.8,  0.1,  False),
            ("ivy_sim_substeps",    "Substeps",        1,    20,     2,    1,    True),
            ("ivy_sim_stiffness",   "Stiffness",       0.0,   1.0,   0.5,  0.01, False),
            ("ivy_sim_damping",     "Damping",         0.0,   1.0,   0.1,  0.01, False),
            ("ivy_sim_start_frame", "Start Frame",  -10000, 10000,   1,    1,    True),
            ("ivy_sim_end_frame",   "End Frame",    -10000, 10000,   100,  1,    True),
        ]
        
        params_grp = _CollapsibleGroup("Vellum Hair Parameters")
        params_gl = QGridLayout(params_grp.body)
        params_gl.setHorizontalSpacing(6)
        params_gl.setVerticalSpacing(3)
        for row_i, (name, label, mn, mx, default, step, is_int) in enumerate(SIM_SPECS):
            if is_int:
                sb = _make_int_spinbox(int(mn), int(mx), int(default))
            else:
                sb = _make_spinbox(mn, mx, default, dec=3, step=step)
            sb.valueChanged.connect(self._on_ivy_sim_param_changed)
            lbl = QLabel(label + ":")
            lbl.setStyleSheet("color:#bbb;")
            params_gl.addWidget(lbl, row_i, 0)
            params_gl.addWidget(sb,  row_i, 1)
            self._ivy_sim_widgets[name] = sb
        sim_scroll_lay.addWidget(params_grp)

        bend_grp = _CollapsibleGroup("Bend")
        bend_vl = QVBoxLayout(bend_grp.body)
        bend_vl.setSpacing(3)
        for bname, blabel, bmn, bmx, bdef, bstep in (
            ("ivy_sim_bend_stiffness",  "Stiffness",       10.0, 1000.0, 10.0, 1.0),
            ("ivy_sim_bend_damping",    "Damping Ratio",   0.0, 1.0, 0.1, 0.01),
            ("ivy_sim_bend_rest_scale", "Rest Angle Scale",0.0, 2.0, 1.0, 0.01),
        ):
            sb = _make_spinbox(bmn, bmx, bdef, dec=3, step=bstep)
            sl = _make_slider(bmn, bmx, bdef)
            _link_slider_spinbox(sl, sb, bmn, bmx, on_change=self._on_ivy_sim_param_changed)
            sb.valueChanged.connect(self._on_ivy_sim_param_changed)
            _param_row(blabel + ":", sl, sb, bend_vl)
            self._ivy_sim_widgets[bname] = sb
            self._ivy_sim_sliders[bname] = sl
        sim_scroll_lay.addWidget(bend_grp)

        col_grp = _CollapsibleGroup("Collision")
        col_gl = QVBoxLayout(col_grp.body)
        col_row = QHBoxLayout()
        col_lbl = QLabel("Collision:")
        col_lbl.setStyleSheet("color:#bbb;")
        self.ivy_sim_collision_le = QLineEdit()
        self.ivy_sim_collision_le.setPlaceholderText("Path to collision SOP/OBJ node…")
        self.ivy_sim_collision_le.setToolTip("Houdini path to the geometry node used as a collision object in the Vellum simulation.")
        self.ivy_sim_collision_le.textEdited.connect(self._on_ivy_sim_collision_changed)
        self.ivy_sim_collision_le.editingFinished.connect(self._on_ivy_sim_collision_changed)
        self.ivy_sim_collision_browse_btn = QPushButton("Browse…")
        self.ivy_sim_collision_browse_btn.setToolTip("Pick a node in the Houdini scene to use as a collision object.")
        self.ivy_sim_collision_browse_btn.clicked.connect(self._browse_ivy_sim_collision)
        col_row.addWidget(col_lbl)
        col_row.addWidget(self.ivy_sim_collision_le, 1)
        col_row.addWidget(self.ivy_sim_collision_browse_btn)
        col_gl.addLayout(col_row)
        sim_scroll_lay.addWidget(col_grp)

        glue_grp = _CollapsibleGroup("Glue on Collision", expanded=False)
        glue_gl = QVBoxLayout(glue_grp.body)
        self.ivy_glue_enabled_cb = QCheckBox("Enable Glue on Collision")
        self.ivy_glue_enabled_cb.setChecked(True)
        self.ivy_glue_enabled_cb.setToolTip("When checked, ivy strands that come within the glue distance of a collision object will stick to it.")
        self.ivy_glue_enabled_cb.stateChanged.connect(self._on_ivy_glue_changed)
        glue_gl.addWidget(self.ivy_glue_enabled_cb)
        self.ivy_glue_distance_sb = _make_spinbox(0.0, 5.0, 0.2, dec=3, step=0.01)
        self.ivy_glue_distance_sl = _make_slider(0.0, 5.0, 0.2)
        self.ivy_glue_distance_sb.setToolTip("Distance threshold at which ivy strands glue to a collision surface.")
        _link_slider_spinbox(self.ivy_glue_distance_sl, self.ivy_glue_distance_sb, 0.0, 5.0, on_change=self._on_ivy_glue_changed)
        self.ivy_glue_distance_sb.valueChanged.connect(self._on_ivy_glue_changed)
        _param_row("Glue Distance:", self.ivy_glue_distance_sl, self.ivy_glue_distance_sb, glue_gl)
        self.ivy_glue_strength_sb = _make_spinbox(0.0, 1.0, 1.0, dec=3, step=0.01)
        self.ivy_glue_strength_sl = _make_slider(0.0, 1.0, 1.0)
        self.ivy_glue_strength_sb.setToolTip("Strength of the glue constraint (0 = no hold, 1 = firmly attached).")
        _link_slider_spinbox(self.ivy_glue_strength_sl, self.ivy_glue_strength_sb, 0.0, 1.0, on_change=self._on_ivy_glue_changed)
        self.ivy_glue_strength_sb.valueChanged.connect(self._on_ivy_glue_changed)
        _param_row("Glue Strength:", self.ivy_glue_strength_sl, self.ivy_glue_strength_sb, glue_gl)
        sim_scroll_lay.addWidget(glue_grp)

        # ── Sim Cache ─────────────────────────────────────────────────────────
        sim_bake_grp = QGroupBox("Sim Cache")
        sv = QVBoxLayout(sim_bake_grp)
        self.ivy_render_btn = QPushButton("💾  Render Sim to Disk ")
        self.ivy_render_btn.setMinimumHeight(32)
        self.ivy_render_btn.setStyleSheet(
            "QPushButton { background-color: #7a1a1a; color: #ffd0d0; border-color: #b03030; font-weight: bold; }"
            "QPushButton:hover { background-color: #8c2020; border-color: #cc4040; }"
            "QPushButton:pressed { background-color: #5a0e0e; }"
        )
        self.ivy_render_btn.setToolTip("Save the Vellum simulation result to disk using the sim cache folder and name settings.")
        self.ivy_render_btn.clicked.connect(self._on_ivy_sim_render)
        sv.addWidget(self.ivy_render_btn)
        self.ivy_sim_loadfromdisk_cb = QCheckBox("Load Sim from Disk")
        self.ivy_sim_loadfromdisk_cb.setToolTip("When checked, the Vellum sim reads the cached file from disk instead of re-simulating.")
        self.ivy_sim_loadfromdisk_cb.setStyleSheet("QCheckBox { font-weight: bold; color: #7ec8e3; font-size: 11px; }")
        self.ivy_sim_loadfromdisk_cb.stateChanged.connect(self._on_ivy_sim_loadfromdisk_changed)
        sv.addWidget(self.ivy_sim_loadfromdisk_cb)
        sim_folder_row = QHBoxLayout()
        sim_folder_row.addWidget(QLabel("Folder:"))
        self.sim_cache_folder_le = QLineEdit("$HIP/geo")
        self.sim_cache_folder_le.setToolTip("Output folder for the simulation cache. Supports Houdini variables like $HIP.")
        self.sim_cache_folder_le.editingFinished.connect(self._on_sim_cache_folder_changed)
        sim_folder_row.addWidget(self.sim_cache_folder_le, 1)
        self.sim_cache_browse_btn = QPushButton("…")
        self.sim_cache_browse_btn.setFixedWidth(24)
        self.sim_cache_browse_btn.setToolTip("Browse for the simulation cache output folder.")
        self.sim_cache_browse_btn.clicked.connect(self._on_sim_cache_folder_browse)
        sim_folder_row.addWidget(self.sim_cache_browse_btn)
        sv.addLayout(sim_folder_row)
        sim_name_row = QHBoxLayout()
        sim_name_row.addWidget(QLabel("Name:"))
        self.sim_cache_name_le = QLineEdit("$HIPNAME.$OS")
        self.sim_cache_name_le.setToolTip("Base name for the simulation cache file. $HIPNAME = scene name, $OS = node name.")
        self.sim_cache_name_le.editingFinished.connect(self._on_sim_cache_name_changed)
        sim_name_row.addWidget(self.sim_cache_name_le, 1)
        sv.addLayout(sim_name_row)
        sim_range_row = QHBoxLayout()
        sim_range_row.addWidget(QLabel("Start:"))
        self.sim_cache_start_sb = QSpinBox()
        self.sim_cache_start_sb.setRange(-99999, 999999)
        self.sim_cache_start_sb.setValue(1)
        self.sim_cache_start_sb.setToolTip("First frame of the sim cache range.")
        self.sim_cache_start_sb.valueChanged.connect(self._on_sim_cache_range_changed)
        sim_range_row.addWidget(self.sim_cache_start_sb)
        sim_range_row.addWidget(QLabel("End:"))
        self.sim_cache_end_sb = QSpinBox()
        self.sim_cache_end_sb.setRange(-99999, 999999)
        self.sim_cache_end_sb.setValue(100)
        self.sim_cache_end_sb.setToolTip("Last frame of the sim cache range.")
        self.sim_cache_end_sb.valueChanged.connect(self._on_sim_cache_range_changed)
        sim_range_row.addWidget(self.sim_cache_end_sb)
        sim_range_row.addWidget(QLabel("Inc:"))
        self.sim_cache_inc_sb = QSpinBox()
        self.sim_cache_inc_sb.setRange(1, 9999)
        self.sim_cache_inc_sb.setValue(1)
        self.sim_cache_inc_sb.setToolTip("Frame step increment for the sim cache.")
        self.sim_cache_inc_sb.valueChanged.connect(self._on_sim_cache_range_changed)
        sim_range_row.addWidget(self.sim_cache_inc_sb)
        sv.addLayout(sim_range_row)
        sim_sub_row = QHBoxLayout()
        sim_sub_row.addWidget(QLabel("Substeps:"))
        self.sim_cache_substeps_sb = QSpinBox()
        self.sim_cache_substeps_sb.setRange(1, 100)
        self.sim_cache_substeps_sb.setValue(1)
        self.sim_cache_substeps_sb.setToolTip("Number of sub-frame samples per frame for the sim cache.")
        self.sim_cache_substeps_sb.valueChanged.connect(self._on_sim_cache_range_changed)
        sim_sub_row.addWidget(self.sim_cache_substeps_sb)
        sim_sub_row.addStretch()
        sv.addLayout(sim_sub_row)

        sim_scroll_lay.addStretch()

        sim_mgmt_row = QHBoxLayout()
        self.ivy_sim_create_btn = QPushButton("Create Sim")
        self.ivy_sim_create_btn.setStyleSheet(
            "QPushButton { background:#2c5a8c; color:#e8f2ff; font-weight:bold; }"
            "QPushButton:hover { background:#3870a8; }"
            "QPushButton:pressed { background:#1e3e66; }"
        )
        self.ivy_sim_create_btn.setToolTip("Build the Vellum simulation SOP chain for ivy physics.")
        self.ivy_sim_create_btn.clicked.connect(self._on_ivy_sim_create)
        sim_mgmt_row.addWidget(self.ivy_sim_create_btn)
        self.ivy_sim_remove_btn = QPushButton("Remove Sim")
        self.ivy_sim_remove_btn.setStyleSheet(
            "QPushButton { background-color: #7a1a1a; color: #ffd0d0; border-color: #b03030; font-weight: bold; }"
            "QPushButton:hover { background-color: #8c2020; border-color: #cc4040; }"
            "QPushButton:pressed { background-color: #5a0e0e; }"
        )
        self.ivy_sim_remove_btn.setToolTip("Remove the Vellum simulation nodes from the ivy network.")
        self.ivy_sim_remove_btn.clicked.connect(self._on_ivy_sim_remove)
        sim_mgmt_row.addWidget(self.ivy_sim_remove_btn)
        lay.addLayout(sim_mgmt_row)

        sim_act_row = QHBoxLayout()
        self.ivy_simulate_btn = QPushButton("▶  Simulate")
        self.ivy_simulate_btn.setMinimumHeight(32)
        self.ivy_simulate_btn.setStyleSheet("QPushButton { background-color: #1a5c1a; color: #7fff7f; border-color: #3a9a3a; }")
        self.ivy_simulate_btn.setToolTip("Run the Vellum simulation over the configured frame range and cache the result.")
        self.ivy_simulate_btn.clicked.connect(self._on_ivy_simulate)
        sim_act_row.addWidget(self.ivy_simulate_btn)
        self.ivy_sim_reset_btn = QPushButton("↺  Reset Simulation")
        self.ivy_sim_reset_btn.setMinimumHeight(32)
        self.ivy_sim_reset_btn.setStyleSheet("QPushButton { background-color: #5c3a1a; color: #e0b898; border-color: #8b5f2b; }")
        self.ivy_sim_reset_btn.setToolTip("Clear the cached simulation and reset the Vellum solver to frame 1.")
        self.ivy_sim_reset_btn.clicked.connect(self._on_ivy_sim_reset)
        sim_act_row.addWidget(self.ivy_sim_reset_btn)
        lay.addLayout(sim_act_row)
        lay.addWidget(sim_bake_grp)

        return w

    def _build_appearance_tab(self):
        """
        Tab for Wire Shape, Noise, and Display settings.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        wire_scroll = QScrollArea()
        wire_scroll.setWidgetResizable(True)
        wire_scroll_w = QWidget()
        wire_scroll_lay = QVBoxLayout(wire_scroll_w)
        wire_scroll_lay.setSpacing(4)
        wire_scroll.setWidget(wire_scroll_w)
        lay.addWidget(wire_scroll, 1)

        wire_shape_grp = _CollapsibleGroup("Wire Shape")
        wire_gl = QVBoxLayout(wire_shape_grp.body)
        WIRE_SPECS = [
            ("ivy_wire_radius",    "Wire Radius",  0.001, 1.0, 0.008, 0.001, False),
            ("ivy_wire_segs",      "Segments",     1,    24,   5,    1,    True),
            ("ivy_wire_divisions", "Divisions",    1,    32,   5,    1,    True),
        ]
        for name, label, mn, mx, default, step, is_int in WIRE_SPECS:
            if is_int:
                sb = _make_int_spinbox(int(mn), int(mx), int(default))
                sl = QSlider(Qt.Horizontal)
                sl.setRange(int(mn), int(mx))
                sl.setValue(int(default))
                sl.valueChanged.connect(lambda v, _sb=sb: (_sb.blockSignals(True), _sb.setValue(v), _sb.blockSignals(False), self._sync_ivy_rt()))
                sb.valueChanged.connect(lambda v, _sl=sl: (_sl.blockSignals(True), _sl.setValue(int(v)), _sl.blockSignals(False)))
            else:
                sb = _make_spinbox(mn, mx, default, dec=3, step=step)
                sl = _make_slider(mn, mx, default)
                _link_slider_spinbox(sl, sb, mn, mx, on_change=self._sync_ivy_rt)
            sb.valueChanged.connect(self._sync_ivy_rt)
            _param_row(label + ":", sl, sb, wire_gl)
            self._ivy_widgets[name] = sb
            self._ivy_sliders[name] = sl
        wire_scroll_lay.addWidget(wire_shape_grp)

        resample_grp = _CollapsibleGroup("Resample & Subdivide")
        resample_gl = QVBoxLayout(resample_grp.body)
        self.ivy_subdivide_cb = QCheckBox("Subdivide")
        self.ivy_subdivide_cb.setToolTip("Apply subdivision to the resampled ivy curve for a smoother wire shape.")
        self.ivy_subdivide_cb.stateChanged.connect(self._on_ivy_subdivide)
        resample_gl.addWidget(self.ivy_subdivide_cb)
        self.ivy_resample_len_sb = _make_spinbox(0.01, 1.0, 0.2, dec=3, step=0.01)
        self.ivy_resample_len_sl = _make_slider(0.01, 1.0, 0.2)
        self.ivy_resample_len_sb.setToolTip("Maximum segment length used when resampling ivy curves. Smaller values give smoother curves but more points.")
        _link_slider_spinbox(self.ivy_resample_len_sl, self.ivy_resample_len_sb, 0.01, 1.0, on_change=self._on_ivy_resample_length)
        self.ivy_resample_len_sb.valueChanged.connect(self._on_ivy_resample_length)
        _param_row("Resample Curve:", self.ivy_resample_len_sl, self.ivy_resample_len_sb, resample_gl)
        wire_scroll_lay.addWidget(resample_grp)

        noise_grp = _CollapsibleGroup("Noise")
        noise_gl = QVBoxLayout(noise_grp.body)
        NOISE_SPECS = [
            ("ivy_noise_amp",   "Amplitude",   0.0,  2.0,  0.163, 0.01, False),
            ("ivy_noise_freq",  "Frequency",   0.0, 10.0,  0.292, 0.05, False),
            ("ivy_noise_rough", "Roughness",   0.0,  1.0,  0.0, 0.05, False),
            ("ivy_noise_turb",  "Turbulence",  0,    8,    0,   1,    True),
        ]
        for n_key, n_label, n_mn, n_mx, n_def, n_step, n_is_int in NOISE_SPECS:
            if n_is_int:
                n_sb = _make_int_spinbox(int(n_mn), int(n_mx), int(n_def))
                n_sl = QSlider(Qt.Horizontal)
                n_sl.setRange(int(n_mn), int(n_mx))
                n_sl.setValue(int(n_def))
                n_sl.valueChanged.connect(lambda v, _sb=n_sb: (_sb.blockSignals(True), _sb.setValue(v), _sb.blockSignals(False), self._on_ivy_noise_changed()))
                n_sb.valueChanged.connect(lambda v, _sl=n_sl: (_sl.blockSignals(True), _sl.setValue(int(v)), _sl.blockSignals(False)))
            else:
                n_sb = _make_spinbox(n_mn, n_mx, n_def, dec=3, step=n_step)
                n_sl = _make_slider(n_mn, n_mx, n_def)
                _link_slider_spinbox(n_sl, n_sb, n_mn, n_mx, on_change=self._on_ivy_noise_changed)
            n_sb.valueChanged.connect(self._on_ivy_noise_changed)
            _param_row(n_label + ":", n_sl, n_sb, noise_gl)
            self._ivy_noise_widgets[n_key] = n_sb
            self._ivy_noise_sliders[n_key] = n_sl
        wire_scroll_lay.addWidget(noise_grp)

        wire_scroll_lay.addStretch()

        _ivy_teal_style = (
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
            "QPushButton:checked { background-color: #0e2030; color: #4a9ab8; border-color: #1e4060; }"
            "QPushButton:checked:hover { background-color: #162838; border-color: #2a6080; }"
        )

        self.ivy_wire_toggle_btn = QPushButton("Disable Ivy Wire")
        self.ivy_wire_toggle_btn.setCheckable(True)
        self.ivy_wire_toggle_btn.setMinimumHeight(30)
        self.ivy_wire_toggle_btn.setStyleSheet(_ivy_teal_style)
        self.ivy_wire_toggle_btn.setToolTip("Bypass the PolyWire SOP — switches off the 3D tube geometry so only the curve is visible.")
        self.ivy_wire_toggle_btn.clicked.connect(self._on_ivy_wire_toggle)
        lay.addWidget(self.ivy_wire_toggle_btn)

        self.instancer_toggle_btn = QPushButton("Hide Assets ")
        self.instancer_toggle_btn.setCheckable(True)
        self.instancer_toggle_btn.setMinimumHeight(30)
        self.instancer_toggle_btn.setStyleSheet(_ivy_teal_style)
        self.instancer_toggle_btn.setToolTip("Bypass the instancer (CopyToPoints) SOP — hides the scattered leaf assets for faster viewport performance.")
        self.instancer_toggle_btn.clicked.connect(self._on_instancer_toggle)
        lay.addWidget(self.instancer_toggle_btn)

        self.ivy_edit_ramp_btn = QPushButton("✎  Edit Ramp")
        self.ivy_edit_ramp_btn.setMinimumHeight(36)
        self.ivy_edit_ramp_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        self.ivy_edit_ramp_btn.setToolTip("Select ivy_pscale_ramp so its Scale Ramp spare parameter appears in the Houdini parameter pane for editing.")
        self.ivy_edit_ramp_btn.clicked.connect(self._on_ivy_edit_ramp)
        lay.addWidget(self.ivy_edit_ramp_btn)

        return w

    def _build_output_bake_tab(self):
        """
        Tab for Baking and Cache settings.
        """
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 20, 8)
        lay.setSpacing(6)

        # 1. Ivy Wires Cache Settings
        wires_cache_grp = QGroupBox("Ivy Wires Cache Settings")
        wires_cv = QVBoxLayout(wires_cache_grp)
        wires_folder_row = QHBoxLayout()
        wires_folder_row.addWidget(QLabel("Folder:"))
        self.ivy_cache_folder_le = QLineEdit("$HIP/geo")
        self.ivy_cache_folder_le.setToolTip("Output folder for the ivy wires cache file. Supports Houdini variables like $HIP.")
        self.ivy_cache_folder_le.editingFinished.connect(self._on_ivy_cache_folder_changed)
        wires_folder_row.addWidget(self.ivy_cache_folder_le, 1)
        self.ivy_cache_browse_btn = QPushButton("…")
        self.ivy_cache_browse_btn.setFixedWidth(24)
        self.ivy_cache_browse_btn.setToolTip("Browse for the ivy wires cache folder.")
        self.ivy_cache_browse_btn.clicked.connect(self._on_ivy_cache_folder_browse)
        wires_folder_row.addWidget(self.ivy_cache_browse_btn)
        wires_cv.addLayout(wires_folder_row)
        wires_name_row = QHBoxLayout()
        wires_name_row.addWidget(QLabel("Name:"))
        self.ivy_cache_name_le = QLineEdit("$HIPNAME.$OS")
        self.ivy_cache_name_le.setToolTip("Base name for the ivy wires cache file. $HIPNAME = scene name, $OS = node name.")
        self.ivy_cache_name_le.editingFinished.connect(self._on_ivy_cache_name_changed)
        wires_name_row.addWidget(self.ivy_cache_name_le, 1)
        wires_cv.addLayout(wires_name_row)
        self.ivy_timedependent_cb = QCheckBox("Time Dependent Cache")
        self.ivy_timedependent_cb.setChecked(True)
        self.ivy_timedependent_cb.setToolTip("When checked, the wires cache writes a file per frame. Uncheck for a static cache.")
        self.ivy_timedependent_cb.toggled.connect(self._on_ivy_timedependent_changed)
        wires_cv.addWidget(self.ivy_timedependent_cb)
        wires_trange_row = QHBoxLayout()
        wires_trange_row.addWidget(QLabel("Evaluate As:"))
        self.ivy_cache_trange_cb = QComboBox()
        self.ivy_cache_trange_cb.addItems(["Single Frame", "Frame Range"])
        self.ivy_cache_trange_cb.setToolTip("Choose whether to cache a single frame or a full frame range.")
        self.ivy_cache_trange_cb.currentIndexChanged.connect(self._on_ivy_trange_changed)
        wires_trange_row.addWidget(self.ivy_cache_trange_cb, 1)
        wires_cv.addLayout(wires_trange_row)
        wires_range_row = QHBoxLayout()
        wires_range_row.addWidget(QLabel("Start:"))
        self.ivy_cache_start_sb = QSpinBox()
        self.ivy_cache_start_sb.setRange(-99999, 999999)
        self.ivy_cache_start_sb.setValue(1)
        self.ivy_cache_start_sb.setToolTip("First frame of the ivy wires cache range.")
        self.ivy_cache_start_sb.valueChanged.connect(self._on_ivy_cache_range_changed)
        wires_range_row.addWidget(self.ivy_cache_start_sb)
        wires_range_row.addWidget(QLabel("End:"))
        self.ivy_cache_end_sb = QSpinBox()
        self.ivy_cache_end_sb.setRange(-99999, 999999)
        self.ivy_cache_end_sb.setValue(50)
        self.ivy_cache_end_sb.setToolTip("Last frame of the ivy wires cache range.")
        self.ivy_cache_end_sb.valueChanged.connect(self._on_ivy_cache_range_changed)
        wires_range_row.addWidget(self.ivy_cache_end_sb)
        wires_range_row.addWidget(QLabel("Increment:"))
        self.ivy_cache_inc_sb = QSpinBox()
        self.ivy_cache_inc_sb.setRange(1, 100)
        self.ivy_cache_inc_sb.setValue(1)
        self.ivy_cache_inc_sb.setToolTip("Frame step increment for the wires cache.")
        self.ivy_cache_inc_sb.valueChanged.connect(self._on_ivy_cache_range_changed)
        wires_range_row.addWidget(self.ivy_cache_inc_sb)
        wires_cv.addLayout(wires_range_row)
        wires_sub_row = QHBoxLayout()
        wires_sub_row.addWidget(QLabel("Substeps:"))
        self.ivy_cache_substeps_sb = QSpinBox()
        self.ivy_cache_substeps_sb.setRange(1, 100)
        self.ivy_cache_substeps_sb.setValue(1)
        self.ivy_cache_substeps_sb.setToolTip("Number of sub-frame samples per frame for the wires cache.")
        self.ivy_cache_substeps_sb.valueChanged.connect(self._on_ivy_cache_range_changed)
        wires_sub_row.addWidget(self.ivy_cache_substeps_sb)
        wires_sub_row.addStretch()
        wires_cv.addLayout(wires_sub_row)
        lay.addWidget(wires_cache_grp)

        # 2. Ivy Leaves Cache Settings
        leaves_cache_grp = QGroupBox("Ivy Leaves Cache Settings")
        leaves_cv = QVBoxLayout(leaves_cache_grp)
        leaves_folder_row = QHBoxLayout()
        leaves_folder_row.addWidget(QLabel("Folder:"))
        self.ivy_leaves_cache_folder_le = QLineEdit("$HIP/geo")
        self.ivy_leaves_cache_folder_le.setToolTip("Output folder for the ivy leaves cache file. Supports Houdini variables like $HIP.")
        self.ivy_leaves_cache_folder_le.editingFinished.connect(self._on_ivy_leaves_cache_folder_changed)
        leaves_folder_row.addWidget(self.ivy_leaves_cache_folder_le, 1)
        self.ivy_leaves_cache_browse_btn = QPushButton("…")
        self.ivy_leaves_cache_browse_btn.setFixedWidth(24)
        self.ivy_leaves_cache_browse_btn.setToolTip("Browse for the ivy leaves cache folder.")
        self.ivy_leaves_cache_browse_btn.clicked.connect(self._on_ivy_leaves_cache_folder_browse)
        leaves_folder_row.addWidget(self.ivy_leaves_cache_browse_btn)
        leaves_cv.addLayout(leaves_folder_row)
        leaves_name_row = QHBoxLayout()
        leaves_name_row.addWidget(QLabel("Name:"))
        self.ivy_leaves_cache_name_le = QLineEdit("$HIPNAME.$OS")
        self.ivy_leaves_cache_name_le.setToolTip("Base name for the ivy leaves cache file. $HIPNAME = scene name, $OS = node name.")
        self.ivy_leaves_cache_name_le.editingFinished.connect(self._on_ivy_leaves_cache_name_changed)
        leaves_name_row.addWidget(self.ivy_leaves_cache_name_le, 1)
        leaves_cv.addLayout(leaves_name_row)
        self.ivy_leaves_timedependent_cb = QCheckBox("Time Dependent Cache")
        self.ivy_leaves_timedependent_cb.setChecked(True)
        self.ivy_leaves_timedependent_cb.setToolTip("When checked, the leaves cache writes a file per frame. Uncheck for a static cache.")
        self.ivy_leaves_timedependent_cb.toggled.connect(self._on_ivy_leaves_timedependent_changed)
        leaves_cv.addWidget(self.ivy_leaves_timedependent_cb)
        leaves_trange_row = QHBoxLayout()
        leaves_trange_row.addWidget(QLabel("Evaluate As:"))
        self.ivy_leaves_cache_trange_cb = QComboBox()
        self.ivy_leaves_cache_trange_cb.addItems(["Single Frame", "Frame Range"])
        self.ivy_leaves_cache_trange_cb.setToolTip("Choose whether to cache a single frame or a full frame range for ivy leaves.")
        self.ivy_leaves_cache_trange_cb.currentIndexChanged.connect(self._on_ivy_leaves_trange_changed)
        leaves_trange_row.addWidget(self.ivy_leaves_cache_trange_cb, 1)
        leaves_cv.addLayout(leaves_trange_row)
        leaves_range_row = QHBoxLayout()
        leaves_range_row.addWidget(QLabel("Start:"))
        self.ivy_leaves_cache_start_sb = QSpinBox()
        self.ivy_leaves_cache_start_sb.setRange(-99999, 999999)
        self.ivy_leaves_cache_start_sb.setValue(1)
        self.ivy_leaves_cache_start_sb.setToolTip("First frame of the ivy leaves cache range.")
        self.ivy_leaves_cache_start_sb.valueChanged.connect(self._on_ivy_leaves_cache_range_changed)
        leaves_range_row.addWidget(self.ivy_leaves_cache_start_sb)
        leaves_range_row.addWidget(QLabel("End:"))
        self.ivy_leaves_cache_end_sb = QSpinBox()
        self.ivy_leaves_cache_end_sb.setRange(-99999, 999999)
        self.ivy_leaves_cache_end_sb.setValue(50)
        self.ivy_leaves_cache_end_sb.setToolTip("Last frame of the ivy leaves cache range.")
        self.ivy_leaves_cache_end_sb.valueChanged.connect(self._on_ivy_leaves_cache_range_changed)
        leaves_range_row.addWidget(self.ivy_leaves_cache_end_sb)
        leaves_range_row.addWidget(QLabel("Increment:"))
        self.ivy_leaves_cache_inc_sb = QSpinBox()
        self.ivy_leaves_cache_inc_sb.setRange(1, 100)
        self.ivy_leaves_cache_inc_sb.setValue(1)
        self.ivy_leaves_cache_inc_sb.setToolTip("Frame step increment for the leaves cache.")
        self.ivy_leaves_cache_inc_sb.valueChanged.connect(self._on_ivy_leaves_cache_range_changed)
        leaves_range_row.addWidget(self.ivy_leaves_cache_inc_sb)
        leaves_cv.addLayout(leaves_range_row)
        leaves_sub_row = QHBoxLayout()
        leaves_sub_row.addWidget(QLabel("Substeps:"))
        self.ivy_leaves_cache_substeps_sb = QSpinBox()
        self.ivy_leaves_cache_substeps_sb.setRange(1, 100)
        self.ivy_leaves_cache_substeps_sb.setValue(1)
        self.ivy_leaves_cache_substeps_sb.setToolTip("Number of sub-frame samples per frame for the leaves cache.")
        self.ivy_leaves_cache_substeps_sb.valueChanged.connect(self._on_ivy_leaves_cache_range_changed)
        leaves_sub_row.addWidget(self.ivy_leaves_cache_substeps_sb)
        leaves_sub_row.addStretch()
        leaves_cv.addLayout(leaves_sub_row)
        lay.addWidget(leaves_cache_grp)

        # 3. Ivy Baking Section (moved under cache settings)
        bake_grp = QGroupBox("Ivy Baking")
        bl = QVBoxLayout(bake_grp)
        self.ivy_bake_btn = QPushButton("💾 Bake Geometry ")
        self.ivy_bake_btn.setMinimumHeight(40)
        self.ivy_bake_btn.setStyleSheet("QPushButton { background:#2c5a8c; color:#e8f2ff; font-weight:bold; padding: 0 10px; }")
        self.ivy_bake_btn.setToolTip("Write the ivy wires and leaves geometry to disk using the cache settings above, then enable Load from Disk.")
        self.ivy_bake_btn.clicked.connect(self._on_ivy_bake)

        _lfd_style = "QCheckBox { font-weight: bold; color: #7ec8e3; font-size: 11px; }"
        self.ivy_loadfromdisk_cb = QCheckBox("Wires: Load from Disk")
        self.ivy_loadfromdisk_cb.setToolTip("When checked, the ivy wires network reads the cached file from disk instead of recomputing.")
        self.ivy_loadfromdisk_cb.setStyleSheet(_lfd_style)
        self.ivy_loadfromdisk_cb.toggled.connect(self._on_ivy_loadfromdisk_changed)
        self.ivy_leaves_loadfromdisk_cb = QCheckBox("Leaves: Load from Disk")
        self.ivy_leaves_loadfromdisk_cb.setToolTip("When checked, the ivy leaves network reads the cached file from disk instead of recomputing.")
        self.ivy_leaves_loadfromdisk_cb.setStyleSheet(_lfd_style)
        self.ivy_leaves_loadfromdisk_cb.toggled.connect(self._on_ivy_leaves_loadfromdisk_changed)

        ivy_proxy_frame = QFrame()
        ivy_proxy_frame.setStyleSheet(
            "QFrame { background: #2e2200; border: 2px solid #c08000; border-radius: 5px; }"
        )
        ipf_lay = QVBoxLayout(ivy_proxy_frame)
        ipf_lay.setContentsMargins(10, 7, 10, 7)
        ipf_lay.setSpacing(5)
        self.ivy_pack_instance_cb = QCheckBox("  Pack and Instance  —  Uncheck this if you're using proxy assets")
        self.ivy_pack_instance_cb.setChecked(True)
        self.ivy_pack_instance_cb.setStyleSheet(
            "QCheckBox { font-weight: bold; color: #ffcc44; font-size: 12px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
        )
        self.ivy_pack_instance_cb.setToolTip(
            "Checked (default): Pack and Instance is ON — geometry is packed.\n"
            "Unchecked: Pack and Instance is OFF — required when using Proxy workflows."
        )
        self.ivy_pack_instance_cb.toggled.connect(self._on_ivy_pack_instance_changed)
        ipf_lay.addWidget(self.ivy_pack_instance_cb)
        ivy_disp_row = QHBoxLayout()
        ivy_disp_lbl = QLabel("Display As:")
        ivy_disp_lbl.setStyleSheet("color: #ffcc44; font-size: 11px;")
        ivy_disp_row.addWidget(ivy_disp_lbl)
        self.ivy_display_as_cb = QComboBox()
        self.ivy_display_as_cb.addItems(["Full Geometry", "Point Cloud", "Bounding Box", "Centroid", "Hidden"])
        self.ivy_display_as_cb.setCurrentText("Bounding Box")
        self.ivy_display_as_cb.setToolTip("Controls how packed instances appear in the viewport.")
        self.ivy_display_as_cb.currentTextChanged.connect(self._on_ivy_display_as_changed)
        ivy_disp_row.addWidget(self.ivy_display_as_cb)
        ivy_disp_row.addStretch()
        ipf_lay.addLayout(ivy_disp_row)
        bl.addWidget(ivy_proxy_frame)
        bl.addWidget(self.ivy_loadfromdisk_cb)
        bl.addWidget(self.ivy_leaves_loadfromdisk_cb)
        bl.addWidget(self.ivy_bake_btn)

        lay.addWidget(bake_grp)

        # ── Solaris ──────────────────────────────────────────────────────────
        ivy_solaris_grp = QGroupBox("Solaris")
        ivy_sl_lay = QVBoxLayout(ivy_solaris_grp)
        ivy_sl_lay.setContentsMargins(8, 10, 8, 8)
        self.ivy_include_wires_cb = QCheckBox("Include Wire Mesh")
        self.ivy_include_wires_cb.setChecked(True)
        self.ivy_include_wires_cb.setToolTip(
            "Export the wire mesh (crawl_OUT / OUT_wires) as a USD reference under "
            "/MSW/<system>/wires.  Leave unchecked to export only the scatter instances."
        )
        ivy_sl_lay.addWidget(self.ivy_include_wires_cb)
        ivy_send_solaris_btn = QPushButton("⬡  Send to Solaris")
        ivy_send_solaris_btn.setMinimumHeight(36)
        ivy_send_solaris_btn.setStyleSheet(
            "QPushButton { background-color:#1a4a5c; color:#a0e8ff; border:1px solid #2a7a9c; font-weight:bold; }"
            "QPushButton:hover { background-color:#1f5f78; border-color:#3ab0d8; }"
            "QPushButton:pressed { background-color:#0f2f3c; }"
        )
        ivy_send_solaris_btn.setToolTip(
            "Create a USD PointInstancer LOP network in /stage for this ivy scatter."
        )
        ivy_send_solaris_btn.clicked.connect(self._on_send_to_solaris)
        ivy_sl_lay.addWidget(ivy_send_solaris_btn)

        # ── Lookdev ───────────────────────────────────────────────────────────
        ivy_ld_grp = QGroupBox("Lookdev")
        ivy_ld_lay = QVBoxLayout(ivy_ld_grp)
        ivy_ld_lay.setContentsMargins(8, 10, 8, 8)
        ivy_lookdev_btn = QPushButton("Lookdev")
        ivy_lookdev_btn.setMinimumHeight(36)
        ivy_lookdev_btn.setToolTip(
            "Open the Lookdev window — build PBR shaders for your ivy assets\n"
            "in Arnold or Redshift, with textures and live parameter tweaks."
        )
        ivy_lookdev_btn.setStyleSheet(
            "QPushButton { background-color:#3a1a5c; color:#d0b0ff; border-color:#5f2b8b; }"
            "QPushButton:hover { background-color:#4f2480; border-color:#8f3cc8; }"
            "QPushButton:pressed { background-color:#241038; }"
        )
        ivy_lookdev_btn.clicked.connect(self._open_lookdev)
        ivy_ld_lay.addWidget(ivy_lookdev_btn)
        lay.addWidget(ivy_ld_grp)
        lay.addWidget(ivy_solaris_grp)

        lay.addStretch()
        scroll.setWidget(w)
        outer_lay.addWidget(scroll, 1)
        return outer

    # ── ivy actions ───────────────────────────────────────────────────────

    def _apply_ivy_preset(self, vals):
        """Apply a preset dict to the ivy spinboxes then sync once."""
        self._prevent_sync = True
        try:
            for name, val in vals.items():
                sb = self._ivy_widgets.get(name)
                if sb is None:
                    continue
                sb.blockSignals(True)
                sb.setValue(val)
                sb.blockSignals(False)
        finally:
            self._prevent_sync = False
        # Always push preset values to the node, regardless of rt_cb state
        self._push_ivy_params(cook=True)

    # ── preset persistence ────────────────────────────────────────────────

    def _load_user_presets(self):
        """Load user-saved ivy presets from disk. Returns {} on first run / errors."""
        path = _ivy_user_presets_path()
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}
        except Exception as e:
            print(f"[Magic Scatter World] Failed to load user ivy presets: {e}")
        return {}

    def _save_user_presets(self):
        """Persist user presets dict to JSON."""
        path = _ivy_user_presets_path()
        try:
            with open(path, "w") as f:
                json.dump(self._user_presets, f, indent=2)
        except Exception as e:
            print(f"[Magic Scatter World] Failed to save user ivy presets: {e}")
            self.ivy_status_l.setText(f"Preset save error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _refresh_preset_combo(self, select_name=None):
        """Rebuild the preset combo with built-in + user presets."""
        cb = self.ivy_preset_cb
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("— Select preset —")
        if IVY_PRESETS:
            for name in IVY_PRESETS.keys():
                cb.addItem(name)
        if self._user_presets:
            for name in sorted(self._user_presets.keys()):
                cb.addItem(name)
        if select_name:
            idx = cb.findText(select_name)
            if idx >= 0:
                cb.setCurrentIndex(idx)
        else:
            cb.setCurrentIndex(0)
        cb.blockSignals(False)

    def _on_ivy_preset_selected(self, index):
        """Apply the chosen preset (skip the placeholder at index 0)."""
        if index <= 0:
            return
        name = self.ivy_preset_cb.itemText(index)
        vals = IVY_PRESETS.get(name) or self._user_presets.get(name)
        if not vals:
            return
        self._apply_ivy_preset(vals)
        self.ivy_status_l.setText(f"Applied preset '{name}'.")
        self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")

    def _on_ivy_preset_save(self):
        """Prompt for a name, then snapshot current ivy spinbox values into a user preset."""
        name, ok = QInputDialog.getText(
            self, "Save Ivy Preset", "Preset name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            self.ivy_status_l.setText("Preset name cannot be empty.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        if name in IVY_PRESETS:
            QMessageBox.warning(
                self, "Reserved name",
                f"'{name}' is a built-in preset name. Choose a different name.")
            return
        if name in self._user_presets:
            reply = QMessageBox.question(
                self, "Overwrite preset?",
                f"A preset named '{name}' already exists. Overwrite it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        # Snapshot current ivy spinbox values
        vals = {}
        for parm_name, sb in self._ivy_widgets.items():
            try:
                vals[parm_name] = sb.value()
            except Exception:
                pass
        self._user_presets[name] = vals
        self._save_user_presets()
        self._refresh_preset_combo(select_name=name)
        self.ivy_status_l.setText(f"Saved preset '{name}'.")
        self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")

    def _on_ivy_preset_update(self):
        """Overwrite the currently selected user preset with current spinbox values."""
        idx = self.ivy_preset_cb.currentIndex()
        if idx <= 0:
            self.ivy_status_l.setText("Select a user preset to update.")
            self.ivy_status_l.setStyleSheet("color:#e0b898; font-size:10px;")
            return
        name = self.ivy_preset_cb.itemText(idx)
        if name in IVY_PRESETS:
            QMessageBox.information(
                self, "Built-in preset",
                f"'{name}' is a built-in preset and cannot be updated. "
                "Use Save to create a new user preset instead.")
            return
        if name not in self._user_presets:
            return
        vals = {}
        for parm_name, sb in self._ivy_widgets.items():
            try:
                vals[parm_name] = sb.value()
            except Exception:
                pass
        self._user_presets[name] = vals
        self._save_user_presets()
        self.ivy_status_l.setText(f"Updated preset '{name}'.")
        self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")

    def _on_ivy_preset_delete(self):
        """Delete the currently selected user preset (built-ins are protected)."""
        idx = self.ivy_preset_cb.currentIndex()
        if idx <= 0:
            self.ivy_status_l.setText("Select a user preset to delete.")
            self.ivy_status_l.setStyleSheet("color:#e0b898; font-size:10px;")
            return
        name = self.ivy_preset_cb.itemText(idx)
        if name in IVY_PRESETS:
            QMessageBox.information(
                self, "Built-in preset",
                f"'{name}' is a built-in preset and cannot be deleted.")
            return
        if name not in self._user_presets:
            return
        reply = QMessageBox.question(
            self, "Delete preset?",
            f"Delete preset '{name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        del self._user_presets[name]
        self._save_user_presets()
        self._refresh_preset_combo()
        self.ivy_status_l.setText(f"Deleted preset '{name}'.")
        self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")

    def _find_ivy_sop(self):
        """
        Locate the ivy_curve_gen Python SOP robustly, without requiring
        self.geo_node to already be set.  Searches in priority order:

          1. self.geo_node   (already tracked — zero cost)
          2. self.scatter_sop_node.parent()  (derive from tracked scatter SOP)
          3. Full scene scan via logic.get_scatter_nodes()

        Updates self.geo_node as a side-effect when found via paths 2 or 3,
        so subsequent calls take the fast path.
        Returns the ivy_curve_gen SOP node, or None if not found.
        """
        # 1. Fast path: geo_node already tracked
        if self.geo_node is not None:
            try:
                sop = self.geo_node.node("ivy_curve_gen")
                if sop is not None:
                    return sop
            except Exception:
                self.geo_node = None   # stale reference — clear it

        # 2. Derive from the tracked scatter SOP
        if self.scatter_sop_node is not None:
            try:
                geo = self.scatter_sop_node.parent()
                if geo is not None:
                    sop = geo.node("ivy_curve_gen")
                    if sop is not None:
                        self.geo_node = geo
                        return sop
            except Exception:
                pass

        # 3. Walk every scatter geo node in the current hip file
        try:
            for geo_node, _ in logic.get_scatter_nodes():
                sop = geo_node.node("ivy_curve_gen")
                if sop is not None:
                    self.geo_node = geo_node
                    return sop
        except Exception:
            pass

        return None

    @debounce(100)
    def _sync_ivy_rt(self, *_):
        """
        Called by every ivy widget signal.
        Finds the ivy_curve_gen SOP (via _find_ivy_sop) and pushes all
        current widget values to it, then force-cooks.
        Does NOT touch the scatter network at all.
        """
        if self._prevent_sync:
            return
        if not getattr(self, "ivy_rt_cb", None):
            return
        if self.ivy_rt_cb.isChecked():
            self._push_ivy_params(cook=True)

    def _push_ivy_params(self, cook=True):
        """
        Read all ivy spinbox values, write them to self.state, and push
        directly to the ivy_curve_gen SOP's spare parameters and to the
        ivy_wire SOP's native parms.

        cook=True  → force-cooks ivy_curve_gen immediately (real-time path).
        cook=False → sets parms only, no cook (batch / preset path).

        Uses _find_ivy_sop() so geo_node does not need to be pre-set —
        the binding works even when the session is resumed after a hip reload.
        """
        ivy_sop = self._find_ivy_sop()
        if ivy_sop is None:
            return                          # no ivy network in scene yet

        ivy_state = {}
        for name in IVY_DEFAULTS:
            sb = self._ivy_widgets.get(name)
            if sb is not None:
                val = sb.value()
                self.state[name] = val
                ivy_state[name] = val

        # Push each parm directly onto the ivy_curve_gen spare parameter
        for name, val in ivy_state.items():
            p = ivy_sop.parm(name)
            if p is not None:
                try:
                    p.set(val)
                except Exception as e:
                    logic.log(f"ivy parm set error ({name}): {e}")

        # Push wire appearance parms onto ivy_wire SOP
        geo_node = ivy_sop.parent()
        if geo_node is not None:
            logic._sync_ivy_wire_parms(geo_node, ivy_state)

        if cook:
            try:
                ivy_sop.cook(force=True)
            except Exception as e:
                logic.log(f"ivy cook error: {e}")

    def _on_ivy_create(self):
        if self.geo_node is None:
            hou.ui.displayMessage(
                "Create a scatter network first (use 'Create Network').",
                severity=hou.severityType.Warning)
            return
        try:
            if logic.ivy_network_exists(self.geo_node):
                self.ivy_status_l.setText("Ivy network already exists — use Regenerate.")
                return
            logic.create_ivy_network(self.geo_node)
            logic.heal_orient_wrangle(self.geo_node)
            ivy_state = {k: self.state[k] for k in IVY_DEFAULTS}
            logic.sync_ivy_params(self.geo_node, ivy_state)
            logic.sync_ivy_orient(
                self.geo_node,
                self.state.get("rot_min",       0.0),
                self.state.get("rot_max",       1.0),
                self.state.get("full_rand",     False),
                self.state.get("rot_randomize", 1.0),
            )
            self._refresh_ivy_cache_widgets()
            self.ivy_status_l.setText(
                f"Ivy network created in {self.geo_node.name()}.")
            self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Ivy create error: {e}")

    def _on_ivy_regen(self):
        """Manual regenerate — always pushes and cooks regardless of rt_cb."""
        if self.geo_node is None:
            hou.ui.displayMessage(
                "No active scatter network.", severity=hou.severityType.Warning)
            return
        if not logic.ivy_network_exists(self.geo_node):
            self.ivy_status_l.setText("No ivy network found — click Create first.")
            return
        try:
            logic.heal_orient_wrangle(self.geo_node)
            self._push_ivy_params(cook=True)
            self.ivy_status_l.setText("Ivy regenerated.")
            self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Ivy regen error: {e}")

    def _on_ivy_subdivide(self, *_):
        """Checkbox toggle → ivy_resample.treatpolysas (1 checked / 0 unchecked)."""
        if self.geo_node is None:
            return
        resample = self.geo_node.node("ivy_resample")
        if resample is None:
            self.ivy_status_l.setText("No ivy_resample — create ivy network first.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        p = resample.parm("treatpolysas")
        if p is None:
            self.ivy_status_l.setText("ivy_resample has no 'treatpolysas' parm.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        try:
            p.set(1 if self.ivy_subdivide_cb.isChecked() else 0)
            logic.cook_ivy(self.geo_node)
        except Exception as e:
            self.ivy_status_l.setText(f"Subdivide error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] subdivide error: {e}")

    def _on_ivy_resample_length(self, *_):
        """Resample Curve spinbox/slider → ivy_resample.length."""
        if self.geo_node is None:
            return
        resample = self.geo_node.node("ivy_resample")
        if resample is None:
            return
        p = resample.parm("length")
        if p is None:
            return
        try:
            p.set(float(self.ivy_resample_len_sb.value()))
            logic.cook_ivy(self.geo_node)
        except Exception as e:
            print(f"[Magic Scatter World] resample length error: {e}")

    @debounce(100)
    def _on_ivy_noise_changed(self, *_):
        """Push all noise widget values to the ivy_attribnoise SOP and recook."""
        if self.geo_node is None:
            return
        # Collect widget values (noise widgets live in self._ivy_noise_widgets)
        widgets = getattr(self, "_ivy_noise_widgets", None)
        if not widgets:
            return
        noise_state = {k: sb.value() for k, sb in widgets.items()}
        try:
            logic.sync_ivy_noise_parms(self.geo_node, noise_state)
            logic.cook_ivy(self.geo_node)
        except Exception as e:
            print(f"[Magic Scatter World] ivy noise sync error: {e}")

    def _on_ivy_remove(self):
        if self.geo_node is None:
            return
        if not logic.ivy_network_exists(self.geo_node):
            self.ivy_status_l.setText("No ivy network to remove.")
            return
        if not hou.ui.displayConfirmation("Delete the ivy network from this geo node?"):
            return
        try:
            # Restore scatter_logic (was bypassed when ivy was created)
            scatter_logic = self.geo_node.node("scatter_logic")
            if scatter_logic is not None:
                scatter_logic.bypass(False)

            # Restore pscale_wrangle → scatter_logic (was rewired through ivy_blast)
            pscale_wr = self.geo_node.node("pscale_wrangle")
            if pscale_wr is not None and scatter_logic is not None:
                pscale_wr.setInput(0, scatter_logic)

            # Restore OUT_scatter → instancer (before destroying ivy_scatter_merge)
            out = self.geo_node.node("OUT_wires") or self.geo_node.node("OUT_scatter")
            instancer = self.geo_node.node("instancer")
            if out is not None and instancer is not None:
                out.setInput(0, instancer)
                if out.name() == "OUT_wires":
                    out.setName("OUT_scatter")

            # Tear down the Vellum sim chain first so input reconnection is clean
            logic.remove_ivy_sim_network(self.geo_node)

            # Destroy all ivy nodes
            for name in ("ivy_wires_filecache", "ivy_filecache", "ivy_scatter_merge", 
                         "ivy_wire", "ivy_attribnoise", "ivy_resample", 
                         "ivy_attr_randomise", "ivy_blast", "ivy_sim_length_scale", 
                         "ivy_curve_gen", "orient_wrangle", "ivy_pscale_ramp", "OUT_leaves"):
                n = self.geo_node.node(name)
                if n:
                    n.destroy()

            # Rename scatter_leaves back to scatter_filecache
            sl = self.geo_node.node("scatter_leaves")
            if sl:
                sl.setName("scatter_filecache")

            # Remove trunk_grp / leaves_grp only if crawl network isn't using them
            if not logic.crawl_ivy_network_exists(self.geo_node):
                for name in ("trunk_grp", "leaves_grp"):
                    n = self.geo_node.node(name)
                    if n:
                        try:
                            n.destroy()
                        except Exception:
                            pass

            self.geo_node.layoutChildren()
            self.ivy_status_l.setText("Ivy network removed.")
            self.ivy_status_l.setStyleSheet("color:#888; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Error: {e}")
            print(f"[Magic Scatter World] Ivy remove error: {e}")

    # ── crawling ivy (surface-creeping system) ────────────────────────────

    # (name, label, default, min, max, step, decimals, is_int) for spinboxes
    _CRAWL_SPINBOX_SPECS = [
        # Seeds & length
        ("crawl_n_seeds",        "Seed Count",        60,    1,     5000,  1,    0, True),
        ("crawl_seed",           "Random Seed",        7,    0,     99999, 1,    0, True),
        ("crawl_strand_length",  "Strand Length",     8.0,   0.1,   500.0, 0.5,  2, False),
        ("crawl_min_strands",    "Min Strand Length", 0.3,   0.0,   50.0,  0.1,  2, False),
        ("crawl_step_size",      "Step Size",         0.1,   0.005, 5.0,   0.01, 3, False),
        # Surface response
        ("crawl_adherence",      "Adherence Radius",  0.25,  0.001, 10.0,  0.01, 3, False),
        ("crawl_gravity",        "Gravity Drop",      0.5,   0.0,   5.0,   0.05, 2, False),
        ("crawl_upward_bias",    "Upward Bias",       0.6,   0.0,   1.0,   0.05, 2, False),
        # Controller (paper §4)
        ("crawl_lag",            "Lag (steps)",        6,    0,     200,   1,    0, True),
        ("crawl_gain",           "Adjustment Gain",   0.25,  0.0,   1.5,   0.05, 2, False),
        ("crawl_noise",          "Sensor Noise",      0.05,  0.0,   1.0,   0.01, 3, False),
        # Branching
        ("crawl_branch_prob",    "Branch Probability",0.015, 0.0,   0.5,   0.005,3, False),
        ("crawl_branch_angle",   "Branch Angle",     45.0,   0.0,   179.0, 1.0,  1, False),
        ("crawl_max_depth",      "Max Branch Depth",   3,    0,     10,    1,    0, True),
        # Wire appearance
        ("crawl_wire_radius",    "Wire Radius",      0.02,   0.001, 1.0,   0.001,3, False),
        ("crawl_wire_segs",      "Wire Segments",      1,    1,     32,    1,    0, True),
        ("crawl_wire_divisions", "Wire Divisions",     5,    1,     32,    1,    0, True),
    ]

    _CRAWL_GROUPS = [
        ("Seeds & Length",  ["crawl_n_seeds", "crawl_seed", "crawl_strand_length",
                             "crawl_min_strands", "crawl_step_size"]),
        ("Surface Response",["crawl_adherence", "crawl_gravity", "crawl_upward_bias"]),
        ("Growth Controller (§4 of paper)",
                            ["crawl_lag", "crawl_gain", "crawl_noise"]),
        ("Branching",       ["crawl_branch_prob", "crawl_branch_angle", "crawl_max_depth"]),
        ("Wire Appearance", ["crawl_wire_radius", "crawl_wire_segs", "crawl_wire_divisions"]),
    ]

    # ── CY (Crawling Ivy tool) tab builders ───────────────────────────────────

    def _build_cy_appearance_tab(self):
        """Appearance tab for CY mode: crawl wire parameters + display toggles."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        wire_grp = _CollapsibleGroup("Wire Appearance")
        grid = QGridLayout(wire_grp.body)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        spec_by_name = {s[0]: s for s in self._CRAWL_SPINBOX_SPECS}
        for row, name in enumerate(["crawl_wire_radius", "crawl_wire_segs", "crawl_wire_divisions"]):
            _, label, default, mn, mx, step, decimals, is_int = spec_by_name[name]
            grid.addWidget(QLabel(label), row, 0)
            slider_lay = QHBoxLayout()
            slider = QSlider(Qt.Horizontal)
            if name == "crawl_wire_radius":
                slider.setRange(int(mn * 1000), int(mx * 1000))
                slider.setSingleStep(max(1, int(step * 1000)))
                slider.setValue(min(int(default * 1000), int(mx * 1000)))
                sb = QDoubleSpinBox()
                sb.setRange(mn, 99999.0)
                sb.setSingleStep(step)
                sb.setDecimals(decimals)
                sb.setFixedWidth(64)
                sb.setValue(default)
                _sl_min, _sl_max = int(mn * 1000), int(mx * 1000)
                slider.valueChanged.connect(
                    lambda val, n=name: self._on_crawl_value_changed(n, val / 1000.0))
                slider.valueChanged.connect(
                    lambda val, s=sb: (s.blockSignals(True), s.setValue(val / 1000.0), s.blockSignals(False)))
                sb.valueChanged.connect(
                    lambda val, n=name: self._on_crawl_value_changed(n, val))
                sb.valueChanged.connect(
                    lambda val, sl=slider, lo=_sl_min, hi=_sl_max: (
                        sl.blockSignals(True),
                        sl.setValue(max(lo, min(hi, int(val * 1000)))),
                        sl.blockSignals(False)))
                slider_lay.addWidget(slider)
                slider_lay.addWidget(sb)
                self._crawl_widgets[name] = sb
            else:
                slider.setRange(int(mn), int(mx))
                slider.setSingleStep(int(step))
                slider.setValue(int(default))
                slider.valueChanged.connect(
                    lambda val, n=name: self._on_crawl_value_changed(n, val))
                val_lbl = QLabel(str(int(default)))
                val_lbl.setFixedWidth(40)
                slider.valueChanged.connect(lambda val, vl=val_lbl: vl.setText(str(val)))
                slider_lay.addWidget(slider)
                slider_lay.addWidget(val_lbl)
                self._crawl_widgets[name] = slider
            grid.addLayout(slider_lay, row, 1)
        lay.addWidget(wire_grp)

        resample_grp = _CollapsibleGroup("Resample")
        res_lay = QVBoxLayout(resample_grp.body)
        res_lay.setContentsMargins(8, 4, 8, 4)
        self.crawl_resample_len_sb = _make_spinbox(0.001, 2.0, 0.05, dec=3, step=0.005)
        self.crawl_resample_len_sb.setToolTip(
            "Segment length used when resampling crawl curves before PolyWire. "
            "Smaller values give smoother wires but more geometry.")
        self.crawl_resample_len_sl = _make_slider(0.001, 2.0, 0.05)
        _link_slider_spinbox(self.crawl_resample_len_sl, self.crawl_resample_len_sb,
                             0.001, 2.0, on_change=self._on_crawl_resample_length_changed)
        self.crawl_resample_len_sb.valueChanged.connect(self._on_crawl_resample_length_changed)
        _param_row("Resample Length:", self.crawl_resample_len_sl, self.crawl_resample_len_sb, res_lay)
        lay.addWidget(resample_grp)

        lay.addStretch()

        _cy_teal_style = (
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
            "QPushButton:checked { background-color: #0e2030; color: #4a9ab8; border-color: #1e4060; }"
            "QPushButton:checked:hover { background-color: #162838; border-color: #2a6080; }"
        )

        self.crawl_wire_toggle_btn = QPushButton("Disable Crawl Wire")
        self.crawl_wire_toggle_btn.setCheckable(True)
        self.crawl_wire_toggle_btn.setMinimumHeight(30)
        self.crawl_wire_toggle_btn.setStyleSheet(_cy_teal_style)
        self.crawl_wire_toggle_btn.setToolTip(
            "Bypass / un-bypass crawl_wire (PolyWire).")
        self.crawl_wire_toggle_btn.clicked.connect(self._on_crawl_wire_toggle)
        lay.addWidget(self.crawl_wire_toggle_btn)

        self.crawl_show_geo_btn = QPushButton("Hide Assets")
        self.crawl_show_geo_btn.setCheckable(True)
        self.crawl_show_geo_btn.setMinimumHeight(30)
        self.crawl_show_geo_btn.setStyleSheet(_cy_teal_style)
        self.crawl_show_geo_btn.setToolTip(
            "Bypass / un-bypass the instancer (CopyToPoints) SOP.")
        self.crawl_show_geo_btn.clicked.connect(self._on_crawl_instancer_toggle)
        lay.addWidget(self.crawl_show_geo_btn)

        self.crawl_edit_ramp_btn = QPushButton("✎  Edit Ramp")
        self.crawl_edit_ramp_btn.setMinimumHeight(36)
        self.crawl_edit_ramp_btn.setStyleSheet(
            "QPushButton { background-color: #1a3a4a; color: #7ac8e0; border-color: #2a5a70; }"
            "QPushButton:hover { background-color: #224a5a; border-color: #4a90b0; }"
            "QPushButton:pressed { background-color: #102030; }"
        )
        self.crawl_edit_ramp_btn.setToolTip(
            "Select crawl_pscale_ramp so its Scale Ramp spare parms appear in the Houdini parameter pane.")
        self.crawl_edit_ramp_btn.clicked.connect(self._on_crawl_edit_ramp)
        lay.addWidget(self.crawl_edit_ramp_btn)

        return w

    def _build_cy_crawl_tab(self):
        """Crawling Ivy parameters tab for CY mode (no wire appearance, no bake/cache)."""
        outer = QWidget()
        v = QVBoxLayout(outer)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        spec_by_name = {s[0]: s for s in self._CRAWL_SPINBOX_SPECS}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(2, 2, 2, 2)
        body_lay.setSpacing(6)

        cy_groups = [g for g in self._CRAWL_GROUPS if g[0] != "Wire Appearance"]
        for group_label, names in cy_groups:
            grp = _CollapsibleGroup(group_label)
            grid = QGridLayout(grp.body)
            grid.setContentsMargins(8, 4, 8, 4)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(4)
            for row, name in enumerate(names):
                _, label, default, mn, mx, step, decimals, is_int = spec_by_name[name]
                lbl = QLabel(label)
                lbl.setMinimumWidth(140)
                grid.addWidget(lbl, row, 0)
                if is_int:
                    sb = QSpinBox()
                    sb.setRange(int(mn), int(mx))
                    sb.setSingleStep(int(step))
                    sb.setValue(int(default))
                    sb.valueChanged.connect(
                        lambda val, n=name: self._on_crawl_value_changed(n, val))
                    self._crawl_widgets[name] = sb
                    grid.addWidget(sb, row, 1)
                else:
                    sb = QDoubleSpinBox()
                    sb.setRange(float(mn), float(mx))
                    sb.setSingleStep(float(step))
                    sb.setDecimals(int(decimals))
                    sb.setValue(float(default))
                    sb.valueChanged.connect(
                        lambda val, n=name: self._on_crawl_value_changed(n, val))
                    self._crawl_widgets[name] = sb
                    grid.addWidget(sb, row, 1)
            body_lay.addWidget(grp)

        body_lay.addStretch()
        scroll.setWidget(body)
        v.addWidget(scroll, 1)

        # Presets
        self._crawl_user_presets = self._load_crawl_user_presets()
        preset_grp = _CollapsibleGroup("Presets")
        pr_outer = QVBoxLayout(preset_grp.body)
        pr_outer.setContentsMargins(2, 2, 2, 2)
        pr_outer.setSpacing(4)
        pr_row = QHBoxLayout()
        pr_row.setSpacing(4)
        self.crawl_preset_cb = QComboBox()
        self.crawl_preset_cb.setToolTip("Select a Crawling Ivy preset to apply")
        self._refresh_crawl_preset_combo()
        self.crawl_preset_cb.activated.connect(self._on_crawl_preset_selected)
        pr_row.addWidget(self.crawl_preset_cb, 1)
        self.crawl_preset_save_btn = QPushButton("Save")
        self.crawl_preset_save_btn.clicked.connect(self._on_crawl_preset_save)
        pr_row.addWidget(self.crawl_preset_save_btn)
        self.crawl_preset_update_btn = QPushButton("Update")
        self.crawl_preset_update_btn.clicked.connect(self._on_crawl_preset_update)
        pr_row.addWidget(self.crawl_preset_update_btn)
        self.crawl_preset_delete_btn = QPushButton("Delete")
        self.crawl_preset_delete_btn.clicked.connect(self._on_crawl_preset_delete)
        pr_row.addWidget(self.crawl_preset_delete_btn)
        pr_outer.addLayout(pr_row)
        v.addWidget(preset_grp)

        # Action buttons
        self.crawl_create_btn = QPushButton("🌿  Create Crawling Ivy")
        self.crawl_create_btn.setMinimumHeight(32)
        self.crawl_create_btn.setToolTip(
            "Build the crawl_* SOP chain inside the geo node.")
        self.crawl_create_btn.clicked.connect(self._on_crawl_create)
        v.addWidget(self.crawl_create_btn)

        self.crawl_regen_btn = QPushButton("⟳  Regenerate")
        self.crawl_regen_btn.setMinimumHeight(28)
        self.crawl_regen_btn.setToolTip("Apply parameter changes and recook the network")
        self.crawl_regen_btn.clicked.connect(self._on_crawl_regen)
        v.addWidget(self.crawl_regen_btn)

        self.crawl_remove_btn = QPushButton("✕  Remove Crawling Ivy")
        self.crawl_remove_btn.setMinimumHeight(28)
        self.crawl_remove_btn.setStyleSheet(
            "QPushButton { color:#ff6060; } QPushButton:hover { background:#5a1a1a; }")
        self.crawl_remove_btn.setToolTip("Delete every crawl_* node from this geo node")
        self.crawl_remove_btn.clicked.connect(self._on_crawl_remove)
        v.addWidget(self.crawl_remove_btn)

        # Real-time + status footer
        rt_row = QHBoxLayout()
        self.crawl_rt_cb = QCheckBox("Real-time update")
        self.crawl_rt_cb.setChecked(True)
        self.crawl_rt_cb.setToolTip(
            "When checked, parameter changes recook the network in real-time.")
        rt_row.addWidget(self.crawl_rt_cb)
        rt_row.addStretch()
        v.addLayout(rt_row)

        self.crawl_status_l = QLabel("No crawling ivy network.")
        self.crawl_status_l.setStyleSheet("color:#888; font-size:10px; padding:2px;")
        self.crawl_status_l.setWordWrap(True)
        v.addWidget(self.crawl_status_l)

        return outer

    def _build_cy_output_bake_tab(self):
        """Output/Bake tab for CY mode: bake, pack instance, curves cache, leaves cache, shared settings."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.crawl_bake_btn = QPushButton("💾  Bake Geometry ")
        self.crawl_bake_btn.setMinimumHeight(40)
        self.crawl_bake_btn.setStyleSheet(
            "QPushButton { background:#2c5a8c; color:#e8f2ff; font-weight:bold; }"
            "QPushButton:hover { background:#3870a8; }")
        self.crawl_bake_btn.setToolTip(
            "Save crawling ivy curves and leaves to disk, "
            "then switch both caches to Load-from-Disk.")
        self.crawl_bake_btn.clicked.connect(self._on_crawl_bake)

        crawl_proxy_frame = QFrame()
        crawl_proxy_frame.setStyleSheet(
            "QFrame { background: #2e2200; border: 2px solid #c08000; border-radius: 5px; }")
        cpf_lay = QVBoxLayout(crawl_proxy_frame)
        cpf_lay.setContentsMargins(10, 7, 10, 7)
        cpf_lay.setSpacing(5)
        self.crawl_pack_instance_cb = QCheckBox("  Pack and Instance  —  Uncheck this if you're using proxy assets")
        self.crawl_pack_instance_cb.setChecked(True)
        self.crawl_pack_instance_cb.setStyleSheet(
            "QCheckBox { font-weight: bold; color: #ffcc44; font-size: 12px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }")
        self.crawl_pack_instance_cb.setToolTip(
            "Checked (default): Pack and Instance is ON — geometry is packed.\n"
            "Unchecked: Pack and Instance is OFF — required when using Proxy workflows.")
        self.crawl_pack_instance_cb.toggled.connect(self._on_crawl_pack_instance_changed)
        cpf_lay.addWidget(self.crawl_pack_instance_cb)
        crawl_disp_row1 = QHBoxLayout()
        crawl_disp_lbl1 = QLabel("Display As:")
        crawl_disp_lbl1.setStyleSheet("color: #ffcc44; font-size: 11px;")
        crawl_disp_row1.addWidget(crawl_disp_lbl1)
        self.crawl_display_as_cb = QComboBox()
        self.crawl_display_as_cb.addItems(["Full Geometry", "Point Cloud", "Bounding Box", "Centroid", "Hidden"])
        self.crawl_display_as_cb.setCurrentText("Bounding Box")
        self.crawl_display_as_cb.setToolTip("Controls how packed instances appear in the viewport.")
        self.crawl_display_as_cb.currentTextChanged.connect(self._on_crawl_display_as_changed)
        crawl_disp_row1.addWidget(self.crawl_display_as_cb)
        crawl_disp_row1.addStretch()
        cpf_lay.addLayout(crawl_disp_row1)

        # ── Curves Cache (crawl_filecache) ─────────────────────────────
        curves_grp = QGroupBox("Curves Cache")
        curves_grp.setStyleSheet("QGroupBox { font-size:10px; color:#bbb; }")
        curves_v = QVBoxLayout(curves_grp)
        curves_v.setContentsMargins(6, 8, 6, 6)
        curves_v.setSpacing(4)

        folder_row = QHBoxLayout()
        folder_lbl = QLabel("Folder:")
        folder_lbl.setFixedWidth(50)
        folder_row.addWidget(folder_lbl)
        self.crawl_cache_folder_le = QLineEdit("$HIP/geo")
        self.crawl_cache_folder_le.setToolTip("Base folder for crawl_filecache (curves).")
        self.crawl_cache_folder_le.editingFinished.connect(self._on_crawl_cache_folder_changed)
        folder_row.addWidget(self.crawl_cache_folder_le, 1)
        self.crawl_cache_browse_btn = QPushButton("…")
        self.crawl_cache_browse_btn.setFixedWidth(24)
        self.crawl_cache_browse_btn.clicked.connect(self._on_crawl_cache_folder_browse)
        folder_row.addWidget(self.crawl_cache_browse_btn)
        curves_v.addLayout(folder_row)

        name_row = QHBoxLayout()
        name_lbl = QLabel("Name:")
        name_lbl.setFixedWidth(50)
        name_row.addWidget(name_lbl)
        self.crawl_cache_name_le = QLineEdit("$HIPNAME.crawl_curves")
        self.crawl_cache_name_le.setToolTip("Cache file basename for crawl_filecache (curves).")
        self.crawl_cache_name_le.editingFinished.connect(self._on_crawl_cache_name_changed)
        name_row.addWidget(self.crawl_cache_name_le, 1)
        curves_v.addLayout(name_row)

        self.crawl_loadfromdisk_cb = QCheckBox("Load from Disk")
        self.crawl_loadfromdisk_cb.setToolTip("Read curves from disk instead of re-running crawl_ivy_gen.")
        self.crawl_loadfromdisk_cb.setStyleSheet("QCheckBox { font-weight: bold; color: #7ec8e3; font-size: 11px; }")
        self.crawl_loadfromdisk_cb.toggled.connect(self._on_crawl_loadfromdisk_changed)
        curves_v.addWidget(self.crawl_loadfromdisk_cb)
        lay.addWidget(curves_grp)

        # ── Leaves Cache (crawl_leaves_filecache) ──────────────────────
        leaves_grp = QGroupBox("Leaves Cache")
        leaves_grp.setStyleSheet("QGroupBox { font-size:10px; color:#bbb; }")
        leaves_v = QVBoxLayout(leaves_grp)
        leaves_v.setContentsMargins(6, 8, 6, 6)
        leaves_v.setSpacing(4)

        lf_row = QHBoxLayout()
        lf_lbl = QLabel("Folder:")
        lf_lbl.setFixedWidth(50)
        lf_row.addWidget(lf_lbl)
        self.crawl_leaves_cache_folder_le = QLineEdit("$HIP/geo")
        self.crawl_leaves_cache_folder_le.setToolTip("Base folder for crawl_leaves_filecache.")
        self.crawl_leaves_cache_folder_le.editingFinished.connect(self._on_crawl_leaves_cache_folder_changed)
        lf_row.addWidget(self.crawl_leaves_cache_folder_le, 1)
        self.crawl_leaves_cache_browse_btn = QPushButton("…")
        self.crawl_leaves_cache_browse_btn.setFixedWidth(24)
        self.crawl_leaves_cache_browse_btn.clicked.connect(self._on_crawl_leaves_cache_folder_browse)
        lf_row.addWidget(self.crawl_leaves_cache_browse_btn)
        leaves_v.addLayout(lf_row)

        ln_row = QHBoxLayout()
        ln_lbl = QLabel("Name:")
        ln_lbl.setFixedWidth(50)
        ln_row.addWidget(ln_lbl)
        self.crawl_leaves_cache_name_le = QLineEdit("$HIPNAME.crawl_leaves")
        self.crawl_leaves_cache_name_le.setToolTip("Cache file basename for crawl_leaves_filecache.")
        self.crawl_leaves_cache_name_le.editingFinished.connect(self._on_crawl_leaves_cache_name_changed)
        ln_row.addWidget(self.crawl_leaves_cache_name_le, 1)
        leaves_v.addLayout(ln_row)

        self.crawl_leaves_loadfromdisk_cb = QCheckBox("Load from Disk")
        self.crawl_leaves_loadfromdisk_cb.setToolTip("Read leaves from disk instead of re-running the instancer.")
        self.crawl_leaves_loadfromdisk_cb.setStyleSheet("QCheckBox { font-weight: bold; color: #7ec8e3; font-size: 11px; }")
        self.crawl_leaves_loadfromdisk_cb.toggled.connect(self._on_crawl_leaves_loadfromdisk_changed)
        leaves_v.addWidget(self.crawl_leaves_loadfromdisk_cb)
        lay.addWidget(leaves_grp)

        # ── Shared Cache Settings ───────────────────────────────────────
        cache_grp = QGroupBox("Cache Settings")
        cache_grp.setStyleSheet("QGroupBox { font-size:10px; color:#bbb; }")
        cache_v = QVBoxLayout(cache_grp)
        cache_v.setContentsMargins(6, 8, 6, 6)
        cache_v.setSpacing(4)

        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("Version:"))
        self.crawl_cache_version_sb = QSpinBox()
        self.crawl_cache_version_sb.setRange(1, 9999)
        self.crawl_cache_version_sb.setValue(1)
        self.crawl_cache_version_sb.setToolTip("Cache version number (applied to both curves and leaves).")
        self.crawl_cache_version_sb.valueChanged.connect(self._on_crawl_cache_version_changed)
        ver_row.addWidget(self.crawl_cache_version_sb)
        ver_row.addStretch()
        cache_v.addLayout(ver_row)

        opt_row = QHBoxLayout()
        self.crawl_cache_timedependent_cb = QCheckBox("Time Dependent Cache")
        self.crawl_cache_timedependent_cb.setChecked(True)
        self.crawl_cache_timedependent_cb.toggled.connect(self._on_crawl_cache_timedependent_changed)
        opt_row.addWidget(self.crawl_cache_timedependent_cb)
        self.crawl_cache_simulation_cb = QCheckBox("Simulation")
        self.crawl_cache_simulation_cb.setChecked(True)
        self.crawl_cache_simulation_cb.toggled.connect(self._on_crawl_cache_simulation_changed)
        opt_row.addWidget(self.crawl_cache_simulation_cb)
        opt_row.addStretch()
        cache_v.addLayout(opt_row)

        eval_row = QHBoxLayout()
        eval_row.addWidget(QLabel("Evaluate As:"))
        self.crawl_cache_trange_cb = QComboBox()
        self.crawl_cache_trange_cb.addItems(["Single Frame", "Frame Range"])
        self.crawl_cache_trange_cb.setCurrentIndex(0)
        self.crawl_cache_trange_cb.currentIndexChanged.connect(self._on_crawl_cache_trange_changed)
        eval_row.addWidget(self.crawl_cache_trange_cb, 1)
        cache_v.addLayout(eval_row)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Start:"))
        self.crawl_cache_start_sb = QSpinBox()
        self.crawl_cache_start_sb.setRange(-99999, 999999)
        self.crawl_cache_start_sb.setValue(1)
        self.crawl_cache_start_sb.valueChanged.connect(self._on_crawl_cache_range_changed)
        range_row.addWidget(self.crawl_cache_start_sb)
        range_row.addWidget(QLabel("End:"))
        self.crawl_cache_end_sb = QSpinBox()
        self.crawl_cache_end_sb.setRange(-99999, 999999)
        self.crawl_cache_end_sb.setValue(50)
        self.crawl_cache_end_sb.valueChanged.connect(self._on_crawl_cache_range_changed)
        range_row.addWidget(self.crawl_cache_end_sb)
        range_row.addWidget(QLabel("Inc:"))
        self.crawl_cache_inc_sb = QSpinBox()
        self.crawl_cache_inc_sb.setRange(1, 9999)
        self.crawl_cache_inc_sb.setValue(1)
        self.crawl_cache_inc_sb.valueChanged.connect(self._on_crawl_cache_range_changed)
        range_row.addWidget(self.crawl_cache_inc_sb)
        cache_v.addLayout(range_row)

        sub_row = QHBoxLayout()
        sub_row.addWidget(QLabel("Substeps:"))
        self.crawl_cache_substeps_sb = QSpinBox()
        self.crawl_cache_substeps_sb.setRange(1, 100)
        self.crawl_cache_substeps_sb.setValue(1)
        self.crawl_cache_substeps_sb.valueChanged.connect(self._on_crawl_cache_range_changed)
        sub_row.addWidget(self.crawl_cache_substeps_sb)
        sub_row.addStretch()
        cache_v.addLayout(sub_row)

        lay.addWidget(cache_grp)
        lay.addWidget(crawl_proxy_frame)
        lay.addWidget(self.crawl_bake_btn)

        # ── Solaris ──────────────────────────────────────────────────────────
        crawl_solaris_grp = QGroupBox("Solaris")
        crawl_sl_lay = QVBoxLayout(crawl_solaris_grp)
        crawl_sl_lay.setContentsMargins(8, 10, 8, 8)
        self.crawl_include_wires_cb = QCheckBox("Include Wire Mesh")
        self.crawl_include_wires_cb.setChecked(True)
        self.crawl_include_wires_cb.setToolTip(
            "Export the wire mesh (crawl_OUT / OUT_wires) as a USD reference under "
            "/MSW/<system>/wires.  Leave unchecked to export only the scatter instances."
        )
        crawl_sl_lay.addWidget(self.crawl_include_wires_cb)
        crawl_send_solaris_btn = QPushButton("⬡  Send to Solaris")
        crawl_send_solaris_btn.setMinimumHeight(36)
        crawl_send_solaris_btn.setStyleSheet(
            "QPushButton { background-color:#1a4a5c; color:#a0e8ff; border:1px solid #2a7a9c; font-weight:bold; }"
            "QPushButton:hover { background-color:#1f5f78; border-color:#3ab0d8; }"
            "QPushButton:pressed { background-color:#0f2f3c; }"
        )
        crawl_send_solaris_btn.setToolTip(
            "Create a USD PointInstancer LOP network in /stage for this crawling ivy scatter."
        )
        crawl_send_solaris_btn.clicked.connect(self._on_send_to_solaris)
        crawl_sl_lay.addWidget(crawl_send_solaris_btn)

        # ── Lookdev ───────────────────────────────────────────────────────────
        crawl_ld_grp = QGroupBox("Lookdev")
        crawl_ld_lay = QVBoxLayout(crawl_ld_grp)
        crawl_ld_lay.setContentsMargins(8, 10, 8, 8)
        crawl_lookdev_btn = QPushButton("Lookdev")
        crawl_lookdev_btn.setMinimumHeight(36)
        crawl_lookdev_btn.setToolTip(
            "Open the Lookdev window — build PBR shaders for your crawling ivy assets\n"
            "in Arnold or Redshift, with textures and live parameter tweaks."
        )
        crawl_lookdev_btn.setStyleSheet(
            "QPushButton { background-color:#3a1a5c; color:#d0b0ff; border-color:#5f2b8b; }"
            "QPushButton:hover { background-color:#4f2480; border-color:#8f3cc8; }"
            "QPushButton:pressed { background-color:#241038; }"
        )
        crawl_lookdev_btn.clicked.connect(self._open_lookdev)
        crawl_ld_lay.addWidget(crawl_lookdev_btn)
        lay.addWidget(crawl_ld_grp)
        lay.addWidget(crawl_solaris_grp)

        lay.addStretch()
        return w

    def _build_ivy_crawl_tab(self):
        """Build the Crawling Ivy sub-tab inside the Ivy parameter tabs."""
        outer = QWidget()
        v = QVBoxLayout(outer)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        intro = QLabel(
            "Surface-creeping ivy — each strand walks the surface using a "
            "delayed proportional controller (Streit, Federl, Sousa 2005)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#9fd0ff; font-size:10px; padding:2px;")
        v.addWidget(intro)

        # Build spinboxes by group
        spec_by_name = {s[0]: s for s in self._CRAWL_SPINBOX_SPECS}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(2, 2, 2, 2)
        body_lay.setSpacing(6)

        for group_label, names in self._CRAWL_GROUPS:
            grp = _CollapsibleGroup(group_label)
            grid = QGridLayout(grp.body)
            grid.setContentsMargins(8, 4, 8, 4)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(4)
            for row, name in enumerate(names):
                _, label, default, mn, mx, step, decimals, is_int = spec_by_name[name]
                lbl = QLabel(label)
                lbl.setMinimumWidth(140)
                grid.addWidget(lbl, row, 0)

                # Use sliders for Wire Appearance parameters
                if name in ("crawl_wire_segs", "crawl_wire_divisions", "crawl_wire_radius"):
                    slider_lay = QHBoxLayout()
                    slider = QSlider(Qt.Horizontal)
                    is_float = name == "crawl_wire_radius"
                    if is_float:
                        # Slider: [mn, mx] visual range; spinbox: unlimited max
                        slider.setRange(int(mn * 1000), int(mx * 1000))
                        slider.setSingleStep(max(1, int(step * 1000)))
                        slider.setValue(min(int(default * 1000), int(mx * 1000)))
                        sb_wr = QDoubleSpinBox()
                        sb_wr.setRange(mn, 99999.0)
                        sb_wr.setSingleStep(step)
                        sb_wr.setDecimals(decimals)
                        sb_wr.setFixedWidth(64)
                        sb_wr.setValue(default)
                        _sl_max = int(mx * 1000)
                        _sl_min = int(mn * 1000)
                        slider.valueChanged.connect(
                            lambda val, n=name: self._on_crawl_value_changed(n, val / 1000.0))
                        slider.valueChanged.connect(
                            lambda val, sb=sb_wr: (
                                sb.blockSignals(True), sb.setValue(val / 1000.0), sb.blockSignals(False)))
                        sb_wr.valueChanged.connect(
                            lambda val, n=name: self._on_crawl_value_changed(n, val))
                        sb_wr.valueChanged.connect(
                            lambda val, sl=slider, lo=_sl_min, hi=_sl_max: (
                                sl.blockSignals(True),
                                sl.setValue(max(lo, min(hi, int(val * 1000)))),
                                sl.blockSignals(False)))
                        slider_lay.addWidget(slider)
                        slider_lay.addWidget(sb_wr)
                        self._crawl_widgets[name] = sb_wr
                        grid.addLayout(slider_lay, row, 1)
                        continue
                    else:
                        slider.setRange(int(mn), int(mx))
                        slider.setSingleStep(int(step))
                        slider.setValue(int(default))
                        slider.valueChanged.connect(
                            lambda val, n=name: self._on_crawl_value_changed(n, val))
                        val_lbl = QLabel(str(int(default)))
                        slider.valueChanged.connect(
                            lambda val, vl=val_lbl: vl.setText(str(val)))
                    val_lbl.setFixedWidth(40)
                    slider_lay.addWidget(slider)
                    slider_lay.addWidget(val_lbl)
                    self._crawl_widgets[name] = slider
                    grid.addLayout(slider_lay, row, 1)
                elif is_int:
                    sb = QSpinBox()
                    sb.setRange(int(mn), int(mx))
                    sb.setSingleStep(int(step))
                    sb.setValue(int(default))
                    sb.valueChanged.connect(
                        lambda val, n=name: self._on_crawl_value_changed(n, val))
                    self._crawl_widgets[name] = sb
                    grid.addWidget(sb, row, 1)
                else:
                    sb = QDoubleSpinBox()
                    sb.setRange(float(mn), float(mx))
                    sb.setSingleStep(float(step))
                    sb.setDecimals(int(decimals))
                    sb.setValue(float(default))
                    sb.valueChanged.connect(
                        lambda val, n=name: self._on_crawl_value_changed(n, val))
                    self._crawl_widgets[name] = sb
                    grid.addWidget(sb, row, 1)
            body_lay.addWidget(grp)

        body_lay.addStretch()
        scroll.setWidget(body)
        v.addWidget(scroll, 1)

        # ── presets — combo + Save / Update / Delete ──────────────────────
        self._crawl_user_presets = self._load_crawl_user_presets()

        preset_grp = _CollapsibleGroup("Presets")
        pr_outer = QVBoxLayout(preset_grp.body)
        pr_outer.setContentsMargins(2, 2, 2, 2)
        pr_outer.setSpacing(4)

        pr_row = QHBoxLayout()
        pr_row.setSpacing(4)
        self.crawl_preset_cb = QComboBox()
        self.crawl_preset_cb.setToolTip("Select a Crawling Ivy preset to apply")
        self._refresh_crawl_preset_combo()
        self.crawl_preset_cb.activated.connect(self._on_crawl_preset_selected)
        pr_row.addWidget(self.crawl_preset_cb, 1)

        self.crawl_preset_save_btn = QPushButton("Save")
        self.crawl_preset_save_btn.setToolTip(
            "Save the current Crawling Ivy parameters as a new preset")
        self.crawl_preset_save_btn.clicked.connect(self._on_crawl_preset_save)
        pr_row.addWidget(self.crawl_preset_save_btn)

        self.crawl_preset_update_btn = QPushButton("Update")
        self.crawl_preset_update_btn.setToolTip(
            "Overwrite the selected user preset with the current values "
            "(built-in presets cannot be updated)")
        self.crawl_preset_update_btn.clicked.connect(self._on_crawl_preset_update)
        pr_row.addWidget(self.crawl_preset_update_btn)

        self.crawl_preset_delete_btn = QPushButton("Delete")
        self.crawl_preset_delete_btn.setToolTip(
            "Delete the selected user preset (built-in presets cannot be deleted)")
        self.crawl_preset_delete_btn.clicked.connect(self._on_crawl_preset_delete)
        pr_row.addWidget(self.crawl_preset_delete_btn)

        pr_outer.addLayout(pr_row)
        v.addWidget(preset_grp)

        # ── action buttons ────────────────────────────────────────────────
        btn_row = QVBoxLayout()
        btn_row.setSpacing(4)

        self.crawl_create_btn = QPushButton("🌿  Create Crawling Ivy")
        self.crawl_create_btn.setMinimumHeight(32)
        self.crawl_create_btn.setToolTip(
            "Build the crawl_* SOP chain (independent of the strand ivy chain).\n"
            "Output null is named 'crawl_OUT' inside the geo node."
        )
        self.crawl_create_btn.clicked.connect(self._on_crawl_create)
        btn_row.addWidget(self.crawl_create_btn)

        self.crawl_regen_btn = QPushButton("⟳  Regenerate")
        self.crawl_regen_btn.setMinimumHeight(28)
        self.crawl_regen_btn.setToolTip("Apply parameter changes and recook the network")
        self.crawl_regen_btn.clicked.connect(self._on_crawl_regen)
        btn_row.addWidget(self.crawl_regen_btn)

        self.crawl_wire_toggle_btn = QPushButton("Disable Crawl Wire")
        self.crawl_wire_toggle_btn.setCheckable(True)
        self.crawl_wire_toggle_btn.setToolTip(
            "Bypass / un-bypass crawl_wire (PolyWire). "
            "The main ivy 'Enable Ivy Wire' button also disables crawl_wire."
        )
        self.crawl_wire_toggle_btn.clicked.connect(self._on_crawl_wire_toggle)
        btn_row.addWidget(self.crawl_wire_toggle_btn)

        self.crawl_show_geo_btn = QPushButton("Hide Assets ")
        self.crawl_show_geo_btn.setCheckable(True)
        self.crawl_show_geo_btn.setToolTip(
            "Bypass / un-bypass the instancer (CopyToPoints) SOP — hides or shows scattered geometry."
        )
        self.crawl_show_geo_btn.clicked.connect(self._on_crawl_instancer_toggle)
        btn_row.addWidget(self.crawl_show_geo_btn)

        self.crawl_edit_ramp_btn = QPushButton("✎  Edit Ramp")
        self.crawl_edit_ramp_btn.setToolTip(
            "Select crawl_pscale_ramp so its Scale Ramp / Width Ramp spare parms "
            "appear in the Houdini parameter pane."
        )
        self.crawl_edit_ramp_btn.clicked.connect(self._on_crawl_edit_ramp)
        btn_row.addWidget(self.crawl_edit_ramp_btn)

        self.crawl_remove_btn = QPushButton("✕  Remove Crawling Ivy")
        self.crawl_remove_btn.setMinimumHeight(28)
        self.crawl_remove_btn.setStyleSheet(
            "QPushButton { color:#ff6060; } QPushButton:hover { background:#5a1a1a; }"
        )
        self.crawl_remove_btn.setToolTip("Delete every crawl_* node from this geo node")
        self.crawl_remove_btn.clicked.connect(self._on_crawl_remove)
        btn_row.addWidget(self.crawl_remove_btn)

        v.addLayout(btn_row)

        # ── Bake row (separated from action buttons; persists generation) ─
        self.crawl_bake_btn = QPushButton("💾  Bake Geometry ")
        self.crawl_bake_btn.setMinimumHeight(34)
        self.crawl_bake_btn.setStyleSheet(
            "QPushButton { background:#2c5a8c; color:#e8f2ff; }"
            "QPushButton:hover { background:#3870a8; }"
        )
        self.crawl_bake_btn.setToolTip(
            "Save the resampled crawling-ivy curves to disk via crawl_filecache, "
            "then switch the cache to Load-from-Disk so the network reads the file "
            "instead of re-running crawl_ivy_gen."
        )
        self.crawl_bake_btn.clicked.connect(self._on_crawl_bake)
        v.addWidget(self.crawl_bake_btn)

        crawl_proxy_frame = QFrame()
        crawl_proxy_frame.setStyleSheet(
            "QFrame { background: #2e2200; border: 2px solid #c08000; border-radius: 5px; }"
        )
        cpf_lay = QVBoxLayout(crawl_proxy_frame)
        cpf_lay.setContentsMargins(10, 7, 10, 7)
        cpf_lay.setSpacing(5)
        self.crawl_pack_instance_cb = QCheckBox("  Pack and Instance  —  Uncheck this if you're using proxy assets")
        self.crawl_pack_instance_cb.setChecked(True)
        self.crawl_pack_instance_cb.setStyleSheet(
            "QCheckBox { font-weight: bold; color: #ffcc44; font-size: 12px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
        )
        self.crawl_pack_instance_cb.setToolTip(
            "Checked (default): Pack and Instance is ON — geometry is packed.\n"
            "Unchecked: Pack and Instance is OFF — required when using Proxy workflows."
        )
        self.crawl_pack_instance_cb.toggled.connect(self._on_crawl_pack_instance_changed)
        cpf_lay.addWidget(self.crawl_pack_instance_cb)
        crawl_disp_row2 = QHBoxLayout()
        crawl_disp_lbl2 = QLabel("Display As:")
        crawl_disp_lbl2.setStyleSheet("color: #ffcc44; font-size: 11px;")
        crawl_disp_row2.addWidget(crawl_disp_lbl2)
        self.crawl_display_as_cb = QComboBox()
        self.crawl_display_as_cb.addItems(["Full Geometry", "Point Cloud", "Bounding Box", "Centroid", "Hidden"])
        self.crawl_display_as_cb.setCurrentText("Bounding Box")
        self.crawl_display_as_cb.setToolTip("Controls how packed instances appear in the viewport.")
        self.crawl_display_as_cb.currentTextChanged.connect(self._on_crawl_display_as_changed)
        crawl_disp_row2.addWidget(self.crawl_display_as_cb)
        crawl_disp_row2.addStretch()
        cpf_lay.addLayout(crawl_disp_row2)
        v.addWidget(crawl_proxy_frame)

        # ── Cache settings (folder / name / load-from-disk) ──────────────
        cache_grp = QGroupBox("Cache")
        cache_grp.setStyleSheet("QGroupBox { font-size:10px; color:#bbb; }")
        cache_v = QVBoxLayout(cache_grp)
        cache_v.setContentsMargins(6, 8, 6, 6)
        cache_v.setSpacing(4)

        # Folder row (basedir) + Browse button
        folder_row = QHBoxLayout()
        folder_lbl = QLabel("Folder:")
        folder_lbl.setFixedWidth(50)
        folder_row.addWidget(folder_lbl)
        self.crawl_cache_folder_le = QLineEdit("$HIP/geo")
        self.crawl_cache_folder_le.setToolTip(
            "Base folder for the crawl_filecache (basedir parm). "
            "Default: $HIP/geo. Houdini variables are evaluated."
        )
        self.crawl_cache_folder_le.editingFinished.connect(
            self._on_crawl_cache_folder_changed)
        folder_row.addWidget(self.crawl_cache_folder_le, 1)
        self.crawl_cache_browse_btn = QPushButton("…")
        self.crawl_cache_browse_btn.setFixedWidth(24)
        self.crawl_cache_browse_btn.setToolTip("Browse for a cache folder.")
        self.crawl_cache_browse_btn.clicked.connect(self._on_crawl_cache_folder_browse)
        folder_row.addWidget(self.crawl_cache_browse_btn)
        cache_v.addLayout(folder_row)

        # Name row (basename)
        name_row = QHBoxLayout()
        name_lbl = QLabel("Name:")
        name_lbl.setFixedWidth(50)
        name_row.addWidget(name_lbl)
        self.crawl_cache_name_le = QLineEdit("$HIPNAME.$OS")
        self.crawl_cache_name_le.setToolTip(
            "Cache file basename (basename parm). Default: $HIPNAME.$OS. "
            "The extension is appended by the file cache SOP."
        )
        self.crawl_cache_name_le.editingFinished.connect(
            self._on_crawl_cache_name_changed)
        name_row.addWidget(self.crawl_cache_name_le, 1)
        cache_v.addLayout(name_row)

        # Load from Disk checkbox
        self.crawl_loadfromdisk_cb = QCheckBox("Load from Disk")
        self.crawl_loadfromdisk_cb.setToolTip(
            "When on, the network reads the cached file instead of "
            "re-running crawl_ivy_gen. Bake automatically enables this "
            "after writing the cache."
        )
        self.crawl_loadfromdisk_cb.toggled.connect(
            self._on_crawl_loadfromdisk_changed)
        cache_v.addWidget(self.crawl_loadfromdisk_cb)

        # Version row
        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("Version:"))
        self.crawl_cache_version_sb = QSpinBox()
        self.crawl_cache_version_sb.setRange(1, 9999)
        self.crawl_cache_version_sb.setValue(1)
        self.crawl_cache_version_sb.setToolTip("Cache version number appended to the filename. Increment to write a new version without overwriting the previous.")
        self.crawl_cache_version_sb.valueChanged.connect(self._on_crawl_cache_version_changed)
        ver_row.addWidget(self.crawl_cache_version_sb)
        ver_row.addStretch()
        cache_v.addLayout(ver_row)

        # Options row (Time Dependent + Simulation)
        opt_row = QHBoxLayout()
        self.crawl_cache_timedependent_cb = QCheckBox("Time Dependent Cache")
        self.crawl_cache_timedependent_cb.setChecked(True)
        self.crawl_cache_timedependent_cb.setToolTip("When checked, the cache writes a separate file per frame. Uncheck for a static single-frame cache.")
        self.crawl_cache_timedependent_cb.toggled.connect(self._on_crawl_cache_timedependent_changed)
        opt_row.addWidget(self.crawl_cache_timedependent_cb)
        self.crawl_cache_simulation_cb = QCheckBox("Simulation")
        self.crawl_cache_simulation_cb.setChecked(True)
        self.crawl_cache_simulation_cb.setToolTip("Enable the simulation flag on the crawl file cache node.")
        self.crawl_cache_simulation_cb.toggled.connect(self._on_crawl_cache_simulation_changed)
        opt_row.addWidget(self.crawl_cache_simulation_cb)
        opt_row.addStretch()
        cache_v.addLayout(opt_row)

        # Evaluate As (trange)
        eval_row = QHBoxLayout()
        eval_row.addWidget(QLabel("Evaluate As:"))
        self.crawl_cache_trange_cb = QComboBox()
        self.crawl_cache_trange_cb.addItems(["Single Frame", "Frame Range"])
        self.crawl_cache_trange_cb.setCurrentIndex(0)
        self.crawl_cache_trange_cb.setToolTip("Choose whether to cache only the current frame or a range of frames for crawling ivy.")
        self.crawl_cache_trange_cb.currentIndexChanged.connect(self._on_crawl_cache_trange_changed)
        eval_row.addWidget(self.crawl_cache_trange_cb, 1)
        cache_v.addLayout(eval_row)

        # Frame range row
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Start:"))
        self.crawl_cache_start_sb = QSpinBox()
        self.crawl_cache_start_sb.setRange(-99999, 999999)
        self.crawl_cache_start_sb.setValue(1)
        self.crawl_cache_start_sb.setToolTip("First frame of the crawling ivy cache range.")
        self.crawl_cache_start_sb.valueChanged.connect(self._on_crawl_cache_range_changed)
        range_row.addWidget(self.crawl_cache_start_sb)
        range_row.addWidget(QLabel("End:"))
        self.crawl_cache_end_sb = QSpinBox()
        self.crawl_cache_end_sb.setRange(-99999, 999999)
        self.crawl_cache_end_sb.setValue(50)
        self.crawl_cache_end_sb.setToolTip("Last frame of the crawling ivy cache range.")
        self.crawl_cache_end_sb.valueChanged.connect(self._on_crawl_cache_range_changed)
        range_row.addWidget(self.crawl_cache_end_sb)
        range_row.addWidget(QLabel("Inc:"))
        self.crawl_cache_inc_sb = QSpinBox()
        self.crawl_cache_inc_sb.setRange(1, 9999)
        self.crawl_cache_inc_sb.setValue(1)
        self.crawl_cache_inc_sb.setToolTip("Frame step increment for the crawling ivy cache.")
        self.crawl_cache_inc_sb.valueChanged.connect(self._on_crawl_cache_range_changed)
        range_row.addWidget(self.crawl_cache_inc_sb)
        cache_v.addLayout(range_row)

        # Substeps row
        sub_row = QHBoxLayout()
        sub_row.addWidget(QLabel("Substeps:"))
        self.crawl_cache_substeps_sb = QSpinBox()
        self.crawl_cache_substeps_sb.setRange(1, 100)
        self.crawl_cache_substeps_sb.setValue(1)
        self.crawl_cache_substeps_sb.setToolTip("Number of sub-frame samples per frame for the crawling ivy cache.")
        self.crawl_cache_substeps_sb.valueChanged.connect(self._on_crawl_cache_range_changed)
        sub_row.addWidget(self.crawl_cache_substeps_sb)
        sub_row.addStretch()
        cache_v.addLayout(sub_row)

        v.addWidget(cache_grp)

        # ── Solaris ──────────────────────────────────────────────────────────
        crawl_ivy_solaris_grp = QGroupBox("Solaris")
        crawl_ivy_sl_lay = QVBoxLayout(crawl_ivy_solaris_grp)
        crawl_ivy_sl_lay.setContentsMargins(8, 10, 8, 8)
        if not hasattr(self, 'crawl_include_wires_cb'):
            self.crawl_include_wires_cb = QCheckBox("Include Wire Mesh")
            self.crawl_include_wires_cb.setChecked(True)
            self.crawl_include_wires_cb.setToolTip(
                "Export the wire mesh (crawl_OUT / OUT_wires) as a USD reference under "
                "/MSW/<system>/wires.  Leave unchecked to export only the scatter instances."
            )
            crawl_ivy_sl_lay.addWidget(self.crawl_include_wires_cb)
        crawl_ivy_send_solaris_btn = QPushButton("⬡  Send to Solaris")
        crawl_ivy_send_solaris_btn.setMinimumHeight(36)
        crawl_ivy_send_solaris_btn.setStyleSheet(
            "QPushButton { background-color:#1a4a5c; color:#a0e8ff; border:1px solid #2a7a9c; font-weight:bold; }"
            "QPushButton:hover { background-color:#1f5f78; border-color:#3ab0d8; }"
            "QPushButton:pressed { background-color:#0f2f3c; }"
        )
        crawl_ivy_send_solaris_btn.setToolTip(
            "Create a USD PointInstancer LOP network in /stage for this crawling ivy scatter."
        )
        crawl_ivy_send_solaris_btn.clicked.connect(self._on_send_to_solaris)
        crawl_ivy_sl_lay.addWidget(crawl_ivy_send_solaris_btn)
        v.addWidget(crawl_ivy_solaris_grp)

        # ── Lookdev ───────────────────────────────────────────────────────────
        crawl_ivy_ld_grp = QGroupBox("Lookdev")
        crawl_ivy_ld_lay = QVBoxLayout(crawl_ivy_ld_grp)
        crawl_ivy_ld_lay.setContentsMargins(8, 10, 8, 8)
        crawl_ivy_lookdev_btn = QPushButton("Lookdev")
        crawl_ivy_lookdev_btn.setMinimumHeight(36)
        crawl_ivy_lookdev_btn.setToolTip(
            "Open the Lookdev window — build PBR shaders for your crawling ivy assets\n"
            "in Arnold or Redshift, with textures and live parameter tweaks."
        )
        crawl_ivy_lookdev_btn.setStyleSheet(
            "QPushButton { background-color:#3a1a5c; color:#d0b0ff; border-color:#5f2b8b; }"
            "QPushButton:hover { background-color:#4f2480; border-color:#8f3cc8; }"
            "QPushButton:pressed { background-color:#241038; }"
        )
        crawl_ivy_lookdev_btn.clicked.connect(self._open_lookdev)
        crawl_ivy_ld_lay.addWidget(crawl_ivy_lookdev_btn)
        v.addWidget(crawl_ivy_ld_grp)

        # ── persistent footer (own rt checkbox + status label) ──────────────
        rt_row = QHBoxLayout()
        self.crawl_rt_cb = QCheckBox("Real-time update")
        self.crawl_rt_cb.setChecked(True)
        self.crawl_rt_cb.setToolTip(
            "When checked, parameter changes recook the network in real-time.\n"
            "For faster slider performance, disable this and use Regenerate."
        )
        rt_row.addWidget(self.crawl_rt_cb)
        rt_row.addStretch()
        v.addLayout(rt_row)

        self.crawl_status_l = QLabel("No crawling ivy network.")
        self.crawl_status_l.setStyleSheet("color:#888; font-size:10px; padding:2px;")
        self.crawl_status_l.setWordWrap(True)
        v.addWidget(self.crawl_status_l)

        return outer

    def _get_crawl_state(self):
        """Collect current crawl widget values into a dict."""
        result = {}
        for k, sb in self._crawl_widgets.items():
            val = sb.value()
            if k in _CRAWL_FLOAT_SLIDER_SCALES:
                val = val / _CRAWL_FLOAT_SLIDER_SCALES[k]
            result[k] = val
        return result

    def _on_crawl_value_changed(self, name, val):
        """Real-time push (when the rt checkbox is on) for a single crawl parm."""
        self.state[name] = val

        # Wire Appearance parameters update crawl_wire directly without cooking
        WIRE_APPEARANCE_PARAMS = {"crawl_wire_radius", "crawl_wire_segs", "crawl_wire_divisions"}
        if name in WIRE_APPEARANCE_PARAMS:
            self._update_crawl_wire_direct(name, val)
        else:
            # Other parameters trigger full sync with cook
            self._sync_crawl_rt()

    def _on_crawl_resample_length_changed(self, *_):
        """Write the resample length value directly to crawl_resample without a full cook."""
        if self.geo_node is None:
            return
        node = self.geo_node.node("crawl_resample")
        if node is None:
            return
        try:
            p = node.parm("length")
            if p is not None:
                p.set(self.crawl_resample_len_sb.value())
        except Exception as e:
            print(f"[CY] crawl_resample length: {e}")

    def _update_crawl_wire_direct(self, name, val):
        """Directly update crawl_wire parameters without cooking."""
        if self.geo_node is None:
            return
        wire = self.geo_node.node("crawl_wire")
        if wire is None:
            return

        wire_parm_map = {
            "crawl_wire_radius": "radius",
            "crawl_wire_segs": "segs",
            "crawl_wire_divisions": "div",
        }

        wire_parm = wire_parm_map.get(name)
        if wire_parm:
            p = wire.parm(wire_parm)
            if p is not None:
                try:
                    p.set(val)
                except Exception as e:
                    print(f"[Magic Scatter World] Error setting {name}: {e}")

    @debounce(100)
    def _sync_crawl_rt(self):
        """Debounced sync for all crawling ivy parameters."""
        if not getattr(self, "crawl_rt_cb", None) or not self.crawl_rt_cb.isChecked():
            return
        if self.geo_node is None or not logic.crawl_ivy_network_exists(self.geo_node):
            return
        try:
            logic.sync_crawl_ivy_params(self.geo_node, self._get_crawl_state(), cook=True)
        except Exception as e:
            print(f"[Magic Scatter World] Crawl param push error: {e}")

    @staticmethod
    def _exit_viewer_paint_state():
        """Switch any active scene viewer to select state.

        The attribpaint viewer state caches a hou.Geometry reference.  If nodes
        are created or destroyed while it is active, that reference becomes stale
        and the next mouse-move triggers hou.ObjectWasDeleted inside Houdini's
        sidefx_stroke.py.  Switching to 'select' first lets the viewer state
        tear down cleanly.
        """
        try:
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            if viewer:
                viewer.setCurrentState("select")
        except Exception:
            pass

    def _on_crawl_create(self):
        if self.geo_node is None:
            hou.ui.displayMessage(
                "Create a scatter network first (set a Surface and click Create Network).",
                severity=hou.severityType.Warning)
            return
        try:
            if logic.crawl_ivy_network_exists(self.geo_node):
                self.crawl_status_l.setText(
                    "Crawling ivy already exists — use Regenerate.")
                return
            self._exit_viewer_paint_state()
            logic.create_crawl_ivy_network(self.geo_node)
            logic.sync_crawl_ivy_params(self.geo_node, self._get_crawl_state(), cook=True)
            logic.sync_crawl_geo_offset(self.geo_node, self.ivy_geo_offset_sb.value())
            self._refresh_crawl_cache_widgets()
            self.crawl_status_l.setText(
                f"Crawling ivy created in {self.geo_node.name()} (output: crawl_OUT).")
            self.crawl_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.crawl_status_l.setText(f"Crawl create error: {e}")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Crawl create error: {e}")

    def _on_crawl_regen(self):
        if self.geo_node is None or not logic.crawl_ivy_network_exists(self.geo_node):
            self.crawl_status_l.setText("No crawling ivy to regenerate — create it first.")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        try:
            logic.sync_crawl_ivy_params(self.geo_node, self._get_crawl_state(), cook=True)
            logic.sync_crawl_geo_offset(self.geo_node, self.ivy_geo_offset_sb.value())
            self.crawl_status_l.setText("Crawling ivy regenerated.")
            self.crawl_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.crawl_status_l.setText(f"Crawl regen error: {e}")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_crawl_remove(self):
        if self.geo_node is None or not logic.crawl_ivy_network_exists(self.geo_node):
            self.crawl_status_l.setText("No crawling ivy to remove.")
            return
        if not hou.ui.displayConfirmation(
                "Delete the Crawling Ivy network from this geo node?"):
            return
        try:
            self._exit_viewer_paint_state()
            logic.remove_crawl_ivy_network(self.geo_node)
            self.crawl_status_l.setText("Crawling ivy removed.")
            self.crawl_status_l.setStyleSheet("color:#888; font-size:10px;")
        except Exception as e:
            self.crawl_status_l.setText(f"Crawl remove error: {e}")
            print(f"[Magic Scatter World] Crawl remove error: {e}")

    def _on_crawl_wire_toggle(self):
        """Bypass / un-bypass crawl_wire only (for the Crawling Ivy wire branch)."""
        if self.geo_node is None:
            self.crawl_wire_toggle_btn.setChecked(False)
            self.crawl_status_l.setText("No geo node — create the crawling ivy network first.")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        bypass = self.crawl_wire_toggle_btn.isChecked()
        try:
            toggled = logic.set_crawl_wire_bypass(self.geo_node, bypass)
            if not toggled:
                self.crawl_wire_toggle_btn.setChecked(False)
                self.crawl_status_l.setText("crawl_wire not found — create crawling ivy first.")
                self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
                return
            self.crawl_wire_toggle_btn.setText(
                "Enable Crawl Wire" if bypass else "Disable Crawl Wire"
            )
            self.crawl_status_l.setText(
                "crawl_wire disabled." if bypass else "crawl_wire enabled."
            )
            self.crawl_status_l.setStyleSheet(
                ("color:#e0b898;" if bypass else "color:#5fdb5f;") + " font-size:10px;"
            )
        except Exception as e:
            self.crawl_wire_toggle_btn.setChecked(not bypass)
            self.crawl_status_l.setText(f"crawl wire toggle error: {e}")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_crawl_instancer_toggle(self):
        """Bypass / un-bypass the instancer (hides or shows scattered geometry)."""
        if self.geo_node is None:
            self.crawl_show_geo_btn.setChecked(False)
            self.crawl_status_l.setText("No active scatter network.")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        bypass = self.crawl_show_geo_btn.isChecked()
        try:
            logic.set_instancer_bypass(self.geo_node, bypass)
            self.crawl_show_geo_btn.setText("Show Assets " if bypass else "Hide Assets ")
            self.crawl_status_l.setText(
                "instancer disabled — scattered geometry hidden."
                if bypass else "instancer enabled — scattered geometry visible."
            )
            self.crawl_status_l.setStyleSheet(
                ("color:#e0b898;" if bypass else "color:#5fdb5f;") + " font-size:10px;"
            )
        except Exception as e:
            self.crawl_show_geo_btn.setChecked(not bypass)
            self.crawl_status_l.setText(f"instancer toggle error: {e}")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_crawl_bake(self):
        """Bake crawl_filecache to disk, then flip it to Load-from-Disk."""
        if self.geo_node is None or not logic.crawl_ivy_network_exists(self.geo_node):
            self.crawl_status_l.setText("No crawling ivy to bake — create it first.")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        # Push the latest folder/name fields before baking (each cache independently).
        try:
            if self._is_crawling_ivy:
                logic.set_crawl_filecache_basedir(self.geo_node, self.crawl_cache_folder_le.text())
                logic.set_crawl_filecache_basename(self.geo_node, self.crawl_cache_name_le.text())
                if hasattr(self, "crawl_leaves_cache_folder_le"):
                    logic.set_crawl_leaves_cache_basedir(self.geo_node, self.crawl_leaves_cache_folder_le.text())
                    logic.set_crawl_leaves_cache_basename(self.geo_node, self.crawl_leaves_cache_name_le.text())
            else:
                logic.set_crawl_cache_basedir(self.geo_node, self.crawl_cache_folder_le.text())
                logic.set_crawl_cache_basename(self.geo_node, self.crawl_cache_name_le.text())
        except Exception as e:
            print(f"[Magic Scatter World] crawl cache parm push error: {e}")
        try:
            file_path = logic.bake_crawl_ivy(self.geo_node)
            # Bake flips loadfromdisk on — reflect that in both checkboxes.
            self.crawl_loadfromdisk_cb.blockSignals(True)
            self.crawl_loadfromdisk_cb.setChecked(True)
            self.crawl_loadfromdisk_cb.blockSignals(False)
            if hasattr(self, "crawl_leaves_loadfromdisk_cb"):
                self.crawl_leaves_loadfromdisk_cb.blockSignals(True)
                self.crawl_leaves_loadfromdisk_cb.setChecked(True)
                self.crawl_leaves_loadfromdisk_cb.blockSignals(False)

            msg = f"Baked → {file_path}" if file_path else "Baked crawling ivy (Load-from-Disk on)."
            self.crawl_status_l.setText(msg)
            self.crawl_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.crawl_status_l.setText(f"Bake error: {e}")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Crawl bake error: {e}")

    def _on_crawl_cache_folder_changed(self):
        if self.geo_node is None:
            return
        try:
            val = self.crawl_cache_folder_le.text()
            if self._is_crawling_ivy:
                logic.set_crawl_filecache_basedir(self.geo_node, val)
            else:
                logic.set_crawl_cache_basedir(self.geo_node, val)
        except Exception as e:
            print(f"[Magic Scatter World] cache folder set error: {e}")

    def _on_crawl_cache_name_changed(self):
        if self.geo_node is None:
            return
        try:
            val = self.crawl_cache_name_le.text()
            if self._is_crawling_ivy:
                logic.set_crawl_filecache_basename(self.geo_node, val)
            else:
                logic.set_crawl_cache_basename(self.geo_node, val)
        except Exception as e:
            print(f"[Magic Scatter World] cache name set error: {e}")

    def _on_crawl_cache_folder_browse(self):
        """Open a folder picker for the cache base dir."""
        try:
            current = self.crawl_cache_folder_le.text() or "$HIP/geo"
            # Try to resolve $HIP-style vars for the dialog start path.
            try:
                start = hou.expandString(current)
            except Exception:
                start = current
            chosen = QFileDialog.getExistingDirectory(self, "Choose cache folder", start)
            if chosen:
                self.crawl_cache_folder_le.setText(chosen)
                self._on_crawl_cache_folder_changed()
        except Exception as e:
            print(f"[Magic Scatter World] cache folder browse error: {e}")

    def _on_crawl_loadfromdisk_changed(self, checked):
        if self.geo_node is None:
            return
        if not logic.crawl_ivy_network_exists(self.geo_node):
            return
        try:
            if self._is_crawling_ivy:
                logic.set_crawl_filecache_loadfromdisk(self.geo_node, bool(checked))
            else:
                logic.set_crawl_loadfromdisk(self.geo_node, bool(checked))
            self.crawl_status_l.setText(
                "Curves: Load from Disk ON." if checked else "Curves: Load from Disk OFF."
            )
            self.crawl_status_l.setStyleSheet("color:#888; font-size:10px;")
        except Exception as e:
            self.crawl_loadfromdisk_cb.blockSignals(True)
            self.crawl_loadfromdisk_cb.setChecked(not checked)
            self.crawl_loadfromdisk_cb.blockSignals(False)
            self.crawl_status_l.setText(f"Load-from-Disk error: {e}")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_crawl_leaves_cache_folder_changed(self):
        if self.geo_node is None:
            return
        try:
            logic.set_crawl_leaves_cache_basedir(self.geo_node, self.crawl_leaves_cache_folder_le.text())
        except Exception as e:
            print(f"[Magic Scatter World] leaves cache folder set error: {e}")

    def _on_crawl_leaves_cache_name_changed(self):
        if self.geo_node is None:
            return
        try:
            logic.set_crawl_leaves_cache_basename(self.geo_node, self.crawl_leaves_cache_name_le.text())
        except Exception as e:
            print(f"[Magic Scatter World] leaves cache name set error: {e}")

    def _on_crawl_leaves_cache_folder_browse(self):
        try:
            current = self.crawl_leaves_cache_folder_le.text() or "$HIP/geo"
            try:
                start = hou.expandString(current)
            except Exception:
                start = current
            chosen = QFileDialog.getExistingDirectory(self, "Choose leaves cache folder", start)
            if chosen:
                self.crawl_leaves_cache_folder_le.setText(chosen)
                self._on_crawl_leaves_cache_folder_changed()
        except Exception as e:
            print(f"[Magic Scatter World] leaves cache folder browse error: {e}")

    def _on_crawl_leaves_loadfromdisk_changed(self, checked):
        if self.geo_node is None:
            return
        if not logic.crawl_ivy_network_exists(self.geo_node):
            return
        try:
            logic.set_crawl_leaves_loadfromdisk(self.geo_node, bool(checked))
            self.crawl_status_l.setText(
                "Leaves: Load from Disk ON." if checked else "Leaves: Load from Disk OFF."
            )
            self.crawl_status_l.setStyleSheet("color:#888; font-size:10px;")
        except Exception as e:
            self.crawl_leaves_loadfromdisk_cb.blockSignals(True)
            self.crawl_leaves_loadfromdisk_cb.setChecked(not checked)
            self.crawl_leaves_loadfromdisk_cb.blockSignals(False)
            self.crawl_status_l.setText(f"Leaves Load-from-Disk error: {e}")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_crawl_cache_version_changed(self, value):
        if self.geo_node is not None:
            logic.set_crawl_cache_version(self.geo_node, value)

    def _on_crawl_cache_timedependent_changed(self, checked):
        if self.geo_node is not None:
            logic.set_crawl_cache_timedependent(self.geo_node, bool(checked))

    def _on_crawl_cache_simulation_changed(self, checked):
        if self.geo_node is not None:
            logic.set_crawl_cache_simulation(self.geo_node, bool(checked))

    def _on_crawl_cache_trange_changed(self, idx):
        if self.geo_node is not None:
            logic.set_crawl_cache_trange(self.geo_node, idx)

    def _on_crawl_cache_range_changed(self, *_):
        if self.geo_node is not None:
            logic.set_crawl_cache_frame_range(
                self.geo_node,
                self.crawl_cache_start_sb.value(),
                self.crawl_cache_end_sb.value(),
                self.crawl_cache_inc_sb.value(),
                self.crawl_cache_substeps_sb.value(),
            )

    def _refresh_crawl_cache_widgets(self):
        """Pull crawl cache parm values into the UI widgets (signals blocked)."""
        if self.geo_node is None or not logic.crawl_ivy_network_exists(self.geo_node):
            return
        try:
            basedir      = logic.get_crawl_cache_basedir(self.geo_node)  or "$HIP/geo"
            basename     = logic.get_crawl_cache_basename(self.geo_node) or "$HIPNAME.$OS"
            lfd          = logic.get_crawl_loadfromdisk(self.geo_node)
            version      = logic.get_crawl_cache_version(self.geo_node)
            timedep      = logic.get_crawl_cache_timedependent(self.geo_node)
            trange       = logic.get_crawl_cache_trange(self.geo_node)
            simulation   = logic.get_crawl_cache_simulation(self.geo_node)
            f1, f2, f3, substep = logic.get_crawl_cache_frame_range(self.geo_node)

            for w, val in (
                (self.crawl_cache_folder_le, basedir),
                (self.crawl_cache_name_le,   basename),
            ):
                w.blockSignals(True)
                w.setText(val)
                w.blockSignals(False)

            for w, val in (
                (self.crawl_loadfromdisk_cb, bool(lfd)),
                (self.crawl_cache_timedependent_cb, bool(timedep)),
                (self.crawl_cache_simulation_cb, bool(simulation)),
            ):
                w.blockSignals(True)
                w.setChecked(val)
                w.blockSignals(False)

            self.crawl_cache_trange_cb.blockSignals(True)
            self.crawl_cache_trange_cb.setCurrentIndex(int(trange))
            self.crawl_cache_trange_cb.blockSignals(False)

            for w, val in (
                (self.crawl_cache_version_sb, version),
                (self.crawl_cache_start_sb, f1),
                (self.crawl_cache_end_sb, f2),
                (self.crawl_cache_inc_sb, f3),
                (self.crawl_cache_substeps_sb, substep),
            ):
                w.blockSignals(True)
                w.setValue(int(val))
                w.blockSignals(False)
            pack_on = logic.get_instancer_pack(self.geo_node)
            for w in (self.ivy_pack_instance_cb, self.crawl_pack_instance_cb):
                w.blockSignals(True)
                w.setChecked(pack_on)
                w.blockSignals(False)
            disp_text = logic.get_instancer_display_as(self.geo_node)
            for w in (self.ivy_display_as_cb, self.crawl_display_as_cb):
                w.blockSignals(True)
                w.setCurrentText(disp_text)
                w.setEnabled(pack_on)
                w.blockSignals(False)

            # Resample length
            if hasattr(self, "crawl_resample_len_sb"):
                resample_node = self.geo_node.node("crawl_resample")
                if resample_node is not None:
                    p = resample_node.parm("length")
                    if p is not None:
                        self.crawl_resample_len_sb.blockSignals(True)
                        self.crawl_resample_len_sb.setValue(p.eval())
                        self.crawl_resample_len_sb.blockSignals(False)

            # Leaves cache (CY mode only)
            if self._is_crawling_ivy and hasattr(self, "crawl_leaves_cache_folder_le"):
                leaves_basedir  = logic.get_crawl_leaves_cache_basedir(self.geo_node)  or "$HIP/geo"
                leaves_basename = logic.get_crawl_leaves_cache_basename(self.geo_node) or "$HIPNAME.$OS"
                leaves_lfd      = logic.get_crawl_leaves_loadfromdisk(self.geo_node)
                for w, val in (
                    (self.crawl_leaves_cache_folder_le, leaves_basedir),
                    (self.crawl_leaves_cache_name_le,   leaves_basename),
                ):
                    w.blockSignals(True)
                    w.setText(val)
                    w.blockSignals(False)
                self.crawl_leaves_loadfromdisk_cb.blockSignals(True)
                self.crawl_leaves_loadfromdisk_cb.setChecked(bool(leaves_lfd))
                self.crawl_leaves_loadfromdisk_cb.blockSignals(False)
        except Exception as e:
            print(f"[Magic Scatter World] crawl cache refresh error: {e}")

    # ── Scatter output filecache handlers ───────────────────────────────────

    def _on_scatter_cache_bake(self):
        if self.geo_node is None:
            self._set_status("No scatter network.", error=True)
            return
        try:
            self._push_scatter_cache_params()
            file_path = logic.bake_scatter_cache(self.geo_node)
            self.scatter_cache_load_cb.blockSignals(True)
            self.scatter_cache_load_cb.setChecked(True)
            self.scatter_cache_load_cb.blockSignals(False)
            self._set_status(f"Scatter cache baked: {file_path}" if file_path else "Scatter cache baked.")
        except Exception as e:
            self._set_status(f"Scatter cache bake error: {e}", error=True)
            print(f"[Magic Scatter World] scatter cache bake error: {e}")

    def _get_solaris_frame_range(self):
        """Return (start, end, inc) when the active mode's cache is set to
        Frame Range, else None (current-frame-only export)."""
        try:
            if getattr(self, '_is_crawling_ivy', False):
                if self.crawl_cache_trange_cb.currentIndex() == 1:
                    return (
                        self.crawl_cache_start_sb.value(),
                        self.crawl_cache_end_sb.value(),
                        self.crawl_cache_inc_sb.value(),
                    )
            elif getattr(self, '_mode', 'scatter') == 'ivy':
                if self.ivy_cache_trange_cb.currentIndex() == 1:
                    return (
                        self.ivy_cache_start_sb.value(),
                        self.ivy_cache_end_sb.value(),
                        self.ivy_cache_inc_sb.value(),
                    )
            else:
                if self.scatter_cache_trange_cb.currentIndex() == 1:
                    return (
                        self.scatter_cache_start_sb.value(),
                        self.scatter_cache_end_sb.value(),
                        self.scatter_cache_inc_sb.value(),
                    )
        except Exception:
            pass
        return None

    def _on_send_to_solaris(self):
        if self.geo_node is None:
            self._set_status("No scatter network.", error=True)
            return
        try:
            frame_range = self._get_solaris_frame_range()
            include_wires = False
            if getattr(self, '_is_crawling_ivy', False) and hasattr(self, 'crawl_include_wires_cb'):
                include_wires = self.crawl_include_wires_cb.isChecked()
            elif getattr(self, '_mode', 'scatter') == 'ivy' and hasattr(self, 'ivy_include_wires_cb'):
                include_wires = self.ivy_include_wires_cb.isChecked()
            node = logic.create_solaris_network(
                self.geo_node,
                frame_range=frame_range,
                include_wires=include_wires,
            )
            if frame_range is not None:
                start, end, inc = frame_range
                self._set_status(
                    f"Solaris import created: {node.path()} "
                    f"(sequence {start}–{end} step {inc})"
                )
            else:
                self._set_status(f"Solaris import created: {node.path()}")
        except Exception as e:
            self._set_status(f"Solaris export failed: {e}", error=True)
            print(f"[Magic Scatter World] Solaris export error: {e}")

    def _push_scatter_cache_params(self):
        if self.geo_node is None:
            return
        logic.sync_scatter_cache_parms(self.geo_node, {
            "scatter_cache_basedir": self.scatter_cache_folder_le.text(),
            "scatter_cache_basename": self.scatter_cache_name_le.text(),
            "scatter_cache_version": self.scatter_cache_version_sb.value(),
            "scatter_cache_loadfromdisk": self.scatter_cache_load_cb.isChecked(),
            "scatter_cache_timedependent": self.scatter_cache_timedependent_cb.isChecked(),
            "scatter_cache_trange": self.scatter_cache_trange_cb.currentIndex(),
            "scatter_cache_simulation": self.scatter_cache_simulation_cb.isChecked(),
            "scatter_cache_start": self.scatter_cache_start_sb.value(),
            "scatter_cache_end": self.scatter_cache_end_sb.value(),
            "scatter_cache_inc": self.scatter_cache_inc_sb.value(),
            "scatter_cache_substeps": self.scatter_cache_substeps_sb.value(),
        })

    def _on_scatter_cache_folder_changed(self):
        if self.geo_node is not None:
            logic.set_scatter_cache_basedir(self.geo_node, self.scatter_cache_folder_le.text())

    def _on_scatter_cache_name_changed(self):
        if self.geo_node is not None:
            logic.set_scatter_cache_basename(self.geo_node, self.scatter_cache_name_le.text())

    def _on_scatter_cache_version_changed(self, value):
        if self.geo_node is not None:
            logic.set_scatter_cache_version(self.geo_node, value)

    def _on_scatter_cache_load_changed(self, checked):
        if self.geo_node is not None:
            logic.set_scatter_cache_loadfromdisk(self.geo_node, bool(checked))

    def _on_scatter_cache_timedependent_changed(self, checked):
        if self.geo_node is not None:
            logic.set_scatter_cache_timedependent(self.geo_node, bool(checked))

    def _on_scatter_cache_simulation_changed(self, checked):
        if self.geo_node is not None:
            logic.set_scatter_cache_simulation(self.geo_node, bool(checked))

    def _on_scatter_cache_trange_changed(self, idx):
        if self.geo_node is not None:
            logic.set_scatter_cache_trange(self.geo_node, idx)

    def _on_scatter_cache_range_changed(self, *_):
        if self.geo_node is not None:
            logic.set_scatter_cache_frame_range(
                self.geo_node,
                self.scatter_cache_start_sb.value(),
                self.scatter_cache_end_sb.value(),
                self.scatter_cache_inc_sb.value(),
                self.scatter_cache_substeps_sb.value(),
            )

    def _on_scatter_cache_folder_browse(self):
        try:
            current = self.scatter_cache_folder_le.text() or "$HIP/geo"
            try:
                start = hou.expandString(current)
            except Exception:
                start = current
            chosen = QFileDialog.getExistingDirectory(self, "Choose cache folder", start)
            if chosen:
                self.scatter_cache_folder_le.setText(chosen)
                self._on_scatter_cache_folder_changed()
        except Exception as e:
            print(f"[Magic Scatter World] scatter cache folder browse error: {e}")

    def _refresh_scatter_cache_widgets(self):
        if self.geo_node is None:
            return
        try:
            values = logic.get_scatter_cache_values(self.geo_node)
            for widget, value in (
                (self.scatter_cache_folder_le, values["scatter_cache_basedir"]),
                (self.scatter_cache_name_le, values["scatter_cache_basename"]),
            ):
                widget.blockSignals(True)
                widget.setText(str(value))
                widget.blockSignals(False)
            for widget, value in (
                (self.scatter_cache_load_cb, bool(values["scatter_cache_loadfromdisk"])),
                (self.scatter_cache_timedependent_cb, bool(values["scatter_cache_timedependent"])),
                (self.scatter_cache_simulation_cb, bool(values["scatter_cache_simulation"])),
            ):
                widget.blockSignals(True)
                widget.setChecked(value)
                widget.blockSignals(False)
            self.scatter_cache_trange_cb.blockSignals(True)
            self.scatter_cache_trange_cb.setCurrentIndex(int(values["scatter_cache_trange"]))
            self.scatter_cache_trange_cb.blockSignals(False)
            for widget, value in (
                (self.scatter_cache_version_sb, values["scatter_cache_version"]),
                (self.scatter_cache_start_sb, values["scatter_cache_start"]),
                (self.scatter_cache_end_sb, values["scatter_cache_end"]),
                (self.scatter_cache_inc_sb, values["scatter_cache_inc"]),
                (self.scatter_cache_substeps_sb, values["scatter_cache_substeps"]),
            ):
                widget.blockSignals(True)
                widget.setValue(int(value))
                widget.blockSignals(False)
            pack_on = logic.get_instancer_pack(self.geo_node)
            self.msw_pack_instance_cb.blockSignals(True)
            self.msw_pack_instance_cb.setChecked(pack_on)
            self.msw_pack_instance_cb.blockSignals(False)
            disp_text = logic.get_instancer_display_as(self.geo_node)
            self.msw_display_as_cb.blockSignals(True)
            self.msw_display_as_cb.setCurrentText(disp_text)
            self.msw_display_as_cb.setEnabled(pack_on)
            self.msw_display_as_cb.blockSignals(False)
        except Exception as e:
            print(f"[Magic Scatter World] scatter cache refresh error: {e}")

    # ── Ivy Generation filecache handlers ────────────────────────────────────

    def _on_ivy_bake(self):
        if self.geo_node is None:
            self.ivy_status_l.setText("No scatter network.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        if not logic.ivy_network_exists(self.geo_node):
            self.ivy_status_l.setText("No ivy network — create one first.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        try:
            # Sync Wires
            logic.set_ivy_cache_basedir(self.geo_node, self.ivy_cache_folder_le.text())
            logic.set_ivy_cache_basename(self.geo_node, self.ivy_cache_name_le.text())
            logic.set_ivy_timedependent(self.geo_node, self.ivy_timedependent_cb.isChecked())
            logic.set_ivy_trange(self.geo_node, self.ivy_cache_trange_cb.currentIndex())
            logic.set_ivy_cache_frame_range(
                self.geo_node,
                self.ivy_cache_start_sb.value(),
                self.ivy_cache_end_sb.value(),
                self.ivy_cache_inc_sb.value(),
                self.ivy_cache_substeps_sb.value(),
            )
            # Sync Leaves
            logic.set_scatter_cache_basedir(self.geo_node, self.ivy_leaves_cache_folder_le.text())
            logic.set_scatter_cache_basename(self.geo_node, self.ivy_leaves_cache_name_le.text())
            logic.set_scatter_cache_timedependent(self.geo_node, self.ivy_leaves_timedependent_cb.isChecked())
            logic.set_scatter_cache_trange(self.geo_node, self.ivy_leaves_cache_trange_cb.currentIndex())
            logic.set_scatter_cache_frame_range(
                self.geo_node,
                self.ivy_leaves_cache_start_sb.value(),
                self.ivy_leaves_cache_end_sb.value(),
                self.ivy_leaves_cache_inc_sb.value(),
                self.ivy_leaves_cache_substeps_sb.value(),
            )
        except Exception as e:
            print(f"[Magic Scatter World] ivy cache parm push error: {e}")
        try:
            # Bake Wires
            file_path_wires = logic.bake_ivy(self.geo_node)
            self.ivy_loadfromdisk_cb.blockSignals(True)
            self.ivy_loadfromdisk_cb.setChecked(True)
            self.ivy_loadfromdisk_cb.blockSignals(False)
            
            # Bake Leaves
            file_path_leaves = logic.bake_ivy_leaves(self.geo_node)
            self.ivy_leaves_loadfromdisk_cb.blockSignals(True)
            self.ivy_leaves_loadfromdisk_cb.setChecked(True)
            self.ivy_leaves_loadfromdisk_cb.blockSignals(False)

            msg = "Baked Ivy (Wires + Leaves)."
            if file_path_wires:
                msg = f"Baked → {file_path_wires}"
            self.ivy_status_l.setText(msg)
            self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Bake error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Ivy bake error: {e}")
    def _on_ivy_cache_folder_changed(self):
        if self.geo_node is None:
            return
        try:
            logic.set_ivy_cache_basedir(self.geo_node, self.ivy_cache_folder_le.text())
        except Exception as e:
            print(f"[Magic Scatter World] ivy cache folder set error: {e}")

    def _on_ivy_cache_name_changed(self):
        if self.geo_node is None:
            return
        try:
            logic.set_ivy_cache_basename(self.geo_node, self.ivy_cache_name_le.text())
        except Exception as e:
            print(f"[Magic Scatter World] ivy cache name set error: {e}")

    def _on_ivy_cache_folder_browse(self):
        try:
            current = self.ivy_cache_folder_le.text() or "$HIP/geo"
            try:
                start = hou.expandString(current)
            except Exception:
                start = current
            chosen = QFileDialog.getExistingDirectory(self, "Choose cache folder", start)
            if chosen:
                self.ivy_cache_folder_le.setText(chosen)
                self._on_ivy_cache_folder_changed()
        except Exception as e:
            print(f"[Magic Scatter World] ivy cache folder browse error: {e}")

    def _on_ivy_loadfromdisk_changed(self, checked):
        if self.geo_node is None:
            return
        if not logic.ivy_network_exists(self.geo_node):
            return
        try:
            logic.set_ivy_loadfromdisk(self.geo_node, bool(checked))
            self.ivy_status_l.setText(
                "Cache: Load from Disk ON." if checked else "Cache: Load from Disk OFF."
            )
            self.ivy_status_l.setStyleSheet("color:#888; font-size:10px;")
        except Exception as e:
            self.ivy_loadfromdisk_cb.blockSignals(True)
            self.ivy_loadfromdisk_cb.setChecked(not checked)
            self.ivy_loadfromdisk_cb.blockSignals(False)
            self.ivy_status_l.setText(f"Load-from-Disk error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_ivy_timedependent_changed(self, checked):
        if self.geo_node is None:
            return
        if not logic.ivy_network_exists(self.geo_node):
            return
        try:
            logic.set_ivy_timedependent(self.geo_node, bool(checked))
        except Exception as e:
            print(f"[Magic Scatter World] ivy timedependent set error: {e}")

    def _on_ivy_trange_changed(self, idx):
        if self.geo_node is None:
            return
        if not logic.ivy_network_exists(self.geo_node):
            return
        try:
            logic.set_ivy_trange(self.geo_node, idx)
        except Exception as e:
            print(f"[Magic Scatter World] ivy trange set error: {e}")

    def _on_ivy_cache_range_changed(self, *_):
        if self.geo_node is None or not logic.ivy_network_exists(self.geo_node):
            return
        try:
            logic.set_ivy_cache_frame_range(
                self.geo_node,
                self.ivy_cache_start_sb.value(),
                self.ivy_cache_end_sb.value(),
                self.ivy_cache_inc_sb.value(),
                self.ivy_cache_substeps_sb.value(),
            )
        except Exception as e:
            print(f"[Magic Scatter World] ivy range set error: {e}")

    # ── Ivy Leaves cache handlers ──

    def _on_ivy_leaves_cache_folder_changed(self):
        if self.geo_node is not None:
            logic.set_scatter_cache_basedir(self.geo_node, self.ivy_leaves_cache_folder_le.text())

    def _on_ivy_leaves_cache_name_changed(self):
        if self.geo_node is not None:
            logic.set_scatter_cache_basename(self.geo_node, self.ivy_leaves_cache_name_le.text())

    def _on_ivy_leaves_cache_folder_browse(self):
        try:
            current = self.ivy_leaves_cache_folder_le.text() or "$HIP/geo"
            try:
                start = hou.expandString(current)
            except Exception:
                start = current
            chosen = QFileDialog.getExistingDirectory(self, "Choose cache folder", start)
            if chosen:
                self.ivy_leaves_cache_folder_le.setText(chosen)
                self._on_ivy_leaves_cache_folder_changed()
        except Exception as e:
            print(f"[Magic Scatter World] ivy leaves folder browse error: {e}")

    def _on_ivy_leaves_loadfromdisk_changed(self, checked):
        if self.geo_node is None:
            return
        try:
            logic.set_ivy_leaves_loadfromdisk(self.geo_node, bool(checked))
            self.ivy_status_l.setText(
                "Leaves: Load from Disk ON." if checked else "Leaves: Load from Disk OFF."
            )
            self.ivy_status_l.setStyleSheet("color:#9ac0e0; font-size:10px;")
        except Exception as e:
            self.ivy_leaves_loadfromdisk_cb.blockSignals(True)
            self.ivy_leaves_loadfromdisk_cb.setChecked(not checked)
            self.ivy_leaves_loadfromdisk_cb.blockSignals(False)
            self.ivy_status_l.setText(f"Leaves cache error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] ivy leaves loadfromdisk error: {e}")

    def _on_ivy_leaves_timedependent_changed(self, checked):
        if self.geo_node is not None:
            logic.set_scatter_cache_timedependent(self.geo_node, bool(checked))

    def _on_ivy_leaves_trange_changed(self, idx):
        if self.geo_node is not None:
            logic.set_scatter_cache_trange(self.geo_node, idx)

    def _on_ivy_leaves_cache_range_changed(self, *_):
        if self.geo_node is not None:
            logic.set_scatter_cache_frame_range(
                self.geo_node,
                self.ivy_leaves_cache_start_sb.value(),
                self.ivy_leaves_cache_end_sb.value(),
                self.ivy_leaves_cache_inc_sb.value(),
                self.ivy_leaves_cache_substeps_sb.value(),
            )

    def _refresh_ivy_cache_widgets(self):
        """Pull ivy (wires + leaves) filecache parm values into the UI widgets."""
        if self.geo_node is None or not logic.ivy_network_exists(self.geo_node):
            return
        try:
            # Wires
            w_basedir  = logic.get_ivy_cache_basedir(self.geo_node) or "$HIP/geo"
            w_basename = logic.get_ivy_cache_basename(self.geo_node) or "$HIPNAME.$OS"
            w_lfd      = logic.get_ivy_loadfromdisk(self.geo_node)
            w_timedep  = logic.get_ivy_timedependent(self.geo_node)
            w_trange   = logic.get_ivy_trange(self.geo_node)
            w_f1, w_f2, w_f3, w_sub = logic.get_ivy_cache_frame_range(self.geo_node)

            for w, val in (
                (self.ivy_cache_folder_le, w_basedir),
                (self.ivy_cache_name_le,   w_basename),
            ):
                w.blockSignals(True)
                w.setText(val)
                w.blockSignals(False)

            for w, val in (
                (self.ivy_loadfromdisk_cb, bool(w_lfd)),
                (self.ivy_timedependent_cb, bool(w_timedep)),
            ):
                w.blockSignals(True)
                w.setChecked(val)
                w.blockSignals(False)

            self.ivy_cache_trange_cb.blockSignals(True)
            self.ivy_cache_trange_cb.setCurrentIndex(int(w_trange))
            self.ivy_cache_trange_cb.blockSignals(False)

            for w, val in (
                (self.ivy_cache_start_sb, w_f1),
                (self.ivy_cache_end_sb, w_f2),
                (self.ivy_cache_inc_sb, w_f3),
                (self.ivy_cache_substeps_sb, w_sub),
            ):
                w.blockSignals(True)
                w.setValue(int(val))
                w.blockSignals(False)

            # Leaves
            l_values = logic.get_scatter_cache_values(self.geo_node)
            l_lfd = logic.get_ivy_leaves_loadfromdisk(self.geo_node)
            for w, val in (
                (self.ivy_leaves_cache_folder_le, l_values["scatter_cache_basedir"]),
                (self.ivy_leaves_cache_name_le,   l_values["scatter_cache_basename"]),
            ):
                w.blockSignals(True)
                w.setText(str(val))
                w.blockSignals(False)

            for w, val in (
                (self.ivy_leaves_loadfromdisk_cb, bool(l_lfd)),
                (self.ivy_leaves_timedependent_cb, bool(l_values["scatter_cache_timedependent"])),
            ):
                w.blockSignals(True)
                w.setChecked(val)
                w.blockSignals(False)

            self.ivy_leaves_cache_trange_cb.blockSignals(True)
            self.ivy_leaves_cache_trange_cb.setCurrentIndex(int(l_values["scatter_cache_trange"]))
            self.ivy_leaves_cache_trange_cb.blockSignals(False)

            for w, val in (
                (self.ivy_leaves_cache_start_sb,    l_values["scatter_cache_start"]),
                (self.ivy_leaves_cache_end_sb,      l_values["scatter_cache_end"]),
                (self.ivy_leaves_cache_inc_sb,      l_values["scatter_cache_inc"]),
                (self.ivy_leaves_cache_substeps_sb, l_values["scatter_cache_substeps"]),
            ):
                w.blockSignals(True)
                w.setValue(int(val))
                w.blockSignals(False)

            pack_on = logic.get_instancer_pack(self.geo_node)
            for w in (self.ivy_pack_instance_cb, self.crawl_pack_instance_cb):
                w.blockSignals(True)
                w.setChecked(pack_on)
                w.blockSignals(False)
            disp_text = logic.get_instancer_display_as(self.geo_node)
            for w in (self.ivy_display_as_cb, self.crawl_display_as_cb):
                w.blockSignals(True)
                w.setCurrentText(disp_text)
                w.setEnabled(pack_on)
                w.blockSignals(False)

        except Exception as e:
            print(f"[Magic Scatter World] ivy cache refresh error: {e}")


    def _on_crawl_edit_ramp(self):
        """Select crawl_pscale_ramp so its spare parms show in the parameter pane."""
        if self.geo_node is None:
            hou.ui.displayMessage(
                "No active scatter network.", severity=hou.severityType.Warning)
            return
        node = self.geo_node.node("crawl_pscale_ramp")
        if node is None:
            hou.ui.displayMessage(
                "crawl_pscale_ramp not found — create the Crawling Ivy network first.",
                severity=hou.severityType.Warning)
            return
        try:
            node.setCurrent(True, clear_all_selected=True)
            self.crawl_status_l.setText(
                f"Selected {node.name()} — edit Scale Ramp / Width Ramp in the parm pane."
            )
            self.crawl_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.crawl_status_l.setText(f"Edit ramp error: {e}")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    # ── crawl presets ─────────────────────────────────────────────────────

    def _load_crawl_user_presets(self):
        """Load user-saved crawling-ivy presets from disk."""
        path = _crawl_user_presets_path()
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}
        except Exception as e:
            print(f"[Magic Scatter World] Failed to load user crawl presets: {e}")
        return {}

    def _save_crawl_user_presets(self):
        path = _crawl_user_presets_path()
        try:
            with open(path, "w") as f:
                json.dump(self._crawl_user_presets, f, indent=2)
        except Exception as e:
            print(f"[Magic Scatter World] Failed to save user crawl presets: {e}")
            self.crawl_status_l.setText(f"Crawl preset save error: {e}")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _refresh_crawl_preset_combo(self, select_name=None):
        cb = self.crawl_preset_cb
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("— Select preset —")
        for name in CRAWL_PRESETS.keys():
            cb.addItem(name)
        for name in sorted(self._crawl_user_presets.keys()):
            cb.addItem(name)
        if select_name:
            idx = cb.findText(select_name)
            if idx >= 0:
                cb.setCurrentIndex(idx)
        else:
            cb.setCurrentIndex(0)
        cb.blockSignals(False)

    def _apply_crawl_preset(self, vals):
        """Apply a preset dict to crawl spinboxes, then push + cook."""
        self._prevent_sync = True
        try:
            for name, val in vals.items():
                sb = self._crawl_widgets.get(name)
                if sb is None:
                    continue
                sb.blockSignals(True)
                scale = _CRAWL_FLOAT_SLIDER_SCALES.get(name)
                sb.setValue(int(round(val * scale)) if scale else val)
                sb.blockSignals(False)
                self.state[name] = val
        finally:
            self._prevent_sync = False
        # Always push to the network if it exists, regardless of rt_cb
        if self.geo_node is not None and logic.crawl_ivy_network_exists(self.geo_node):
            try:
                logic.sync_crawl_ivy_params(
                    self.geo_node, self._get_crawl_state(), cook=True)
            except Exception as e:
                print(f"[Magic Scatter World] Crawl preset apply error: {e}")

    def _on_crawl_preset_selected(self, index):
        if index <= 0:
            return
        name = self.crawl_preset_cb.itemText(index)
        vals = CRAWL_PRESETS.get(name) or self._crawl_user_presets.get(name)
        if not vals:
            return
        self._apply_crawl_preset(vals)
        self.crawl_status_l.setText(f"Applied crawl preset '{name}'.")
        self.crawl_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")

    def _on_crawl_preset_save(self):
        name, ok = QInputDialog.getText(
            self, "Save Crawling Ivy Preset", "Preset name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            self.crawl_status_l.setText("Preset name cannot be empty.")
            self.crawl_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        if name in CRAWL_PRESETS:
            QMessageBox.warning(
                self, "Reserved name",
                f"'{name}' is a built-in preset name. Choose a different name.")
            return
        if name in self._crawl_user_presets:
            reply = QMessageBox.question(
                self, "Overwrite preset?",
                f"A preset named '{name}' already exists. Overwrite it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self._crawl_user_presets[name] = self._get_crawl_state()
        self._save_crawl_user_presets()
        self._refresh_crawl_preset_combo(select_name=name)
        self.crawl_status_l.setText(f"Saved crawl preset '{name}'.")
        self.crawl_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")

    def _on_crawl_preset_update(self):
        idx = self.crawl_preset_cb.currentIndex()
        if idx <= 0:
            self.crawl_status_l.setText("Select a user preset to update.")
            self.crawl_status_l.setStyleSheet("color:#e0b898; font-size:10px;")
            return
        name = self.crawl_preset_cb.itemText(idx)
        if name in CRAWL_PRESETS:
            QMessageBox.information(
                self, "Built-in preset",
                f"'{name}' is a built-in preset and cannot be updated. "
                "Use Save to create a new user preset instead.")
            return
        if name not in self._crawl_user_presets:
            return
        self._crawl_user_presets[name] = self._get_crawl_state()
        self._save_crawl_user_presets()
        self.crawl_status_l.setText(f"Updated crawl preset '{name}'.")
        self.crawl_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")

    def _on_crawl_preset_delete(self):
        idx = self.crawl_preset_cb.currentIndex()
        if idx <= 0:
            self.crawl_status_l.setText("Select a user preset to delete.")
            self.crawl_status_l.setStyleSheet("color:#e0b898; font-size:10px;")
            return
        name = self.crawl_preset_cb.itemText(idx)
        if name in CRAWL_PRESETS:
            QMessageBox.information(
                self, "Built-in preset",
                f"'{name}' is a built-in preset and cannot be deleted.")
            return
        if name not in self._crawl_user_presets:
            return
        reply = QMessageBox.question(
            self, "Delete preset?",
            f"Delete preset '{name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        del self._crawl_user_presets[name]
        self._save_crawl_user_presets()
        self._refresh_crawl_preset_combo()
        self.crawl_status_l.setText(f"Deleted crawl preset '{name}'.")
        self.crawl_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")

    # ── wire simulation (Vellum) ──────────────────────────────────────────

    def _get_ivy_sim_state(self):
        """Collect current sim widget values into a state dict."""
        widgets = getattr(self, "_ivy_sim_widgets", {})
        return {k: sb.value() for k, sb in widgets.items()}

    def _restore_ivy_sim_from_meta(self, meta):
        """Restore Simulation-tab values saved as UI metadata."""
        try:
            for name, val in (meta.get("ivy_sim") or {}).items():
                sb = self._ivy_sim_widgets.get(name)
                if sb is None:
                    continue
                sb.blockSignals(True)
                sb.setValue(int(val) if isinstance(sb, QSpinBox) else val)
                sb.blockSignals(False)
                sl = self._ivy_sim_sliders.get(name)
                if sl is not None:
                    sl.blockSignals(True)
                    sl.setValue(int(val) if isinstance(sb, QSpinBox) else int(float(val) * 1000))
                    sl.blockSignals(False)

            length = meta.get("ivy_sim_length") or {}
            if "min_length" in length:
                self._ivy_sim_min_len_sb.setValue(length["min_length"])
                self._ivy_sim_min_len_sl.setValue(int(float(length["min_length"]) * 1000))
            if "max_length" in length:
                self._ivy_sim_max_len_sb.setValue(length["max_length"])
                self._ivy_sim_max_len_sl.setValue(int(float(length["max_length"]) * 1000))

            if "ivy_collision" in meta:
                self.ivy_sim_collision_le.setText(str(meta.get("ivy_collision") or ""))

            glue = meta.get("ivy_glue") or {}
            if "ivy_glue_enabled" in glue:
                self.ivy_glue_enabled_cb.setChecked(bool(glue["ivy_glue_enabled"]))
            if "ivy_glue_distance" in glue:
                self.ivy_glue_distance_sb.setValue(glue["ivy_glue_distance"])
                self.ivy_glue_distance_sl.setValue(int(float(glue["ivy_glue_distance"]) * 1000))
            if "ivy_glue_strength" in glue:
                self.ivy_glue_strength_sb.setValue(glue["ivy_glue_strength"])
                self.ivy_glue_strength_sl.setValue(int(float(glue["ivy_glue_strength"]) * 1000))
        except Exception as e:
            print(f"[Magic Scatter World] ivy sim meta restore error: {e}")

    def _on_ivy_sim_create(self):
        if self.geo_node is None:
            self.ivy_status_l.setText("No geo node. Create ivy first.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        try:
            logic.create_ivy_sim_network(self.geo_node)
            logic.sync_ivy_sim_parms(self.geo_node, self._get_ivy_sim_state())
            logic.sync_ivy_glue_parms(self.geo_node, self._get_ivy_glue_state())
            col_path = self.ivy_sim_collision_le.text().strip()
            if col_path:
                try:
                    logic.set_ivy_sim_collision_object(self.geo_node, col_path)
                except Exception as e:
                    print(f"[Magic Scatter World] Apply initial collision path: {e}")
            self._refresh_sim_cache_widgets()
            self.ivy_status_l.setText("Vellum sim network created.")
            self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Sim create error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Sim create error: {e}")

    def _on_ivy_sim_remove(self):
        if self.geo_node is None:
            return
        if not logic.ivy_sim_network_exists(self.geo_node):
            self.ivy_status_l.setText("No sim network to remove.")
            self.ivy_status_l.setStyleSheet("color:#888; font-size:10px;")
            return
        try:
            logic.remove_ivy_sim_network(self.geo_node)
            self.ivy_status_l.setText("Sim network removed.")
            self.ivy_status_l.setStyleSheet("color:#888; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Sim remove error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_ivy_sim_param_changed(self, *_):
        """Push sim spinbox values to the Vellum SOPs when they exist."""
        if self.geo_node is None:
            return
        self.sync_state(save=True)
        if not logic.ivy_sim_network_exists(self.geo_node):
            return
        try:
            logic.sync_ivy_sim_parms(self.geo_node, self._get_ivy_sim_state())
        except Exception as e:
            print(f"[Magic Scatter World] ivy sim sync error: {e}")

    def _on_ivy_simulate(self):
        if self.geo_node is None:
            return
        if not logic.ivy_sim_network_exists(self.geo_node):
            self.ivy_status_l.setText("Create the sim network first.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        sim = self._get_ivy_sim_state()
        try:
            # Push current params + collision path before simulating
            logic.sync_ivy_sim_parms(self.geo_node, sim)
            self._apply_ivy_sim_collision_path()
            logic.simulate_ivy(
                self.geo_node,
                sim["ivy_sim_start_frame"],
                sim["ivy_sim_end_frame"],
            )
            self.ivy_status_l.setText(
                f"Simulated frames {sim['ivy_sim_start_frame']}–{sim['ivy_sim_end_frame']}."
            )
            self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Simulate error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Simulate error: {e}")

    def _apply_ivy_sim_collision_path(self):
        """
        Read the current Collision line-edit value and push it to
        ivy_sim_collision.objpath1. Safe to call at any time — does nothing
        silently if the geo/sim network isn't available.
        """
        try:
            self._find_ivy_sop()
        except Exception:
            pass
        if self.geo_node is None:
            return
        if not logic.ivy_sim_network_exists(self.geo_node):
            return
        path = self.ivy_sim_collision_le.text().strip()
        try:
            logic.set_ivy_sim_collision_object(self.geo_node, path)
        except Exception as e:
            print(f"[Magic Scatter World] Collision apply error: {e}")

    def _browse_ivy_sim_collision(self):
        """Open Houdini's node-picker and push the result to the SOP."""
        try:
            picked = hou.ui.selectNode(
                title="Pick Collision Node",
                node_type_filter=hou.nodeTypeFilter.NoFilter,
            )
        except Exception as e:
            self.ivy_status_l.setText(f"Node picker error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        if not picked:
            return
        self.ivy_sim_collision_le.setText(picked)
        self._on_ivy_sim_collision_changed()

    def _on_ivy_sim_collision_changed(self):
        """Push the line-edit path to ivy_sim_collision's objpath1."""
        # Refresh self.geo_node from the tracked scatter SOP if it's stale.
        try:
            self._find_ivy_sop()
        except Exception:
            pass
        if self.geo_node is None:
            self.ivy_status_l.setText("No ivy geo — create ivy/sim first.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        path = self.ivy_sim_collision_le.text().strip()
        # If the sim network isn't built yet we can't write the parm. Keep
        # the path in the line edit — _on_ivy_sim_create will apply it.
        if not logic.ivy_sim_network_exists(self.geo_node):
            self.ivy_status_l.setText(
                "Path stored — will apply when Create Sim is pressed."
            )
            self.ivy_status_l.setStyleSheet("color:#888; font-size:10px;")
            return
        try:
            logic.set_ivy_sim_collision_object(self.geo_node, path)
            if path:
                self.ivy_status_l.setText(f"Collision → {path}")
                self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
            else:
                self.ivy_status_l.setText("Collision cleared.")
                self.ivy_status_l.setStyleSheet("color:#888; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Collision set error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Collision set error: {e}")

    def _on_ivy_wire_toggle(self):
        """Toggle bypass on both the ivy_wire and crawl_wire (PolyWire) SOPs."""
        if self.geo_node is None:
            self.ivy_wire_toggle_btn.setChecked(False)
            self.ivy_status_l.setText("No geo node. Create ivy first.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        bypass = self.ivy_wire_toggle_btn.isChecked()
        try:
            logic.set_ivy_wire_bypass(self.geo_node, bypass)
            crawl_toggled = logic.set_crawl_wire_bypass(self.geo_node, bypass)
            self.ivy_wire_toggle_btn.setText(
                "Enable Ivy Wire" if bypass else "Disable Ivy Wire"
            )
            label = "ivy_wire + crawl_wire" if crawl_toggled else "ivy_wire"
            self.ivy_status_l.setText(
                f"{label} disabled." if bypass else f"{label} enabled."
            )
            self.ivy_status_l.setStyleSheet(
                ("color:#e0b898;" if bypass else "color:#5fdb5f;") + " font-size:10px;"
            )
        except Exception as e:
            self.ivy_wire_toggle_btn.setChecked(not bypass)
            self.ivy_status_l.setText(f"wire toggle error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_instancer_toggle(self):
        """Toggle bypass on the instancer (CopyToPoints) SOP — hide/show scattered geometry."""
        if self.geo_node is None:
            self.instancer_toggle_btn.setChecked(False)
            self.ivy_status_l.setText("No active scatter network.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        bypass = self.instancer_toggle_btn.isChecked()
        try:
            logic.set_instancer_bypass(self.geo_node, bypass)
            self.instancer_toggle_btn.setText(
                "Show Assets " if bypass else "Hide Assets "
            )
            self.ivy_status_l.setText(
                "instancer disabled — scattered geometry hidden."
                if bypass else "instancer enabled — scattered geometry visible."
            )
            self.ivy_status_l.setStyleSheet(
                ("color:#e0b898;" if bypass else "color:#5fdb5f;") + " font-size:10px;"
            )
        except Exception as e:
            self.instancer_toggle_btn.setChecked(not bypass)
            self.ivy_status_l.setText(f"instancer toggle error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_msw_pack_instance_changed(self, checked):
        self.msw_display_as_cb.setEnabled(checked)
        if self.geo_node is None:
            return
        try:
            logic.set_instancer_pack(self.geo_node, checked)
        except Exception as e:
            print(f"[Magic Scatter World] pack instance error: {e}")

    def _on_msw_display_as_changed(self, text):
        if self.geo_node is None:
            return
        try:
            logic.set_instancer_display_as(self.geo_node, text)
        except Exception as e:
            print(f"[Magic Scatter World] display as error: {e}")

    def _on_ivy_pack_instance_changed(self, checked):
        self.ivy_display_as_cb.setEnabled(checked)
        if self.geo_node is None:
            return
        try:
            logic.set_instancer_pack(self.geo_node, checked)
            self.crawl_pack_instance_cb.blockSignals(True)
            self.crawl_pack_instance_cb.setChecked(checked)
            self.crawl_pack_instance_cb.blockSignals(False)
            self.crawl_display_as_cb.setEnabled(checked)
        except Exception as e:
            print(f"[Magic Scatter World] pack instance error: {e}")

    def _on_ivy_display_as_changed(self, text):
        if self.geo_node is None:
            return
        try:
            logic.set_instancer_display_as(self.geo_node, text)
        except Exception as e:
            print(f"[Magic Scatter World] display as error: {e}")

    def _on_crawl_pack_instance_changed(self, checked):
        self.crawl_display_as_cb.setEnabled(checked)
        if self.geo_node is None:
            return
        try:
            logic.set_instancer_pack(self.geo_node, checked)
            self.ivy_pack_instance_cb.blockSignals(True)
            self.ivy_pack_instance_cb.setChecked(checked)
            self.ivy_pack_instance_cb.blockSignals(False)
            self.ivy_display_as_cb.setEnabled(checked)
        except Exception as e:
            print(f"[Magic Scatter World] pack instance error: {e}")

    def _on_crawl_display_as_changed(self, text):
        if self.geo_node is None:
            return
        try:
            logic.set_instancer_display_as(self.geo_node, text)
        except Exception as e:
            print(f"[Magic Scatter World] display as error: {e}")

    def _on_ivy_edit_ramp(self):
        """Select ivy_pscale_ramp so Houdini's parameter pane shows its spare parms."""
        if self.geo_node is None:
            hou.ui.displayMessage(
                "No active scatter network.", severity=hou.severityType.Warning)
            return
        node = self.geo_node.node("ivy_pscale_ramp")
        if node is None:
            hou.ui.displayMessage(
                "ivy_pscale_ramp not found — create the ivy network first.",
                severity=hou.severityType.Warning)
            return
        try:
            node.setCurrent(True, clear_all_selected=True)
            self.ivy_status_l.setText(
                f"Selected {node.name()} — edit Scale Ramp / Width Ramp in the parm pane."
            )
            self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Edit ramp error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_ivy_sim_loadfromdisk_changed(self):
        """Push the checkbox value to ivy_sim_cache.loadfromdisk."""
        if self.geo_node is None:
            return
        if not logic.ivy_sim_network_exists(self.geo_node):
            return
        enabled = self.ivy_sim_loadfromdisk_cb.isChecked()
        try:
            logic.set_ivy_sim_loadfromdisk(self.geo_node, enabled)
            self.ivy_status_l.setText(
                "Cache: Load from Disk ON." if enabled else "Cache: Load from Disk OFF."
            )
            self.ivy_status_l.setStyleSheet("color:#888; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Load-from-Disk error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_ivy_sim_reset(self):
        if self.geo_node is None:
            return
        if not logic.ivy_sim_network_exists(self.geo_node):
            self.ivy_status_l.setText("Create the sim network first.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        try:
            self._apply_ivy_sim_collision_path()
            logic.reset_ivy_sim(self.geo_node)
            self.ivy_status_l.setText("Simulation reset.")
            self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        except Exception as e:
            self.ivy_status_l.setText(f"Reset error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Sim reset error: {e}")

    def _on_ivy_sim_render(self):
        if self.geo_node is None:
            return
        if not logic.ivy_sim_network_exists(self.geo_node):
            self.ivy_status_l.setText("Create the sim network first.")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            return
        sim = self._get_ivy_sim_state()
        start = self.sim_cache_start_sb.value()
        end   = self.sim_cache_end_sb.value()
        inc   = self.sim_cache_inc_sb.value()
        subs  = self.sim_cache_substeps_sb.value()
        try:
            logic.sync_ivy_sim_parms(self.geo_node, sim)
            self._apply_ivy_sim_collision_path()
            logic.set_sim_cache_basedir(self.geo_node, self.sim_cache_folder_le.text())
            logic.set_sim_cache_basename(self.geo_node, self.sim_cache_name_le.text())
            logic.render_ivy_sim_to_disk(self.geo_node, start, end, inc, subs)
            self.ivy_status_l.setText(f"Rendered {start}–{end} to disk.")
            self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
            self.ivy_sim_loadfromdisk_cb.blockSignals(True)
            self.ivy_sim_loadfromdisk_cb.setChecked(True)
            self.ivy_sim_loadfromdisk_cb.blockSignals(False)
        except Exception as e:
            self.ivy_status_l.setText(f"Render error: {e}")
            self.ivy_status_l.setStyleSheet("color:#ff6060; font-size:10px;")
            print(f"[Magic Scatter World] Render error: {e}")

    def _on_sim_cache_range_changed(self, *_):
        if self.geo_node is not None and logic.ivy_sim_network_exists(self.geo_node):
            try:
                logic.set_sim_cache_frame_range(
                    self.geo_node,
                    self.sim_cache_start_sb.value(),
                    self.sim_cache_end_sb.value(),
                    self.sim_cache_inc_sb.value(),
                    self.sim_cache_substeps_sb.value(),
                )
            except Exception as e:
                print(f"[Magic Scatter World] sim cache range set error: {e}")

    def _on_sim_cache_folder_changed(self):
        if self.geo_node is None:
            return
        try:
            logic.set_sim_cache_basedir(self.geo_node, self.sim_cache_folder_le.text())
        except Exception as e:
            print(f"[Magic Scatter World] sim cache folder set error: {e}")

    def _on_sim_cache_name_changed(self):
        if self.geo_node is None:
            return
        try:
            logic.set_sim_cache_basename(self.geo_node, self.sim_cache_name_le.text())
        except Exception as e:
            print(f"[Magic Scatter World] sim cache name set error: {e}")

    def _on_sim_cache_folder_browse(self):
        try:
            current = self.sim_cache_folder_le.text() or "$HIP/geo"
            try:
                start = hou.expandString(current)
            except Exception:
                start = current
            chosen = QFileDialog.getExistingDirectory(self, "Choose cache folder", start)
            if chosen:
                self.sim_cache_folder_le.setText(chosen)
                self._on_sim_cache_folder_changed()
        except Exception as e:
            print(f"[Magic Scatter World] sim cache folder browse error: {e}")

    def _refresh_sim_cache_widgets(self):
        """Pull ivy_sim_cache settings into the UI widgets."""
        if self.geo_node is None or not logic.ivy_sim_network_exists(self.geo_node):
            return
        try:
            basedir  = logic.get_sim_cache_basedir(self.geo_node)  or "$HIP/geo"
            basename = logic.get_sim_cache_basename(self.geo_node) or "$HIPNAME.$OS"
            for w, val in (
                (self.sim_cache_folder_le, basedir),
                (self.sim_cache_name_le,   basename),
            ):
                w.blockSignals(True)
                w.setText(val)
                w.blockSignals(False)
            self.ivy_sim_loadfromdisk_cb.blockSignals(True)
            self.ivy_sim_loadfromdisk_cb.setChecked(logic.get_ivy_sim_loadfromdisk(self.geo_node))
            self.ivy_sim_loadfromdisk_cb.blockSignals(False)
            f1, f2, f3, substep = logic.get_sim_cache_frame_range(self.geo_node)
            for w, val in (
                (self.sim_cache_start_sb,    f1),
                (self.sim_cache_end_sb,      f2),
                (self.sim_cache_inc_sb,      f3),
                (self.sim_cache_substeps_sb, substep),
            ):
                w.blockSignals(True)
                w.setValue(int(val))
                w.blockSignals(False)
        except Exception as e:
            print(f"[Magic Scatter World] sim cache refresh error: {e}")

    def _refresh_ivy_sim_widgets(self):
        """Pull Simulation-tab values from the existing Houdini sim network."""
        if self.geo_node is None or not logic.ivy_sim_network_exists(self.geo_node):
            return
        try:
            sim_values = logic.get_ivy_sim_params(self.geo_node)
            for name, val in sim_values.items():
                sb = self._ivy_sim_widgets.get(name)
                if sb is not None:
                    sb.blockSignals(True)
                    sb.setValue(int(val) if isinstance(sb, QSpinBox) else val)
                    sb.blockSignals(False)
                sl = self._ivy_sim_sliders.get(name)
                if sl is not None:
                    sl.blockSignals(True)
                    sl.setValue(int(val) if isinstance(sb, QSpinBox) else int(float(val) * 1000))
                    sl.blockSignals(False)

            length_values = logic.get_ivy_sim_length_scale(self.geo_node)
            self._ivy_sim_min_len_sb.blockSignals(True)
            self._ivy_sim_min_len_sb.setValue(length_values["min_length"])
            self._ivy_sim_min_len_sb.blockSignals(False)
            self._ivy_sim_min_len_sl.blockSignals(True)
            self._ivy_sim_min_len_sl.setValue(int(length_values["min_length"] * 1000))
            self._ivy_sim_min_len_sl.blockSignals(False)
            self._ivy_sim_max_len_sb.blockSignals(True)
            self._ivy_sim_max_len_sb.setValue(length_values["max_length"])
            self._ivy_sim_max_len_sb.blockSignals(False)
            self._ivy_sim_max_len_sl.blockSignals(True)
            self._ivy_sim_max_len_sl.setValue(int(length_values["max_length"] * 1000))
            self._ivy_sim_max_len_sl.blockSignals(False)

            self.ivy_sim_collision_le.blockSignals(True)
            self.ivy_sim_collision_le.setText(logic.get_ivy_sim_collision_object(self.geo_node))
            self.ivy_sim_collision_le.blockSignals(False)

            glue_values = logic.get_ivy_glue_params(self.geo_node)
            self.ivy_glue_enabled_cb.blockSignals(True)
            self.ivy_glue_enabled_cb.setChecked(bool(glue_values["ivy_glue_enabled"]))
            self.ivy_glue_enabled_cb.blockSignals(False)
            self.ivy_glue_distance_sb.blockSignals(True)
            self.ivy_glue_distance_sb.setValue(glue_values["ivy_glue_distance"])
            self.ivy_glue_distance_sb.blockSignals(False)
            self.ivy_glue_distance_sl.blockSignals(True)
            self.ivy_glue_distance_sl.setValue(int(glue_values["ivy_glue_distance"] * 1000))
            self.ivy_glue_distance_sl.blockSignals(False)
            self.ivy_glue_strength_sb.blockSignals(True)
            self.ivy_glue_strength_sb.setValue(glue_values["ivy_glue_strength"])
            self.ivy_glue_strength_sb.blockSignals(False)
            self.ivy_glue_strength_sl.blockSignals(True)
            self.ivy_glue_strength_sl.setValue(int(glue_values["ivy_glue_strength"] * 1000))
            self.ivy_glue_strength_sl.blockSignals(False)
        except Exception as e:
            print(f"[Magic Scatter World] ivy sim widget refresh error: {e}")

    def _refresh_ivy_appearance_widgets(self):
        """Pull Appearance-tab values from live Ivy nodes."""
        if self.geo_node is None or not logic.ivy_network_exists(self.geo_node):
            return
        try:
            resample = logic.get_ivy_resample_settings(self.geo_node)
            self.ivy_subdivide_cb.blockSignals(True)
            self.ivy_subdivide_cb.setChecked(bool(resample["subdivide"]))
            self.ivy_subdivide_cb.blockSignals(False)
            self.ivy_resample_len_sb.blockSignals(True)
            self.ivy_resample_len_sb.setValue(float(resample["length"]))
            self.ivy_resample_len_sb.blockSignals(False)
            self.ivy_resample_len_sl.blockSignals(True)
            self.ivy_resample_len_sl.setValue(int(float(resample["length"]) * 1000))
            self.ivy_resample_len_sl.blockSignals(False)

            for name, val in logic.get_ivy_noise_params(self.geo_node).items():
                sb = self._ivy_noise_widgets.get(name)
                if sb is not None:
                    sb.blockSignals(True)
                    sb.setValue(int(val) if isinstance(sb, QSpinBox) else val)
                    sb.blockSignals(False)
                sl = self._ivy_noise_sliders.get(name)
                if sl is not None:
                    sl.blockSignals(True)
                    sl.setValue(int(val) if isinstance(sb, QSpinBox) else int(float(val) * 1000))
                    sl.blockSignals(False)

            if hasattr(self, "ivy_geo_offset_sb"):
                self.ivy_geo_offset_sb.blockSignals(True)
                self.ivy_geo_offset_sb.setValue(logic.get_ivy_geo_offset(self.geo_node))
                self.ivy_geo_offset_sb.blockSignals(False)
                self.ivy_geo_offset_sl.blockSignals(True)
                self.ivy_geo_offset_sl.setValue(int(logic.get_ivy_geo_offset(self.geo_node) * 1000))
                self.ivy_geo_offset_sl.blockSignals(False)

            wire_bypassed = logic.get_ivy_wire_bypass(self.geo_node)
            self.ivy_wire_toggle_btn.blockSignals(True)
            self.ivy_wire_toggle_btn.setChecked(wire_bypassed)
            self.ivy_wire_toggle_btn.setText("Enable Ivy Wire" if wire_bypassed else "Disable Ivy Wire")
            self.ivy_wire_toggle_btn.blockSignals(False)

            instancer_bypassed = logic.get_instancer_bypass(self.geo_node)
            self.instancer_toggle_btn.blockSignals(True)
            self.instancer_toggle_btn.setChecked(instancer_bypassed)
            self.instancer_toggle_btn.setText("Show Assets " if instancer_bypassed else "Hide Assets ")
            self.instancer_toggle_btn.blockSignals(False)
        except Exception as e:
            print(f"[Magic Scatter World] ivy appearance refresh error: {e}")

    def _refresh_ivy_transform_widgets(self):
        """Pull shared Paint Mask / Transformation values from live Ivy nodes."""
        if self.geo_node is None:
            return
        try:
            values = logic.get_ivy_transform_params(self.geo_node)
            for key, widget in (
                ("radius", self.r_sb),
                ("density", self.d_sb),
                ("spacing", self.s_sb),
                ("falloff_amount", self.fa_sb),
                ("falloff_softness", self.fs_sb),
                ("relax_iter", self.relax_sb),
                ("max_points", self.max_pts_sb),
                ("rot_min", self.rot_min_sb),
                ("rot_max", self.rot_max_sb),
                ("rot_randomize", self.rot_rand_sb),
                ("global_scale", self.gs_sb),
                ("pscale_randomize", self.pscale_rand_sb),
            ):
                if key in values:
                    widget.setValue(int(values[key]) if isinstance(widget, QSpinBox) else values[key])
            if "full_rand" in values:
                self.full_rand_cb.setChecked(bool(values["full_rand"]))
            if "uniform_xyz" in values:
                self.uni_cb.setChecked(bool(values["uniform_xyz"]))
                self._on_uniform_toggled(self.uni_cb.isChecked())
            if "scl_min" in values:
                vals = values["scl_min"]
                self.smn_x.setValue(vals[0])
                self.smn_y.setValue(vals[1])
                self.smn_z.setValue(vals[2])
            if "scl_max" in values:
                vals = values["scl_max"]
                self.smx_x.setValue(vals[0])
                self.smx_y.setValue(vals[1])
                self.smx_z.setValue(vals[2])
        except Exception as e:
            print(f"[Magic Scatter World] ivy transform refresh error: {e}")

    def _on_ivy_sim_length_changed(self, *_):
        ivy_sop = self._find_ivy_sop()
        if ivy_sop is None:
            return
        try:
            logic.sync_ivy_sim_length_scale(
                ivy_sop.parent(),
                self._ivy_sim_min_len_sb.value(),
                self._ivy_sim_max_len_sb.value(),
            )
        except Exception as e:
            print(f"[Magic Scatter World] length scale sync error: {e}")

    def _on_ivy_geo_offset_changed(self, *_):
        ivy_sop = self._find_ivy_sop()
        geo_node = ivy_sop.parent() if ivy_sop is not None else self.geo_node
        if geo_node is None:
            return
        val = self.ivy_geo_offset_sb.value()
        try:
            logic.sync_ivy_geo_offset(geo_node, val)
        except Exception as e:
            print(f"[Magic Scatter World] ivy geo offset sync error: {e}")
        try:
            logic.sync_crawl_geo_offset(geo_node, val)
        except Exception as e:
            print(f"[Magic Scatter World] crawl geo offset sync error: {e}")

    def _get_ivy_glue_state(self):
        """Collect the current glue widget values into a state dict."""
        return {
            "ivy_glue_enabled":  self.ivy_glue_enabled_cb.isChecked(),
            "ivy_glue_distance": self.ivy_glue_distance_sb.value(),
            "ivy_glue_strength": self.ivy_glue_strength_sb.value(),
        }

    def _on_ivy_glue_changed(self, *_):
        """Push glue widget values to ivy_sim_glue_constraints when it exists."""
        if self.geo_node is None:
            return
        if not logic.ivy_sim_network_exists(self.geo_node):
            return
        try:
            logic.sync_ivy_glue_parms(self.geo_node, self._get_ivy_glue_state())
        except Exception as e:
            print(f"[Magic Scatter World] ivy glue sync error: {e}")

    # ── status bar ────────────────────────────────────────────────────────
    def _build_status_bar(self):
        lay = QHBoxLayout()
        self.count_l = QLabel("0 pts")
        self.count_l.setObjectName("count_label")
        self.status_l = QLabel("Ready")
        self.status_l.setStyleSheet("color:#888; font-size:10px;")
        lay.addWidget(self.count_l)
        lay.addStretch()
        lay.addWidget(self.status_l)
        return lay

    # ======================================================================
    # Scene / asset management
    # ======================================================================

    def _set_surface(self):
        """Replace the entire surface list with the selected node(s)."""
        try:
            sel = hou.selectedNodes()
            if not sel:
                hou.ui.displayMessage("Select a geometry node first.",
                                      severity=hou.severityType.Warning)
                return
            self.surface_paths = [n.path() for n in sel]
            self._apply_surface_paths()
            self._set_status(f"{len(self.surface_paths)} surface(s) set.")
            self.sync_state()
        except Exception as e:
            self._set_status(f"Error: {e}", error=True)

    def _add_surface(self):
        """Append selected node(s) to the surface list."""
        try:
            sel = hou.selectedNodes()
            if not sel:
                hou.ui.displayMessage("Select a geometry node first.",
                                      severity=hou.severityType.Warning)
                return
            for n in sel:
                if n.path() not in self.surface_paths:
                    self.surface_paths.append(n.path())
            self._apply_surface_paths()
            self._set_status(f"{len(self.surface_paths)} surface(s) set.")
            self.sync_state()
        except Exception as e:
            self._set_status(f"Error: {e}", error=True)

    def _remove_surface(self, path):
        """Remove a surface from the list by path."""
        try:
            if path in self.surface_paths:
                self.surface_paths.remove(path)
            self._apply_surface_paths()
            self.sync_state()
        except Exception as e:
            self._set_status(f"Error: {e}", error=True)

    def _apply_surface_paths(self):
        """Push surface_paths to UI label, surface list widget, and Houdini network."""
        if not self.surface_paths:
            self.surf_l.setText("Surface: —")
        else:
            name = self.surface_paths[0].split("/")[-1]
            extra = f" +{len(self.surface_paths)-1}" if len(self.surface_paths) > 1 else ""
            self.surf_l.setText(f"Surface: {name}{extra}")
        self._refresh_surface_list()
        self._measure_surface()
        if self.scatter_sop_node and self.surface_paths:
            geo = self.scatter_sop_node.parent()
            logic.update_surface_inputs(geo, self.surface_paths)

    def _refresh_surface_list(self):
        """Rebuild the collapsible surface dropdown list."""
        layout = self._surf_list_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        paths = self.surface_paths
        multi = len(paths) > 1

        # Show all surfaces (including primary) in the dropdown so every entry
        # can be deleted, including the primary (which moves paths[1] to primary).
        for path in paths:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(path.split("/")[-1])
            lbl.setToolTip(path)
            lbl.setStyleSheet("color: #c8d8e8; font-size: 11px; padding: 1px 4px;")
            btn = QPushButton("Delete")
            btn.setFixedHeight(18)
            btn.setStyleSheet(
                "QPushButton { background-color: #5c1a1a; color: #e09a9a;"
                "  border-color: #8b2b2b; font-size: 10px; padding: 0 6px; }"
                "QPushButton:hover { background-color: #7a2424; border-color: #c83c3c; }"
            )
            btn.clicked.connect(lambda _=False, p=path: self._remove_surface(p))
            row.addWidget(lbl, 1)
            row.addWidget(btn)
            w = QWidget()
            w.setStyleSheet("QWidget { background: transparent; border: none; }")
            w.setLayout(row)
            layout.addWidget(w)

        # Update toggle button
        self._surf_toggle_btn.setVisible(multi)
        if not multi:
            # Collapse automatically when back to one surface
            self._surf_toggle_btn.blockSignals(True)
            self._surf_toggle_btn.setChecked(False)
            self._surf_toggle_btn.blockSignals(False)
            self._surf_list_w.setVisible(False)
        else:
            n = len(paths)
            arrow = "▲" if self._surf_toggle_btn.isChecked() else "▼"
            self._surf_toggle_btn.setText(f"{arrow} {n} surfaces")
            # Keep list visible state as-is (user controls it)

    def _on_scatter_on_scatter(self):
        """Use the instanced output of a selected scatter network as a surface.

        Selects node(s) in the Houdini viewport, checks each is a Magic Scatter
        geo node, creates the unpack output chain in the source network, then
        adds that path to this network's surface list.
        """
        try:
            sel = hou.selectedNodes()
            if not sel:
                hou.ui.displayMessage(
                    "Select a Magic Scatter geo node in the viewport first.",
                    severity=hou.severityType.Warning,
                )
                return

            added = 0
            skipped = []
            for node in sel:
                # Accept the geo node directly or a SOP inside it
                geo = node if node.type().name() == "geo" else node.parent()
                if geo is None or geo.userData(logic.SCATTER_TAG) != "1":
                    skipped.append(node.name())
                    continue
                if self.geo_node and geo.path() == self.geo_node.path():
                    skipped.append(node.name() + " (same network)")
                    continue
                path = logic.ensure_scatter_on_scatter_output(geo)
                if path and path not in self.surface_paths:
                    self.surface_paths.append(path)
                    added += 1

            if skipped:
                hou.ui.displayMessage(
                    f"Skipped (not a Magic Scatter geo node): {', '.join(skipped)}",
                    severity=hou.severityType.Warning,
                )
            if added:
                self._apply_surface_paths()
                self._set_status(f"Scatter-on-scatter: {added} source(s) added.")
                self.sync_state()
            elif not skipped:
                self._set_status("No new scatter sources added.", error=False)
        except Exception as e:
            self._set_status(f"Scatter-on-scatter error: {e}", error=True)

    def _measure_surface(self):
        """Measure bounding box across all surfaces and update altitude-mask Y range."""
        self._surface_y_min = 0.0
        self._surface_y_max = 1.0
        self._surface_size = (0.0, 0.0)
        paths = getattr(self, "surface_paths", [])
        if not paths:
            return
        try:
            xmins, ymins, zmins, xmaxs, ymaxs, zmaxs = [], [], [], [], [], []
            for path in paths:
                node = hou.node(path)
                bb = logic.measure_surface_bbox(node)
                if bb is None:
                    continue
                (x0, y0, z0), (x1, y1, z1) = bb
                xmins.append(x0); ymins.append(y0); zmins.append(z0)
                xmaxs.append(x1); ymaxs.append(y1); zmaxs.append(z1)
            if not xmins:
                return
            xmin, ymin, zmin = min(xmins), min(ymins), min(zmins)
            xmax, ymax, zmax = max(xmaxs), max(ymaxs), max(zmaxs)
            self._surface_y_min = float(ymin)
            self._surface_y_max = float(ymax)
            self._surface_size = (xmax - xmin, zmax - zmin)
            name = paths[0].split("/")[-1]
            extra = f" +{len(paths)-1}" if len(paths) > 1 else ""
            self.surf_l.setText(
                f"Surface: {name}{extra}  ·  "
                f"{(xmax - xmin):.1f}×{(zmax - zmin):.1f} u, "
                f"Y: {ymin:.1f} → {ymax:.1f}"
            )
            if hasattr(self, "_alt_y_range_lbl"):
                self._alt_y_range_lbl.setText(
                    f"Y: {ymin:.1f} → {ymax:.1f} (range {(ymax - ymin):.1f})"
                )
        except Exception as e:
            print(f"[Magic Scatter World] _measure_surface: {e}")

    def _add_objects(self):
        try:
            for node in hou.selectedNodes():
                self._add_asset(node.path(), update_layout=False)
            self._refresh_asset_layout()
            self._save_asset_paths()
            if self.scatter_sop_node:
                logic.update_instancing_network(
                    self.scatter_sop_node,
                    [w.node_path for w in self.asset_rows]
                )
                self._reapply_lookdev_bindings(self.scatter_sop_node)
            self.sync_state()
            self._set_status(f"{len(self.asset_rows)} asset(s) loaded.")
        except Exception as e:
            self._set_status(f"Error: {e}", error=True)

    def _add_asset(self, node_path, update_layout=True):
        if any(w.node_path == node_path for w in self.asset_rows):
            return
        aw = AssetWidget(node_path, self, self._asset_container)
        if self._asset_size_preset != "small":
            aw.set_size(*_ASSET_SIZE_PRESETS[self._asset_size_preset])
        aw.rem_btn.clicked.connect(lambda: self._remove_asset(aw))
        self.asset_rows.append(aw)
        self._asset_layout.addWidget(aw)
        if update_layout:
            self._refresh_asset_layout()

    def _remove_asset(self, aw):
        if aw not in self.asset_rows:
            return
        self.asset_rows.remove(aw)
        # remove from FlowLayout
        for i in range(self._asset_layout.count()):
            if self._asset_layout.itemAt(i) and self._asset_layout.itemAt(i).widget() is aw:
                self._asset_layout.takeAt(i)
                break
        aw.hide()
        aw.deleteLater()
        self._refresh_asset_layout()
        self._save_asset_paths()
        if self.scatter_sop_node:
            logic.update_instancing_network(
                self.scatter_sop_node,
                [w.node_path for w in self.asset_rows]
            )
            self._reapply_lookdev_bindings(self.scatter_sop_node)
        self.sync_state()

    def _refresh_asset_layout(self):
        self._asset_container.update()
        self._asset_layout.invalidate()
        self._rebuild_lod_asset_table()

    def _show_asset_context_menu(self, global_pos):
        menu = QMenu(self)
        menu.setTitle("Thumbnail Size")
        for key, label in (("small", "Small"), ("medium", "Medium"),
                           ("large", "Large"), ("huge", "Huge")):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._asset_size_preset == key)
            action.triggered.connect(lambda _=False, k=key: self._resize_assets(k))
        menu.exec_(global_pos)

    def _resize_assets(self, preset):
        self._asset_size_preset = preset
        card_w, card_h, thumb_size = _ASSET_SIZE_PRESETS[preset]
        for aw in self.asset_rows:
            aw.set_size(card_w, card_h, thumb_size)
        self._refresh_asset_layout()

    def _clear_assets(self):
        while self._asset_layout.count():
            item = self._asset_layout.takeAt(0)
            if item:
                wi = item.widget()
                if wi:
                    wi.hide()
                    wi.deleteLater()
        self.asset_rows = []

    def _save_asset_paths(self):
        if self.scatter_sop_node:
            logic.save_asset_node_paths(
                self.scatter_sop_node,
                [w.node_path for w in self.asset_rows],
                weights=[w.weight_sl.value() / 100.0 for w in self.asset_rows],
            )

    def _on_asset_clicked(self, aw, modifiers):
        if modifiers & Qt.ControlModifier:
            aw.setSelected(not aw.selected)
        else:
            for x in self.asset_rows:
                x.setSelected(x is aw)
        self.sync_state()

    # ── setup management ──────────────────────────────────────────────────

    def _on_new_setup(self):
        self._prevent_sync = True
        try:
            self.scatter_sop_node  = None
            self.geo_node          = None
            self.surface_paths     = []
            self.surf_l.setText("Surface: —")
            self._refresh_surface_list()
            self.node_l.setText("Node: —")
            self.resume_cb.blockSignals(True)
            self.resume_cb.setCurrentIndex(0)
            self.resume_cb.blockSignals(False)
            self._clear_assets()
            self._placement_rules = []
            self._rule_cards = []
            self._rebuild_rules_ui()
        finally:
            self._prevent_sync = False
            self.sync_state(save=False)
        self._update_point_count()
        self._set_status("New setup ready.")
        # ivy_status_l only exists in ivy mode.
        if self._mode == "ivy":
            self.ivy_status_l.setText("No ivy network.")
            self.ivy_status_l.setStyleSheet("color:#888; font-size:10px;")

    def _on_create(self):
        text, ok = QInputDialog.getText(self, "Create Scatter Network", "Prefix name:")
        if not ok or not text.strip():
            return
        try:
            obj = hou.node("/obj")
            geo, sop = logic.create_scatter_network(obj, text.strip())
            self.geo_node         = geo
            self.scatter_sop_node = sop
            self.node_l.setText(f"Node: {sop.path()}")
            if self.surface_paths:
                logic.update_surface_inputs(geo, self.surface_paths)
            self._refresh_resume_dropdown()
            self._select_resume_item(sop.path())
            self._save_asset_paths()
            self.sync_state()
            self._sync_cone_orient()  # scatter: push cone angle to attribrandomize_orient
            if self._mode == "scatter":
                self._refresh_scatter_cache_widgets()

            if self._mode == "ivy":
                logic.sync_ivy_orient(
                    self.geo_node,
                    self.state.get("rot_min",      0.0),
                    self.state.get("rot_max",      1.0),
                    self.state.get("full_rand",    False),
                    self.state.get("rot_randomize", 1.0),
                )
            self._set_status(f"Network '{text.strip()}' created.")
        except Exception as e:
            hou.ui.displayMessage(f"Error creating scatter network:\n{e}",
                                  severity=hou.severityType.Error)

    def _on_clear_all(self):
        if self.scatter_sop_node is None:
            hou.ui.displayMessage("No active scatter node.", severity=hou.severityType.Warning)
            return
        paint_node = self._get_active_paint_node() or self.scatter_sop_node
        layer_name = getattr(self, "_active_mask_layer", "mask") or "mask"
        if hou.ui.displayConfirmation(f"Clear all painted strokes on '{layer_name}'?"):
            logic.clear_points(paint_node)
            self._update_point_count()
            self._set_status(f"Strokes cleared on '{layer_name}'.")

    # ── curve scatter actions ─────────────────────────────────────────────

    def _on_draw_curve(self):
        """
        Create or reuse a curve node, then activate
        Houdini's built-in curve draw viewer state so the user can draw
        directly on the surface.
        """
        if self.scatter_sop_node is None:
            hou.ui.displayMessage("Create a scatter network first.",
                                  severity=hou.severityType.Warning)
            return
        if not self.surface_node_path:
            hou.ui.displayMessage("Set a surface first.",
                                  severity=hou.severityType.Warning)
            return

        try:
            geo_node = self.scatter_sop_node.parent()

            # 1. Create the drawcurve node right away
            existing = logic.get_drawcurve_nodes(geo_node)
            target_name = "drawcurve" if not existing else f"drawcurve_{len(existing) + 1}"
            
            new_node = geo_node.createNode("drawcurve", target_name)
            
            # 2. Hook up input 0 to surface_input
            surf_in = geo_node.node("surface_input")
            if surf_in:
                try:
                    new_node.setInput(0, surf_in)
                except Exception:
                    pass
            
            # 3. Set Parameter:stroke_prototype to 4
            p_proto = new_node.parm("stroke_prototype")
            if p_proto:
                try:
                    p_proto.set(4)
                except Exception:
                    pass
            
            # 4. Set Projection to Geometry (index 4)
            p_proj = new_node.parm("projtype")
            if p_proj:
                try:
                    p_proj.set(4)  # 4 = Geometry
                except Exception:
                    pass

            # 5. Immediately apply — wire the curve into the scatter stream
            spacing   = self.curve_spacing_sb.value()
            subdivide = self.curve_subdivide_cb.isChecked()
            rand_rot  = self.curve_rand_rot_sb.value()

            logic.create_curve_scatter_network(
                geo_node, self.scatter_sop_node,
                resample_length=spacing,
                jitter=self.curve_jitter_sb.value(),
                subdivide=subdivide,
                rand_rot=rand_rot,
            )
            geo_node.layoutChildren()
            self.sync_state(save=True)
            self._refresh_curve_selector()

            # Select it so the viewer state uses it
            new_node.setSelected(True, clear_all_selected=True)

            # Dive inside SP_Scatter and enter the existing drawcurve node's state
            # (setCurrentState would create a duplicate — enterCurrentNodeState reuses ours)
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            if viewer:
                viewer.setPwd(geo_node)
                viewer.setCurrentNode(new_node)
                viewer.enterCurrentNodeState()
                self.curve_status_l.setText(
                    f"Drawing '{new_node.name()}' on surface — stream connected.\n"
                    "Draw on the surface. Points update live."
                )
                self.curve_status_l.setStyleSheet("color:#7ab0ff; font-size:10px;")
            else:
                self.curve_status_l.setText("No viewport found.")
        except Exception as e:
            self.curve_status_l.setText(f"Error: {e}")
            print(f"[Magic Scatter World] Draw curve error: {e}")

    def _on_add_curve(self):
        """
        Activate the curve draw state so the user can draw an additional curve.
        The new curve will be merged with all existing ones before curve_pscale.
        """
        if self.scatter_sop_node is None:
            hou.ui.displayMessage("Create a scatter network first.",
                                  severity=hou.severityType.Warning)
            return
        if not self.surface_node_path:
            hou.ui.displayMessage("Set a surface first.",
                                  severity=hou.severityType.Warning)
            return

        geo_node = self.scatter_sop_node.parent()
        existing = logic.get_drawcurve_nodes(geo_node)
        if not existing:
            hou.ui.displayMessage(
                "Draw and apply a first curve before adding more.",
                severity=hou.severityType.Warning,
            )
            return

        try:
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            if viewer:
                viewer.setPwd(geo_node)
                
                # Create the additional node right away
                n_idx = len(existing) + 1
                new_node = geo_node.createNode("drawcurve", f"drawcurve_{n_idx}")
                
                # Hook up input 0 to surface_input
                surf_in = geo_node.node("surface_input")
                if surf_in:
                    try:
                        new_node.setInput(0, surf_in)
                    except Exception:
                        pass
                
                # Set Parameter:stroke_prototype to 4
                p_proto = new_node.parm("stroke_prototype")
                if p_proto:
                    try:
                        p_proto.set(4)
                    except Exception:
                        pass
                
                # Set Projection to Geometry (index 4)
                p_proj = new_node.parm("projtype")
                if p_proj:
                    try:
                        p_proj.set(4)  # 4 = Geometry
                    except Exception:
                        pass

                # Immediately apply — wire the curve into the scatter stream
                spacing   = self.curve_spacing_sb.value()
                subdivide = self.curve_subdivide_cb.isChecked()
                rand_rot  = self.curve_rand_rot_sb.value()

                logic.create_curve_scatter_network(
                    geo_node, self.scatter_sop_node,
                    resample_length=spacing,
                    jitter=self.curve_jitter_sb.value(),
                    subdivide=subdivide,
                    rand_rot=rand_rot,
                )
                geo_node.layoutChildren()
                self.sync_state(save=True)
                self._refresh_curve_selector()

                new_node.setSelected(True, clear_all_selected=True)
                viewer.setCurrentNode(new_node)
                viewer.enterCurrentNodeState()

                self.curve_status_l.setText(
                    f"Drawing curve #{n_idx} ('{new_node.name()}') — stream connected.\n"
                    "Draw on the surface. Points update live."
                )
                self.curve_status_l.setStyleSheet("color:#7ab0ff; font-size:10px;")
            else:
                self.curve_status_l.setText("No viewport found.")
        except Exception as e:
            self.curve_status_l.setText(f"Error: {e}")
            print(f"[Magic Scatter World] Add curve error: {e}")


    def _on_apply_curve(self):
        """Apply curve scatter (kept for compatibility — now auto-applied on draw)."""
        pass

    def _on_clear_curve(self):
        """Remove the entire curve scatter branch from the network."""
        if self.scatter_sop_node is None:
            return
        try:
            geo_node = self.scatter_sop_node.parent()

            # Remove all drawcurve* nodes
            for node in logic.get_drawcurve_nodes(geo_node):
                node.destroy()

            # Remove all per-curve processing nodes (resample, pointjitter, pscale, rot_wrangle)
            per_curve_prefixes = (
                "curve_resample", "curve_pointjitter", "curve_pscale", "curve_rot_wrangle",
            )
            for child in list(geo_node.children()):
                nm = child.name()
                for pfx in per_curve_prefixes:
                    if nm == pfx or nm.startswith(pfx + "_"):
                        child.destroy()
                        break

            # Remove shared curve-related nodes
            for name in ("curves_merge", "curve_ray", "curve_scatter_merge",
                         "curve_to_surface", "curve_points", "surface_for_ray"):
                n = geo_node.node(name)
                if n:
                    n.destroy()

            # Restore geo_offset → pscale_wrangle direct connection
            pscale_wr  = geo_node.node("pscale_wrangle")
            geo_offset = geo_node.node("geo_offset")
            if pscale_wr and geo_offset:
                geo_offset.setInput(0, pscale_wr)

            geo_node.layoutChildren()
            self.curve_status_l.setText("Curve(s) cleared.")
            self.curve_status_l.setStyleSheet("color:#888; font-size:10px;")
            self._update_point_count()
            self._set_status("Curve scatter cleared.")
            self._refresh_curve_selector()
        except Exception as e:
            self._set_status(f"Clear curve error: {e}", error=True)
            print(f"[Magic Scatter World] Clear curve error: {e}")

    # ── curve selector helpers ────────────────────────────────────────────

    def _refresh_curve_selector(self, select_name=None):
        """Rebuild the curve-selector combo box from current drawcurve* nodes.

        select_name: if given, select that curve; otherwise select the last one.
        """
        self.curve_selector_cb.blockSignals(True)
        self.curve_selector_cb.clear()
        if self.scatter_sop_node is None:
            self.curve_selector_cb.addItem("No network active")
            self.curve_selector_cb.blockSignals(False)
            return

        geo_node = self.scatter_sop_node.parent()
        curves   = logic.get_drawcurve_nodes(geo_node)
        if not curves:
            self.curve_selector_cb.addItem("No curves drawn yet")
        else:
            for cn in curves:
                self.curve_selector_cb.addItem(cn.name(), userData=cn.name())
            # Select the requested curve, or default to the last (most recently created)
            target_idx = self.curve_selector_cb.count() - 1
            if select_name:
                for i in range(self.curve_selector_cb.count()):
                    if self.curve_selector_cb.itemData(i) == select_name:
                        target_idx = i
                        break
            self.curve_selector_cb.setCurrentIndex(target_idx)

        self.curve_selector_cb.blockSignals(False)
        # Load per-curve params for the now-selected curve (triggers button state too)
        self._on_curve_selected(self.curve_selector_cb.currentIndex())

    def _on_curve_selected(self, _idx):
        """Enable / disable action buttons and load per-curve resample params into the UI."""
        has_sel = bool(self.curve_selector_cb.currentData())
        self.select_curve_btn.setEnabled(has_sel)
        self.rename_curve_btn.setEnabled(has_sel)
        self.delete_curve_btn.setEnabled(has_sel)

        if not has_sel or self.scatter_sop_node is None:
            return
        curve_name = self.curve_selector_cb.currentData()
        geo_node   = self.scatter_sop_node.parent()

        rs  = logic.get_curve_resample_params(geo_node, curve_name)
        pj  = logic.get_curve_pointjitter_params(geo_node, curve_name)
        ps  = logic.get_curve_pscale_params(geo_node, curve_name)
        rot = logic.get_curve_rot_params(geo_node, curve_name)

        widgets = (
            self.curve_spacing_sb, self.curve_spacing_sl,
            self.curve_jitter_sb,  self.curve_jitter_sl,
            self.curve_scale_sb,   self.curve_scale_sl,
            self.curve_rand_rot_sb, self.curve_rand_rot_sl,
            self.curve_subdivide_cb,
        )
        for w in widgets:
            w.blockSignals(True)

        self.curve_spacing_sb.setValue(rs["length"])
        self.curve_spacing_sl.setValue(min(int(rs["length"] * 1000), self.curve_spacing_sl.maximum()))
        self.curve_subdivide_cb.setChecked(rs["treatpolysas"] == 1)
        self.curve_jitter_sb.setValue(pj["scale"])
        self.curve_jitter_sl.setValue(min(int(pj["scale"] * 1000), self.curve_jitter_sl.maximum()))
        self.curve_scale_sb.setValue(ps["curve_scale"])
        self.curve_scale_sl.setValue(min(int(ps["curve_scale"] * 1000), self.curve_scale_sl.maximum()))
        self.curve_rand_rot_sb.setValue(rot["rand_rot"])
        self.curve_rand_rot_sl.setValue(min(int(rot["rand_rot"] * 1000), self.curve_rand_rot_sl.maximum()))

        for w in widgets:
            w.blockSignals(False)

    def _selected_curve_name(self):
        """Return the curve node name currently chosen in the selector, or None."""
        return self.curve_selector_cb.currentData()

    def _on_select_curve_in_network(self):
        """Select the chosen drawcurve node in the Houdini network editor."""
        name = self._selected_curve_name()
        if not name or self.scatter_sop_node is None:
            return
        geo_node = self.scatter_sop_node.parent()
        node     = geo_node.node(name)
        if node is None:
            self.curve_status_l.setText(f"Node '{name}' not found.")
            return
        try:
            hou.clearAllSelected()
            node.setSelected(True, clear_all_selected=True)
            # Navigate the network editor to it
            for pane in hou.ui.paneTabs():
                if pane.type() == hou.paneTabType.NetworkEditor:
                    pane.setCurrentNode(node)
                    break
            self.curve_status_l.setText(f"Selected: {name}")
            self.curve_status_l.setStyleSheet("color:#7ab0ff; font-size:10px;")
        except Exception as e:
            self.curve_status_l.setText(f"Error: {e}")

    def _on_rename_curve(self):
        """Prompt the user for a new name and rename the selected curve node."""
        name = self._selected_curve_name()
        if not name or self.scatter_sop_node is None:
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename Curve", "New node name:", text=name
        )
        if not ok or not new_name.strip():
            return
        geo_node = self.scatter_sop_node.parent()
        if logic.rename_curve_node(geo_node, name, new_name.strip()):
            self._refresh_curve_selector()
            self.curve_status_l.setText(f"Renamed '{name}' → '{new_name.strip()}'")
            self.curve_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
        else:
            self.curve_status_l.setText(f"Rename failed — node '{name}' not found.")
            self.curve_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_delete_selected_curve(self):
        """Delete the selected curve node and rewire the network."""
        name = self._selected_curve_name()
        if not name or self.scatter_sop_node is None:
            return
        if not hou.ui.displayConfirmation(
            f"Delete curve '{name}' and rewire the scatter network?"
        ):
            return
        geo_node = self.scatter_sop_node.parent()
        if logic.delete_curve_node(geo_node, name):
            self._refresh_curve_selector()
            remaining = logic.get_drawcurve_nodes(geo_node)
            if remaining:
                self.curve_status_l.setText(
                    f"Deleted '{name}'. {len(remaining)} curve(s) remaining."
                )
                self.curve_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
            else:
                self.curve_status_l.setText("All curves deleted.")
                self.curve_status_l.setStyleSheet("color:#888; font-size:10px;")
            self._update_point_count()
        else:
            self.curve_status_l.setText(f"Delete failed — '{name}' not found.")
            self.curve_status_l.setStyleSheet("color:#ff6060; font-size:10px;")

    def _on_recache_strokes(self):
        """Press the recache button on the currently active paint node."""
        paint_node = self._get_active_paint_node()
        if paint_node is None:
            return
        try:
            recache_btn = paint_node.parm("recache")
            if recache_btn:
                recache_btn.pressButton()
                self._set_status(f"Strokes recached on '{self._active_mask_layer}'.")
            else:
                self._set_status("Recache parameter not found.", error=True)
        except Exception as e:
            self._set_status(f"Recache error: {e}", error=True)
            print(f"[Magic Scatter World] Recache error: {e}")

    def _on_curve_spacing_changed(self):
        """Live-update resample length on the currently selected curve."""
        curve_name = self._selected_curve_name()
        if self.scatter_sop_node is None or not curve_name:
            return
        logic.set_curve_resample_length(
            self.scatter_sop_node.parent(),
            self.curve_spacing_sb.value(),
            curve_name=curve_name,
        )

    def _on_curve_jitter_changed(self):
        """Live-update pointjitter on the currently selected curve."""
        curve_name = self._selected_curve_name()
        if self.scatter_sop_node is None or not curve_name:
            return
        logic.set_curve_jitter(
            self.scatter_sop_node.parent(),
            self.curve_jitter_sb.value(),
            curve_name=curve_name,
        )

    def _on_curve_subdivide_changed(self):
        """Live-update treatpolysas on the currently selected curve's resample node."""
        curve_name = self._selected_curve_name()
        if self.scatter_sop_node is None or not curve_name:
            return
        logic.set_curve_subdivide(
            self.scatter_sop_node.parent(),
            self.curve_subdivide_cb.isChecked(),
            curve_name=curve_name,
        )

    def _on_curve_rand_rot_changed(self):
        """Live-update random Y rotation on the currently selected curve's rot_wrangle."""
        curve_name = self._selected_curve_name()
        if self.scatter_sop_node is None or not curve_name:
            return
        logic.set_curve_rand_rot(
            self.scatter_sop_node.parent(),
            self.curve_rand_rot_sb.value(),
            curve_name=curve_name,
        )

    def _on_curve_scale_changed(self):
        """Live-update pscale on the currently selected curve."""
        curve_name = self._selected_curve_name()
        if self.scatter_sop_node is None or not curve_name:
            return
        logic.set_curve_pscale(
            self.scatter_sop_node.parent(),
            self.state.get("scl_min", [1, 1, 1]),
            self.state.get("scl_max", [1, 1, 1]),
            self.state.get("pscale_randomize", 1.0),
            self.curve_scale_sb.value(),
            curve_name=curve_name,
        )
        self._sync_rt()

    # ── resume ────────────────────────────────────────────────────────────

    def _refresh_resume_dropdown(self):
        self.resume_cb.blockSignals(True)
        self.resume_cb.clear()
        self.resume_cb.addItem("Select existing session…")
        for geo_node, sop in logic.get_scatter_nodes():
            self.resume_cb.addItem(geo_node.name(), userData=sop.path())
        self.resume_cb.blockSignals(False)

    def _auto_resume_last(self):
        """Auto-resume to the last active scatter network if it still exists."""
        global _last_scatter_sop_path

        # Try in-memory path first
        if _last_scatter_sop_path is not None:
            try:
                sop = hou.node(_last_scatter_sop_path)
                if sop is not None:
                    self._resume(sop)
                    return
            except Exception:
                pass

        # If in-memory path lost (module reload), try to recover from session state
        try:
            saved_path = hou.session.sp_scatter_last_sop_path if hasattr(hou.session, "sp_scatter_last_sop_path") else None
            if saved_path:
                sop = hou.node(saved_path)
                if sop is not None:
                    self._resume(sop)
                    return
        except Exception:
            pass

    def _select_resume_item(self, sop_path):
        """Select a dropdown item by scatter node path and resume it."""
        for i in range(1, self.resume_cb.count()):
            if self.resume_cb.itemData(i) == sop_path:
                self.resume_cb.blockSignals(True)
                self.resume_cb.setCurrentIndex(i)
                self.resume_cb.blockSignals(False)
                return

    def _on_resume_dropdown(self, idx):
        if idx < 1:
            return
        sop_path = self.resume_cb.itemData(idx)
        if sop_path:
            sop = hou.node(sop_path)
            if sop:
                self._resume(sop)

    def _resume(self, scatter_sop):
        global _last_scatter_sop_path
        self._prevent_sync = True
        try:
            self.scatter_sop_node = scatter_sop
            self.geo_node         = scatter_sop.parent()
            _last_scatter_sop_path = scatter_sop.path()  # Save for auto-resume on reload
            # Also save to session state to survive module reloads
            try:
                hou.session.sp_scatter_last_sop_path = scatter_sop.path()
            except Exception:
                pass
            self.node_l.setText(f"Node: {scatter_sop.path()}")

            meta = logic.load_meta(scatter_sop)
            if meta:
                _surf_single = meta.get("surf", "")
                self.surface_paths = meta.get("surfs", [_surf_single] if _surf_single else [])
                self._apply_surface_paths()

                # Brush widgets exist in both modes (Paint Mask tab in ivy).
                self.r_sb.setValue(meta.get("rad",       RADIUS_DEF))
                self.d_sb.setValue(meta.get("dens",       DENS_DEF))
                self.s_sb.setValue(meta.get("spacing",    SPC_DEF))
                self.fa_sb.setValue(meta.get("f_amt",     FAL_AMT_DEF))
                self.fs_sb.setValue(meta.get("f_soft",    FAL_SFT_DEF))
                self.relax_sb.setValue(meta.get("relax_iter", RELAX_DEF))
                self.max_pts_sb.setValue(meta.get("max_pts",  MAX_PTS_DEF))
                self.mdist_sb.setValue(meta.get("min_distance", MDIST_DEF))

                # Curve widgets — only exist in scatter mode
                if self._mode == "scatter":
                    self.curve_spacing_sb.setValue(meta.get("c_spacing", 0.5))
                    self.curve_jitter_sb.setValue(meta.get("c_jitter", 0.0))
                    self.curve_rand_rot_sb.setValue(meta.get("c_rot", 0.0))
                    self.curve_scale_sb.setValue(meta.get("c_scale", 1.0))
                    self.curve_subdivide_cb.setChecked(meta.get("c_subdiv", False))

                # Stamp layers — scatter mode only; migrate from old single-layer format.
                if self._mode == "scatter" and hasattr(self, "_stamp_layers"):
                    if "stamp_layers" in meta:
                        self._restore_stamp_layers(meta["stamp_layers"])
                    elif meta.get("use_tex") and meta.get("tex"):
                        self._restore_stamp_layers([{
                            "enabled": True,
                            "path":    meta.get("tex", ""),
                            "rot":     meta.get("s_rot", 0.0),
                            "fx":      meta.get("s_fx", False),
                            "fy":      meta.get("s_fy", False),
                        }])
                    if hasattr(self, "stamp_scale_sb"):
                        self.stamp_scale_sb.setValue(float(meta.get("stamp_scale", 1.0)))
                    if hasattr(self, "stamp_mask_layer_cb"):
                        # Backward compat: old stamp_use_mask=True → "mask"
                        ml = meta.get("stamp_mask_layer",
                                      "mask" if meta.get("stamp_use_mask", False) else "")
                        idx = self.stamp_mask_layer_cb.findText(ml if ml else "None")
                        self.stamp_mask_layer_cb.blockSignals(True)
                        self.stamp_mask_layer_cb.setCurrentIndex(max(0, idx))
                        self.stamp_mask_layer_cb.blockSignals(False)

                    noise_meta = meta.get("scatter_noise", {})
                    for key, default in logic.SCATTER_NOISE_DEFAULTS.items():
                        widget = self._scatter_noise_widgets.get(key)
                        if widget is None:
                            continue
                        val = noise_meta.get(key, default)
                        widget.blockSignals(True)
                        if isinstance(widget, QComboBox):
                            widget.setCurrentIndex(int(val))
                        elif isinstance(widget, QLineEdit):
                            widget.setText(str(val))
                        elif isinstance(widget, QCheckBox):
                            widget.setChecked(bool(val))
                        elif hasattr(widget, "setValue"):
                            widget.setValue(val)
                        widget.blockSignals(False)

                    # Restore mask layers
                    if hasattr(self, "_mask_layers_vlay"):
                        self._clear_mask_layers()
                        for name in meta.get("mask_layers", ["mask"]):
                            self._add_mask_layer_row(name)
                        self._update_mask_remove_buttons()
                        self._refresh_mask_layer_combo()
                        active_name = meta.get("active_mask_layer", "mask")
                        for le, _, _, rb, _ in self._mask_layer_rows:
                            if le.currentText().strip() == active_name:
                                rb.blockSignals(True)
                                rb.setChecked(True)
                                rb.blockSignals(False)
                                self._active_mask_layer = active_name
                                break
                        # Restore mask gating list (new format), with backward
                        # compat for the previous single-mask fields.
                        gating = meta.get("scatter_noise_mask_gating", None)
                        if gating is None:
                            legacy_layer = meta.get("scatter_noise_multiply_mask", "")
                            legacy_op = int(meta.get("scatter_noise_mask_op", 0))
                            gating = [{"layer": legacy_layer, "op": legacy_op}] if legacy_layer else []
                        if hasattr(self, "_mask_gating_vlay"):
                            self._clear_mask_gating_rows()
                            for entry in gating:
                                self._add_mask_gating_row(
                                    entry.get("layer", ""),
                                    int(entry.get("op", 0)),
                                    float(entry.get("blend", 1.0)),
                                    bool(entry.get("invert", False)),
                                )
                            if not self._mask_gating_entries:
                                self._add_mask_gating_row("", 0, 1.0)
                            self._refresh_mask_layer_combo()

                # Transformation (Rotation + Scale) — exists in both modes.
                # normal_align_cb only in scatter mode.
                self.rot_min_sb.setValue(meta.get("rot_min",       ROT_MIN_DEF))
                self.rot_max_sb.setValue(meta.get("rot_max",       ROT_MAX_DEF))
                self.rot_rand_sb.setValue(meta.get("rot_randomize", ROT_RAND_DEF))
                if hasattr(self, "cone_sb"):
                    self.cone_sb.setValue(meta.get("cone_angle", CONE_DEF))
                if self._mode == "scatter":
                    self.normal_align_cb.setChecked(meta.get("normal_align", False))
                self.full_rand_cb.setChecked(meta.get("full_rand", False))

                self.gs_sb.setValue(meta.get("gl_scl", GS_DEF))
                self.pscale_rand_sb.setValue(meta.get("pscale_randomize", PSCALE_RAND_DEF))
                self.uni_cb.setChecked(meta.get("uni_xyz", True))
                smn = meta.get("scl_min", [SCL_MIN_DEF] * 3)
                smx = meta.get("scl_max", [SCL_MAX_DEF] * 3)
                self.smn_x.setValue(smn[0]); self.smn_y.setValue(smn[1]); self.smn_z.setValue(smn[2])
                self.smx_x.setValue(smx[0]); self.smx_y.setValue(smx[1]); self.smx_z.setValue(smx[2])

                self._refresh_scatter_cache_widgets()

                # Camera Frustum Culling — restore widgets from meta
                if hasattr(self, "_cam_frustum_cb"):
                    self._cam_frustum_cb.blockSignals(True)
                    self._cam_frustum_cb.setChecked(meta.get("cam_frustum_enabled", False))
                    self._cam_frustum_cb.blockSignals(False)
                    self._populate_camera_combo()
                    saved_cam = meta.get("cam_frustum_path", "")
                    if saved_cam:
                        idx = self._cam_combo.findData(saved_cam)
                        if idx >= 0:
                            self._cam_combo.blockSignals(True)
                            self._cam_combo.setCurrentIndex(idx)
                            self._cam_combo.blockSignals(False)
                    self._cam_fov_pad_sb.blockSignals(True)
                    self._cam_fov_pad_sb.setValue(meta.get("cam_fov_padding", 0.0))
                    self._cam_fov_pad_sb.blockSignals(False)

                # Clumping — restore widgets from meta
                if hasattr(self, "clump_enabled_cb"):
                    for widget, key, default in (
                        (self.clump_enabled_cb,    "clump_enabled",   False),
                        (self.clump_radius_sb,     "clump_radius",    2.0),
                        (self.clump_strength_sb,   "clump_strength",  0.7),
                        (self.clump_min_count_sb,  "clump_min_count", 2),
                        (self.clump_seed_sb,       "clump_seed",      42),
                    ):
                        widget.blockSignals(True)
                        if isinstance(widget, QCheckBox):
                            widget.setChecked(bool(meta.get(key, default)))
                        else:
                            widget.setValue(meta.get(key, default))
                        widget.blockSignals(False)

                # Color Variation — restore widgets from meta
                if hasattr(self, "color_var_enabled_cb"):
                    self.color_var_enabled_cb.blockSignals(True)
                    self.color_var_enabled_cb.setChecked(
                        bool(meta.get("color_variation_enabled", True)))
                    self.color_var_enabled_cb.blockSignals(False)
                    for btn, key in (
                        (self.color_var_a_btn, "color_variation_a"),
                        (self.color_var_b_btn, "color_variation_b"),
                    ):
                        rgb = meta.get(key, logic.COLOR_VARIATION_DEFAULTS[key])
                        r, g, b = [int(v * 255) for v in rgb[:3]]
                        btn._color = QColor(r, g, b)
                        btn.setStyleSheet(
                            f"background:rgb({r},{g},{b}); border:1px solid #555;")
                    self.color_var_seed_sb.blockSignals(True)
                    self.color_var_seed_sb.setValue(
                        int(meta.get("color_variation_seed", 0)))
                    self.color_var_seed_sb.blockSignals(False)

                # Proximity Exclusion — restore widgets from meta
                if hasattr(self, "_prox_enabled_cb"):
                    self._prox_enabled_cb.blockSignals(True)
                    self._prox_enabled_cb.setChecked(bool(meta.get("prox_enabled", False)))
                    self._prox_enabled_cb.blockSignals(False)
                    self._prox_radius_sb.blockSignals(True)
                    self._prox_radius_sb.setValue(float(meta.get("prox_radius", 2.0)))
                    self._prox_radius_sb.blockSignals(False)
                    self._prox_sop_le.blockSignals(True)
                    self._prox_sop_le.setText(meta.get("prox_sop_path", ""))
                    self._prox_sop_le.blockSignals(False)

                # LOD — restore widgets from meta
                if hasattr(self, "_lod_enabled_cb"):
                    self._lod_enabled_cb.blockSignals(True)
                    self._lod_enabled_cb.setChecked(bool(meta.get("lod_enabled", False)))
                    self._lod_enabled_cb.blockSignals(False)
                    self._lod1_dist_sb.blockSignals(True)
                    self._lod1_dist_sb.setValue(float(meta.get("lod1_dist", 20.0)))
                    self._lod1_dist_sb.blockSignals(False)
                    self._lod2_dist_sb.blockSignals(True)
                    self._lod2_dist_sb.setValue(float(meta.get("lod2_dist", 50.0)))
                    self._lod2_dist_sb.blockSignals(False)
                    self._lod_cull_sb.blockSignals(True)
                    self._lod_cull_sb.setValue(float(meta.get("lod_cull_dist", 100.0)))
                    self._lod_cull_sb.blockSignals(False)
                    self.state["lod1_path_map"] = meta.get("lod1_path_map", {})
                    self.state["lod2_path_map"] = meta.get("lod2_path_map", {})
                    self._populate_lod_cam_combo()
                    saved_cam = meta.get("lod_cam_path", "")
                    if saved_cam:
                        idx = self._lod_cam_combo.findData(saved_cam)
                        if idx >= 0:
                            self._lod_cam_combo.blockSignals(True)
                            self._lod_cam_combo.setCurrentIndex(idx)
                            self._lod_cam_combo.blockSignals(False)
                    if hasattr(self, "_lod_assets_widget"):
                        self._lod_assets_widget.setVisible(
                            bool(meta.get("lod_enabled", False)))

                # Placement Rules — restore from meta
                if hasattr(self, "_rules_layout"):
                    self._placement_rules = list(meta.get("placement_rules", []))
                    self._rebuild_rules_ui()

            # Assets — always load, even when meta is empty (Ivy mode never
            # calls save_meta, so get_asset_node_paths falls back to reading
            # objpath1 directly from the object_merge nodes in the network).
            asset_paths   = logic.get_asset_node_paths(scatter_sop)
            print(f"[Magic Scatter World] _resume: asset_paths={asset_paths}, "
                  f"meta_assets={meta.get('assets', 'KEY_MISSING')}")
            saved_weights = meta.get("asset_weights", [])
            self._clear_assets()
            for p in asset_paths:
                node_ok = hou.node(p) is not None
                print(f"[Magic Scatter World] _resume: hou.node({p!r}) ok={node_ok}")
                if node_ok:
                    self._add_asset(p, update_layout=False)
            self._refresh_asset_layout()
            for idx, aw in enumerate(self.asset_rows):
                if idx < len(saved_weights):
                    aw.weight_sl.blockSignals(True)
                    aw.weight_sl.setValue(int(float(saved_weights[idx]) * 100))
                    aw.weight_sl.blockSignals(False)
            logic.update_instancing_network(scatter_sop, [w.node_path for w in self.asset_rows])
            self._reapply_lookdev_bindings(scatter_sop)
            logic.sync_asset_weights(
                scatter_sop,
                [w.weight_sl.value() / 100.0 for w in self.asset_rows],
            )

            # Ivy state — only restore in ivy mode (widgets and status labels
            # are not built in scatter mode).
            if self._mode == "ivy":
                self._restore_ivy_sim_from_meta(meta)
                ivy_params = logic.get_ivy_params(self.geo_node)
                for name, val in ivy_params.items():
                    sb = self._ivy_widgets.get(name)
                    if sb is not None:
                        sb.blockSignals(True)
                        sb.setValue(val)
                        sb.blockSignals(False)
                    sl = self._ivy_sliders.get(name)
                    if sl is not None:
                        sl.blockSignals(True)
                        sl.setValue(int(val) if isinstance(sb, QSpinBox) else int(float(val) * 1000))
                        sl.blockSignals(False)

                if logic.crawl_ivy_network_exists(self.geo_node):
                    crawl_params = logic.get_crawl_ivy_params(self.geo_node)
                    for name, val in crawl_params.items():
                        sb = self._crawl_widgets.get(name)
                        if sb is not None:
                            sb.blockSignals(True)
                            scale = _CRAWL_FLOAT_SLIDER_SCALES.get(name)
                            sb.setValue(int(round(val * scale)) if scale else val)
                            sb.blockSignals(False)
                        self.state[name] = val
                    self._refresh_crawl_cache_widgets()
                    self.crawl_status_l.setText(
                        f"Crawling ivy found in {self.geo_node.name()}.")
                    self.crawl_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
                else:
                    self.crawl_status_l.setText("No crawling ivy — click Create Crawling Ivy.")
                    self.crawl_status_l.setStyleSheet("color:#888; font-size:10px;")

                if logic.ivy_network_exists(self.geo_node):
                    self._refresh_ivy_transform_widgets()
                    self._refresh_ivy_appearance_widgets()
                    self._refresh_ivy_cache_widgets()
                    self._refresh_ivy_sim_widgets()
                    self._refresh_sim_cache_widgets()
                    self.ivy_status_l.setText(f"Ivy network found in {self.geo_node.name()}.")
                    self.ivy_status_l.setStyleSheet("color:#5fdb5f; font-size:10px;")
                else:
                    self.ivy_status_l.setText("No ivy network — click Create Ivy Network.")
                    self.ivy_status_l.setStyleSheet("color:#888; font-size:10px;")
        finally:
            self._prevent_sync = False
            self.sync_state(save=False)
        if self._mode == "scatter" and self.scatter_sop_node is not None:
            logic.sync_scatter_params(self.scatter_sop_node, self.state)
            self._refresh_scatter_cache_widgets()
        self._sync_cone_orient()  # scatter mode: push cone angle to attribrandomize_orient
        if self._mode == "ivy":
            logic.heal_orient_wrangle(self.geo_node)
            logic.sync_ivy_orient(
                self.geo_node,
                self.state.get("rot_min",      0.0),
                self.state.get("rot_max",      1.0),
                self.state.get("full_rand",    False),
                self.state.get("rot_randomize", 1.0),
            )
        self._update_point_count()
        self._set_status(f"Resumed: {scatter_sop.path()}")

    # ======================================================================
    # Paint mode
    # ======================================================================

    def _toggle_mode(self, mode, active):
        if active:
            self.state["mode"] = mode
            # Mutual exclusion
            if mode == "paint":
                self.e_btn.setChecked(False)
            else:
                self.p_btn.setChecked(False)

            if not self.surface_node_path:
                hou.ui.displayMessage("Set a surface first.",
                                      severity=hou.severityType.Warning)
                self.p_btn.setChecked(False)
                self.e_btn.setChecked(False)
                return

            if self.scatter_sop_node:
                active_paint = self._get_active_paint_node() or self.scatter_sop_node
                op = 2 if mode == "erase" else 0
                try:
                    active_paint.setParms({"lmboperation": op})
                except Exception:
                    pass
                # Capture for the deferred callback
                _sop  = active_paint
                _mode = mode
                def _activate_paint_state(sop=_sop):
                    try:
                        geo_node = sop.parent()
                        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
                        if viewer is None:
                            return
                        # Dive the viewer into the geo network
                        viewer.setPwd(geo_node)
                        # Make paint_mask the current & selected node
                        sop.setSelected(True, clear_all_selected=True)
                        sop.setCurrent(True)
                        # Now activate the state — Houdini has full context
                        viewer.setCurrentState("attribpaint")
                    except Exception as e:
                        print(f"[Magic Scatter World] Could not activate paint state: {e}")
                # Defer until Qt has finished processing the button click,
                # so Houdini's UI thread is fully ready to accept the state change
                hou.ui.postEventCallback(_activate_paint_state)
            self._set_status(f"Mode: {mode.upper()}")
        else:
            if not self.p_btn.isChecked() and not self.e_btn.isChecked():
                try:
                    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
                    if viewer:
                        rc.deactivate_state(viewer)
                except Exception:
                    pass
                self._set_status("Ready")

    def _on_state_exit(self):
        """Called when the Houdini viewer state is exited (Esc)."""
        self.p_btn.setChecked(False)
        self.e_btn.setChecked(False)

    # Stub paint callbacks used by raycast.py
    def on_press(self, hit_pos, hit_normal):    pass
    def on_drag(self,  hit_pos, hit_normal):    pass
    def on_release(self):                       pass

    # ======================================================================
    # Parameter callbacks
    # ======================================================================

    @debounce(100)
    def _on_rot_changed(self, *_):
        """Rotation slider/spinbox changed.
        Calls the standard _sync_rt path AND always pushes orient_wrangle
        directly in ivy mode — no rt_cb gate for the orient push.
        """
        self._sync_rt()
        if self._mode == "ivy" and self.geo_node is not None:
            logic.sync_ivy_orient(
                self.geo_node,
                self.rot_min_sb.value(),
                self.rot_max_sb.value(),
                self.full_rand_cb.isChecked(),
                self.rot_rand_sb.value(),
            )

    def _on_paint_changed(self, *_):
        """Brush Radius / Opacity / Falloff Soft changed.
        Updates paint_mask parms immediately, debounces state sync.
        Works in both scatter and ivy modes.
        """
        # Update paint_mask parameters IMMEDIATELY (not debounced)
        # to prevent snap-back during slider drag-release transitions
        source_node = None
        if self.scatter_sop_node is not None:
            source_node = self.scatter_sop_node
        elif self.geo_node is not None:
            source_node = self.geo_node

        if source_node is not None:
            try:
                geo_node = None
                if source_node.type().name() == "geo":
                    geo_node = source_node
                else:
                    geo_node = source_node.parent()

                if geo_node:
                    radius   = self.r_sb.value()
                    opacity  = self.fa_sb.value()
                    softness = self.fs_sb.value()
                    for child in geo_node.children():
                        nm = child.name()
                        if child.type().name() == "attribpaint" and (
                            nm == "paint_mask" or nm.startswith("paint_mask_")
                        ):
                            try:
                                child.setParms({
                                    "stroke_radius":   radius,
                                    "stroke_opacity":  opacity,
                                    "stroke_softedge": softness,
                                })
                            except Exception:
                                pass
            except Exception:
                pass

        # Debounce the state sync separately
        self._sync_rt()

    def _on_full_rand_toggled(self, state):
        enabled = not bool(state)
        for w_ in (self.rot_min_sb, self.rot_min_sl,
                   self.rot_max_sb, self.rot_max_sl):
            w_.setEnabled(enabled)
        if state:
            self.rot_min_sb.setValue(0.0)
            self.rot_max_sb.setValue(1.0)
        self._on_rot_changed()

    def _populate_camera_combo(self):
        """Refresh the camera dropdown with all /obj camera nodes in the scene."""
        if not hasattr(self, "_cam_combo"):
            return
        self._cam_combo.blockSignals(True)
        prev = self._cam_combo.currentData()
        self._cam_combo.clear()
        self._cam_combo.addItem("-- None --", "")
        obj = hou.node("/obj")
        if obj:
            for node in sorted(obj.children(), key=lambda n: n.name()):
                if node.type().name() in ("cam", "cam::2.0"):
                    self._cam_combo.addItem(node.name(), node.path())
        if prev:
            idx = self._cam_combo.findData(prev)
            if idx >= 0:
                self._cam_combo.setCurrentIndex(idx)
        self._cam_combo.blockSignals(False)

    def _on_camera_frustum_changed(self, *_):
        """Camera frustum setting changed — sync to network and save meta."""
        if self.geo_node is None:
            return
        logic.sync_camera_frustum(
            self.geo_node,
            self._cam_frustum_cb.isChecked(),
            self._cam_combo.currentData() or "",
            self._cam_fov_pad_sb.value(),
        )
        self.sync_state(save=True)

    # ── Placement Rules ───────────────────────────────────────────────────────

    def _add_placement_rule(self, rule_type):
        defaults = logic.RULE_DEFAULTS.get(rule_type, {}).copy()
        defaults["type"] = rule_type
        if not hasattr(self, "_placement_rules"):
            self._placement_rules = []
        self._placement_rules.append(defaults)
        self._rebuild_rules_ui()
        self._push_placement_rules()

    def _remove_placement_rule(self, index):
        if not hasattr(self, "_placement_rules"):
            return
        if 0 <= index < len(self._placement_rules):
            self._placement_rules.pop(index)
        self._rebuild_rules_ui()
        self._push_placement_rules()

    def _on_remove_rule_clicked(self):
        sender = self.sender()
        if sender is None:
            return
        idx = sender.property("rule_index")
        if idx is None:
            return
        try:
            self._remove_placement_rule(int(idx))
        except Exception as e:
            print(f"[Magic Scatter World] _on_remove_rule_clicked failed: {e}")
            self._set_status(f"Rule remove failed: {e}", error=True)

    def _rebuild_rules_ui(self):
        if not hasattr(self, "_rules_layout"):
            return
        # Pull every item out of the layout, including the trailing stretch.
        # setParent(None) is what actually detaches widgets from the screen in
        # Houdini's Qt build (removeWidget alone leaves them visible).
        while self._rules_layout.count():
            item = self._rules_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rule_cards = []

        rules = getattr(self, "_placement_rules", [])
        for i, rule in enumerate(rules):
            card = self._make_rule_row(i, rule)
            self._rules_layout.addWidget(card)
            self._rule_cards.append(card)
        self._rules_layout.addStretch()

    def _make_rule_row(self, index, rule):
        rtype = rule.get("type", "slope")
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background:#2a2a2a; border:1px solid #444; border-radius:4px; }"
        )
        vlay = QVBoxLayout(card)
        vlay.setContentsMargins(6, 4, 6, 4)
        vlay.setSpacing(4)

        # Header row: label + enable checkbox + Remove button
        hdr = QHBoxLayout()
        hdr.setSpacing(6)
        type_lbl = QLabel(logic.RULE_TYPES.get(rtype, rtype))
        type_lbl.setStyleSheet("color:#ddd; font-weight:bold; font-size:10px;")
        hdr.addWidget(type_lbl)
        hdr.addStretch()

        en_cb = QCheckBox("Enabled")
        en_cb.setChecked(bool(rule.get("enabled", True)))
        en_cb.toggled.connect(lambda v, i=index, k="enabled": self._on_rule_param_changed(i, k, v))
        hdr.addWidget(en_cb)

        rem_btn = QPushButton("✕")
        rem_btn.setFixedSize(20, 20)
        rem_btn.setStyleSheet(
            "QPushButton { background:#553333; color:#f88; border:none; border-radius:3px; font-size:9px; }"
            "QPushButton:hover { background:#664444; }"
            "QPushButton:pressed { background:#774444; }"
        )
        rem_btn.setProperty("rule_index", int(index))
        rem_btn.clicked.connect(self._on_remove_rule_clicked)
        hdr.addWidget(rem_btn)
        vlay.addLayout(hdr)

        # Type-specific parameter rows
        def _float_row(label, key, mn, mx, default, step=0.1):
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label + ":")
            lbl.setFixedWidth(100)
            lbl.setStyleSheet("color:#aaa; font-size:10px;")
            sb = _make_spinbox(mn, mx, float(rule.get(key, default)), dec=2, step=step)
            sb.valueChanged.connect(lambda v, i=index, k=key: self._on_rule_param_changed(i, k, v))
            row.addWidget(lbl)
            row.addWidget(sb)
            row.addStretch()
            vlay.addLayout(row)

        def _int_row(label, key, mn, mx, default):
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label + ":")
            lbl.setFixedWidth(100)
            lbl.setStyleSheet("color:#aaa; font-size:10px;")
            sb = _make_int_spinbox(mn, mx, int(rule.get(key, default)))
            sb.valueChanged.connect(lambda v, i=index, k=key: self._on_rule_param_changed(i, k, v))
            row.addWidget(lbl)
            row.addWidget(sb)
            row.addStretch()
            vlay.addLayout(row)

        def _path_row(label, key, default=""):
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label + ":")
            lbl.setFixedWidth(100)
            lbl.setStyleSheet("color:#aaa; font-size:10px;")
            le = QLineEdit(str(rule.get(key, default)))
            le.setPlaceholderText("SOP path…")
            le.editingFinished.connect(lambda i=index, k=key, w=le: self._on_rule_param_changed(i, k, w.text()))
            pick = QPushButton("Pick")
            pick.setFixedWidth(40)
            pick.clicked.connect(lambda *_a, i=index, k=key, w=le: self._pick_rule_sop(i, k, w))
            row.addWidget(lbl)
            row.addWidget(le, 1)
            row.addWidget(pick)
            vlay.addLayout(row)

        if rtype == "slope":
            _float_row("Max Slope (°)", "max_slope", 0.0, 90.0, 30.0, step=1.0)
        elif rtype == "altitude":
            _float_row("Min Altitude", "min_alt", -10000.0, 10000.0, 0.0, step=1.0)
            _float_row("Max Altitude", "max_alt", -10000.0, 10000.0, 100.0, step=1.0)
        elif rtype == "noise":
            _float_row("Frequency",  "frequency",  0.0, 10.0, 0.5)
            _float_row("Threshold",  "threshold",  0.0, 1.0,  0.4)
            _int_row("Seed", "seed", 0, 9999, 0)
        elif rtype == "dist_path":
            _float_row("Min Distance", "min_dist", 0.0, 1000.0, 0.0, step=1.0)
            _float_row("Max Distance", "max_dist", 0.0, 1000.0, 10.0, step=1.0)
            _path_row("Path SOP", "sop_path")

        return card

    def _on_rule_param_changed(self, index, key, value):
        rules = getattr(self, "_placement_rules", [])
        if 0 <= index < len(rules):
            rules[index][key] = value
        self._push_placement_rules()

    def _pick_rule_sop(self, rule_index, key, line_edit):
        try:
            import hou
            path = hou.ui.selectNode(
                title="Pick Path SOP",
                node_type_filter=hou.nodeTypeFilter.Sop,
            )
            if path:
                line_edit.setText(path)
                self._on_rule_param_changed(rule_index, key, path)
        except Exception as e:
            logic.log(f"_pick_rule_sop: {e}")
            self._set_status(f"Pick error: {e}", error=True)

    def _push_placement_rules(self):
        if self.geo_node is None:
            return
        rules = getattr(self, "_placement_rules", [])
        logic.sync_placement_rules(self.geo_node, rules)
        self.sync_state(save=True)

    # ── Manual Scatter (single placement) ─────────────────────────────────────

    def _on_place_mode(self):
        """Enter click-to-place mode: user clicks in the viewport to place one asset."""
        if self.geo_node is None:
            self._set_status("Create a scatter network first.", error=True)
            return
        logic.ensure_manual_scatter(self.geo_node)

        piece_idx = 0
        if hasattr(self, "_manual_piece_sb"):
            piece_idx = self._manual_piece_sb.value()

        try:
            import hou
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            if viewer is None:
                self._set_status("No Scene Viewer pane found.", error=True)
                return
            positions = viewer.selectPositions(
                prompt="Click to place asset (right-click when done)",
                number_of_positions=-1,
                connect_positions=False,
                show_coordinates=True,
            )
            if not positions:
                return
            for p in positions:
                logic.add_manual_point(self.geo_node, (p[0], p[1], p[2]), piece_idx)
            self._set_status(f"Placed {len(positions)} point(s) manually.")
            self.sync_state(save=True)
        except Exception as e:
            self._set_status(f"Place error: {e}", error=True)
            logic.log(f"_on_place_mode: {e}")

    def _on_clear_manual(self):
        if self.geo_node is None:
            return
        logic.clear_manual_points(self.geo_node)
        self._set_status("Manual points cleared.")
        self.sync_state(save=True)

    def _pick_prox_sop(self):
        """Open Houdini node picker for the proximity exclusion SOP path."""
        try:
            import hou
            path = hou.ui.selectNode(
                relative_to_node=None,
                node_type_filter=hou.nodeTypeFilter.Sop,
            )
            if path and hasattr(self, "_prox_sop_le"):
                self._prox_sop_le.setText(path)
        except Exception as e:
            logic.log(f"_pick_prox_sop: {e}")

    def _populate_lod_cam_combo(self):
        """Refresh the LOD camera dropdown with all cameras in the scene."""
        if not hasattr(self, "_lod_cam_combo"):
            return
        self._lod_cam_combo.blockSignals(True)
        self._lod_cam_combo.clear()
        self._lod_cam_combo.addItem("-- None --", "")
        try:
            import hou
            for n in hou.node("/obj").children():
                if n.type().name() in ("cam", "camera"):
                    self._lod_cam_combo.addItem(n.name(), n.path())
        except Exception:
            pass
        self._lod_cam_combo.blockSignals(False)

    def _on_lod_toggled(self, *_):
        """Show/hide per-asset LOD table and trigger sync."""
        enabled = hasattr(self, "_lod_enabled_cb") and self._lod_enabled_cb.isChecked()
        if hasattr(self, "_lod_assets_widget"):
            self._lod_assets_widget.setVisible(enabled)
        self._sync_rt()

    def _rebuild_lod_asset_table(self):
        """Rebuild the per-asset LOD path rows to match current asset list."""
        if not hasattr(self, "_lod_table_lay"):
            return
        # Clear existing rows
        while self._lod_table_lay.count():
            item = self._lod_table_lay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        lod1_map = self.state.get("lod1_path_map", {})
        lod2_map = self.state.get("lod2_path_map", {})

        for aw in getattr(self, "asset_rows", []):
            asset_path = aw.node_path
            short = asset_path.split("/")[-1]
            if len(short) > 14:
                short = short[:13] + "…"

            row_w = QWidget()
            row = QHBoxLayout(row_w)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)

            name_lbl = QLabel(short)
            name_lbl.setStyleSheet("color:#7ab0ff; font-size:10px;")
            name_lbl.setToolTip(asset_path)
            row.addWidget(name_lbl, 1)

            for level, path_map in ((1, lod1_map), (2, lod2_map)):
                le = QLineEdit()
                le.setPlaceholderText(f"/obj/geo1/OUT_lod{level}")
                le.setText(path_map.get(asset_path, ""))
                le.setToolTip(f"LOD {level} variant of {short}")
                le.setProperty("asset_path", asset_path)
                le.setProperty("lod_level", level)
                le.textChanged.connect(self._on_lod_path_changed)

                pick = QPushButton("…")
                pick.setFixedWidth(22)
                pick.setToolTip(f"Pick LOD {level} SOP node")
                pick.clicked.connect(lambda _=False, _le=le: self._pick_lod_sop(_le))

                sub = QHBoxLayout()
                sub.setContentsMargins(0, 0, 0, 0)
                sub.setSpacing(2)
                sub.addWidget(le, 1)
                sub.addWidget(pick)
                row.addLayout(sub, 2)

            self._lod_table_lay.addWidget(row_w)

    def _on_lod_path_changed(self):
        """Update the LOD path maps in state when a path field changes."""
        le = self.sender()
        if le is None:
            return
        asset_path = le.property("asset_path")
        level      = le.property("lod_level")
        path       = le.text()
        map_key    = f"lod{level}_path_map"
        m = dict(self.state.get(map_key, {}))
        if path:
            m[asset_path] = path
        else:
            m.pop(asset_path, None)
        self.state[map_key] = m
        self._sync_rt()

    def _pick_lod_sop(self, line_edit):
        """Open Houdini node picker and set the given LOD path field."""
        try:
            import hou
            path = hou.ui.selectNode(
                relative_to_node=None,
                node_type_filter=hou.nodeTypeFilter.Sop,
            )
            if path:
                line_edit.setText(path)
        except Exception as e:
            logic.log(f"_pick_lod_sop: {e}")

    def _on_uniform_toggled(self, state):
        uniform = bool(state)
        self._uni_slider_widget.setVisible(uniform)
        self._axis_grid_widget.setVisible(not uniform)
        for sb in (self.smn_y, self.smn_z, self.smx_y, self.smx_z):
            sb.setEnabled(not uniform)
        self._sync_rt()

    def _propagate_uniform_min(self, v):
        if self.uni_cb.isChecked():
            self._prevent_sync = True
            self.smn_y.setValue(v)
            self.smn_z.setValue(v)
            self._prevent_sync = False
            self._sync_rt()

    def _propagate_uniform_max(self, v):
        if self.uni_cb.isChecked():
            self._prevent_sync = True
            self.smx_y.setValue(v)
            self.smx_z.setValue(v)
            self._prevent_sync = False
            self._sync_rt()

    # ======================================================================
    # State sync / persistence
    # ======================================================================

    @debounce(100)
    def _sync_rt(self, *_):
        """Triggered by any widget change; syncs immediately if real-time is on."""
        self.sync_state(save=self.rt_cb.isChecked())

    def _on_weight_changed(self):
        """Per-asset weight spinbox changed — persist to meta then live-sync.

        Without the explicit save_asset_node_paths call here, the new weight
        would only land in meta on the next add/remove of an asset.
        """
        self._save_asset_paths()
        if self.scatter_sop_node:
            logic.sync_asset_weights(
                self.scatter_sop_node,
                [w.weight_sl.value() / 100.0 for w in self.asset_rows],
            )
        self._sync_rt()

    def _on_scatter_noise_changed(self, *_):
        """Push Noises-tab values to mask_noise when the scatter network exists."""
        self._sync_rt()

    def _populate_mask_layer_combo(self, combo):
        """Populate combo box with available mask attributes from paint network."""
        combo.blockSignals(True)
        current = combo.currentText()
        combo.clear()

        paint_node = self._get_active_paint_node()
        if paint_node and paint_node.parent():
            geo = paint_node.parent()
            attrs = logic.get_available_mask_attributes(geo)
            if attrs:
                combo.addItems(attrs)

        if current and combo.findText(current) == -1:
            combo.addItem(current)

        if current:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    def _add_mask_layer_row(self, name="mask"):
        row_w = QWidget()
        row_h = QHBoxLayout(row_w)
        row_h.setContentsMargins(0, 0, 0, 0)
        row_h.setSpacing(4)
        rb = QRadioButton()
        rb.setToolTip("Set as active paint layer")
        rb.toggled.connect(self._on_active_mask_layer_toggled)
        self._mask_layer_radio_group.addButton(rb)
        row_h.addWidget(rb)

        combo = _RefreshingComboBox(self._populate_mask_layer_combo)
        combo.setEditable(True)
        combo.setToolTip("Select or type a point attribute name for this paint layer.\nDropdown lists attributes available to scatter_logic's Density Attribute.")
        combo.currentTextChanged.connect(self._on_mask_layer_changed)
        self._populate_mask_layer_combo(combo)
        combo.setCurrentText(name)
        row_h.addWidget(combo, 1)

        en_cb = QCheckBox()
        en_cb.setChecked(True)
        en_cb.setToolTip("Enable or disable this mask layer.")
        def _toggle_mask_layer(enabled, _combo=combo, _rb=rb):
            _combo.setEnabled(enabled)
            _rb.setEnabled(enabled)
            if self.scatter_sop_node is not None:
                layer_name = _combo.currentText().strip() or "mask"
                if layer_name == "mask":
                    node = self.scatter_sop_node
                else:
                    geo = self.scatter_sop_node.parent()
                    node = geo.node(f"paint_mask_{layer_name}") if geo else None
                if node is not None:
                    try:
                        node.bypass(not enabled)
                    except Exception:
                        pass
            self._on_mask_layer_changed()
        en_cb.toggled.connect(_toggle_mask_layer)
        row_h.addWidget(en_cb)

        rem_btn = QPushButton("×")
        rem_btn.setFixedWidth(24)
        rem_btn.setToolTip("Remove this mask layer.")
        rem_btn.clicked.connect(lambda checked=False, w=row_w: self._on_remove_mask_layer(w))
        row_h.addWidget(rem_btn)
        self._mask_layers_vlay.addWidget(row_w)
        self._mask_layer_rows.append((combo, rem_btn, row_w, rb, en_cb))
        if len(self._mask_layer_rows) == 1:
            rb.setChecked(True)
        self._update_mask_remove_buttons()
        return combo

    def _update_mask_remove_buttons(self):
        for _, btn, _, _, _ in self._mask_layer_rows:
            btn.setEnabled(len(self._mask_layer_rows) > 1)

    def _on_add_mask_layer(self):
        existing = {le.currentText().strip() for le, _, _, _, _ in self._mask_layer_rows}
        i = 2
        while f"mask{i}" in existing:
            i += 1
        self._add_mask_layer_row(f"mask{i}")
        self._on_mask_layer_changed()

    def _on_remove_mask_layer(self, row_widget):
        removed_active = False
        for i, (le, btn, w, rb, _) in enumerate(self._mask_layer_rows):
            if w is row_widget:
                if rb.isChecked():
                    removed_active = True
                self._mask_layer_radio_group.removeButton(rb)
                self._mask_layer_rows.pop(i)
                self._mask_layers_vlay.removeWidget(w)
                w.deleteLater()
                break
        if removed_active and self._mask_layer_rows:
            self._mask_layer_rows[0][3].setChecked(True)
        self._update_mask_remove_buttons()
        self._on_mask_layer_changed()

    def _clear_mask_layers(self):
        for _, _, row_w, rb, _ in self._mask_layer_rows:
            self._mask_layer_radio_group.removeButton(rb)
            self._mask_layers_vlay.removeWidget(row_w)
            row_w.deleteLater()
        self._mask_layer_rows.clear()

    def _on_active_mask_layer_toggled(self, checked):
        if not checked:
            return
        sender = self.sender()
        for le, _, _, rb, _ in self._mask_layer_rows:
            if rb is sender:
                self._active_mask_layer = le.currentText().strip() or "mask"
                self._push_active_paint_brush_params()
                node = self._get_active_paint_node()
                if node is not None:
                    try:
                        node.setSelected(True, clear_all_selected=True)
                        node.setCurrent(True)
                    except Exception:
                        pass
                return

    def _on_mask_layer_changed(self, *_):
        for le, _, _, rb, _ in self._mask_layer_rows:
            if rb.isChecked():
                self._active_mask_layer = le.currentText().strip() or "mask"
                break
        self._refresh_mask_layer_combo()
        self._sync_rt()

    def _refresh_mask_layer_combo(self):
        """Repopulate every Mask Gating layer dropdown with the current set of
        attribute names from the Brush > Mask Layers list (deduped)."""
        if not hasattr(self, "_mask_gating_entries"):
            return
        names = []
        seen = set()
        for le, _, _, _, _ in self._mask_layer_rows:
            n = le.currentText().strip()
            if n and n not in seen:
                names.append(n)
                seen.add(n)
        for layer_cb, _, _, _, _, _, _ in self._mask_gating_entries:
            current = layer_cb.currentText()
            layer_cb.blockSignals(True)
            layer_cb.clear()
            layer_cb.addItem("None")
            for n in names:
                layer_cb.addItem(n)
            idx = layer_cb.findText(current)
            layer_cb.setCurrentIndex(max(0, idx))
            layer_cb.blockSignals(False)

        # Also refresh the mask layer selection combos themselves
        if hasattr(self, "_mask_layer_rows"):
            for combo, _, _, _, _ in self._mask_layer_rows:
                self._populate_mask_layer_combo(combo)

        # Refresh global stamp mask layer selector
        if hasattr(self, "stamp_mask_layer_cb"):
            current = self.stamp_mask_layer_cb.currentText()
            self.stamp_mask_layer_cb.blockSignals(True)
            self.stamp_mask_layer_cb.clear()
            self.stamp_mask_layer_cb.addItem("None")
            for n in names:
                self.stamp_mask_layer_cb.addItem(n)
            idx = self.stamp_mask_layer_cb.findText(current)
            self.stamp_mask_layer_cb.setCurrentIndex(max(0, idx))
            self.stamp_mask_layer_cb.blockSignals(False)

        # Refresh per-layer stamp mask selectors
        if hasattr(self, "_stamp_layers"):
            for ld in self._stamp_layers:
                cb = ld.get("layer_mask_cb")
                if cb is None:
                    continue
                current = cb.currentText()
                cb.blockSignals(True)
                cb.clear()
                cb.addItem("None")
                for n in names:
                    cb.addItem(n)
                idx = cb.findText(current)
                cb.setCurrentIndex(max(0, idx))
                cb.blockSignals(False)

    def _add_mask_gating_row(self, layer_name="", op=0, blend=1.0, invert=False):
        row_w = QWidget()
        row_h = QHBoxLayout(row_w)
        row_h.setContentsMargins(0, 0, 0, 0)
        row_h.setSpacing(4)

        layer_cb = QComboBox()
        layer_cb.addItem("None")
        layer_cb.setToolTip("Choose the mask layer attribute that gates the noise effect.")
        for le, _, _, _, _ in self._mask_layer_rows:
            n = le.currentText().strip()
            if n and layer_cb.findText(n) < 0:
                layer_cb.addItem(n)
        if layer_name:
            idx = layer_cb.findText(layer_name)
            if idx < 0:
                layer_cb.addItem(layer_name)
                idx = layer_cb.findText(layer_name)
            layer_cb.setCurrentIndex(max(0, idx))
        layer_cb.currentIndexChanged.connect(self._on_scatter_noise_changed)

        op_cb = QComboBox()
        op_cb.addItems(["Subtract", "Multiply", "Add", "Average", "Min", "Max"])
        op_cb.setCurrentIndex(int(op))
        op_cb.setToolTip(
            "Subtract: mask - layer * blend (clamped to 0).\n"
            "Multiply: lerp(mask, mask * layer, blend).\n"
            "Add: mask + layer * blend (clamped to 1).\n"
            "Average: lerp(mask, (mask + layer) * 0.5, blend).\n"
            "Min: lerp(mask, min(mask, layer), blend).\n"
            "Max: lerp(mask, max(mask, layer), blend)."
        )
        op_cb.currentIndexChanged.connect(self._on_scatter_noise_changed)

        blend_sb = _make_spinbox(0.0, 1.0, float(blend), dec=3, step=0.01, width=64)
        blend_sb.setToolTip("How strongly this layer affects the mask (0 = no effect, 1 = full effect).")
        blend_sb.valueChanged.connect(self._on_scatter_noise_changed)

        inv_cb = QCheckBox()
        inv_cb.setChecked(bool(invert))
        inv_cb.setToolTip("Invert this mask layer (1 − value) before applying the operation.")
        inv_cb.toggled.connect(self._on_scatter_noise_changed)

        en_cb = QCheckBox()
        en_cb.setChecked(True)
        en_cb.setToolTip("Enable or disable this mask gating entry.")
        def _toggle_gating(enabled, _l=layer_cb, _o=op_cb, _b=blend_sb, _i=inv_cb):
            _l.setEnabled(enabled)
            _o.setEnabled(enabled)
            _b.setEnabled(enabled)
            _i.setEnabled(enabled)
            self._on_scatter_noise_changed()
        en_cb.toggled.connect(_toggle_gating)

        rem_btn = QPushButton("×")
        rem_btn.setFixedWidth(24)
        rem_btn.setToolTip("Remove this mask gating entry.")
        rem_btn.clicked.connect(lambda checked=False, w=row_w: self._on_remove_mask_gating(w))

        row_h.addWidget(layer_cb, 1)
        row_h.addWidget(op_cb)
        row_h.addWidget(blend_sb)
        row_h.addWidget(inv_cb)
        row_h.addWidget(en_cb)
        row_h.addWidget(rem_btn)
        self._mask_gating_vlay.addWidget(row_w)
        self._mask_gating_entries.append((layer_cb, op_cb, blend_sb, rem_btn, row_w, en_cb, inv_cb))
        self._update_mask_gating_remove_buttons()

    def _update_mask_gating_remove_buttons(self):
        for _, _, _, btn, _, _, _ in self._mask_gating_entries:
            btn.setEnabled(len(self._mask_gating_entries) > 1)

    def _on_add_mask_gating(self):
        self._add_mask_gating_row("", 0, 1.0)
        self._refresh_mask_layer_combo()
        self._on_scatter_noise_changed()

    def _on_remove_mask_gating(self, row_widget):
        for i, (_, _, _, _, w, _, _) in enumerate(self._mask_gating_entries):
            if w is row_widget:
                self._mask_gating_entries.pop(i)
                self._mask_gating_vlay.removeWidget(w)
                w.deleteLater()
                break
        self._update_mask_gating_remove_buttons()
        self._on_scatter_noise_changed()

    def _clear_mask_gating_rows(self):
        for _, _, _, _, w, _, _ in self._mask_gating_entries:
            self._mask_gating_vlay.removeWidget(w)
            w.deleteLater()
        self._mask_gating_entries.clear()

    def _reapply_lookdev_bindings(self, scatter_sop):
        """Re-inject material wrangles after the instancing network changes.
        Silently no-ops if no bindings exist or the lookdev module is missing."""
        paint_node = scatter_sop
        if paint_node is None and self.geo_node is not None:
            paint_node = self.geo_node.node("paint_mask")
        if paint_node is None:
            return
        try:
            from scatter_tool.lookdev import assign as _ld_assign
            _ld_assign.apply_bindings(paint_node)
        except Exception as e:
            print(f"[Magic Scatter World] Lookdev rebind skipped: {e}")

    def _open_lookdev(self):
        """Open the Lookdev window for the current scatter/ivy/crawl network."""
        paint_node = self.scatter_sop_node
        if paint_node is None and self.geo_node is not None:
            paint_node = self.geo_node.node("paint_mask")
        if paint_node is None:
            QMessageBox.information(
                self, "Lookdev",
                "Create a scatter network first, then add at least one asset.",
            )
            return
        try:
            import importlib
            from scatter_tool import logic as _l_reload
            importlib.reload(_l_reload)
            from scatter_tool.lookdev import ui as lookdev_ui
            importlib.reload(lookdev_ui)
        except Exception as e:
            QMessageBox.warning(self, "Lookdev", f"Failed to load Lookdev module:\n{e}")
            return
        # Hold a reference so the window isn't garbage-collected
        self._lookdev_win = lookdev_ui.open_window(paint_node, parent=self)

    def _get_active_paint_node(self):
        """Return the AttribPaint SOP for the currently active mask layer.
        Falls back to the primary paint_mask (self.scatter_sop_node)."""
        if self.scatter_sop_node is None:
            return None
        name = getattr(self, "_active_mask_layer", "mask") or "mask"
        if name == "mask":
            return self.scatter_sop_node
        geo = self.scatter_sop_node.parent()
        if geo is None:
            return self.scatter_sop_node
        node = geo.node(f"paint_mask_{name}")
        return node if node is not None else self.scatter_sop_node

    def _push_active_paint_brush_params(self):
        """Push brush params directly to the active paint node so the viewport
        state reflects the current Radius/Opacity/Soft Edge immediately."""
        node = self._get_active_paint_node()
        if node is None:
            return
        try:
            node.setParms({
                "stroke_radius":   self.r_sb.value(),
                "stroke_opacity":  self.fa_sb.value(),
                "stroke_softedge": self.fs_sb.value(),
            })
        except Exception:
            pass

    @debounce(100)
    def _sync_cone_orient(self, *_):
        """Push the Cone Angle slider value onto attribrandomize_orient
        (useconeangle=1, coneangle). Scatter mode only."""
        if self.geo_node is None or not hasattr(self, "cone_sb"):
            return
        logic.sync_orient_cone_angle(
            self.geo_node, self.cone_sb.value(), enable=True
        )

    def sync_state(self, save=True):
        if self._prevent_sync:
            return

        # Brush widgets exist in both modes (Set Dressing > Brush in scatter,
        # Paint Mask tab in ivy).
        self.state.update({
            "radius":           self.r_sb.value(),
            "density":          self.d_sb.value(),
            "spacing":          self.s_sb.value(),
            "falloff_amount":   self.fa_sb.value(),
            "falloff_softness": self.fs_sb.value(),
            "relax_iter":           self.relax_sb.value(),
            "max_points":           self.max_pts_sb.value(),
            "min_distance":         self.mdist_sb.value(),
            "remove_overlapping":   self.remove_overlap_cb.isChecked() if hasattr(self, "remove_overlap_cb") else False,
            "overlap_tolerance":    self.overlap_tol_sb.value() if hasattr(self, "overlap_tol_sb") else OVLP_TOL_DEF,
            "real_time":            self.rt_cb.isChecked(),
            "curve_scale":      self.curve_scale_sb.value() if hasattr(self, "curve_scale_sb") else 1.0,
        })

        if self._mode == "scatter" and hasattr(self, "_stamp_layers"):
            self.state["stamp_layers"] = self._get_stamp_layers_state()
        if self._mode == "scatter" and hasattr(self, "stamp_scale_sb"):
            self.state["stamp_scale"] = self.stamp_scale_sb.value()
        if self._mode == "scatter" and hasattr(self, "stamp_mask_layer_cb"):
            txt = self.stamp_mask_layer_cb.currentText()
            self.state["stamp_mask_layer"] = "" if txt == "None" else txt

        # Rotation + Scale widgets exist in both modes (Transformation tab is shared).
        # Blend-normal and Cone Angle widgets are scatter-only.
        self.state.update({
            "rot_min":          self.rot_min_sb.value(),
            "rot_max":          self.rot_max_sb.value(),
            "rot_randomize":    self.rot_rand_sb.value(),
            "full_rand":        self.full_rand_cb.isChecked(),
            "global_scale":     self.gs_sb.value(),
            "uniform_xyz":      self.uni_cb.isChecked(),
            "scl_min":          [self.smn_x.value(), self.smn_y.value(), self.smn_z.value()],
            "scl_max":          [self.smx_x.value(), self.smx_y.value(), self.smx_z.value()],
            "pscale_randomize":  self.pscale_rand_sb.value(),
            "weights":          [w.weight_sl.value() / 100.0 for w in self.asset_rows],
        })
        if self._mode == "scatter":
            self.state.update({
                "cone_angle":       self.cone_sb.value(),
                "normal_align":     self.normal_align_cb.isChecked(),
                "blend_axis":       self.blend_axis_cb.currentIndex(),
                "blend_amount":     self.blend_amount_sb.value(),
                "geo_offset":       self.geo_offset_sb.value() if hasattr(self, "geo_offset_sb") else 0.0,
                "cam_frustum_enabled": self._cam_frustum_cb.isChecked() if hasattr(self, "_cam_frustum_cb") else False,
                "cam_frustum_path":    (self._cam_combo.currentData() or "") if hasattr(self, "_cam_combo") else "",
                "cam_fov_padding":     self._cam_fov_pad_sb.value() if hasattr(self, "_cam_fov_pad_sb") else 0.0,
            })

            for key, widget in self._scatter_noise_widgets.items():
                if isinstance(widget, QComboBox):
                    self.state[key] = widget.currentIndex()
                elif isinstance(widget, QLineEdit):
                    self.state[key] = widget.text()
                elif isinstance(widget, QCheckBox):
                    self.state[key] = widget.isChecked()
                elif hasattr(widget, "value"):
                    self.state[key] = widget.value()

            if hasattr(self, "_mask_layer_rows"):
                self.state["scatter_mask_layers"] = [
                    le.currentText().strip()
                    for le, _, _, _, _ in self._mask_layer_rows
                    if le.currentText().strip()
                ]
                self.state["scatter_active_mask_layer"] = (
                    getattr(self, "_active_mask_layer", "mask") or "mask"
                )
            if hasattr(self, "_mask_gating_entries"):
                self.state["scatter_noise_mask_gating"] = [
                    {
                        "layer": layer_cb.currentText() if layer_cb.currentIndex() > 0 else "",
                        "op": op_cb.currentIndex(),
                        "blend": float(blend_sb.value()),
                        "invert": inv_cb.isChecked(),
                    }
                    for layer_cb, op_cb, blend_sb, _, _, en_cb, inv_cb in self._mask_gating_entries
                    if en_cb.isChecked()
                ]

            self.state["placement_rules"] = list(getattr(self, "_placement_rules", []))

            self.state.update({
                "scatter_cache_basedir": self.scatter_cache_folder_le.text(),
                "scatter_cache_basename": self.scatter_cache_name_le.text(),
                "scatter_cache_version": self.scatter_cache_version_sb.value(),
                "scatter_cache_loadfromdisk": self.scatter_cache_load_cb.isChecked(),
                "scatter_cache_timedependent": self.scatter_cache_timedependent_cb.isChecked(),
                "scatter_cache_trange": self.scatter_cache_trange_cb.currentIndex(),
                "scatter_cache_simulation": self.scatter_cache_simulation_cb.isChecked(),
                "scatter_cache_start": self.scatter_cache_start_sb.value(),
                "scatter_cache_end": self.scatter_cache_end_sb.value(),
                "scatter_cache_inc": self.scatter_cache_inc_sb.value(),
                "scatter_cache_substeps": self.scatter_cache_substeps_sb.value(),
            })

        # Clumping + Color Variation + Proximity Exclusion + LOD (scatter mode only)
        if self._mode == "scatter":
            if hasattr(self, "_prox_enabled_cb"):
                self.state.update({
                    "prox_enabled":  self._prox_enabled_cb.isChecked(),
                    "prox_radius":   self._prox_radius_sb.value(),
                    "prox_sop_path": self._prox_sop_le.text(),
                })
            if hasattr(self, "_lod_enabled_cb"):
                self.state.update({
                    "lod_enabled":   self._lod_enabled_cb.isChecked(),
                    "lod_cam_path":  self._lod_cam_combo.currentData() or "",
                    "lod1_dist":     self._lod1_dist_sb.value(),
                    "lod2_dist":     self._lod2_dist_sb.value(),
                    "lod_cull_dist": self._lod_cull_sb.value(),
                    # lod1_path_map / lod2_path_map updated live via _on_lod_path_changed
                })
            if hasattr(self, "clump_enabled_cb"):
                self.state.update({
                    "clump_enabled":   self.clump_enabled_cb.isChecked(),
                    "clump_radius":    self.clump_radius_sb.value(),
                    "clump_strength":  self.clump_strength_sb.value(),
                    "clump_min_count": self.clump_min_count_sb.value(),
                    "clump_seed":      self.clump_seed_sb.value(),
                })
            if hasattr(self, "color_var_enabled_cb"):
                c_a = self.color_var_a_btn._color
                c_b = self.color_var_b_btn._color
                self.state.update({
                    "color_variation_enabled": self.color_var_enabled_cb.isChecked(),
                    "color_variation_a": [c_a.redF(), c_a.greenF(), c_a.blueF()],
                    "color_variation_b": [c_b.redF(), c_b.greenF(), c_b.blueF()],
                    "color_variation_seed": self.color_var_seed_sb.value(),
                })

        # Ivy parameters — collect widget values into state (no cook here;
        # the dedicated _sync_ivy_rt / _push_ivy_params handles the ivy cook).
        # In scatter mode self._ivy_widgets is empty, so this is a no-op there.
        for name in IVY_DEFAULTS:
            sb = self._ivy_widgets.get(name)
            if sb is not None:
                self.state[name] = sb.value()

        if self._mode == "ivy":
            self.state["ivy_sim"] = self._get_ivy_sim_state()
            self.state["ivy_glue"] = self._get_ivy_glue_state()
            self.state["ivy_sim_length"] = {
                "min_length": self._ivy_sim_min_len_sb.value(),
                "max_length": self._ivy_sim_max_len_sb.value(),
            }
            self.state["ivy_collision"] = self.ivy_sim_collision_le.text()

        if save and self.scatter_sop_node is not None:
            logic.sync_scatter_params(self.scatter_sop_node, self.state)
            if self._mode == "scatter" and self.geo_node is not None:
                logic.sync_camera_frustum(
                    self.geo_node,
                    self.state.get("cam_frustum_enabled", False),
                    self.state.get("cam_frustum_path", ""),
                    self.state.get("cam_fov_padding", 0.0),
                )
            # Push ivy parms only when ivy widgets exist (ivy mode).
            if self._mode == "ivy":
                self._push_ivy_params(cook=False)
                logic.sync_ivy_orient(
                    self.geo_node,
                    self.state.get("rot_min",      0.0),
                    self.state.get("rot_max",      1.0),
                    self.state.get("full_rand",    False),
                    self.state.get("rot_randomize", 1.0),
                )
            # save_meta persists scatter-flow metadata (brush/stamp/transform/
            # assets). Only the scatter window owns that contract; ivy mode
            # writes its state directly to network parms via _push_ivy_params.
            if self._mode == "scatter":
                logic.save_meta(
                    self.scatter_sop_node,
                    surf          = self.surface_node_path,
                    surfs         = self.surface_paths,
                    rad           = self.state["radius"],
                    dens          = self.state["density"],
                    spacing       = self.state["spacing"],
                    stamp_layers  = self.state.get("stamp_layers", []),
                    rot_min       = self.state["rot_min"],
                    rot_max       = self.state["rot_max"],
                    cone_angle    = self.state["cone_angle"],
                    normal_align  = self.state["normal_align"],
                    full_rand     = self.state["full_rand"],
                    uni_xyz       = self.state["uniform_xyz"],
                    scl_min       = self.state["scl_min"],
                    scl_max       = self.state["scl_max"],
                    gl_scl        = self.state["global_scale"],
                    pscale_randomize = self.state["pscale_randomize"],
                    relax_iter    = int(self.state["relax_iter"]),
                    f_amt         = self.state["falloff_amount"],
                    f_soft        = self.state["falloff_softness"],
                    max_pts       = int(self.state["max_points"]),
                    min_distance  = self.state["min_distance"],
                    c_spacing     = self.curve_spacing_sb.value(),
                    c_jitter      = self.curve_jitter_sb.value(),
                    c_rot         = self.curve_rand_rot_sb.value(),
                    c_scale       = self.curve_scale_sb.value(),
                    c_subdiv      = self.curve_subdivide_cb.isChecked(),
                    scatter_noise = {
                        k: self.state.get(k, logic.SCATTER_NOISE_DEFAULTS.get(k))
                        for k in logic.SCATTER_NOISE_DEFAULTS
                    },
                    scatter_cache = {
                        k: self.state.get(k, logic.SCATTER_CACHE_DEFAULTS.get(k))
                        for k in logic.SCATTER_CACHE_DEFAULTS
                    },
                    mask_layers   = self.state.get("scatter_mask_layers", ["mask"]),
                    active_mask_layer = self.state.get("scatter_active_mask_layer", "mask"),
                    scatter_noise_mask_gating = self.state.get("scatter_noise_mask_gating", []),
                    cam_frustum_enabled = self.state.get("cam_frustum_enabled", False),
                    cam_frustum_path    = self.state.get("cam_frustum_path", ""),
                    cam_fov_padding     = self.state.get("cam_fov_padding", 0.0),
                    stamp_scale         = self.state.get("stamp_scale", 1.0),
                    stamp_mask_layer    = self.state.get("stamp_mask_layer", ""),
                    clump_enabled       = self.state.get("clump_enabled", False),
                    clump_radius        = self.state.get("clump_radius", 2.0),
                    clump_strength      = self.state.get("clump_strength", 0.7),
                    clump_min_count     = self.state.get("clump_min_count", 2),
                    clump_seed          = self.state.get("clump_seed", 42),
                    color_variation_enabled = self.state.get("color_variation_enabled", True),
                    color_variation_a   = self.state.get("color_variation_a", logic.COLOR_VARIATION_DEFAULTS["color_variation_a"]),
                    color_variation_b   = self.state.get("color_variation_b", logic.COLOR_VARIATION_DEFAULTS["color_variation_b"]),
                    color_variation_seed = self.state.get("color_variation_seed", 0),
                    prox_enabled        = self.state.get("prox_enabled", False),
                    prox_radius         = self.state.get("prox_radius", 2.0),
                    prox_sop_path       = self.state.get("prox_sop_path", ""),
                    lod_enabled         = self.state.get("lod_enabled", False),
                    lod_cam_path        = self.state.get("lod_cam_path", ""),
                    lod1_dist           = self.state.get("lod1_dist", 20.0),
                    lod2_dist           = self.state.get("lod2_dist", 50.0),
                    lod_cull_dist       = self.state.get("lod_cull_dist", 100.0),
                    lod1_path_map       = self.state.get("lod1_path_map", {}),
                    lod2_path_map       = self.state.get("lod2_path_map", {}),
                    placement_rules     = self.state.get("placement_rules", []),
                )
            elif self._mode == "ivy":
                logic.save_meta(
                    self.scatter_sop_node,
                    surf          = self.surface_node_path,
                    surfs         = self.surface_paths,
                    rad           = self.state["radius"],
                    dens          = self.state["density"],
                    spacing       = self.state["spacing"],
                    rot_min       = self.state["rot_min"],
                    rot_max       = self.state["rot_max"],
                    full_rand     = self.state["full_rand"],
                    uni_xyz       = self.state["uniform_xyz"],
                    scl_min       = self.state["scl_min"],
                    scl_max       = self.state["scl_max"],
                    gl_scl        = self.state["global_scale"],
                    pscale_randomize = self.state["pscale_randomize"],
                    relax_iter    = int(self.state["relax_iter"]),
                    f_amt         = self.state["falloff_amount"],
                    f_soft        = self.state["falloff_softness"],
                    max_pts       = int(self.state["max_points"]),
                    min_distance  = self.state["min_distance"],
                    ivy_sim       = self.state.get("ivy_sim", {}),
                    ivy_glue      = self.state.get("ivy_glue", {}),
                    ivy_sim_length = self.state.get("ivy_sim_length", {}),
                    ivy_collision = self.state.get("ivy_collision", ""),
                )

    # ======================================================================
    # Misc helpers
    # ======================================================================

    def _update_point_count(self):
        n = logic.get_point_count(self.scatter_sop_node)
        self.count_l.setText(f"{n:,} pts")

    def _set_status(self, msg, error=False):
        color = "#ff6060" if error else "#888"
        self.status_l.setStyleSheet(f"color:{color}; font-size:10px;")
        self.status_l.setText(msg)

    def _show_about(self):
        QMessageBox.information(
            self, "Magic Scatter World – About",
            f"Magic Scatter World for Houdini\nVersion: {TOOL_VERSION}\n\n"
            f"Original Maya version by Aydar Nagimov.\n"
            f"Houdini port by Arslan Abdusalyamov – pure Python, no C++ plugin required.\n\n"
            f"Scatter data is stored as packed prims inside the .hip file."
        )

    # ── theme ─────────────────────────────────────────────────────────────

    def _load_theme_pref(self):
        """Read the saved theme name from disk; fall back to the default."""
        path = _theme_pref_path()
        if not os.path.isfile(path):
            return DEFAULT_THEME
        try:
            with open(path, "r") as f:
                data = json.load(f)
            name = data.get("theme") if isinstance(data, dict) else None
            if name in THEMES:
                return name
        except Exception as e:
            print(f"[Magic Scatter World] Failed to load theme pref: {e}")
        return DEFAULT_THEME

    def _save_theme_pref(self, name):
        """Persist the chosen theme name."""
        try:
            with open(_theme_pref_path(), "w") as f:
                json.dump({"theme": name}, f, indent=2)
        except Exception as e:
            print(f"[Magic Scatter World] Failed to save theme pref: {e}")

    def _on_theme_changed(self, _index):
        name = self.theme_cb.currentText()
        if name not in THEMES or name == self._current_theme:
            return
        self._apply_theme(name)
        self._save_theme_pref(name)

    def _apply_theme(self, name):
        """Apply a theme by name and update internal state."""
        if name not in THEMES:
            return
        self._current_theme = name
        self.setStyleSheet(_build_stylesheet(name))

    def _refresh_theme_combo(self, select_name=None):
        """Rebuild the theme dropdown after user themes are added/removed."""
        cb = self.theme_cb
        cb.blockSignals(True)
        cb.clear()
        # Built-ins first (in their declared order), then user skins alphabetically
        for n in BUILTIN_THEMES:
            if n in THEMES:
                cb.addItem(n)
        user_names = sorted(n for n in THEMES if n not in BUILTIN_THEMES)
        for n in user_names:
            cb.addItem(n)
        target = select_name if select_name in THEMES else self._current_theme
        idx = cb.findText(target)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        cb.blockSignals(False)

    # ── skin editor ───────────────────────────────────────────────────────

    def _on_skin_new(self):
        """Open the skin editor to create a new user skin (starts from current theme)."""
        seed_tokens = dict(THEMES.get(self._current_theme, THEMES[DEFAULT_THEME]))
        dlg = _SkinEditorDialog(self, initial_name="", initial_tokens=seed_tokens)
        if dlg.exec_() != QDialog.Accepted:
            return
        name = dlg.get_name()
        if not name:
            QMessageBox.warning(self, "Invalid name", "Skin name cannot be empty.")
            return
        if name in BUILTIN_THEMES:
            QMessageBox.warning(
                self, "Reserved name",
                f"'{name}' is a built-in skin name. Please pick a different name.")
            return
        if name in THEMES:
            reply = QMessageBox.question(
                self, "Overwrite skin?",
                f"A skin named '{name}' already exists. Overwrite it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        tokens = dlg.get_tokens()
        try:
            _save_user_theme(name, tokens)
        except Exception as e:
            QMessageBox.warning(self, "Save failed", f"Could not save skin: {e}")
            return
        THEMES[name] = tokens
        self._refresh_theme_combo(select_name=name)
        self._apply_theme(name)
        self._save_theme_pref(name)

    def _on_skin_edit(self):
        """Edit the currently selected user skin (built-ins are read-only)."""
        name = self.theme_cb.currentText()
        if name in BUILTIN_THEMES:
            QMessageBox.information(
                self, "Built-in skin",
                f"'{name}' is a built-in skin and cannot be edited. "
                "Use '+ New' to create a custom skin based on it.")
            return
        if name not in THEMES:
            return
        dlg = _SkinEditorDialog(
            self, initial_name=name, initial_tokens=THEMES[name], locked_name=True)
        if dlg.exec_() != QDialog.Accepted:
            return
        tokens = dlg.get_tokens()
        try:
            _save_user_theme(name, tokens)
        except Exception as e:
            QMessageBox.warning(self, "Save failed", f"Could not save skin: {e}")
            return
        THEMES[name] = tokens
        # Re-apply if currently active
        if self._current_theme == name:
            self._apply_theme(name)

    def _on_skin_delete(self):
        """Delete the selected user skin (built-ins protected)."""
        name = self.theme_cb.currentText()
        if name in BUILTIN_THEMES:
            QMessageBox.information(
                self, "Built-in skin",
                f"'{name}' is a built-in skin and cannot be deleted.")
            return
        if name not in THEMES:
            return
        reply = QMessageBox.question(
            self, "Delete skin?",
            f"Delete skin '{name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            _delete_user_theme(name)
        except Exception as e:
            QMessageBox.warning(self, "Delete failed", f"Could not delete skin: {e}")
            return
        del THEMES[name]
        # Fall back to default theme
        fallback = DEFAULT_THEME if DEFAULT_THEME in THEMES else next(iter(THEMES))
        self._apply_theme(fallback)
        self._save_theme_pref(fallback)
        self._refresh_theme_combo(select_name=fallback)

    def _setup_hip_callbacks(self):
        try:
            hou.hipFile.addEventCallback(self._on_hip_event)
        except Exception:
            pass

    def _on_hip_event(self, event_type):
        if event_type in (hou.hipFileEventType.AfterLoad,
                          hou.hipFileEventType.AfterClear):
            self._refresh_resume_dropdown()

    def closeEvent(self, event):
        try:
            hou.hipFile.removeEventCallback(self._on_hip_event)
        except Exception:
            pass
        global _window, _window_ivy
        if _window is self:
            _window = None
        if _window_ivy is self:
            _window_ivy = None
        super().closeEvent(event)


# =============================================================================
# Python Panel entry point
# =============================================================================

def createInterface():
    """
    Called by Houdini when the Python Panel pane tab is opened.
    Returns the ScatterWindow widget (Houdini owns the lifetime).

    To register this panel in Houdini:
      Edit > Python Panel Editor → New Interface
      Module path: scatter_tool.ui
      Factory:     createInterface
    """
    global _window
    # Reuse an existing instance if already embedded in a panel
    if _window is not None:
        try:
            _window.deleteLater()
        except Exception:
            pass
    win = ScatterWindow()
    _window = win
    return win


# =============================================================================
# Fallback: floating window (for shelf button / launcher.py)
# =============================================================================

def _fit_to_screen(desired_w, desired_h):
    """Return (w, h) clamped to the available screen geometry with a margin."""
    try:
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            return min(desired_w, avail.width() - 40), min(desired_h, avail.height() - 80)
    except Exception:
        pass
    return desired_w, desired_h


def show():
    """Open Magic Scatter World as a floating tool window (shelf / legacy path)."""
    global _window

    app = QApplication.instance()
    if app:
        for w in app.topLevelWidgets():
            if w.objectName() == "SPScatterPanel" and isinstance(w, ScatterWindow):
                w.close()
                w.deleteLater()

    try:
        parent = hou.qt.mainWindow()
    except Exception:
        parent = None

    win = ScatterWindow(parent)
    win.setWindowFlags(Qt.Window)
    win.setWindowTitle(f"Magic Scatter World  v{TOOL_VERSION}")
    win.setMinimumSize(520, 560)
    w, h = _fit_to_screen(600, 860)
    win.resize(w, h)
    win.show()
    win.raise_()
    _window = win
    return win


# =============================================================================
# Ivy Scatter entry points (independent window — Transformation + Ivy tabs only)
# =============================================================================

def createInterfaceIvy():
    """Python Panel factory for the Ivy Scatter window."""
    global _window_ivy
    if _window_ivy is not None:
        try:
            _window_ivy.deleteLater()
        except Exception:
            pass
    win = ScatterWindow(mode="ivy")
    _window_ivy = win
    return win


def show_ivy():
    """Open Ivy Scatter as a floating tool window (shelf button)."""
    global _window_ivy

    app = QApplication.instance()
    if app:
        for w in app.topLevelWidgets():
            if w.objectName() == "IvyScatterPanel" and isinstance(w, ScatterWindow):
                w.close()
                w.deleteLater()

    try:
        parent = hou.qt.mainWindow()
    except Exception:
        parent = None

    win = ScatterWindow(parent, mode="ivy")
    win.setWindowFlags(Qt.Window)
    win.setWindowTitle(f"Ivy Scatter  v{TOOL_VERSION}")
    win.setMinimumSize(400, 440)
    w, h = _fit_to_screen(600, 860)
    win.resize(w, h)
    win.show()
    win.raise_()
    _window_ivy = win
    return win


def createInterfaceCrawlingIvy():
    """Python Panel factory for the Crawling Ivy window."""
    global _window_crawling_ivy
    if _window_crawling_ivy is not None:
        try:
            _window_crawling_ivy.deleteLater()
        except Exception:
            pass
    win = ScatterWindow(mode="crawling_ivy")
    _window_crawling_ivy = win
    return win


def show_crawling_ivy():
    """Open Crawling Ivy as a standalone floating window."""
    global _window_crawling_ivy

    app = QApplication.instance()
    if app:
        for w in app.topLevelWidgets():
            if w.objectName() == "CrawlingIvyPanel" and isinstance(w, ScatterWindow):
                w.close()
                w.deleteLater()

    try:
        parent = hou.qt.mainWindow()
    except Exception:
        parent = None

    win = ScatterWindow(parent, mode="crawling_ivy")
    win.setWindowFlags(Qt.Window)
    win.setWindowTitle(f"Crawling Ivy  v{TOOL_VERSION}")
    win.setMinimumSize(520, 560)
    ww, h = _fit_to_screen(600, 860)
    win.resize(ww, h)
    win.show()
    win.raise_()
    _window_crawling_ivy = win
    return win
