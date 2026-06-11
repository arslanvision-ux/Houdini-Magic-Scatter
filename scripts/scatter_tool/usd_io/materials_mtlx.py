"""
MaterialX emitter.

Translates the lookdev binding schema (the same `textures` + `params` dicts
the SOP-side Arnold/Redshift engines consume) into a USD MaterialX shader
network authored directly into a cached prototype USD file. Targets Karma
and Arnold-via-USD render contexts.

Schema parity with the SOP engines:
    textures (6 slots) — diffuse | roughness | metallic | normal | opacity | displacement
    params   (14 keys) — basecolor_tint, opacity, roughness_mult, metallic_mult,
                         ior, transmission, coat_weight, coat_roughness,
                         sss_weight, normal_strength, displace_scale,
                         displace_mid, emission_color, emission_intensity
"""

import os

import hou
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

# MaterialX node IDs (NodeDef names) — the `info:id` token USD uses to
# resolve to the actual shader implementation at render time.
ND_SURFACE = "ND_standard_surface_surfaceshader"
ND_IMAGE_C = "ND_image_color3"
ND_IMAGE_F = "ND_image_float"
ND_MUL_C   = "ND_multiply_color3"
ND_MUL_F   = "ND_multiply_float"
ND_NORMAL  = "ND_normalmap"
ND_RANGE   = "ND_range_float"
ND_DISP    = "ND_displacement_float"

DEFAULT_MATERIAL_NAME = "PBR"


# ── Helpers ─────────────────────────────────────────────────────────────────
def _asset_path(p):
    """Normalise a texture path to forward slashes (USD asset values)."""
    return str(p).replace("\\", "/") if p else ""


def _create_shader(stage, prim_path, node_id):
    """Define a UsdShade.Shader at `prim_path` and set its MaterialX node id."""
    shader = UsdShade.Shader.Define(stage, prim_path)
    shader.CreateIdAttr(node_id)
    return shader


def _set_color3(shader, name, rgb):
    inp = shader.CreateInput(name, Sdf.ValueTypeNames.Color3f)
    inp.Set(Gf.Vec3f(float(rgb[0]), float(rgb[1]), float(rgb[2])))
    return inp


def _set_float(shader, name, v):
    inp = shader.CreateInput(name, Sdf.ValueTypeNames.Float)
    inp.Set(float(v))
    return inp


def _connect(dst_shader, dst_name, dst_type, src_shader, src_out="out", src_type=None):
    """Connect `src_shader.<src_out>` → `dst_shader.<dst_name>` (both as
    MaterialX-typed surfaces)."""
    src_out_attr = src_shader.CreateOutput(
        src_out, src_type if src_type is not None else dst_type
    )
    dst_inp = dst_shader.CreateInput(dst_name, dst_type)
    dst_inp.ConnectToSource(src_out_attr)
    return dst_inp


