"""
Arnold (HtoA) shader builder.

Builds an arnold material container in /mat with:

    OUT_material  (surface, displacement)
        ▲                ▲
        │                │
    standard_surface     [range]
        ▲ base_color     ▲
        │                │
        [tint mul] ◄ image (displacement)
        ▲
        image (diffuse)
        ...

Container, multiply, and range node-type names vary across HtoA releases.
Each createNode call uses a candidate chain and falls back gracefully if
an optional helper node is missing — so the shader still builds with a
simpler graph instead of erroring out.
"""

import hou

from .. import conventions as conv

NAME = "Arnold"


# ── Node-type candidate chains (in priority order) ──────────────────────────
T_BUILDER  = ["arnold_materialbuilder", "arnold_vopnet", "arnold::materialbuilder"]
T_SURFACE  = ["arnold::standard_surface"]
T_IMAGE    = ["arnold::image"]
T_NORMAL   = ["arnold::normal_map"]
T_MULTIPLY = ["arnold::multiply", "arnold::math_multiply"]
T_RANGE    = ["arnold::range"]


def _first_existing_type(category, candidates):
    for n in candidates:
        if hou.nodeType(category, n) is not None:
            return n
    return None


def _discover_builder_types():
    """Scan all registered VOP types for any Arnold material-container node.
    Used as a last resort when the candidate chain produces no match."""
    cat = hou.vopNodeTypeCategory()
    found = []
    for name in cat.nodeTypes():
        nl = name.lower()
        if "arnold" in nl and ("material" in nl or "vopnet" in nl) and "standard" not in nl:
            found.append(name)
    return sorted(found)


def is_available():
    cat = hou.vopNodeTypeCategory()
    return _first_existing_type(cat, T_SURFACE) is not None


def _try_create(parent, candidates, node_name):
    """Try each type name; return the created node or None on no-match.
    Prints to console which type ultimately worked, so you can see what
    HtoA is actually shipping in this Houdini version."""
    last_err = None
    for t in candidates:
        try:
            n = parent.createNode(t, node_name)
            return n
        except hou.OperationFailed as e:
            last_err = e
            continue
    if last_err is not None:
        print(f"[Lookdev/Arnold] no usable type in {candidates}: {last_err}")
    return None


# Node names inside the materialbuilder — stable so update() can find them
N_SURFACE    = "standard_surface"
N_TINT_MUL   = "tint_diffuse"
N_ROUGH_MUL  = "mul_roughness"
N_METAL_MUL  = "mul_metallic"
N_OPACITY_MUL = "mul_opacity"
N_NORMAL     = "normal_map"
N_DISP_RNG   = "disp_range"


def _img(builder, name, path, raw=False):
    img = _try_create(builder, T_IMAGE, name)
    if img is None:
        raise RuntimeError("arnold::image node type not found in this Houdini")
    p = img.parm("filename")
    if p is not None:
        p.set(conv.replace_udim_token(path, conv.ARNOLD["udim_token"]))
    cs = img.parm("color_space")
    if cs is not None:
        cs.set(conv.ARNOLD["cs_raw"] if raw else conv.ARNOLD["cs_color"])
    return img


def _connect(dst, dst_input, src):
    """Wire src's first output into dst's named input. Robust to output-name drift."""
    try:
        dst.setNamedInput(dst_input, src, 0)
        return
    except hou.OperationFailed:
        pass
    for out in ("rgba", "rgb", "out", "shader", "output", "color"):
        try:
            dst.setNamedInput(dst_input, src, out)
            return
        except hou.OperationFailed:
            continue
    # Last resort — wire by input index
    try:
        ti = dst.inputNames().index(dst_input) if dst_input in dst.inputNames() else 0
        dst.setInput(ti, src)
    except Exception as e:
        print(f"[Lookdev/Arnold] could not connect {src.name()} → {dst.name()}.{dst_input}: {e}")


def _multiply(builder, name, source_node, factor_rgba):
    """Insert a multiply VOP. Returns the multiplier node, or `source_node`
    unchanged if arnold has no multiply type (graceful fallback)."""
    mul = _try_create(builder, T_MULTIPLY, name)
    if mul is None:
        return source_node
    _connect(mul, "input1", source_node)
    pt = mul.parmTuple("input2")
    if pt is not None:
        try:
            pt.set(factor_rgba)
        except Exception:
            # Some versions name it differently — try input2r/g/b/a
            for suf, val in zip(("r", "g", "b", "a"), factor_rgba):
                p = mul.parm(f"input2{suf}")
                if p is not None:
                    p.set(float(val))
    return mul


