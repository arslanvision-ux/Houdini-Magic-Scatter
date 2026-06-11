"""
SP Scatter for Houdini – Thumbnail Generation
===============================================
Priority order for resolving a thumbnail:

  1. Memory cache
  2. Icons folder match  — finds an image in the package icons/ folder
                           whose filename (without extension) matches a prefix
                           of the asset node name, or vice-versa.
                           e.g. node "mushroom_01" matches "mushroom.png"
                                node "mushroom"    matches "mushroom.png"
                                node "rock_large"  matches "rock.png"
  3. Coloured placeholder with node name
"""

import os

try:
    from PySide2.QtGui import QPixmap, QImage, QPainter, QColor
    from PySide2.QtCore import Qt, QSize
except ImportError:
    from PySide6.QtGui import QPixmap, QImage, QPainter, QColor
    from PySide6.QtCore import Qt, QSize

# In-memory cache: cache_key → QPixmap
_PIX_CACHE = {}

# Supported image extensions (checked in order)
_IMG_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".exr")


# ---------------------------------------------------------------------------
# Icons folder discovery
# ---------------------------------------------------------------------------

def get_icons_dir():
    """
    Return the absolute path to the package icons/ folder.
    Walks up from this file:  scatter_tool/ -> scripts/ -> package_root/icons/
    """
    this_dir    = os.path.dirname(os.path.abspath(__file__))  # scatter_tool/
    scripts_dir = os.path.dirname(this_dir)                   # scripts/
    package_dir = os.path.dirname(scripts_dir)                # package root
    icons_dir   = os.path.join(package_dir, "icons")
    return icons_dir if os.path.isdir(icons_dir) else None


def _build_icons_index(icons_dir):
    """
    Return a dict mapping lowercase stem -> absolute file path for every
    image file found in icons_dir.
    e.g. {"mushroom": "/path/icons/mushroom.png", "rock": "/path/icons/rock.png"}
    """
    index = {}
    if not icons_dir or not os.path.isdir(icons_dir):
        return index
    for fname in os.listdir(icons_dir):
        stem, ext = os.path.splitext(fname)
        if ext.lower() in _IMG_EXTS:
            index[stem.lower()] = os.path.join(icons_dir, fname)
    return index


# Module-level icon index (rebuilt on first use and on force-refresh)
_ICONS_INDEX = None


def _get_icons_index(force=False):
    global _ICONS_INDEX
    if _ICONS_INDEX is None or force:
        _ICONS_INDEX = _build_icons_index(get_icons_dir())
    return _ICONS_INDEX


# ---------------------------------------------------------------------------
# Icon matching logic
# ---------------------------------------------------------------------------

def find_icon_for_node(node_name):
    """
    Try to find an image in the icons folder that matches node_name.

    Matching rules (all case-insensitive):
      1. Exact match:           node "mushroom"    -> mushroom.png
      2. Node is more specific: node "mushroom_01" -> mushroom.png
                                (node name starts with icon stem + separator)
      3. Icon is more specific: node "rock"        -> rock_large.png
                                (icon stem starts with node name + separator)

    Returns the absolute file path of the best match, or None.
    """
    index = _get_icons_index()
    if not index:
        return None

    name_lower = node_name.lower()

    # 1. Exact match
    if name_lower in index:
        return index[name_lower]

    # 2. Node name starts with icon stem  (mushroom_01 -> mushroom)
    #    Pick the longest stem so the most specific icon wins
    best     = None
    best_len = 0
    for stem, path in index.items():
        sep_pos = len(stem)
        if (len(name_lower) > sep_pos
                and name_lower.startswith(stem)
                and (name_lower[sep_pos] in ("_", "-", ".", " ") or name_lower[sep_pos].isdigit())):
            if sep_pos > best_len:
                best_len = sep_pos
                best     = path
    if best:
        return best

    # 3. Icon stem starts with node name  (rock -> rock_large)
    for stem, path in index.items():
        sep_pos = len(name_lower)
        if (len(stem) > sep_pos
                and stem.startswith(name_lower)
                and stem[sep_pos] in ("_", "-", ".", " ")):
            return path

    return None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def clear_cache():
    global _PIX_CACHE, _ICONS_INDEX
    _PIX_CACHE   = {}
    _ICONS_INDEX = None  # force re-scan of icons folder


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_thumbnail(node_path, width=100, height=100, session_id=None, force=False):
    """
    Return a QPixmap thumbnail for the given Houdini node path.

    Resolution order:
      1. Memory cache
      2. Icons folder match (by node name prefix)
      3. Coloured placeholder
    """
    global _PIX_CACHE

    cache_key = f"{node_path}_{width}x{height}_{session_id}"

    # 1. Memory cache
    if not force and cache_key in _PIX_CACHE:
        return _PIX_CACHE[cache_key]

    if force:
        _PIX_CACHE.pop(cache_key, None)
        _get_icons_index(force=True)  # re-scan icons folder

    node_name = node_path.split("/")[-1] if node_path else "unknown"

    # 2. Icons folder match
    pix = None
    icon_path = find_icon_for_node(node_name)
    if icon_path:
        pix = _load_and_scale(icon_path, width, height)

    # 3. Placeholder
    if pix is None or pix.isNull():
        pix = _make_placeholder(node_name, width, height)

    if pix and not pix.isNull():
        _PIX_CACHE[cache_key] = pix

    return pix


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_and_scale(path, width, height):
    """Load an image from disk and centre-crop it to width x height."""
    try:
        pix = QPixmap(path)
        if pix and not pix.isNull():
            scaled = pix.scaled(
                QSize(width, height),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = (scaled.width()  - width)  // 2
            y = (scaled.height() - height) // 2
            return scaled.copy(x, y, width, height)
    except Exception:
        pass
    return None


def _make_placeholder(label, width, height):
    """Coloured rectangle with the node name centred."""
    img = QImage(width, height, QImage.Format_RGB32)
    col = QColor.fromHsv(hash(label) % 360, 110, 75)
    img.fill(col)

    painter = QPainter(img)
    painter.setPen(QColor(210, 210, 210))
    short = (label[:12] + "…") if len(label) > 12 else label
    painter.drawText(img.rect(), Qt.AlignCenter, short)
    painter.end()

    return QPixmap.fromImage(img)
