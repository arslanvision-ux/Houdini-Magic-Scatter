"""
Common helpers shared by every engine builder.

Engines themselves are plain modules (not classes) — the interface is
duck-typed and documented in `engines/__init__.py`.
"""

import hou


def find_node_type(category, candidates):
    """Return the first matching hou.NodeType from `candidates`, or None.
    `category` is e.g. hou.vopNodeTypeCategory()."""
    for n in candidates:
        nt = hou.nodeType(category, n)
        if nt is not None:
            return nt
    return None


def ensure_matnet(path="/mat/scatter_lookdev"):
    """Return the /mat sub-folder that will hold our materials.
    Falls back to /mat itself if a nested matnet can't be created."""
    mat_root = hou.node("/mat")
    if mat_root is None:
        mat_root = hou.node("/")
    leaf = path.rsplit("/", 1)[-1]
    existing = mat_root.node(leaf)
    if existing is not None:
        return existing
    try:
        return mat_root.createNode("matnet", leaf)
    except Exception:
        # /mat doesn't allow nested matnets — drop materials directly in /mat
        print(f"[Lookdev] Placing materials directly in {mat_root.path()} "
              f"(nested matnet not supported by this Houdini build)")
        return mat_root


def safe_destroy(node):
    if node is None:
        return
    try:
        node.destroy()
    except Exception:
        pass


def uniquify(parent, base):
    """Return a unique child-name for `parent` based on `base`."""
    if parent.node(base) is None:
        return base
    i = 1
    while parent.node(f"{base}_{i}") is not None:
        i += 1
    return f"{base}_{i}"