def build(matnet, name, textures, params):
    """Build (or rebuild) an Arnold shader at <matnet>/<name>.
    Returns the materialbuilder node."""
    existing = matnet.node(name)
    if existing is not None:
        existing.destroy()

    builder = _try_create(matnet, T_BUILDER, name)
    if builder is None:
        # Candidate chain failed — try a live scan of registered types
        discovered = _discover_builder_types()
        if discovered:
            print(f"[Lookdev/Arnold] dynamic builder candidates: {discovered}")
            builder = _try_create(matnet, discovered, name)
    if builder is None:
        cat = hou.vopNodeTypeCategory()
        all_arn = sorted(n for n in cat.nodeTypes() if "arnold" in n.lower())
        print(f"[Lookdev/Arnold] all registered Arnold VOP types: {all_arn}")
        raise RuntimeError(
            f"Could not create Arnold material container — tried {T_BUILDER} plus dynamic scan. "
            "Check the Houdini Python Shell for available types. Is HtoA loaded?"
        )

    out_mat = builder.node("OUT_material")
    if out_mat is None:
        for child in builder.children():
            tname = child.type().name().lower()
            if "material" in tname and "builder" not in tname:
                out_mat = child
                break
    if out_mat is None:
        raise RuntimeError(
            f"'{builder.type().name()}' built without an OUT_material child — "
            "unexpected HtoA layout"
        )

    surface = _try_create(builder, T_SURFACE, N_SURFACE)
    if surface is None:
        raise RuntimeError("arnold::standard_surface not found — HtoA missing?")
    _connect(out_mat, "surface", surface)

    tint = tuple(params.get("basecolor_tint", (1.0, 1.0, 1.0)))
    rough_mul = float(params.get("roughness_mult", 1.0))
    metal_mul = float(params.get("metallic_mult", 1.0))
    norm_str  = float(params.get("normal_strength", 1.0))
    disp_scl  = float(params.get("displace_scale", 0.05))
    disp_mid  = float(params.get("displace_mid", 0.5))
    em_col    = tuple(params.get("emission_color", (1.0, 1.0, 1.0)))
    em_int    = float(params.get("emission_intensity", 0.0))

    # ── Base color ──────────────────────────────────────────────────────────
    diff = textures.get("diffuse") or ""
    if diff:
        img = _img(builder, "tex_diffuse", diff, raw=False)
        node_into_surface = _multiply(builder, N_TINT_MUL, img, tint + (1.0,))
        _connect(surface, "base_color", node_into_surface)
    else:
        pt = surface.parmTuple("base_color")
        if pt is not None:
            try:
                pt.set(tint)
            except Exception:
                pass

    # ── Roughness ───────────────────────────────────────────────────────────
    rough = textures.get("roughness") or ""
    if rough:
        img = _img(builder, "tex_roughness", rough, raw=True)
        node_into = _multiply(builder, N_ROUGH_MUL, img,
                              (rough_mul, rough_mul, rough_mul, 1.0))
        _connect(surface, "specular_roughness", node_into)
    else:
        p = surface.parm("specular_roughness")
        if p is not None:
            p.set(max(0.0, min(1.0, rough_mul * 0.5)))

    # ── Metallic ────────────────────────────────────────────────────────────
    metal = textures.get("metallic") or ""
    if metal:
        img = _img(builder, "tex_metallic", metal, raw=True)
        node_into = _multiply(builder, N_METAL_MUL, img,
                              (metal_mul, metal_mul, metal_mul, 1.0))
        _connect(surface, "metalness", node_into)
    else:
        p = surface.parm("metalness")
        if p is not None:
            p.set(0.0)

    # ── Normal ──────────────────────────────────────────────────────────────
    normal = textures.get("normal") or ""
    if normal:
        img = _img(builder, "tex_normal", normal, raw=True)
        nrm = _try_create(builder, T_NORMAL, N_NORMAL)
        if nrm is not None:
            _connect(nrm, "input", img)
            if nrm.parm("strength") is not None:
                nrm.parm("strength").set(norm_str)
            _connect(surface, "normal", nrm)
        else:
            _connect(surface, "normal", img)

    # ── Emission ────────────────────────────────────────────────────────────
    pt = surface.parmTuple("emission_color")
    if pt is not None:
        try:
            pt.set(em_col)
        except Exception:
            pass
    if surface.parm("emission") is not None:
        surface.parm("emission").set(em_int)

    # ── Opacity ──────────────────────────────────────────────────────────────
    opacity_val = float(params.get("opacity", 1.0))
    opacity_tex = textures.get("opacity") or ""
    if opacity_tex:
        img = _img(builder, "tex_opacity", opacity_tex, raw=True)
        node_into = _multiply(builder, N_OPACITY_MUL, img,
                              (opacity_val, opacity_val, opacity_val, 1.0))
        _connect(surface, "opacity", node_into)
    else:
        p = surface.parm("opacity")
        if p is not None:
            try:
                p.set(opacity_val)
            except Exception:
                pass

    # ── Extra PBR parms (IOR / transmission / coat / SSS) ────────────────────
    for parm_name, key, default in (
        ("specular_IOR",    "ior",            1.5),
        ("transmission",    "transmission",   0.0),
        ("coat",            "coat_weight",    0.0),
        ("coat_roughness",  "coat_roughness", 0.1),
        ("subsurface",      "sss_weight",     0.0),
    ):
        p = surface.parm(parm_name)
        if p is not None:
            try:
                p.set(float(params.get(key, default)))
            except Exception:
                pass

    # ── Displacement ────────────────────────────────────────────────────────
    disp = textures.get("displacement") or ""
    if disp:
        img = _img(builder, "tex_displace", disp, raw=True)
        rng = _try_create(builder, T_RANGE, N_DISP_RNG)
        if rng is not None:
            _connect(rng, "input", img)
            for p, v in (("input_min", disp_mid - 0.5),
                         ("input_max", disp_mid + 0.5),
                         ("output_min", -disp_scl),
                         ("output_max",  disp_scl)):
                if rng.parm(p) is not None:
                    rng.parm(p).set(v)
            _connect(out_mat, "displacement", rng)
        else:
            _connect(out_mat, "displacement", img)

    try:
        builder.layoutChildren()
    except Exception:
        pass
    return builder