# ── Network authoring ──────────────────────────────────────────────────────
def _author_network(stage, material_path, textures, params):
    """Build the MaterialX network under `material_path` (a UsdShade.Material
    prim) and return that material so the caller can bind to it."""
    mat = UsdShade.Material.Define(stage, material_path)

    surface = _create_shader(stage, f"{material_path}/standard_surface", ND_SURFACE)

    # Explicit UV reader — wired into every image node so Arnold-USD and Karma
    # both find the correct primvar without relying on renderer-specific defaults.
    texcoord = _create_shader(stage, f"{material_path}/texcoord", "ND_texcoord_vector2")
    texcoord.CreateInput("index", Sdf.ValueTypeNames.Int).Set(0)
    texcoord_out = texcoord.CreateOutput("out", Sdf.ValueTypeNames.Float2)

    tint     = tuple(params.get("basecolor_tint", (1.0, 1.0, 1.0)))
    opacity  = float(params.get("opacity", 1.0))
    rough_m  = float(params.get("roughness_mult", 1.0))
    metal_m  = float(params.get("metallic_mult", 1.0))
    ior      = float(params.get("ior", 1.5))
    trans    = float(params.get("transmission", 0.0))
    coat_w   = float(params.get("coat_weight", 0.0))
    coat_r   = float(params.get("coat_roughness", 0.1))
    sss      = float(params.get("sss_weight", 0.0))
    norm_str = float(params.get("normal_strength", 1.0))
    disp_scl = float(params.get("displace_scale", 0.05))
    disp_mid = float(params.get("displace_mid", 0.5))
    em_col   = tuple(params.get("emission_color", (1.0, 1.0, 1.0)))
    em_int   = float(params.get("emission_intensity", 0.0))

    # ── Base color ──────────────────────────────────────────────────────────
    diff_path = _asset_path(textures.get("diffuse"))
    if diff_path:
        img = _create_shader(stage, f"{material_path}/tex_diffuse", ND_IMAGE_C)
        img.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(diff_path)
        img.CreateInput("texcoord", Sdf.ValueTypeNames.Float2).ConnectToSource(texcoord_out)
        if any(c != 1.0 for c in tint):
            mul = _create_shader(stage, f"{material_path}/tint_diffuse", ND_MUL_C)
            _connect(mul, "in1", Sdf.ValueTypeNames.Color3f, img, src_type=Sdf.ValueTypeNames.Color3f)
            _set_color3(mul, "in2", tint)
            _connect(surface, "base_color", Sdf.ValueTypeNames.Color3f, mul,
                     src_type=Sdf.ValueTypeNames.Color3f)
        else:
            _connect(surface, "base_color", Sdf.ValueTypeNames.Color3f, img,
                     src_type=Sdf.ValueTypeNames.Color3f)
    else:
        _set_color3(surface, "base_color", tint)

    # ── Roughness ───────────────────────────────────────────────────────────
    rough_path = _asset_path(textures.get("roughness"))
    if rough_path:
        img = _create_shader(stage, f"{material_path}/tex_roughness", ND_IMAGE_F)
        img.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(rough_path)
        img.CreateInput("texcoord", Sdf.ValueTypeNames.Float2).ConnectToSource(texcoord_out)
        if rough_m != 1.0:
            mul = _create_shader(stage, f"{material_path}/mul_roughness", ND_MUL_F)
            _connect(mul, "in1", Sdf.ValueTypeNames.Float, img, src_type=Sdf.ValueTypeNames.Float)
            _set_float(mul, "in2", rough_m)
            _connect(surface, "specular_roughness", Sdf.ValueTypeNames.Float, mul,
                     src_type=Sdf.ValueTypeNames.Float)
        else:
            _connect(surface, "specular_roughness", Sdf.ValueTypeNames.Float, img,
                     src_type=Sdf.ValueTypeNames.Float)
    else:
        _set_float(surface, "specular_roughness", max(0.0, min(1.0, rough_m * 0.5)))

    # ── Metallic ────────────────────────────────────────────────────────────
    metal_path = _asset_path(textures.get("metallic"))
    if metal_path:
        img = _create_shader(stage, f"{material_path}/tex_metallic", ND_IMAGE_F)
        img.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(metal_path)
        img.CreateInput("texcoord", Sdf.ValueTypeNames.Float2).ConnectToSource(texcoord_out)
        if metal_m != 1.0:
            mul = _create_shader(stage, f"{material_path}/mul_metallic", ND_MUL_F)
            _connect(mul, "in1", Sdf.ValueTypeNames.Float, img, src_type=Sdf.ValueTypeNames.Float)
            _set_float(mul, "in2", metal_m)
            _connect(surface, "metalness", Sdf.ValueTypeNames.Float, mul,
                     src_type=Sdf.ValueTypeNames.Float)
        else:
            _connect(surface, "metalness", Sdf.ValueTypeNames.Float, img,
                     src_type=Sdf.ValueTypeNames.Float)
    else:
        _set_float(surface, "metalness", max(0.0, min(1.0, metal_m)))

    # ── Normal ──────────────────────────────────────────────────────────────
    normal_path = _asset_path(textures.get("normal"))
    if normal_path:
        img = _create_shader(stage, f"{material_path}/tex_normal", ND_IMAGE_C)
        img.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(normal_path)
        img.CreateInput("texcoord", Sdf.ValueTypeNames.Float2).ConnectToSource(texcoord_out)
        nrm = _create_shader(stage, f"{material_path}/normal_map", ND_NORMAL)
        _connect(nrm, "in", Sdf.ValueTypeNames.Float3, img, src_type=Sdf.ValueTypeNames.Color3f)
        _set_float(nrm, "scale", norm_str)
        _connect(surface, "normal", Sdf.ValueTypeNames.Float3, nrm,
                 src_type=Sdf.ValueTypeNames.Float3)

    # ── Emission ────────────────────────────────────────────────────────────
    _set_color3(surface, "emission_color", em_col)
    _set_float(surface, "emission", em_int)

    # ── Opacity ─────────────────────────────────────────────────────────────
    opacity_path = _asset_path(textures.get("opacity"))
    if opacity_path:
        img = _create_shader(stage, f"{material_path}/tex_opacity", ND_IMAGE_F)
        img.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(opacity_path)
        img.CreateInput("texcoord", Sdf.ValueTypeNames.Float2).ConnectToSource(texcoord_out)
        if opacity != 1.0:
            mul = _create_shader(stage, f"{material_path}/mul_opacity", ND_MUL_F)
            _connect(mul, "in1", Sdf.ValueTypeNames.Float, img, src_type=Sdf.ValueTypeNames.Float)
            _set_float(mul, "in2", opacity)
            _connect(surface, "opacity", Sdf.ValueTypeNames.Color3f, mul,
                     src_type=Sdf.ValueTypeNames.Float)
        else:
            _connect(surface, "opacity", Sdf.ValueTypeNames.Color3f, img,
                     src_type=Sdf.ValueTypeNames.Float)
    else:
        _set_float(surface, "opacity", opacity)

    # ── Extra PBR scalars ──────────────────────────────────────────────────
    _set_float(surface, "specular_IOR", ior)
    _set_float(surface, "transmission", trans)
    _set_float(surface, "coat", coat_w)
    _set_float(surface, "coat_roughness", coat_r)
    _set_float(surface, "subsurface", sss)

    # ── Surface output → Material ──────────────────────────────────────────
    surf_out = surface.CreateOutput("out", Sdf.ValueTypeNames.Token)
    mat.CreateSurfaceOutput("mtlx").ConnectToSource(surf_out)   # Karma / Arnold
    mat.CreateSurfaceOutput().ConnectToSource(surf_out)          # Redshift (universal)

    # ── Displacement ────────────────────────────────────────────────────────
    disp_path = _asset_path(textures.get("displacement"))
    if disp_path:
        img = _create_shader(stage, f"{material_path}/tex_displace", ND_IMAGE_F)
        img.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(disp_path)
        img.CreateInput("texcoord", Sdf.ValueTypeNames.Float2).ConnectToSource(texcoord_out)
        rng = _create_shader(stage, f"{material_path}/disp_range", ND_RANGE)
        _connect(rng, "in", Sdf.ValueTypeNames.Float, img, src_type=Sdf.ValueTypeNames.Float)
        _set_float(rng, "inlow",  disp_mid - 0.5)
        _set_float(rng, "inhigh", disp_mid + 0.5)
        _set_float(rng, "outlow",  -disp_scl)
        _set_float(rng, "outhigh",  disp_scl)
        disp = _create_shader(stage, f"{material_path}/disp_out", ND_DISP)
        _connect(disp, "displacement", Sdf.ValueTypeNames.Float, rng,
                 src_type=Sdf.ValueTypeNames.Float)
        disp_out = disp.CreateOutput("out", Sdf.ValueTypeNames.Token)
        mat.CreateDisplacementOutput("mtlx").ConnectToSource(disp_out)
        mat.CreateDisplacementOutput().ConnectToSource(disp_out)

    return mat


