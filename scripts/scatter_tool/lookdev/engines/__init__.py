"""
Engine registry.

A LookdevEngine is a thin module exposing:
    NAME              str
    is_available()    -> bool
    build(matnet, name, textures, params) -> hou.Node
    update(mat_node, params, textures)    -> None
    exposed_parms()   -> list[(key, label, type, default)]

The window picks one engine per material; the registry returns only the
engines whose plugin nodes are loaded in the current Houdini session.
"""

import hou

from . import arnold, redshift

ALL_ENGINES = [arnold, redshift]


def available_engines():
    """Return the engine modules whose Houdini plugin is loaded."""
    return [e for e in ALL_ENGINES if e.is_available()]


def get_engine(name):
    """Resolve an engine by NAME (case-insensitive). Returns None if unknown."""
    name = (name or "").strip().lower()
    for e in ALL_ENGINES:
        if e.NAME.lower() == name:
            return e
    return None