_TEX_SLOT_TO_NODE = {
    "diffuse":      "tex_diffuse",
    "roughness":    "tex_roughness",
    "metallic":     "tex_metallic",
    "normal":       "tex_normal",
    "opacity":      "tex_opacity",
    "displacement": "tex_displace",
}


def _safe_set_parm(parm, value):
    if parm is None:
        return
    try:
        parm.set(value)
    except Exception:
        try:
            parm.set(float(value))
        except Exception:
            pass


def update(mat_node, params, textures):
    """Live-tweak existing shader. Returns True if all updates applied
    in-place; False if a texture was added/removed (caller must rebuild)."""
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
        pt = surface.parmTuple("emission_color")
        if pt is not None:
            try: pt.set(em_col)
            except Exception: pass
        if surface.parm("emission") is not None:
            surface.parm("emission").set(em_int)
        if mat_node.node(N_TINT_MUL) is None:
            pt = surface.parmTuple("base_color")
            if pt is not None:
                try: pt.set(tint)
                except Exception: pass
        if mat_node.node(N_ROUGH_MUL) is None and surface.parm("specular_roughness") is not None:
            surface.parm("specular_roughness").set(max(0.0, min(1.0, rough_mul * 0.5)))
        op_mul = mat_node.node(N_OPACITY_MUL)
        opacity_val = float(params.get("opacity", 1.0))
        if op_mul is not None:
            _set_mul(op_mul, (opacity_val, opacity_val, opacity_val, 1.0))
        else:
            _safe_set_parm(surface.parm("opacity"), opacity_val)
        _safe_set_parm(surface.parm("specular_IOR"), float(params.get("ior", 1.5)))
        _safe_set_parm(surface.parm("transmission"), float(params.get("transmission", 0.0)))
        _safe_set_parm(surface.parm("coat"), float(params.get("coat_weight", 0.0)))
        _safe_set_parm(surface.parm("coat_roughness"), float(params.get("coat_roughness", 0.1)))
        _safe_set_parm(surface.parm("subsurface"), float(params.get("sss_weight", 0.0)))

    def _set_mul(node, rgba):
        if node is None:
            return
        pt = node.parmTuple("input2")
        if pt is not None:
            try:
                pt.set(rgba)
                return
            except Exception:
                pass
        for suf, val in zip(("r", "g", "b", "a"), rgba):
            p = node.parm(f"input2{suf}")
            if p is not None:
                p.set(float(val))

    _set_mul(mat_node.node(N_TINT_MUL),  tint + (1.0,))
    _set_mul(mat_node.node(N_ROUGH_MUL), (rough_mul, rough_mul, rough_mul, 1.0))
    _set_mul(mat_node.node(N_METAL_MUL), (metal_mul, metal_mul, metal_mul, 1.0))

    nrm = mat_node.node(N_NORMAL)
    if nrm is not None and nrm.parm("strength") is not None:
        nrm.parm("strength").set(norm_str)

    rng = mat_node.node(N_DISP_RNG)
    if rng is not None:
        for p, v in (("input_min", disp_mid - 0.5),
                     ("input_max", disp_mid + 0.5),
                     ("output_min", -disp_scl),
                     ("output_max",  disp_scl)):
            if rng.parm(p) is not None:
                rng.parm(p).set(v)

    # ── Texture path updates (in-place file swap) ──────────────────────────
    for slot, node_name in _TEX_SLOT_TO_NODE.items():
        path = (textures.get(slot) or "").strip()
        tex_node = mat_node.node(node_name)
        if (tex_node is None) != (not path):
            return False
        if tex_node is not None and path:
            p = tex_node.parm("filename")
            if p is not None:
                from .. import conventions as _conv
                p.set(_conv.replace_udim_token(path, _conv.ARNOLD["udim_token"]))
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
