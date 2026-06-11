"""
Redshift shader builder.

Builds a Redshift material container (typically `redshift_vopnet`) with:

    redshift_material  (Surface, Displacement)
        ▲ Surface              ▲ Displacement
        │                      │
        Material               Displacement
        ▲ diffuse_color        ▲ texMap
        │                      │
        TextureSampler (diff)  TextureSampler (disp)

Type names vary across Redshift releases — every createNode goes through
`_try_create()` with a candidate chain and falls back to a runtime scan
of all registered redshift-prefixed types, so the shader still builds
even when names drift.
"""

import hou

from .. import conventions as conv

NAME = "Redshift"


# ── Node-type candidate chains (in priority order) ──────────────────────────
T_BUILDER   = ["redshift_vopnet", "Redshift_vopnet", "redshift::vopnet",
               "rs_materialbuilder", "redshift_materialbuilder"]
T_SURFACE   = ["redshift::Material", "redshift::StandardMaterial",
               "Redshift::Material"]
T_TEXTURE   = ["redshift::TextureSampler", "Redshift::TextureSampler",
               "redshift::texturesampler"]
T_BUMP      = ["redshift::BumpMap", "Redshift::BumpMap", "redshift::bumpmap"]
T_DISP      = ["redshift::Displacement", "Redshift::Displacement",
               "redshift::displacement"]
T_SPRITE    = ["redshift::Sprite", "Redshift::Sprite", "redshift::sprite"]


# Node names inside the container — stable so update() can find them
N_SURFACE   = "Material"
N_DISP_NODE = "Displacement"
N_NORMAL    = "BumpMap"
N_SPRITE    = "Sprite"
N_TEX_DIFF  = "tex_diffuse"
N_TEX_ROUGH = "tex_roughness"
N_TEX_METAL = "tex_metallic"
N_TEX_NORMAL = "tex_normal"
N_TEX_DISP  = "tex_displace"


def _first_existing_type(category, candidates):
    for n in candidates:
        if hou.nodeType(category, n) is not None:
            return n
    return None


def _discover_builder_types():
    """Last-resort scan of all VOP types for any Redshift material container."""
    cat = hou.vopNodeTypeCategory()
    found = []
    for name in cat.nodeTypes():
        nl = name.lower()
        if ("redshift" in nl or nl.startswith("rs_")) and ("vopnet" in nl or "materialbuilder" in nl):
            found.append(name)
    return sorted(found)


def is_available():
    cat = hou.vopNodeTypeCategory()
    return _first_existing_type(cat, T_SURFACE) is not None


def _try_create(parent, candidates, node_name):
    """Try each type name; return the created node or None on no-match."""
    last_err = None
    for t in candidates:
        try:
            return parent.createNode(t, node_name)
        except hou.OperationFailed as e:
            last_err = e
            continue
    if last_err is not None:
        print(f"[Lookdev/Redshift] no usable type in {candidates}: {last_err}")
    return None


def _connect(dst, dst_input, src):
    """Wire src's first output into dst's named input. Robust to output-name drift."""
    try:
        dst.setNamedInput(dst_input, src, 0)
        return
    except hou.OperationFailed:
        pass
    for out in ("outColor", "out", "out_color", "outClr", "outDisp",
                "outDisplacement", "output", "shader"):
        try:
            dst.setNamedInput(dst_input, src, out)
            return
        except hou.OperationFailed:
            continue
    try:
        ti = dst.inputNames().index(dst_input) if dst_input in dst.inputNames() else 0
        dst.setInput(ti, src)
    except Exception as e:
        print(f"[Lookdev/Redshift] could not connect {src.name()} → {dst.name()}.{dst_input}: {e}")


def _safe_set(parm, value):
    """Set a parm with type-fallback: try float, then int, then string.
    Some Redshift parms we expect to be numeric are actually string
    ordinals in certain releases (e.g. BumpMap inputType menus)."""
    if parm is None:
        return False
    for cast in (float, int, str):
        try:
            parm.set(cast(value))
            return True
        except (TypeError, ValueError, hou.OperationFailed):
            continue
    print(f"[Lookdev/Redshift] could not set {parm.path()} = {value!r}")
    return False