# ── Public entry point ─────────────────────────────────────────────────────
def author_into_cache(cache_path, mesh_prim_path, material_name, textures, params):
    """Open a previously-cached prototype USD, add a MaterialX network at
    `<default_prim>/materials/<material_name>`, bind the mesh at
    `mesh_prim_path` to it, and save.

    cache_path        – absolute path to the cached prototype .usd
    mesh_prim_path    – USD path of the Mesh to bind (e.g. /asset/geo/...)
    material_name     – material prim name (alphanumeric/_)
    textures, params  – same shape as the SOP-side lookdev binding
    """
    if not os.path.exists(cache_path):
        raise hou.NodeError(
            f"author_into_cache: cache file not found at {cache_path}"
        )

    # Reuse the existing layer if it's already in USD's registry so we don't
    # collide on overwrite (same pattern as prototypes._read_cached_digest).
    layer = Sdf.Layer.FindOrOpen(cache_path)
    if layer is None:
        raise hou.NodeError(
            f"author_into_cache: could not open layer at {cache_path}"
        )
    stage = Usd.Stage.Open(layer)

    default_prim = stage.GetDefaultPrim()
    if not default_prim:
        raise hou.NodeError(
            f"author_into_cache: {cache_path} has no defaultPrim — cannot "
            "place materials under it."
        )

    materials_scope_path = default_prim.GetPath().AppendChild("materials")
    if not stage.GetPrimAtPath(materials_scope_path):
        UsdGeom.Scope.Define(stage, materials_scope_path)

    material_path = materials_scope_path.AppendChild(material_name)
    material = _author_network(stage, str(material_path), textures, params)

    # Bind the material explicitly to every Mesh in the prototype. Per-mesh
    # explicit bindings are the most portable path — renderers (including
    # Redshift) don't need to walk ancestors or rely on inheritance through
    # the PointInstancer prototype scope. Overrides any sopimport bindings so
    # the lookdev material is consistently applied across all sub-meshes.
    bound = False
    for prim in Usd.PrimRange(default_prim):
        if prim.IsA(UsdGeom.Mesh):
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
            bound = True
    if not bound:
        UsdShade.MaterialBindingAPI.Apply(default_prim).Bind(material)
    layer.Save()
