"""
Source-side material binding.

Each asset in the scatter network passes through:

    object_merge (asset_N)
        │
        ▼
    attribwrangle (asset_N_piece)        ← adds i@piece, primgroup
        │
        ▼
    attribwrangle (asset_N_material)     ← OWNED BY LOOKDEV
        │
        ▼
    merge_assets

The material wrangle reads its snippet from the lookdev binding stored
in the scatter network's userData and writes `s@shop_materialpath` on
the primitives whose `@name` matches the target groups (or all prims
if no groups are specified).

This wrangle is rebuilt by `apply_bindings()` whenever the binding
changes; `update_instancing_network()` in logic.py destroys/recreates
the upstream wrangles on asset list changes, so we re-inject after
that step too.
"""

import json
import hou

LOOKDEV_KEY = "scatter_lookdev_bindings"
MAT_WRANGLE_SUFFIX = "_material"


# ── Binding storage ─────────────────────────────────────────────────────────
def load_bindings(paint_node):
    if paint_node is None:
        return {}
    raw = paint_node.userData(LOOKDEV_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_bindings(paint_node, bindings):
    if paint_node is None:
        return
    paint_node.setUserData(LOOKDEV_KEY, json.dumps(bindings))


def set_binding(paint_node, asset_path, binding):
    """Upsert a single asset's binding. Pass binding=None to remove."""
    data = load_bindings(paint_node)
    if binding is None:
        data.pop(asset_path, None)
    else:
        data[asset_path] = binding
    save_bindings(paint_node, data)


def get_binding(paint_node, asset_path):
    return load_bindings(paint_node).get(asset_path)


# ── Group introspection ─────────────────────────────────────────────────────
def get_asset_groups(asset_path):
    """Return the unique `name` primitive attribute values of the source asset,
    so the UI can present a list of pieces inside the asset. Empty if the
    asset has no `name` attribute or fails to cook."""
    node = hou.node(asset_path)
    if node is None:
        return []
    try:
        geo = node.geometry()
    except Exception:
        return []
    if geo is None:
        return []
    attr = geo.findPrimAttrib("name")
    if attr is None:
        return []
    names = set()
    for v in attr.strings():
        if v:
            names.add(v)
    return sorted(names)


# ── Wrangle injection ───────────────────────────────────────────────────────
def _find_piece_wrangles(geo_node):
    """Return [(index, piece_aw)] for each asset_N_piece wrangle wired into
    merge_assets / assets_merge, in input order."""
    merge = geo_node.node("merge_assets") or geo_node.node("assets_merge")
    if merge is None:
        return []
    out = []
    for idx, conn in enumerate(merge.inputs()):
        if conn is None:
            continue
        out.append((idx, conn))
    return out


def _snippet_for(asset_path, binding):
    """VEX snippet that writes shop_materialpath, gated by group membership."""
    if not binding:
        return ""
    mat_path = binding.get("mat_path") or ""
    if not mat_path:
        return ""
    groups = binding.get("groups") or []
    mat_lit = json.dumps(mat_path)
    if groups:
        # gate by @name membership
        names_lit = ", ".join(json.dumps(g) for g in groups)
        return (
            "string targets[] = array({names});\n"
            "if (find(targets, s@name) >= 0) {{\n"
            "    s@shop_materialpath = {mat};\n"
            "}}\n"
        ).format(names=names_lit, mat=mat_lit)
    return f"s@shop_materialpath = {mat_lit};\n"


def _ensure_material_wrangle(geo_node, piece_aw, asset_path, binding):
    """Insert/refresh the asset_N_material wrangle downstream of piece_aw."""
    mat_name = piece_aw.name() + MAT_WRANGLE_SUFFIX
    existing = geo_node.node(mat_name)

    snippet = _snippet_for(asset_path, binding)

    if not snippet:
        # No active binding — remove the material wrangle if present, restoring
        # the direct piece_aw → merge_assets wiring
        if existing is not None:
            merge = geo_node.node("merge_assets") or geo_node.node("assets_merge")
            if merge is not None:
                for idx, conn in enumerate(merge.inputs()):
                    if conn is existing:
                        merge.setInput(idx, piece_aw)
                        break
            try:
                existing.destroy()
            except Exception:
                pass
        return None

    aw = existing
    is_new = aw is None
    if is_new:
        aw = geo_node.createNode("attribwrangle", mat_name)
    aw.setInput(0, piece_aw)
    aw.setParms({"class": 1, "snippet": snippet})

    # Place the material wrangle directly under piece_aw so the chain
    # reads top-to-bottom in the network view instead of spilling sideways.
    if is_new:
        try:
            px, py = piece_aw.position()
            aw.setPosition([px, py - 1.0])
        except Exception:
            pass

    # Rewire merge_assets so it consumes the material wrangle, not piece_aw
    merge = geo_node.node("merge_assets") or geo_node.node("assets_merge")
    if merge is not None:
        for idx, conn in enumerate(merge.inputs()):
            if conn is piece_aw:
                merge.setInput(idx, aw)
                break
    return aw


def apply_bindings(paint_node):
    """Rebuild every asset_N_material wrangle to match the current bindings.
    Safe to call after asset list changes, on .hip load, or after a binding edit."""
    if paint_node is None:
        return
    geo = paint_node.parent()
    bindings = load_bindings(paint_node)

    # Each merge_assets input is either the piece_aw directly (no binding
    # yet) or our asset_N_material wrangle (binding active). Climb to the
    # true piece_aw, then the object_merge under it carries objpath1.
    for idx, node in _find_piece_wrangles(geo):
        if node.name().endswith(MAT_WRANGLE_SUFFIX):
            piece_aw = node.input(0)
        else:
            piece_aw = node
        if piece_aw is None:
            continue
        om = piece_aw.input(0)
        if om is None or om.parm("objpath1") is None:
            continue
        asset_path = om.parm("objpath1").eval()
        binding = bindings.get(asset_path)
        # Skip if the bound material no longer exists in /mat
        if binding and hou.node(binding.get("mat_path", "")) is None:
            binding = None
        _ensure_material_wrangle(geo, piece_aw, asset_path, binding)