def _set_color(node, parm_base, rgb):
    """Try a few common color-parm naming schemes (r/g/b vs 1/2/3)."""
    pt = node.parmTuple(parm_base)
    if pt is not None:
        try:
            pt.set(rgb)
            return
        except Exception:
            pass
    for suf in (("r", "g", "b"), ("1", "2", "3"), ("_r", "_g", "_b")):
        parms = [node.parm(f"{parm_base}{s}") for s in suf]
        if all(p is not None for p in parms):
            for p, v in zip(parms, rgb):
                _safe_set(p, v)
            return


def _set_float(node, candidates, value):
    for n in candidates:
        p = node.parm(n)
        if p is not None:
            _safe_set(p, value)
            return


def _tex(builder, name, path, raw=False):
    t = _try_create(builder, T_TEXTURE, name)
    if t is None:
        raise RuntimeError(f"Redshift TextureSampler not found — tried {T_TEXTURE}")
    p = t.parm("tex0")
    if p is not None:
        p.set(conv.replace_udim_token(path, conv.REDSHIFT["udim_token"]))
    cs = t.parm("tex0_colorSpace") or t.parm("tex0_colorspace")
    if cs is not None:
        cs.set(conv.REDSHIFT["cs_raw"] if raw else conv.REDSHIFT["cs_color"])
    return t


def build(matnet, name, textures, params):
    """Build (or rebuild) a Redshift shader at <matnet>/<name>."""
    existing = matnet.node(name)
    if existing is not None:
        existing.destroy()

    builder = _try_create(matnet, T_BUILDER, name)
    if builder is None:
        # Fallback: scan registered types
        discovered = _discover_builder_types()
        if discovered:
            print(f"[Lookdev/Redshift] dynamic builder candidates: {discovered}")
            builder = _try_create(matnet, discovered, name)
    if builder is None:
        cat = hou.vopNodeTypeCategory()
        all_rs = sorted(n for n in cat.nodeTypes() if "redshift" in n.lower())
        print(f"[Lookdev/Redshift] all registered Redshift VOP types: {all_rs}")
        raise RuntimeError(
            f"Could not create Redshift material container — tried {T_BUILDER} plus dynamic scan. "
            "Check the Houdini Python Shell for available types. Is Redshift loaded?"
        )

    # Locate the output node (redshift_material) inside the builder
    out = builder.node("redshift_material")
    if out is None:
        for child in builder.children():
            tname = child.type().name().lower()
            if "material" in tname and "vopnet" not in tname and "builder" not in tname \
                    and "standard" not in tname and "texture" not in tname:
                out = child
                break
    if out is None:
        # Some versions auto-create a "suboutput" instead
        out = builder.node("suboutput1")
    if out is None:
        raise RuntimeError(
            f"'{builder.type().name()}' built without an output node — unexpected Redshift layout"
        )

    surface = _try_create(builder, T_SURFACE, N_SURFACE)
    if surface is None:
        raise RuntimeError(f"Redshift Material VOP not found — tried {T_SURFACE}")

    tint = tuple(params.get("basecolor_tint", (1.0, 1.0, 1.0)))
    rough_mul = float(params.get("roughness_mult", 1.0))
    metal_mul = float(params.get("metallic_mult", 1.0))
    norm_str  = float(params.get("normal_strength", 1.0))
    disp_scl  = float(params.get("displace_scale", 0.05))
    disp_mid  = float(params.get("displace_mid", 0.5))
    em_col    = tuple(params.get("emission_color", (1.0, 1.0, 1.0)))
    em_int    = float(params.get("emission_intensity", 0.0))

    # ── Diffuse ─────────────────────────────────────────────────────────────
    diff = textures.get("diffuse") or ""
    if diff:
        t = _tex(builder, N_TEX_DIFF, diff, raw=False)
        _connect(surface, "diffuse_color", t)
    _set_color(surface, "diffuse_color", tint)

    # ── Roughness ───────────────────────────────────────────────────────────
    rough = textures.get("roughness") or ""
    if rough:
        t = _tex(builder, N_TEX_ROUGH, rough, raw=True)
        _connect(surface, "refl_roughness", t)
    _set_float(surface, ["refl_roughness"], min(1.0, rough_mul * 0.5))

    # ── Metallic ────────────────────────────────────────────────────────────
    metal = textures.get("metallic") or ""
    if metal:
        t = _tex(builder, N_TEX_METAL, metal, raw=True)
        _connect(surface, "refl_metalness", t)
    _set_float(surface, ["refl_metalness"], max(0.0, min(1.0, metal_mul)))

    # ── Normal ──────────────────────────────────────────────────────────────
    normal = textures.get("normal") or ""
    if normal:
        t = _tex(builder, N_TEX_NORMAL, normal, raw=True)
        bump = _try_create(builder, T_BUMP, N_NORMAL)
        if bump is not None:
            _set_float(bump, ["inputType", "input_type"], 1)
            _set_float(bump, ["scale"], norm_str)
            _connect(bump, "input", t)
            _connect(surface, "bump_input", bump)
        else:
            _connect(surface, "bump_input", t)

    # ── Emission ────────────────────────────────────────────────────────────
    _set_color(surface, "emission_color", em_col)
    _set_float(surface, ["emission_weight"], em_int)

    # ── Opacity — RS_Sprite wraps the surface when a texture is provided ─────
    opacity_val = float(params.get("opacity", 1.0))
    opacity_tex = textures.get("opacity") or ""
    if opacity_tex:
        sprite = _try_create(builder, T_SPRITE, N_SPRITE)
        if sprite is not None:
            for pname in ("tex0", "imageName", "image_name"):
                p = sprite.parm(pname)
                if p is not None:
                    p.set(conv.replace_udim_token(opacity_tex, conv.REDSHIFT["udim_token"]))
                    break
            _connect(sprite, "input", surface)
            _connect(out, "Surface", sprite)
        else:
            print("[Lookdev/Redshift] RS_Sprite not available — opacity texture ignored")
            _set_float(surface, ["opacity_color_r", "opacity_color"], opacity_val)
            _connect(out, "Surface", surface)
    else:
        _set_float(surface, ["opacity_color_r", "opacity_color"], opacity_val)
        _connect(out, "Surface", surface)

    # ── Extra PBR parms ────────────────────────────────────────────────────
    _set_float(surface, ["refl_ior"], float(params.get("ior", 1.5)))
    _set_float(surface, ["refr_weight"], float(params.get("transmission", 0.0)))
    _set_float(surface, ["coat_weight"], float(params.get("coat_weight", 0.0)))
    _set_float(surface, ["coat_roughness"], float(params.get("coat_roughness", 0.1)))
    _set_float(surface, ["ms_amount"], float(params.get("sss_weight", 0.0)))

    # ── Displacement ────────────────────────────────────────────────────────
    disp = textures.get("displacement") or ""
    if disp:
        t = _tex(builder, N_TEX_DISP, disp, raw=True)
        d = _try_create(builder, T_DISP, N_DISP_NODE)
        if d is not None:
            _set_float(d, ["scale"], disp_scl)
            _set_float(d, ["newRange_min", "minNewRange"], -disp_scl)
            _set_float(d, ["newRange_max", "maxNewRange"], disp_scl)
            _set_float(d, ["oldRange_min", "minOldRange"], disp_mid - 0.5)
            _set_float(d, ["oldRange_max", "maxOldRange"], disp_mid + 0.5)
            _connect(d, "texMap", t)
            _connect(out, "Displacement", d)
        else:
            _connect(out, "Displacement", t)

    try:
        builder.layoutChildren()
    except Exception:
        pass
    return builder


_TEX_SLOT_TO_NODE = {
    "diffuse":      N_TEX_DIFF,
    "roughness":    N_TEX_ROUGH,
    "metallic":     N_TEX_METAL,
    "normal":       N_TEX_NORMAL,
    "opacity":      N_SPRITE,
    "displacement": N_TEX_DISP,
}


def update(mat_node, params, textures):
    """Live-tweak the existing shader. Returns True if all updates were
    applied in-place; False if a texture was added or removed (caller
    should call build() to rebuild the graph)."""
    if mat_node is None:
        return False

    tint = tuple(params.get("basecolor_tint", (1.0, 1.0, 1.0)))
    rough_mul = float(params.get("roughness_mult", 1.0))
    metal_mul = float(params.get("metallic_mult", 1.0))
    norm_str  = float(params.get("normal_strength", 1.0))
    disp_scl  = float(params.get("displace_scale", 0.05))
    disp_mid  = float(params.get("displace_mid", 0.5))
    em_col    = tuple(params.get("emission_color", (1.0, 1.0, 1.0)))
    em_int    = float(params.get("emission_intensity", 0.0))

    surface = mat_node.node(N_SURFACE)
    if surface is not None:
        _set_color(surface, "diffuse_color", tint)
        _set_float(surface, ["refl_roughness"], min(1.0, rough_mul * 0.5))
        _set_float(surface, ["refl_metalness"], max(0.0, min(1.0, metal_mul)))
        _set_color(surface, "emission_color", em_col)
        _set_float(surface, ["emission_weight"], em_int)
        if mat_node.node(N_SPRITE) is None:
            _set_float(surface, ["opacity_color_r", "opacity_color"],
                       float(params.get("opacity", 1.0)))
        _set_float(surface, ["refl_ior"], float(params.get("ior", 1.5)))
        _set_float(surface, ["refr_weight"], float(params.get("transmission", 0.0)))
        _set_float(surface, ["coat_weight"], float(params.get("coat_weight", 0.0)))
        _set_float(surface, ["coat_roughness"], float(params.get("coat_roughness", 0.1)))
        _set_float(surface, ["ms_amount"], float(params.get("sss_weight", 0.0)))

    bump = mat_node.node(N_NORMAL)
    if bump is not None:
        _set_float(bump, ["scale"], norm_str)

    d = mat_node.node(N_DISP_NODE)
    if d is not None:
        _set_float(d, ["scale"], disp_scl)
        _set_float(d, ["newRange_min", "minNewRange"], -disp_scl)
        _set_float(d, ["newRange_max", "maxNewRange"], disp_scl)
        _set_float(d, ["oldRange_min", "minOldRange"], disp_mid - 0.5)
        _set_float(d, ["oldRange_max", "maxOldRange"], disp_mid + 0.5)

    # ── Texture path updates (in-place file swap) ──────────────────────────
    # If a slot's texture node presence does not match the current path state
    # (node exists but path empty, or path set but no node), the graph
    # topology has changed and we need a full rebuild.
    for slot, node_name in _TEX_SLOT_TO_NODE.items():
        path = (textures.get(slot) or "").strip()
        tex_node = mat_node.node(node_name)
        if (tex_node is None) != (not path):
            return False
        if tex_node is not None and path:
            if slot == "opacity":
                for pname in ("tex0", "imageName", "image_name"):
                    p = tex_node.parm(pname)
                    if p is not None:
                        p.set(conv.replace_udim_token(path, conv.REDSHIFT["udim_token"]))
                        break
            else:
                p = tex_node.parm("tex0")
                if p is not None:
                    p.set(conv.replace_udim_token(path, conv.REDSHIFT["udim_token"]))
    return True


def exposed_parms():
    return [
        ("basecolor_tint",     "Base Color Tint",     "color", (1.0, 1.0, 1.0)),
        ("opacity",            "Opacity",             "float", 1.0),
        ("roughness_mult",     "Roughness Mult",      "float", 1.0),
        ("metallic_mult",      "Metallic Mult",       "float", 1.0),
        ("ior",                "IOR",                 "float", 1.5),
        ("transmission",       "Transmission",        "float", 0.0),
        ("coat_weight",        "Coat Weight",         "float", 0.0),
        ("coat_roughness",     "Coat Roughness",      "float", 0.1),
        ("sss_weight",         "SSS Weight",          "float", 0.0),
        ("normal_strength",    "Normal Strength",     "float", 1.0),
        ("displace_scale",     "Displace Scale",      "float", 0.05),
        ("displace_mid",       "Displace Mid",        "float", 0.5),
        ("emission_color",     "Emission Color",      "color", (1.0, 1.0, 1.0)),
        ("emission_intensity", "Emission Intensity",  "float", 0.0),
    ]
