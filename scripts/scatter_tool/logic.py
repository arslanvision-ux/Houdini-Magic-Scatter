"""
SP Scatter for Houdini – Logic Layer
=====================================
Pure-Python scatter backend. No Maya imports. Stores scattered instances
as packed primitives inside a Houdini Geometry (SOP) node so that all
data is saved automatically with the .hip file.

Replaces the Maya scatterPaint C++ node with a Python-managed hou.Geometry.
"""

import hou
import os
import json
import random
import math
import re

from scatter_tool.usd_io import prototypes as usd_prototypes
from scatter_tool.usd_io import materials_mtlx as usd_materials_mtlx
from scatter_tool.lookdev import assign as lookdev_assign

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------
TOOL_VERSION = "1.3.0"
DENSITY_COEFF = 0.01     # same scaling as Maya version
DEBUG = False

SCATTER_CACHE_DEFAULTS = {
    "scatter_cache_basedir": "$HIP/geo",
    "scatter_cache_basename": "$HIPNAME.$OS",
    "scatter_cache_version": 1,
    "scatter_cache_loadfromdisk": False,
    "scatter_cache_timedependent": False,
    "scatter_cache_trange": 0,
    "scatter_cache_simulation": True,
    "scatter_cache_start": 1,
    "scatter_cache_end": 50,
    "scatter_cache_inc": 1,
    "scatter_cache_substeps": 1,
}

CLUMP_DEFAULTS = {
    "clump_enabled":   False,
    "clump_radius":    2.0,
    "clump_strength":  0.7,
    "clump_min_count": 2,
    "clump_seed":      42,
}

COLOR_VARIATION_DEFAULTS = {
    "color_variation_enabled": True,
    "color_variation_a":       [0.22, 0.45, 0.10],
    "color_variation_b":       [0.38, 0.65, 0.18],
    "color_variation_seed":    0,
}

FLIP_DEFAULTS = {
    "flip_enabled":     False,
    "flip_probability": 0.5,
    "flip_seed":        0,
}

PROXIMITY_DEFAULTS = {
    "prox_enabled":  False,
    "prox_radius":   2.0,
    "prox_sop_path": "",
}

LOD_DEFAULTS = {
    "lod_enabled":   False,
    "lod_cam_path":  "",
    "lod1_dist":     20.0,
    "lod2_dist":     50.0,
    "lod_cull_dist": 100.0,
    "lod1_path_map": {},
    "lod2_path_map": {},
}

_CLUMP_VEX = """\
if (!chi("clump_enabled")) return;
float radius   = chf("clump_radius");
float strength = chf("clump_strength");
int   min_n    = chi("clump_min_count");
int   seed     = chi("clump_seed");

int pts[] = pcfind(0, "P", @P, radius, 100);
int neighbor_count = len(pts) - 1;

if (neighbor_count < min_n) {
    removepoint(0, @ptnum);
    return;
}

vector centroid = {0, 0, 0};
foreach (int pt; pts) {
    if (pt != @ptnum) centroid += point(0, "P", pt);
}
centroid /= float(max(1, neighbor_count));

float t = strength * fit01(rand(float(@ptnum) * 1234.5 + seed), 0.4, 1.0);
@P = lerp(@P, centroid, t);
"""

_FLIP_VEX = """\
if (!chi("flip_enabled")) return;
float prob = chf("flip_prob");
int   seed = chi("flip_seed");
if (rand(float(@ptnum) * 2345.67 + seed) > prob) return;
if (length(@orient) < 0.001) { @orient = set(0.0, 0.0, 0.0, 1.0); }
vector axis = length(@N) > 0.001 ? normalize(@N) : set(0.0, 1.0, 0.0);
vector4 flip_q = quaternion(radians(180.0), axis);
@orient = qmultiply(flip_q, @orient);
"""

_PROXIMITY_VEX = """\
if (!chi("prox_enabled")) return;
if (npoints(1) == 0) return;
float radius = chf("prox_radius");
int near = nearpoint(1, @P, radius);
if (near >= 0) {
    removepoint(0, @ptnum);
}
"""

_LOD_VEX = """\
if (!chi("lod_enabled")) return;
string cam = chs("cam_path");
if (cam == "") return;
matrix xform = optransform(cam);
vector cam_pos = set(getcomp(xform,3,0), getcomp(xform,3,1), getcomp(xform,3,2));
float dist = distance(@P, cam_pos);
int n = chi("asset_count");
float cull_dist = chf("cull_dist");
float lod2_dist = chf("lod2_dist");
float lod1_dist = chf("lod1_dist");
if (cull_dist > 0.0 && dist > cull_dist) { removepoint(0, @ptnum); return; }
if (n > 0 && lod2_dist > 0.0 && dist > lod2_dist) { i@piece += 2*n; return; }
if (n > 0 && lod1_dist > 0.0 && dist > lod1_dist) { i@piece += n; }
"""

_COLOR_VEX = """\
if (!chi("color_enabled")) return;
int    seed  = chi("color_seed");
vector col_a = chv("color_a");
vector col_b = chv("color_b");
float  t     = rand(float(@ptnum) * 3141.59 + seed);
v@Cd = lerp(col_a, col_b, t);
"""

CRAWL_CACHE_DEFAULTS = {
    "crawl_cache_basedir":  "$HIP/geo",
    "crawl_cache_basename": "$HIPNAME.crawl_curves",
    "crawl_cache_version": 1,
    "crawl_cache_loadfromdisk": False,
    "crawl_cache_timedependent": False,
    "crawl_cache_trange": 0,
    "crawl_cache_simulation": True,
    "crawl_cache_start": 1,
    "crawl_cache_end": 100,
    "crawl_cache_inc": 1,
    "crawl_cache_substeps": 1,
}

SCATTER_NOISE_DEFAULTS = {
    "scatter_noise_enabled": False,
    "scatter_noise_group": "",
    "scatter_noise_enable_blend": False,
    "scatter_noise_blend": 1.0,
    "scatter_noise_attrib_type": 0,  # Float
    "scatter_noise_attrib": "mask",
    "scatter_noise_class": 0,
    "scatter_noise_along_vector": False,
    "scatter_noise_operation": 1,   # Add
    "scatter_noise_range": 1,       # Zero Centered
    "scatter_noise_amplitude": 3.577,
    "scatter_noise_output_raw": True,
    "scatter_noise_enable_remap": False,
    "scatter_noise_type": 1,        # Sparse Convolution
    "scatter_noise_location_attr": "P",
    "scatter_noise_element_size": 1.491,
    "scatter_noise_offset": 44.715,
    "scatter_noise_use_vexpression": False,
    "scatter_noise_animate": False,
    "scatter_noise_pulse_duration": 3.523,
    "scatter_noise_fractal_type": 2,  # Terrain
    "scatter_noise_max_octaves": 6,
    "scatter_noise_lacunarity": 6.938,
    "scatter_noise_roughness": 0.089,
    "scatter_noise_enable_min": False,
    "scatter_noise_min": 0.0,
    "scatter_noise_enable_max": False,
    "scatter_noise_max": 0.407,
    "scatter_noise_unit_length": False,
    "scatter_noise_recompute_normals": True,
}

# ---------------------------------------------------------------------------
# Placement Rules
# ---------------------------------------------------------------------------

RULE_TYPES = {
    "slope":     "Slope Filter",
    "altitude":  "Altitude Filter",
    "noise":     "Noise Filter",
    "dist_path": "Distance from Path",
}

RULE_DEFAULTS = {
    "slope":     {"enabled": True, "max_slope": 30.0},
    "altitude":  {"enabled": True, "min_alt": 0.0, "max_alt": 100.0},
    "noise":     {"enabled": True, "frequency": 0.5, "threshold": 0.4, "seed": 0},
    "dist_path": {"enabled": True, "min_dist": 0.0, "max_dist": 10.0, "sop_path": ""},
}

_RULE_VEX = {
    "slope": """\
if (!chi("enabled")) return;
float angle = degrees(acos(clamp(dot(normalize(@N), set(0,1,0)), -1.0, 1.0)));
if (angle > chf("max_slope")) removepoint(0, @ptnum);
""",
    "altitude": """\
if (!chi("enabled")) return;
float lo = chf("min_alt");
float hi = chf("max_alt");
if (@P.y < lo || @P.y > hi) removepoint(0, @ptnum);
""",
    "noise": """\
if (!chi("enabled")) return;
float freq  = chf("frequency");
float thresh = chf("threshold");
int   seed  = chi("seed");
float n = noise(@P * freq + set(seed*1.734, seed*2.134, seed*0.867));
n = fit(n, 0.2, 0.8, 0.0, 1.0);
if (n < thresh) removepoint(0, @ptnum);
""",
    "dist_path": """\
if (!chi("enabled")) return;
if (npoints(1) == 0) return;
float min_d = chf("min_dist");
float max_d = chf("max_dist");
int near = nearpoint(1, @P, max(min_d, max_d) + 0.001);
float d = near >= 0 ? distance(@P, point(1, "P", near)) : 1e9;
if (min_d > 0 && d < min_d) { removepoint(0, @ptnum); return; }
if (max_d > 0 && d > max_d) { removepoint(0, @ptnum); return; }
""",
}

# Tag written to every scatter geo node so we can find them later
SCATTER_TAG = "sp_scatter_node"
META_KEY    = "scatter_meta"



def log(msg):
    if DEBUG:
        print(f"[Magic Scatter World DEBUG] {msg}")


def _set_parm(node, parm_names, value):
    """Set the first existing parm from parm_names, ignoring Houdini-version drift."""
    if node is None:
        return
    if isinstance(parm_names, str):
        parm_names = (parm_names,)
    for pname in parm_names:
        p = node.parm(pname)
        if p is None:
            continue
        try:
            p.set(value)
            return
        except Exception as e:
            log(f"{node.name()} parm {pname} set error: {e}")


def sync_scatter_noise_parms(geo_node, state):
    """Push SP Scatter Noises-tab values onto mask_noise Attribute Noise."""
    if geo_node is None:
        return
    noise = geo_node.node("mask_noise")
    if noise is None:
        return

    # Enable/Disable (Bypass) the node
    enabled = state.get("scatter_noise_enabled", SCATTER_NOISE_DEFAULTS["scatter_noise_enabled"])
    try:
        noise.bypass(not bool(enabled))
    except Exception:
        pass

    defaults = SCATTER_NOISE_DEFAULTS
    attr = state.get("scatter_noise_attrib", defaults["scatter_noise_attrib"])
    _set_parm(noise, "attribtype", state.get("scatter_noise_attrib_type", defaults["scatter_noise_attrib_type"]))
    _set_parm(noise, "attribs", attr)
    _set_parm(noise, "attribname", attr)
    range_value = state.get("scatter_noise_range", defaults["scatter_noise_range"])
    _set_parm(noise, "noiserange", range_value)
    _set_parm(noise, "range", range_value)
    _set_parm(noise, "rangevalues", range_value)

    parm_map = (
        (("group",), "scatter_noise_group"),
        (("doblend", "useblend", "enableblend"), "scatter_noise_enable_blend"),
        (("blendweight", "blend"), "scatter_noise_blend"),
        (("class", "attribclass"), "scatter_noise_class"),
        (("noisealongvector", "noisealongvectorx"), "scatter_noise_along_vector"),
        (("operation",), "scatter_noise_operation"),
        (("amplitude", "amplitudev"), "scatter_noise_amplitude"),
        (("outputraw", "outputrawvalue"), "scatter_noise_output_raw"),
        (("enableremap", "remap"), "scatter_noise_enable_remap"),
        (("basis", "noisetype", "noise"), "scatter_noise_type"),
        (("locationattrib", "locationattr", "locattr"), "scatter_noise_location_attr"),
        (("elementsize", "elementsizev"), "scatter_noise_element_size"),
        (("offset", "offsetv"), "scatter_noise_offset"),
        (("usevexpression", "vexpression"), "scatter_noise_use_vexpression"),
        (("animated", "animatenoise", "animate"), "scatter_noise_animate"),
        (("pulseduration", "pulse"), "scatter_noise_pulse_duration"),
        (("fractaltype", "fbmtype", "fractal"), "scatter_noise_fractal_type"),
        (("oct", "maxoctaves", "octaves"), "scatter_noise_max_octaves"),
        (("lacunarity", "lac"), "scatter_noise_lacunarity"),
        (("roughness", "rough"), "scatter_noise_roughness"),
        (("doclampmin", "usemin", "enablemin", "minenable"), "scatter_noise_enable_min"),
        (("clampminvalue", "minimum", "min"), "scatter_noise_min"),
        (("doclampmax", "usemax", "enablemax", "maxenable"), "scatter_noise_enable_max"),
        (("clampmaxvalue", "maximum", "max"), "scatter_noise_max"),
        (("makeunitlength", "makevectorsunitlength"), "scatter_noise_unit_length"),
        (("recomputenormals", "recomputeN"), "scatter_noise_recompute_normals"),
    )
    for parm_names, state_key in parm_map:
        value = state.get(state_key, defaults.get(state_key))
        if isinstance(value, bool):
            value = int(value)
        _set_parm(noise, parm_names, value)


def sync_mask_layers(geo_node, state):
    """Create/destroy AttribPaint nodes for each mask layer beyond the primary
    'mask' layer, chain them in order, and push shared brush params to all paint
    nodes. Returns the ordered list of paint nodes (primary first)."""
    if geo_node is None:
        return []

    layers = state.get("scatter_mask_layers", ["mask"]) or ["mask"]

    primary = geo_node.node("paint_mask")
    if primary is None:
        return []

    # Keep the primary AttribPaint SOP's output attribute in sync with the
    # first row of the Mask Layers UI (e.g. rename "mask" → "flowers").
    primary_name = (layers[0] if layers else "mask") or "mask"
    try:
        if primary.parm("attribname1").eval() != primary_name:
            primary.setParms({"attribname1": primary_name})
    except Exception:
        pass

    # Discover existing extra paint nodes (paint_mask_<layer>)
    existing_extras = {}
    for child in geo_node.children():
        nm = child.name()
        if nm.startswith("paint_mask_") and child.type().name() == "attribpaint":
            existing_extras[nm[len("paint_mask_"):]] = child

    extras_wanted = [n for n in layers[1:] if n]
    extras_target = set(extras_wanted)
    needs_relayout = False

    # Delete unwanted extras
    for layer_name in list(existing_extras.keys()):
        if layer_name not in extras_target:
            try:
                existing_extras[layer_name].destroy()
                needs_relayout = True
            except Exception:
                pass
            existing_extras.pop(layer_name, None)

    # Create missing extras
    for layer_name in extras_wanted:
        if layer_name not in existing_extras:
            node = geo_node.createNode("attribpaint", f"paint_mask_{layer_name}")
            node.setParms({"attribname1": layer_name})
            existing_extras[layer_name] = node
            needs_relayout = True

    # Build ordered list and wire chain
    paint_nodes = [primary] + [existing_extras[n] for n in extras_wanted]
    for i in range(1, len(paint_nodes)):
        cur_in = paint_nodes[i].input(0)
        if cur_in is None or cur_in.path() != paint_nodes[i-1].path():
            paint_nodes[i].setInput(0, paint_nodes[i-1])
            needs_relayout = True

    # Sync brush params to all paint nodes
    radius   = state.get("radius", 1.0)
    opacity  = state.get("falloff_amount", 1.0)
    softness = state.get("falloff_softness", 0.5)
    for pn in paint_nodes:
        try:
            pn.setParms({
                "stroke_radius":   radius,
                "stroke_opacity":  opacity,
                "stroke_softedge": softness,
            })
        except Exception:
            pass

    if needs_relayout:
        try:
            geo_node.layoutChildren()
        except Exception:
            pass

    return paint_nodes


def _mask_chain_tail(geo_node):
    """Return the last paint node in the paint_mask → paint_mask_<n> chain."""
    primary = geo_node.node("paint_mask")
    if primary is None:
        return None
    tail = primary
    seen = {primary.path()}
    while True:
        nxt = None
        for child in geo_node.children():
            if child.path() in seen:
                continue
            if child.type().name() != "attribpaint":
                continue
            if not child.name().startswith("paint_mask_"):
                continue
            inp = child.input(0)
            if inp is not None and inp.path() == tail.path():
                nxt = child
                break
        if nxt is None:
            break
        tail = nxt
        seen.add(tail.path())
    return tail


def get_available_mask_attributes(geo_node):
    """Get list of available mask attributes from scatter_logic's input geometry.

    This mirrors what scatter_logic's Density Attribute dropdown shows — all
    numeric point attributes on the geometry feeding into the scatter node,
    with vector attributes expanded into their components (e.g. flowdir → flowdir_x).
    """
    if geo_node is None:
        return []
    scatter = geo_node.node("scatter_logic")
    if scatter is None:
        return []
    try:
        input_node = scatter.input(0)
        if input_node is None:
            return []
        try:
            input_node.cook(force=False)
        except Exception:
            pass
        geo = input_node.geometry()
        if geo is None:
            return []
        names = []
        for a in geo.pointAttribs():
            nm = a.name()
            if nm in ('P', 'Pw', 'id'):
                continue
            try:
                size = a.size()
            except Exception:
                size = 1
            if size == 1:
                names.append(nm)
            elif size in (2, 3, 4):
                suffixes = ['x', 'y', 'z', 'w'][:size]
                for s in suffixes:
                    names.append(f"{nm}_{s}")
        return sorted(set(names))
    except Exception as e:
        log(f"Error getting mask attributes from scatter_logic: {e}")
        return []


def ensure_scatter_mask_noise(geo_node):
    """Ensure chain: last_paint → mask_noise → mask_post_apply → scatter_logic.

    mask_post_apply's snippet is generated from the mask gating entries by
    sync_mask_gating(); each entry applies sequentially so they stack."""
    if geo_node is None:
        return None
    scatter = geo_node.node("scatter_logic")
    tail = _mask_chain_tail(geo_node)
    if tail is None or scatter is None:
        return None

    # Older versions of this tool created a 'mask_pre_capture' wrangle in the
    # chain. The new gating formula doesn't need it — destroy it if present.
    old_pre = geo_node.node("mask_pre_capture")
    if old_pre is not None:
        try:
            old_pre.destroy()
        except Exception:
            pass

    # Save the painted mask before noise so we can constrain noise to painted areas.
    save = geo_node.node("mask_paint_save")
    if save is None:
        save = geo_node.createNode("attribwrangle", "mask_paint_save")
        save.setParms({"class": 2, "snippet": "f@_pmask = @mask;"})
    if save.input(0) is None or save.input(0).path() != tail.path():
        save.setInput(0, tail)

    noise = geo_node.node("mask_noise")
    if noise is None:
        noise = geo_node.createNode("attribnoise", "mask_noise")
        sync_scatter_noise_parms(geo_node, SCATTER_NOISE_DEFAULTS)
    if noise.input(0) is None or noise.input(0).path() != save.path():
        noise.setInput(0, save)

    post = geo_node.node("mask_post_apply")
    if post is None:
        post = geo_node.createNode("attribwrangle", "mask_post_apply")
        post.setParms({"class": 2, "snippet": "// no mask gating"})
    if post.input(0) is None or post.input(0).path() != noise.path():
        post.setInput(0, noise)

    # If the altitude mask wrangle exists, route through it: post → altitude_mask → scatter.
    # Otherwise wire post directly to scatter.
    alt = geo_node.node("altitude_mask")
    if alt is not None:
        if alt.input(0) is None or alt.input(0).path() != post.path():
            alt.setInput(0, post)
        if scatter.input(0) is None or scatter.input(0).path() != alt.path():
            scatter.setInput(0, alt)
    else:
        if scatter.input(0) is None or scatter.input(0).path() != post.path():
            scatter.setInput(0, post)

    return noise


def sync_mask_gating(geo_node, entries):
    """Generate the mask_post_apply wrangle's snippet from a list of gating
    entries. Each entry is a dict with:
      'layer' — attribute name on the surface (e.g. "mask2")
      'op'    — 0=Subtract, 1=Multiply, 2=Add, 3=Average, 4=Min, 5=Max
      'blend' — 0.0..1.0 scaling for this layer's effect (default 1.0)

    Entries apply sequentially — the result of entry i feeds into entry i+1,
    so adding more layers stacks on top.

    Subtract: @mask = max(@mask - lv*blend, 0)
    Multiply: @mask = lerp(@mask, @mask*lv, blend)
    Add:      @mask = min(@mask + lv*blend, 1)
    Average:  @mask = lerp(@mask, (@mask + lv)*0.5, blend)
    Min:      @mask = lerp(@mask, min(@mask, lv), blend)
    Max:      @mask = lerp(@mask, max(@mask, lv), blend)
    """
    if geo_node is None:
        return
    post = geo_node.node("mask_post_apply")
    if post is None:
        return

    lines = []
    for entry in entries or []:
        layer = (entry.get("layer") or "").strip()
        op = int(entry.get("op", 0))
        blend = float(entry.get("blend", 1.0))
        invert = bool(entry.get("invert", False))
        if not layer or blend <= 0.0:
            continue
        # Escape double quotes defensively in case of unusual layer names
        safe = layer.replace('"', '\\"')
        invert_line = "    lv = 1.0 - lv;\n" if invert else ""
        if op == 1:
            expr = f'@mask = lerp(@mask, @mask * lv, {blend});'
        elif op == 2:
            expr = f'@mask = min(@mask + lv * {blend}, 1.0);'
        elif op == 3:
            expr = f'@mask = lerp(@mask, (@mask + lv) * 0.5, {blend});'
        elif op == 4:
            expr = f'@mask = lerp(@mask, min(@mask, lv), {blend});'
        elif op == 5:
            expr = f'@mask = lerp(@mask, max(@mask, lv), {blend});'
        else:
            expr = f'@mask = max(@mask - lv * {blend}, 0.0);'
        lines.append(
            f'if (haspointattrib(0, "{safe}")) {{\n'
            f'    float lv = clamp(point(0, "{safe}", @ptnum), 0, 1);\n'
            f'{invert_line}'
            f'    {expr}\n'
            f'}}'
        )

    # Always constrain: zero out noise where the original paint was absent.
    lines.append(
        'if (haspointattrib(0, "_pmask")) {\n'
        '    if (point(0, "_pmask", @ptnum) < 0.001) @mask = 0.0;\n'
        '}'
    )
    snippet = "\n".join(lines)
    try:
        post.setParms({"class": 2, "snippet": snippet})
    except Exception:
        pass


def _get_raw_parm(node, parm_name, default=""):
    p = node.parm(parm_name) if node is not None else None
    if p is None:
        return default
    try:
        return p.unexpandedString()
    except Exception:
        try:
            return p.eval()
        except Exception:
            return default


def ensure_scatter_filecache(geo_node):
    """Ensure topology: instancer → leaves_grp → scatter_filecache → OUT_scatter.

    In SP Scatter mode (no leaves_grp), feed directly from instancer.
    In plain Ivy mode (ivy_filecache exists), OUT_scatter is fed by ivy_filecache
    (the wires output) — leave it alone.
    """
    if geo_node is None:
        return None
    instancer = geo_node.node("instancer")
    out = geo_node.node("OUT_scatter")
    if instancer is None or out is None:
        return None

    cache = geo_node.node("scatter_leaves") or geo_node.node("scatter_filecache")
    if cache is None:
        cache = _create_node_with_fallback(
            geo_node,
            ["filecache::2.0", "filecache", "filecache::1.0"],
            "scatter_filecache",
        )
    leaves_grp = geo_node.node("leaves_grp")
    ivy_cache  = geo_node.node("ivy_wires_filecache") or geo_node.node("ivy_filecache")

    # instancer → leaves_grp (if present) → scatter_filecache
    if leaves_grp is not None:
        if leaves_grp.input(0) is not instancer:
            leaves_grp.setInput(0, instancer)
        if cache.input(0) is not leaves_grp:
            cache.setInput(0, leaves_grp)
    else:
        if cache.input(0) is not instancer:
            cache.setInput(0, instancer)

    # OUT_scatter wiring:
    #  - Plain Ivy mode (ivy_filecache active): leave alone (wired to ivy_filecache)
    #  - Otherwise (SP Scatter / Crawl): OUT_scatter ← scatter_filecache
    current = out.input(0)
    if ivy_cache is not None and current is ivy_cache:
        pass  # plain Ivy mode — OUT_scatter holds the wires output
    elif current is not cache:
        out.setInput(0, cache)
    return cache


def sync_scatter_cache_parms(geo_node, state):
    cache = ensure_scatter_filecache(geo_node)
    if cache is None:
        return
    defaults = SCATTER_CACHE_DEFAULTS
    _set_parm(cache, "basedir", state.get("scatter_cache_basedir", defaults["scatter_cache_basedir"]))
    _set_parm(cache, "basename", state.get("scatter_cache_basename", defaults["scatter_cache_basename"]))
    _set_parm(cache, "version", int(state.get("scatter_cache_version", defaults["scatter_cache_version"])))
    _set_parm(cache, "loadfromdisk", int(bool(state.get("scatter_cache_loadfromdisk", defaults["scatter_cache_loadfromdisk"]))))
    _set_parm(cache, "timedependent", int(bool(state.get("scatter_cache_timedependent", defaults["scatter_cache_timedependent"]))))
    _set_parm(cache, "trange", int(state.get("scatter_cache_trange", defaults["scatter_cache_trange"])))
    _set_parm(cache, ("simulation", "dosimulation"), int(bool(state.get("scatter_cache_simulation", defaults["scatter_cache_simulation"]))))
    set_scatter_cache_frame_range(
        geo_node,
        state.get("scatter_cache_start", defaults["scatter_cache_start"]),
        state.get("scatter_cache_end", defaults["scatter_cache_end"]),
        state.get("scatter_cache_inc", defaults["scatter_cache_inc"]),
        state.get("scatter_cache_substeps", defaults["scatter_cache_substeps"]),
    )


def _get_scatter_filecache(geo_node):
    """Return the scatter_filecache (or scatter_leaves) node directly, without topology checks."""
    if geo_node is None: return None
    return geo_node.node("scatter_leaves") or geo_node.node("scatter_filecache")


def _get_first_parm_value(node, parm_names, default=None):
    """Evaluate the first existing parm from parm_names."""
    if node is None:
        return default
    if isinstance(parm_names, str):
        parm_names = (parm_names,)
    for pname in parm_names:
        p = node.parm(pname)
        if p is None:
            continue
        try:
            return p.eval()
        except Exception:
            pass
    return default


def _set_all_existing_parms(node, parm_names, value):
    """Set every existing parm in parm_names."""
    if node is None:
        return
    if isinstance(parm_names, str):
        parm_names = (parm_names,)
    for pname in parm_names:
        p = node.parm(pname)
        if p is None:
            continue
        try:
            p.set(value)
        except Exception as e:
            log(f"{node.name()} parm {pname} set error: {e}")


def set_scatter_cache_basedir(geo_node, value):
    cache = _get_scatter_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "basedir", value)


def set_scatter_cache_basename(geo_node, value):
    cache = _get_scatter_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "basename", value)


def set_scatter_cache_version(geo_node, value):
    cache = _get_scatter_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "version", int(value))


def set_scatter_cache_loadfromdisk(geo_node, enabled):
    cache = _get_scatter_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "loadfromdisk", int(bool(enabled)))


def set_scatter_cache_timedependent(geo_node, enabled):
    cache = _get_scatter_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "timedependent", int(bool(enabled)))


def set_scatter_cache_trange(geo_node, value):
    cache = _get_scatter_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "trange", int(value))


def set_scatter_cache_simulation(geo_node, enabled):
    cache = _get_scatter_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, ("simulation", "dosimulation"), int(bool(enabled)))


def set_scatter_cache_frame_range(geo_node, start, end, inc=1, substeps=1):
    cache = _get_scatter_filecache(geo_node)
    if cache is None:
        return
    s, e, i, sub = int(start), int(end), int(inc), int(substeps)
    pt = cache.parmTuple("f")
    if pt is not None and len(pt) >= 3:
        try:
            pt.set((s, e, i))
        except Exception as ex:
            log(f"scatter_filecache f tuple set: {ex}")
    for pname, val in (("f1", s), ("f2", e), ("f3", i)):
        _set_parm(cache, pname, val)
    _set_all_existing_parms(cache, ("substep", "substeps"), sub)


def get_scatter_cache_values(geo_node):
    cache = _get_scatter_filecache(geo_node)
    values = dict(SCATTER_CACHE_DEFAULTS)
    if cache is None:
        return values
    for key, pname in (
        ("scatter_cache_basedir", "basedir"),
        ("scatter_cache_basename", "basename"),
    ):
        values[key] = _get_raw_parm(cache, pname, values[key])
    for key, pname in (
        ("scatter_cache_version", "version"),
        ("scatter_cache_loadfromdisk", "loadfromdisk"),
        ("scatter_cache_timedependent", "timedependent"),
        ("scatter_cache_trange", "trange"),
        ("scatter_cache_simulation", "simulation"),
    ):
        p = cache.parm(pname) or (cache.parm("dosimulation") if key == "scatter_cache_simulation" else None)
        if p is not None:
            try:
                values[key] = p.eval()
            except Exception:
                pass
    pt = cache.parmTuple("f")
    if pt is not None and len(pt) >= 3:
        try:
            vals = pt.eval()
            values["scatter_cache_start"] = int(vals[0])
            values["scatter_cache_end"] = int(vals[1])
            values["scatter_cache_inc"] = int(vals[2])
        except Exception:
            pass
    for key, pname in (
        ("scatter_cache_start", "f1"),
        ("scatter_cache_end", "f2"),
        ("scatter_cache_inc", "f3"),
        ("scatter_cache_substeps", ("substep", "substeps")),
    ):
        val = _get_first_parm_value(cache, pname, None)
        if val is not None:
            values[key] = int(val)
    return values


def _ensure_scatter_points_out(geo_node):
    """Return OUT_scatter_points null, creating it wired from piece_attr if missing."""
    existing = geo_node.node('OUT_scatter_points')
    if existing is not None:
        return existing
    piece_attr = geo_node.node('piece_attr')
    if piece_attr is None:
        return None
    out_pts = geo_node.createNode('null', 'OUT_scatter_points')
    out_pts.setInput(0, piece_attr)
    return out_pts


def _gen_wires_mesh_code(wire_cache_path, system_name):
    """Python LOP snippet that references the baked wire-mesh USD as a plain
    prim (not a PointInstancer) at /MSW/<system>/wires."""
    return f'''\
from pxr import Sdf, Usd
import hou

lopnode = hou.pwd()
stage = lopnode.editableStage()

wire_path = "/MSW/{system_name}/wires"
prim = stage.OverridePrim(Sdf.Path(wire_path))
prim.GetReferences().ClearReferences()
prim.GetReferences().AddReference({wire_cache_path!r})
'''


def _gen_prototypes_code(regular_refs):
    """Generate a Python LOP snippet that adds one Reference per regular-geo
    asset to its target prototype prim. Proxy assets are handled separately
    by chained Redshift Proxy LOPs, so they are not in this list."""
    return f'''\
from pxr import Sdf, Usd
import hou

lopnode = hou.pwd()
stage = lopnode.editableStage()

regular_refs = {regular_refs!r}

for proto_path, cache_path in regular_refs:
    prim = stage.OverridePrim(Sdf.Path(proto_path))
    prim.GetReferences().ClearReferences()
    prim.GetReferences().AddReference(cache_path)
'''


def _gen_pointinstancer_code(scatter_pts_path, proto_root, system_name, n_protos):
    return f'''\
from pxr import UsdGeom, Gf, Vt
import hou

lopnode = hou.pwd()
stage = lopnode.editableStage()

sop = hou.node({scatter_pts_path!r})
if sop is None:
    raise hou.NodeError("Scatter points SOP not found: {scatter_pts_path}")

geo = sop.geometry()
positions, orientations, scales, indices = [], [], [], []

for pt in geo.points():
    p = pt.position()
    positions.append(Gf.Vec3f(p[0], p[1], p[2]))
    try:
        o = pt.attribValue("orient")
        orientations.append(Gf.Quath(o[3], o[0], o[1], o[2]))
    except Exception:
        orientations.append(Gf.Quath(1, 0, 0, 0))
    try:
        pscale = float(pt.attribValue("pscale"))
    except Exception:
        pscale = 1.0
    scales.append(Gf.Vec3f(pscale, pscale, pscale))
    try:
        indices.append(int(pt.attribValue("piece")))
    except Exception:
        indices.append(0)

instancer_path = "/MSW/{system_name}/scatter"
instancer = UsdGeom.PointInstancer.Define(stage, instancer_path)
instancer.GetPositionsAttr().Set(Vt.Vec3fArray(positions))
instancer.GetOrientationsAttr().Set(Vt.QuathArray(orientations))
instancer.GetScalesAttr().Set(Vt.Vec3fArray(scales))
instancer.GetProtoIndicesAttr().Set(Vt.IntArray(indices))

proto_rel = instancer.GetPrototypesRel()
for i in range({n_protos}):
    proto_rel.AddTarget("{proto_root}/asset_" + str(i))
'''


def create_solaris_network(geo_node, frame_range=None, include_wires=True):
    """Builds a USD PointInstancer LOP network in /stage for the scatter system.

    Network layout inside /stage/MSW_<name>_solaris:
      proto_N_import (sopimport per asset) → proto_merge → MSW_PointInstancer (python LOP)

    The Python LOP reads OUT_scatter_points (added to the SOP network on first call)
    and builds a UsdGeom.PointInstancer with positions, orientations, scales and
    per-prototype indices derived from @piece.

    frame_range — optional (start, end, inc) tuple.  When provided all prototype
    and wire-mesh USD files are written with that frame range baked as time samples.
    The scatter instancer positions are already handled frame-by-frame by the live
    Python LOP regardless of this setting.
    """
    # Force-reload the USD submodules so signature changes (e.g. frame_range)
    # take effect even if the launcher's reload chain didn't fire for them.
    import importlib
    importlib.reload(usd_prototypes)
    importlib.reload(usd_materials_mtlx)
    raw = geo_node.name()
    system_name = raw[4:] if raw.startswith('MSW_') else raw
    # USD SdfPath components must start with a letter or underscore.
    if system_name and system_name[0].isdigit():
        system_name = '_' + system_name

    out_pts = _ensure_scatter_points_out(geo_node)
    if out_pts is None:
        raise RuntimeError("piece_attr node not found in scatter network.")

    assets_merge = geo_node.node('assets_merge')
    asset_sop_paths = []
    if assets_merge is not None:
        for inp in assets_merge.inputs():
            if inp is not None:
                asset_sop_paths.append(inp.path())

    if not asset_sop_paths:
        raise RuntimeError("No assets found in scatter network.")

    stage_net = hou.node('/stage')
    if stage_net is None:
        stage_net = hou.node('/').createNode('lopnet', 'stage')

    prefix = f'MSW_{system_name}_'
    proto_root = f'/MSW/{system_name}/scatter/Prototypes'

    # Graph surgery: save predecessor/successor before deleting old nodes so we
    # can stitch the remaining chain back together on re-export.
    existing_proto = stage_net.node(f'{prefix}prototypes')
    # Use wires LOP as tail when it exists (it's chained after PointInstancer).
    existing_tail  = stage_net.node(f'{prefix}wires') or stage_net.node(f'{prefix}PointInstancer')
    predecessor = (existing_proto.inputs() or [None])[0] if existing_proto else None
    successor   = (existing_tail.outputs()  or [None])[0] if existing_tail  else None

    for child in list(stage_net.children()):
        if child.name().startswith(prefix):
            child.destroy()

    if successor is not None:
        successor.setInput(0, predecessor)

    # New nodes append to the end of whatever is already in the stage.
    chain_tail = None
    for child in stage_net.children():
        if not child.outputs():
            chain_tail = child

    # Look up the paint node (holds lookdev bindings) so we can author
    # MaterialX networks per asset. Bindings are keyed by the original
    # user-picked asset path, not by the wrangle inside the scatter network,
    # so we resolve each wrangle's upstream object_merge.objpath1 below.
    paint_node = geo_node.node('paint_mask')
    bindings = lookdev_assign.load_bindings(paint_node) if paint_node else {}

    def _original_asset_path(wrangle_node):
        om = wrangle_node.input(0) if wrangle_node is not None else None
        if om is None:
            return None
        p = om.parm('objpath1')
        return p.eval() if p is not None else None

    # Per-asset dispatch:
    #   regular geo  → cache to disk, reference into the stage in a Python LOP
    #   RS proxy     → no cache; author the prim live via a Redshift Proxy LOP
    regular_refs = []   # list of (proto_path, cache_path)
    proxy_specs  = []   # list of (asset_index, proto_path, rs_path)
    for i, sop_path in enumerate(asset_sop_paths):
        asset_sop = hou.node(sop_path)
        if asset_sop is None:
            raise hou.NodeError(f"Asset SOP not found: {sop_path}")
        proto_path = f'{proto_root}/asset_{i}'
        info = usd_prototypes.classify_asset(asset_sop)
        if info['kind'] == 'redshift_proxy':
            # Proxies carry baked materials in the .rs archive — no USD
            # material authoring needed.
            proxy_specs.append((i, proto_path, info['path']))
        else:
            cache_path = usd_prototypes.cache_path_for(
                system_name, i, asset_sop.name()
            )
            usd_prototypes.cache_asset(asset_sop, cache_path, frame_range=frame_range)
            regular_refs.append((proto_path, cache_path))

            # MaterialX network for Karma/Arnold targets, authored into the
            # cached prototype USD alongside the geometry.
            original_path = _original_asset_path(asset_sop)
            binding = bindings.get(original_path) if original_path else None
            if binding:
                mat_name = binding.get('mat_name') or f'asset_{i}_mat'
                try:
                    usd_materials_mtlx.author_into_cache(
                        cache_path=cache_path,
                        mesh_prim_path=f'/{usd_prototypes.DEFAULT_PRIM_NAME}',
                        material_name=mat_name,
                        textures=binding.get('textures') or {},
                        params=binding.get('params') or {},
                    )
                except Exception as e:
                    # Material failure shouldn't block the export — the
                    # prototype still has geometry; user can debug binding.
                    print(f"[MSW/USD] mtlx authoring failed for "
                          f"{original_path}: {e}")

    proto_lop = stage_net.createNode('pythonscript', f'{prefix}prototypes')
    proto_lop.parm('python').set(
        _gen_prototypes_code(regular_refs=regular_refs)
    )
    if chain_tail is not None:
        proto_lop.setInput(0, chain_tail)

    upstream = proto_lop
    for idx, proto_path, rs_path in proxy_specs:
        rs_lop = usd_prototypes.create_redshift_proxy_lop(
            parent=stage_net,
            name=f'{prefix}asset_{idx}_rsproxy',
            rs_path=rs_path,
            primpath=proto_path,
        )
        rs_lop.setInput(0, upstream)
        upstream = rs_lop

    py_lop = stage_net.createNode('pythonscript', f'{prefix}PointInstancer')
    py_lop.setInput(0, upstream)
    py_lop.parm('python').set(
        _gen_pointinstancer_code(
            scatter_pts_path=out_pts.path(),
            proto_root=proto_root,
            system_name=system_name,
            n_protos=len(asset_sop_paths),
        )
    )

    # Ivy / Crawl networks: export the wire mesh as a standalone reference prim.
    last_lop = py_lop
    wire_sop = get_wire_sop(geo_node) if include_wires else None
    if wire_sop is not None:
        wire_cache_path = os.path.join(
            usd_prototypes.cache_dir_for(system_name), "wires.usd"
        ).replace("\\", "/")
        try:
            usd_prototypes.cache_asset(wire_sop, wire_cache_path, frame_range=frame_range)
            usd_prototypes.ensure_curves_widths(wire_cache_path)
        except Exception as e:
            print(f"[MSW/USD] wires cache failed — skipping wire mesh export: {e}")
        else:
            wire_binding = bindings.get(wire_sop.path())
            if wire_binding:
                mat_name = wire_binding.get('mat_name') or 'wires_mat'
                try:
                    usd_materials_mtlx.author_into_cache(
                        cache_path=wire_cache_path,
                        mesh_prim_path=f'/{usd_prototypes.DEFAULT_PRIM_NAME}',
                        material_name=mat_name,
                        textures=wire_binding.get('textures') or {},
                        params=wire_binding.get('params') or {},
                    )
                except Exception as e:
                    print(f"[MSW/USD] mtlx authoring failed for wires: {e}")

            wires_lop = stage_net.createNode('pythonscript', f'{prefix}wires')
            wires_lop.parm('python').set(
                _gen_wires_mesh_code(wire_cache_path, system_name)
            )
            wires_lop.setInput(0, py_lop)
            last_lop = wires_lop

    stage_net.layoutChildren()
    return last_lop


def bake_scatter_cache(geo_node):
    cache = ensure_scatter_filecache(geo_node)
    if cache is None:
        raise RuntimeError("scatter_filecache not found.")
    _set_parm(cache, "loadfromdisk", 0)
    for btn_name in ("execute", "save", "savefile", "render"):
        p = cache.parm(btn_name)
        if p is not None:
            p.pressButton()
            break
    else:
        raise RuntimeError("Could not find an execute button on scatter_filecache.")
    _set_parm(cache, "loadfromdisk", 1)
    p = cache.parm("file") or cache.parm("sopoutput")
    if p is not None:
        try:
            return p.eval()
        except Exception:
            return _get_raw_parm(cache, p.name(), "")
    return ""
    return noise


# ---------------------------------------------------------------------------
# Network creation
# ---------------------------------------------------------------------------

def sync_orient_cone_angle(geo_node, angle, enable=True):
    """
    Push the Ivy-Scatter Normal-Alignment settings onto attribrandomize_orient:
      * distribution  → 4  (cone-around-normal distribution)
      * useconeangle  → 1
      * coneangle     → <angle>
    Called only from ivy-mode UI paths. No-op when the geo_node or
    attribrandomize_orient is missing.
    """
    if geo_node is None:
        return
    orient = geo_node.node("attribrandomize_orient")
    if orient is None:
        return

    # Distribution → 4. Token type varies by Houdini version (int vs string).
    p_dist = orient.parm("distribution")
    if p_dist is not None:
        for val in (4, "4"):
            try:
                p_dist.set(val)
                break
            except Exception:
                continue

    p_use = orient.parm("useconeangle")
    if p_use is not None:
        try:
            p_use.set(1 if enable else 0)
        except Exception:
            pass
    p_angle = orient.parm("coneangle")
    if p_angle is not None:
        try:
            p_angle.set(float(angle))
        except Exception:
            pass


def _configure_attribrandomize_orient(orient_rand):
    """
    Set name='orient', dimensions=4 (Quaternion), distribution=4 on an
    Attribute Randomize SOP. The dimension parm name has shifted across
    Houdini versions (`dimension` / `dimens` / `dimensions`) and the menu
    tokens are sometimes integers and sometimes strings — try every shape
    so the parm reliably ends up at 4.
    """
    if orient_rand is None:
        return

    # 1. Attribute name (always a string).
    p_name = orient_rand.parm("name")
    if p_name is not None:
        try:
            p_name.set("orient")
        except Exception:
            pass

    # 2. Dimension parameter — name varies by Houdini version.
    for pname in ("dimensions", "dimens", "dimension"):
        p = orient_rand.parm(pname)
        if p is None:
            continue
        for val in (4, "4"):                # int first, string fallback
            try:
                p.set(val)
                break
            except Exception:
                continue
        break                                # stop at the first matching parm

    # 3. Distribution → 4 (typically Uniform Direction / Quaternion).
    p_dist = orient_rand.parm("distribution")
    if p_dist is not None:
        for val in (4, "4"):
            try:
                p_dist.set(val)
                break
            except Exception:
                continue


_ORIENT_WRANGLE_CODE = """\
float rmin = chf("rot_min") * 6.28318530;
float rmax = chf("rot_max") * 6.28318530;
int   full = chi("full_rand");
float randomize = chf("rot_randomize");

float lo = full ? 0.0 : rmin;
float hi = full ? 6.28318530 : rmax;

float rx = fit(rand(@ptnum * 1.1 + 1111.0), 0.0, 1.0, lo, hi);
float ry = fit(rand(@ptnum * 2.3 + 2222.0), 0.0, 1.0, lo, hi);
float rz = fit(rand(@ptnum * 3.7 + 3333.0), 0.0, 1.0, lo, hi);
rx = lerp(0.0, rx, randomize);
ry = lerp(0.0, ry, randomize);
rz = lerp(0.0, rz, randomize);

vector4 qx = quaternion(rx, {1,0,0});
vector4 qy = quaternion(ry, {0,1,0});
vector4 qz = quaternion(rz, {0,0,1});
vector4 delta = qmultiply(qmultiply(qx, qy), qz);

@orient = qmultiply(@orient, delta);
"""


def _add_orient_wrangle_spare_parms(node):
    """Add rot_min, rot_max, full_rand, rot_randomize spare parameters to orient_wrangle."""
    try:
        ptg = node.parmTemplateGroup()
        if ptg.find("rot_min") is None:
            ptg.append(hou.FloatParmTemplate(
                "rot_min", "Rot Min", 1,
                default_value=(0.0,),
                min=0.0, max=1.0,
                min_is_strict=True, max_is_strict=True,
            ))
        if ptg.find("rot_max") is None:
            ptg.append(hou.FloatParmTemplate(
                "rot_max", "Rot Max", 1,
                default_value=(1.0,),
                min=0.0, max=1.0,
                min_is_strict=True, max_is_strict=True,
            ))
        if ptg.find("full_rand") is None:
            ptg.append(hou.ToggleParmTemplate(
                "full_rand", "Full Random",
                default_value=False,
            ))
        if ptg.find("rot_randomize") is None:
            ptg.append(hou.FloatParmTemplate(
                "rot_randomize", "Randomize", 1,
                default_value=(1.0,),
                min=0.0, max=1.0,
                min_is_strict=True, max_is_strict=True,
            ))
        node.setParmTemplateGroup(ptg)
    except Exception as e:
        log(f"orient_wrangle spare parms error: {e}")


def heal_orient_wrangle(geo_node):
    """Ensure orient_wrangle has class=2, the current snippet, and all spare parms.

    Called once at network create / regenerate / resume — NOT on every slider
    change.  Keeping snippet updates out of the hot-path prevents Houdini from
    resetting chf() parm values when VEX is recompiled mid-session.
    """
    if geo_node is None:
        return
    wr = geo_node.node("orient_wrangle")
    if wr is None:
        return
    try:
        cls_p = wr.parm("class")
        if cls_p is not None and cls_p.eval() != 2:
            cls_p.set(2)
    except Exception:
        pass
    try:
        snip_p = wr.parm("snippet")
        if snip_p is not None and snip_p.eval().strip() != _ORIENT_WRANGLE_CODE.strip():
            snip_p.set(_ORIENT_WRANGLE_CODE)
    except Exception:
        pass
    if (wr.parm("rot_min") is None
            or wr.parm("rot_max") is None
            or wr.parm("full_rand") is None
            or wr.parm("rot_randomize") is None):
        _add_orient_wrangle_spare_parms(wr)


def sync_ivy_orient(geo_node, rot_min, rot_max, full_rand, rot_randomize=1.0):
    """Push rotation parameters onto orient_wrangle spare parms.

    Only sets values — never touches snippet or class.  Call heal_orient_wrangle
    first (at create/resume time) to ensure the node is correctly configured.
    """
    if geo_node is None:
        log(f"sync_ivy_orient: geo_node is None")
        return
    wr = geo_node.node("orient_wrangle")
    if wr is None:
        log(f"sync_ivy_orient: orient_wrangle not found in {geo_node.path()}")
        return
    for pname, val in (("rot_min",       float(rot_min)),
                       ("rot_max",       float(rot_max)),
                       ("full_rand",     int(bool(full_rand))),
                       ("rot_randomize", float(rot_randomize))):
        p = wr.parm(pname)
        if p is not None:
            try:
                p.set(val)
                log(f"sync_ivy_orient: set {pname}={val}")
            except Exception as e:
                log(f"orient_wrangle set {pname}={val}: {e}")
        else:
            log(f"sync_ivy_orient: parm {pname} not found on orient_wrangle")


def create_scatter_network(obj_context, prefix="NewSystem"):
    """
    Builds a procedural mask-driven scatter network:
    Input Null -> Attribute Paint (mask) -> Scatter and Align -> Copy to Points
    """
    # Houdini node names must match [A-Za-z_][A-Za-z0-9_]*. Sanitize so that
    # spaces, punctuation, or non-ASCII (e.g. Cyrillic) user input still works.
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", (prefix or "").strip()).strip("_")
    if not safe:
        safe = "NewSystem"
    geo = obj_context.createNode("geo", f"MSW_{safe}")
    geo.setUserData(SCATTER_TAG, "1")

    for child in geo.children():
        child.destroy()

    # 1. Surface Input
    surf_merge = geo.createNode("object_merge", "surface_input")
    surf_merge.setParms({"xformtype": 1}) # Into This Object

    # surface_merge unifies all surfaces so multi-surface scatter works without
    # touching any downstream node.  Extra surfaces land at slots 1, 2, ...
    surf_unified = geo.createNode("merge", "surface_merge")
    surf_unified.setInput(0, surf_merge)

    # 1a. Group — tags all incoming mesh primitives as "mesh"
    mesh_group = geo.createNode("groupcreate", "mesh")
    mesh_group.setInput(0, surf_unified)
    mesh_group.setParms({"groupname": "mesh", "grouptype": 1})  # grouptype 1 = Primitives

    # 1b. AttribFromMap (Stamp)
    stamp = geo.createNode("attribfrommap", "stamp_map")
    stamp.setInput(0, mesh_group)
    stamp.setParms({
        "export_attribute": "mask"
    })
    stamp.bypass(True)

    # 2. Attribute Paint (Mask)
    paint = geo.createNode("attribpaint", "paint_mask")
    paint.setInput(0, stamp)
    paint.setParms({
        "attribname1": "mask"
    })

    # 3. Attribute Noise for painted mask
    mask_noise = geo.createNode("attribnoise", "mask_noise")
    mask_noise.setInput(0, paint)
    sync_scatter_noise_parms(geo, SCATTER_NOISE_DEFAULTS)

    # 4. Scatter and Align
    scatter = geo.createNode("scatteralign", "scatter_logic")
    scatter.setInput(0, mask_noise)
    scatter.setParms({
        "mode": 0,           # Scattered
        "pointcountmethod": 1, # By Density
        "densityattrib": "mask",
        "usedensityattrib": 1,
        "relax": 1,
        "relaxiterations": 10,
        "useminspacing": 1,
        "minspacing": 0.1
    })

    # 4. Wrangle for Pscale
    pscale_wr = geo.createNode("attribwrangle", "pscale_wrangle")
    pscale_wr.setInput(0, scatter)
    pscale_wr.setParms({
        "snippet": "float base_pscale = haspointattrib(0, \"pscale\") ? @pscale : 1.0;\nfloat global = 8.20100;\nfloat rand_scale = fit01(rand(@ptnum + 1234), 0.0, 0.382);\nrand_scale = lerp(1.0, rand_scale, 1.0);\n@pscale = base_pscale * rand_scale * global;\n@pscale = clamp(@pscale, 0.0, global);"
    })

    # Altitude mask — inserted between mask_post_apply and scatter_logic.
    # Wrangle exists but is disabled until a biome with altitude is applied.
    ensure_scatter_mask_noise(geo)         # build the mask chain first
    ensure_altitude_mask_wrangle(geo)
    ensure_altitude_vis_branch(geo)

    # Camera Frustum Culling — inserted between scatter_logic and pscale_wrangle
    ensure_camera_frustum_wrangle(geo)

    # Clumping — inserted between cam_frustum_cull and pscale_wrangle
    ensure_clump_wrangle(geo)

    # Proximity Exclusion — inserted between cam_frustum_cull and clump_wrangle
    ensure_proximity_filter(geo)

    # 4e. Geometry Offset — translates points along surface normal (outward/inward)
    geo_offset = geo.createNode("attribwrangle", "geo_offset")
    geo_offset.setInput(0, pscale_wr)
    geo_offset.setParms({"class": 2, "snippet": '@P += normalize(@N) * chf("offset");'})
    try:
        _ptg = geo_offset.parmTemplateGroup()
        _ptg.append(hou.FloatParmTemplate(
            "offset", "Offset", 1, default_value=(0.0,),
            min=-5.0, max=5.0, min_is_strict=False, max_is_strict=False,
        ))
        geo_offset.setParmTemplateGroup(_ptg)
    except Exception as _e:
        log(f"geo_offset spare parm: {_e}")

    # 4c. Orient Along Curve — bakes curve-tangent orient attr onto scatter points
    orient_curve = geo.createNode("orientalongcurve", "orientalongcurve1")
    orient_curve.setInput(0, geo_offset)

    # 4c-2. Attribute Randomize — randomises the orient attribute per point
    orient_rand = geo.createNode("attribrandomize", "attribrandomize_orient")
    orient_rand.setInput(0, orient_curve)
    _configure_attribrandomize_orient(orient_rand)
    orient_rand.bypass(True)

    # 4d. Add (Keep Points) — passes all points through; explicit "keep" step
    #     Tab index 2 = Keep Points mode in the Add SOP
    add_keep = geo.createNode("add", "add_keep")
    add_keep.setInput(0, orient_rand)
    add_keep.setParms({"switcher1": 2})   # Keep Points tab

    # 5. Asset Merge
    assets_merge = geo.createNode("merge", "assets_merge")

    # lod_assets_merge is what the instancer reads — keeps assets_merge clean (base only)
    # so attribfrompieces only distributes base piece indices 0..N-1
    lod_assets_merge = geo.createNode("merge", "lod_assets_merge")
    lod_assets_merge.setInput(0, assets_merge)

    # 4b. AttribFromPieces
    piece_attr = geo.createNode("attribfrompieces", "piece_attr")
    piece_attr.setInput(0, add_keep)
    piece_attr.setInput(1, assets_merge)
    piece_attr.setParms({
        "pieceattrib": "piece"
    })
    _init_piece_attr_defaults(piece_attr)

    # Points-only output for Solaris PointInstancer (no asset geometry, just scatter pts)
    out_scatter_pts = geo.createNode("null", "OUT_scatter_points")
    out_scatter_pts.setInput(0, piece_attr)

    # 6. Copy to Points
    ctp = geo.createNode("copytopoints::2.0", "instancer")
    ctp.setInput(0, lod_assets_merge)
    ctp.setInput(1, piece_attr)
    ctp.setParms({
        "useidattrib": 1,
        "idattrib": "piece",
        "pack": 1
    })
    _reset_attrib_from_target(ctp)

    # Color Variation — after piece_attr so prototype Cd can't overwrite ours
    ensure_color_wrangle(geo)

    # LOD — last node before instancer input 1
    ensure_lod_wrangle(geo)

    # 5. Output — will be rewired to ivy_scatter_merge when ivy network is created
    scatter_cache = _create_node_with_fallback(
        geo,
        ["filecache::2.0", "filecache", "filecache::1.0"],
        "scatter_filecache",
    )
    scatter_cache.setInput(0, ctp)
    sync_scatter_cache_parms(geo, SCATTER_CACHE_DEFAULTS)

    out = geo.createNode("null", "OUT_scatter")
    out.setInput(0, scatter_cache)
    out.setRenderFlag(True)
    out.setDisplayFlag(True)

    # Manual placement chain (starts with 0 points, user adds via Place mode)
    ensure_manual_scatter(geo)

    geo.layoutChildren()
    return geo, paint


def _ensure_pscale_wrangle_global_parm(node, value):
    """Add/update the global_scale spare parm on pscale_wrangle.

    Also enforces class=2 (Run Over Points) so @ptnum-based VEX works.
    The parm is what chf("global_scale") reads; without it the VEX returns 0.
    """
    try:
        cls_p = node.parm("class")
        if cls_p is not None and cls_p.eval() != 2:
            cls_p.set(2)
    except Exception:
        pass
    try:
        ptg = node.parmTemplateGroup()
        if ptg.find("global_scale") is None:
            ptg.append(hou.FloatParmTemplate(
                "global_scale", "Global Scale", 1,
                default_value=(1.0,),
                min=0.001, max=10.0,
                min_is_strict=False, max_is_strict=False,
            ))
            node.setParmTemplateGroup(ptg)
        p = node.parm("global_scale")
        if p is not None:
            p.set(float(value))
    except Exception as e:
        log(f"pscale_wrangle global_scale parm: {e}")


def sync_geo_offset(geo_node, value):
    """Push offset value onto geo_offset wrangle; creates the node if missing."""
    if geo_node is None:
        return
    node = geo_node.node("geo_offset")
    if node is None:
        pscale_wr = geo_node.node("pscale_wrangle")
        orient_curve = geo_node.node("orientalongcurve1")
        if pscale_wr is None:
            return
        node = geo_node.createNode("attribwrangle", "geo_offset")
        node.setParms({"class": 2, "snippet": '@P += normalize(@N) * chf("offset");'})
        try:
            _ptg = node.parmTemplateGroup()
            _ptg.append(hou.FloatParmTemplate(
                "offset", "Offset", 1, default_value=(0.0,),
                min=-5.0, max=5.0, min_is_strict=False, max_is_strict=False,
            ))
            node.setParmTemplateGroup(_ptg)
        except Exception as _e:
            log(f"geo_offset spare parm (create): {_e}")
        if orient_curve is not None:
            node.setInput(0, pscale_wr)
            orient_curve.setInput(0, node)
        else:
            node.setInput(0, pscale_wr)
        try:
            geo_node.layoutChildren()
        except Exception:
            pass
    p = node.parm("offset")
    if p is not None:
        try:
            p.set(float(value))
        except Exception as e:
            log(f"geo_offset set: {e}")


def sync_ivy_geo_offset(geo_node, value):
    """Push offset value onto ivy_geo_offset wrangle (sim path only — no-op if node absent)."""
    if geo_node is None:
        return
    node = geo_node.node("ivy_geo_offset")
    if node is None:
        return
    p = node.parm("offset")
    if p is not None:
        try:
            p.set(float(value))
        except Exception as e:
            log(f"ivy_geo_offset set: {e}")


def get_ivy_geo_offset(geo_node):
    """Return ivy_geo_offset.offset, or 0.0 when the node/parm is absent."""
    node = geo_node.node("ivy_geo_offset") if geo_node is not None else None
    p = node.parm("offset") if node is not None else None
    if p is None:
        return 0.0
    try:
        return p.eval()
    except Exception:
        return 0.0


def sync_crawl_geo_offset(geo_node, value):
    """Push offset value onto crawl_geo_offset wrangle (no-op if node absent)."""
    if geo_node is None:
        return
    node = geo_node.node("crawl_geo_offset")
    if node is None:
        return
    p = node.parm("offset")
    if p is not None:
        try:
            p.set(float(value))
            log(f"crawl_geo_offset offset set to {value}")
        except Exception as e:
            log(f"crawl_geo_offset parm set error: {e}")
    else:
        log(f"crawl_geo_offset node found but 'offset' parm not found")


_STAMP_BLEND_EXPRS = {
    "multiply": "result * src",
    "add":      "clamp(result + src, 0.0, 1.0)",
    "screen":   "1.0 - (1.0 - result) * (1.0 - src)",
    "overlay":  "(result < 0.5 ? 2.0*result*src : 1.0 - 2.0*(1.0-result)*(1.0-src))",
    "subtract": "clamp(result - src, 0.0, 1.0)",
    "divide":   "(src > 0.001 ? min(result / src, 1.0) : 0.0)",
    "average":  "(result + src) * 0.5",
    "over":     "max(result, src)",
    "min":      "min(result, src)",
}


def _generate_stamp_vex(valid_layers, mask_attr=""):
    """Generate VEX snippet for stamp_blend wrangle from a list of enabled layers.

    mask_attr: global mask — multiply final result by @<mask_attr>.
    Each layer may also carry a "layer_mask" key to mask its own contribution
    before blending.
    """
    inv0 = "1.0 - " if valid_layers[0].get("invert", False) else ""
    lm0 = valid_layers[0].get("layer_mask", "")
    if lm0:
        lines = [f"float result = clamp({inv0}@stamp_layer_0 * max(@{lm0}, 0.0), 0.0, 1.0);"]
    else:
        lines = [f"float result = {inv0}@stamp_layer_0;"]
    for i, layer in enumerate(valid_layers[1:], 1):
        expr = _STAMP_BLEND_EXPRS.get(layer.get("mode", "multiply"),
                                      _STAMP_BLEND_EXPRS["multiply"])
        amount = float(layer.get("amount", 1.0))
        inv = "1.0 - " if layer.get("invert", False) else ""
        lm = layer.get("layer_mask", "")
        if lm:
            src_line = f"    float src = clamp({inv}@stamp_layer_{i} * max(@{lm}, 0.0), 0.0, 1.0);"
        else:
            src_line = f"    float src = {inv}@stamp_layer_{i};"
        lines += [
            "{",
            src_line,
            f"    float blended = {expr};",
            f"    result = lerp(result, blended, {amount}f);",
            "}",
        ]
    if mask_attr:
        lines.append(f"@mask = clamp(result * max(@{mask_attr}, 0.0), 0.0, 1.0);")
    else:
        lines.append("@mask = clamp(result, 0.0, 1.0);")
    return "\n".join(lines)


def sync_stamp_layers(geo_node, layers, mask_attr="", use_mask=False):
    """
    Build / rebuild the stamp-layer chain inside geo_node.

    mask_attr="" (default):
      mesh → stamp_layer_0 → … → stamp_blend → paint_mask
      Stamp sets the base density; paint modifies on top.

    mask_attr="<name>":
      mesh → paint_mask → stamp_layer_0 → … → stamp_blend → [mask_paint_save]
      Stamp restricts scatter to areas painted in @<name>.

    When the layer count is unchanged, parameters are updated in-place so that the
    attribpaint viewer state's intersection-geometry reference stays valid (prevents
    hou.ObjectWasDeleted when the user swaps a texture while painting).
    """
    # Support legacy bool kwarg; mask_attr takes precedence
    if not mask_attr and use_mask:
        mask_attr = "mask"
    use_mask = bool(mask_attr)

    paint_node = geo_node.node("paint_mask")
    mesh_group = geo_node.node("mesh")
    if not paint_node or not mesh_group:
        return

    # Remove legacy single-node stamp (backward compat)
    old = geo_node.node("stamp_map")
    if old:
        old.destroy()

    valid = [l for l in (layers or [])
             if l.get("enabled", True) and l.get("path", "").strip()]

    # Gather existing stamp nodes (sorted by index)
    existing = sorted(
        [c for c in geo_node.children() if c.name().startswith("stamp_layer_")],
        key=lambda n: int(n.name().rsplit("_", 1)[-1])
    )
    existing_blend = geo_node.node("stamp_blend")

    if not valid:
        # No layers — remove stamp nodes and wire paint directly to mesh
        paint_node.setInput(0, mesh_group)
        for n in existing:
            n.destroy()
        if existing_blend:
            existing_blend.destroy()
        return

    # Collect all mask attributes required (global + per-layer)
    required_attrs = set()
    if mask_attr:
        required_attrs.add(mask_attr)
    for layer in valid:
        lm = layer.get("layer_mask", "")
        if lm:
            required_attrs.add(lm)

    # Determine the upstream source for stamp layers
    if required_attrs:
        # Ensure primary paint reads from mesh so the full paint chain is grounded.
        paint_node.setInput(0, mesh_group)
        # Walk the ordered paint chain to find the deepest node we need.
        # Paint nodes: paint_mask → paint_mask_X → paint_mask_Y → …
        try:
            primary_attr = paint_node.parm("attribname1").eval() or "mask"
        except Exception:
            primary_attr = "mask"
        ordered_paint = [paint_node]
        cur = paint_node
        visited = {paint_node.path()}
        while True:
            nxt = None
            for child in geo_node.children():
                if (child.type().name() == "attribpaint" and
                        child.name().startswith("paint_mask_") and
                        child.input(0) is not None and
                        child.input(0).path() == cur.path() and
                        child.path() not in visited):
                    nxt = child
                    break
            if nxt is None:
                break
            visited.add(nxt.path())
            ordered_paint.append(nxt)
            cur = nxt
        # Map attr name → paint node
        def _attr_of(n):
            try:
                return n.parm("attribname1").eval() or ""
            except Exception:
                return ""
        # Find the last node in ordered_paint that covers a required attr
        stamp_upstream = paint_node
        for n in ordered_paint:
            if _attr_of(n) in required_attrs:
                stamp_upstream = n
    else:
        stamp_upstream = mesh_group

    if len(valid) == len(existing) and existing_blend:
        # Same layer count — update parameters in-place, no node destruction.
        # This keeps the attribpaint viewer state's geometry reference alive.
        prev = stamp_upstream
        for i, (afm, layer) in enumerate(zip(existing, valid)):
            afm.setInput(0, prev)
            afm.setParms({
                "export_attribute": f"stamp_layer_{i}",
                "filename":         layer["path"],
                "uv_invertu":       1 if layer.get("fx", False) else 0,
                "uv_invertv":       1 if layer.get("fy", False) else 0,
                "uv_rz":            float(layer.get("rot", 0.0)),
            })
            prev = afm
        existing_blend.setInput(0, prev)
        existing_blend.setParms({"class": 2, "snippet": _generate_stamp_vex(valid, mask_attr)})
        if not required_attrs:
            paint_node.setInput(0, existing_blend)
        else:
            # stamp_blend is the tail — wire it to mask_paint_save if present
            save = geo_node.node("mask_paint_save")
            if save is not None:
                save.setInput(0, existing_blend)
        return

    # Layer count changed — must rebuild. Disconnect paint_mask first so the
    # viewer state can fall back to mesh_group before old nodes are destroyed.
    paint_node.setInput(0, mesh_group)
    for n in existing:
        n.destroy()
    if existing_blend:
        existing_blend.destroy()

    prev = stamp_upstream
    for i, layer in enumerate(valid):
        afm = geo_node.createNode("attribfrommap", f"stamp_layer_{i}")
        afm.setInput(0, prev)
        afm.setParms({
            "export_attribute": f"stamp_layer_{i}",
            "filename":         layer["path"],
            "uv_invertu":       1 if layer.get("fx", False) else 0,
            "uv_invertv":       1 if layer.get("fy", False) else 0,
            "uv_rz":            float(layer.get("rot", 0.0)),
        })
        prev = afm

    blend = geo_node.createNode("attribwrangle", "stamp_blend")
    blend.setInput(0, prev)
    blend.setParms({"class": 2, "snippet": _generate_stamp_vex(valid, mask_attr)})

    if not required_attrs:
        paint_node.setInput(0, blend)
    else:
        # stamp_blend is the tail — wire it to mask_paint_save if present
        save = geo_node.node("mask_paint_save")
        if save is not None:
            save.setInput(0, blend)

    try:
        geo_node.layoutChildren()
    except Exception:
        pass


def get_asset_max_radius(geo_node):
    """Return the half-diagonal of the largest loaded asset's bounding box.

    Reads the object_merge nodes wired into assets_merge to avoid cooking the
    full instanced network; returns 0.0 if no assets are loaded or an error occurs.
    """
    import math
    merge = geo_node.node("assets_merge")
    if merge is None:
        return 0.0
    max_r = 0.0
    for piece_aw in merge.inputs():
        if piece_aw is None:
            continue
        om = piece_aw.input(0)
        if om is None:
            continue
        p = om.parm("objpath1")
        if p is None:
            continue
        path = p.eval()
        if not path:
            continue
        try:
            asset_node = hou.node(path)
            if asset_node is None:
                continue
            geom = asset_node.geometry()
            if geom is None:
                continue
            bbox = geom.boundingBox()
            size = bbox.sizevec()
            half_diag = math.sqrt(size[0]**2 + size[1]**2 + size[2]**2) / 2.0
            max_r = max(max_r, half_diag)
        except Exception as e:
            log(f"get_asset_max_radius: {e}")
    return max_r


def sync_scatter_params(paint_node, state):
    """
    Syncs UI state dictionary to the SOPs (paint, scatter, randomization).
    """
    geo = paint_node.parent() if paint_node else None
    if not geo: return

    ensure_surface_merge(geo)   # upgrade old networks to multi-surface architecture
    sync_mask_layers(geo, state)
    ensure_scatter_mask_noise(geo)
    sync_scatter_noise_parms(geo, state)
    sync_mask_gating(geo, state.get("scatter_noise_mask_gating", []))
    sync_scatter_cache_parms(geo, state)
    set_curve_pscale(geo, state.get("scl_min", [1,1,1]), state.get("scl_max", [1,1,1]), state.get("pscale_randomize", 1.0), state.get("curve_scale", 1.0))

    # 0. Sync Stamp Layers
    sync_stamp_layers(geo, state.get("stamp_layers", []),
                      mask_attr=state.get("stamp_mask_layer", ""),
                      use_mask=state.get("stamp_use_mask", False))

    # 1. Sync Paint Mask Properties
    try:
        paint_node.setParms({
            "stroke_radius":   state.get("radius", 1.0),
            "stroke_opacity":  state.get("falloff_amount", 1.0),
            "stroke_softedge": state.get("falloff_softness", 0.5)
        })
    except Exception as e:
        log(f"Error syncing paint mask parameters: {e}")

    # 2. Sync Scatter Logic Parameters
    scatter = geo.node("scatter_logic")
    if not scatter:
        # Fallback: Find the first scatteralign node by type
        for child in geo.children():
            if child.type().name().startswith("scatteralign"):
                scatter = child
                break
                
    if scatter:
        # Map UI states to SOP parameters
        mask_layers = state.get("scatter_mask_layers", ["mask"]) or ["mask"]
        primary_mask_layer = mask_layers[0] if mask_layers else "mask"

        parms = {
            "densityscale":     state.get("density", 1.0),
            "densityattrib":    primary_mask_layer,
            "usedensityattrib": 1,
            "coverage":         state.get("spacing", 1.0),
            "useemergencylimit": 1,
            "emergencylimit":    int(state.get("max_points", 1000000)),
            "relaxiterations":  int(state.get("relax_iter", 10)),
            "uniformscale":     state.get("global_scale", 1.0),
        }
        
        # Rotation Range
        parms["perprotrandmin"] = state.get("rot_min", 0.0) * 360.0
        parms["perprotrandmax"] = state.get("rot_max", 1.0) * 360.0
        parms["uniformrand"] = state.get("cone_angle", 0.0)

        # Scale Range (using X component for uniform variety range)
        parms["minradius"] = state.get("scl_min", [1, 1, 1])[0]
        parms["maxradius"] = state.get("scl_max", [1, 1, 1])[0]
        
        # Normal blending: enable flag + amount
        parms["blendtowardtarget"] = 1 if state.get("normal_align", False) else 0
        parms["blendamount"] = state.get("blend_amount", 1.0)

        # Min spacing: use the larger of the UI slider value and the asset
        # bounding-sphere diameter scaled by global_scale * min_scale.
        # This stops instances from collapsing through each other.
        ui_min = float(state.get("min_distance", 0.1))
        asset_r = get_asset_max_radius(geo)
        gs = float(state.get("global_scale", 1.0))
        scl_min = float((state.get("scl_min") or [1.0])[0])
        bbox_min = asset_r * 2.0 * gs * scl_min
        parms["useminspacing"] = 1
        parms["minspacing"] = max(ui_min, bbox_min) if bbox_min > 1e-4 else ui_min

        # Remove overlapping points post-process.
        remove_ovlp = state.get("remove_overlapping", False)
        parms["removeoverlapping"] = 1 if remove_ovlp else 0
        parms["overlaptolerance"] = float(state.get("overlap_tolerance", 1.0))

        try:
            scatter.setParms(parms)
        except Exception as e:
            log(f"Sync error: {e}")

        # Target axis: pass combo index (0=X, 1=Y, 2=Z) directly to blendtarget
        axis_index = int(state.get("blend_axis", 1))
        p = scatter.parm("blendtarget")
        if p is not None:
            try:
                p.set(max(0, min(2, axis_index)))
            except Exception as e:
                log(f"Blend axis parm 'blendtarget' set error: {e}")

    # 3. Sync Pscale Wrangle
    wrangle = geo.node("pscale_wrangle")
    if not wrangle and scatter:
        # Auto-upgrade existing networks
        ctp = geo.node("instancer")
        if ctp:
            wrangle = geo.createNode("attribwrangle", "pscale_wrangle")
            wrangle.setInput(0, scatter)
            ctp.setInput(1, wrangle)
            try: geo.layoutChildren()
            except: pass

    if wrangle:
        uni_xyz = state.get("uniform_xyz", True)
        scl_min = state.get("scl_min", [1, 1, 1])
        scl_max = state.get("scl_max", [1, 1, 1])
        g_scl = state.get("global_scale", 1.0)
        pscale_randomize = state.get("pscale_randomize", 1.0)
        stamp_scale = state.get("stamp_scale", 1.0)

        if uni_xyz:
            snippet = (
                f"float base_pscale = haspointattrib(0, 'pscale') ? @pscale : 1.0;\n"
                f"float stamp_s = (@mask > 0) ? {stamp_scale:.5f} : 1.0;\n"
                f"float global = chf(\"global_scale\") * stamp_s;\n"
                f"float rand_scale = fit01(rand(@ptnum + 1234), {scl_min[0]:.5f}, {scl_max[0]:.5f});\n"
                f"rand_scale = lerp(1.0, rand_scale, {pscale_randomize:.5f});\n"
                f"@pscale = base_pscale * rand_scale * global;\n"
                f"@pscale = clamp(@pscale, 0.0, global);"
            )
        else:
            snippet = (
                f"float base_pscale = haspointattrib(0, 'pscale') ? @pscale : 1.0;\n"
                f"float stamp_s = (@mask > 0) ? {stamp_scale:.5f} : 1.0;\n"
                f"float global = chf(\"global_scale\") * stamp_s;\n"
                f"vector rand_scale = set("
                f"fit01(rand(@ptnum + 1234), {scl_min[0]:.5f}, {scl_max[0]:.5f}), "
                f"fit01(rand(@ptnum + 2345), {scl_min[1]:.5f}, {scl_max[1]:.5f}), "
                f"fit01(rand(@ptnum + 3456), {scl_min[2]:.5f}, {scl_max[2]:.5f}));\n"
                f"rand_scale = lerp({{1.0, 1.0, 1.0}}, rand_scale, {pscale_randomize:.5f});\n"
                f"v@scale = rand_scale * global * base_pscale;\n"
                f"v@scale = set(clamp(@scale.x, 0.0, global), clamp(@scale.y, 0.0, global), clamp(@scale.z, 0.0, global));"
            )
        try:
            wrangle.setParms({"snippet": snippet})
        except Exception as e:
            log(f"Wrangle sync error: {e}")
        _ensure_pscale_wrangle_global_parm(wrangle, g_scl)

    # 4. Sync AttribFromPieces
    piece_attr = geo.node("piece_attr")
    if not piece_attr and scatter:
        # Clean up old piece_wrangle if present
        old_wr = geo.node("piece_wrangle")
        if old_wr:
            old_wr.destroy()

        pscale_wr    = geo.node("pscale_wrangle")
        ctp          = geo.node("instancer")
        assets_merge = geo.node("assets_merge")

        if pscale_wr and ctp and assets_merge:
            # Ensure orientalongcurve1 exists between pscale_wrangle and piece_attr
            orient_curve = geo.node("orientalongcurve1")
            if orient_curve is None:
                orient_curve = geo.createNode("orientalongcurve", "orientalongcurve1")
                orient_curve.setInput(0, pscale_wr)

            # Ensure attribrandomize_orient exists between orientalongcurve1 and add_keep
            orient_rand = geo.node("attribrandomize_orient")
            if orient_rand is None:
                orient_rand = geo.createNode("attribrandomize", "attribrandomize_orient")
                orient_rand.setInput(0, orient_curve)
                _configure_attribrandomize_orient(orient_rand)
            else:
                # Already exists — re-apply the dimension setting in case it's stale.
                _configure_attribrandomize_orient(orient_rand)

            # Ensure add_keep (Keep Points) exists after attribrandomize_orient
            add_keep = geo.node("add_keep")
            if add_keep is None:
                add_keep = geo.createNode("add", "add_keep")
                add_keep.setInput(0, orient_rand)
                add_keep.setParms({"switcher1": 2})

            piece_attr = geo.createNode("attribfrompieces", "piece_attr")
            piece_attr.setInput(0, add_keep)
            piece_attr.setInput(1, assets_merge)
            piece_attr.setParms({
                "pieceattrib": "piece"
            })
            ctp.setInput(1, piece_attr)
            ctp.setParms({
                "useidattrib": 1,
                "idattrib": "piece"
            })
            lod_assets_merge = geo.node("lod_assets_merge")
            if lod_assets_merge is None:
                lod_assets_merge = geo.createNode("merge", "lod_assets_merge")
                lod_assets_merge.setInput(0, assets_merge)
            if ctp.input(0) is None or ctp.input(0).path() != lod_assets_merge.path():
                ctp.setInput(0, lod_assets_merge)
            try: geo.layoutChildren()
            except: pass

    # 5. Sync per-asset density weights (drop-probability filter)
    sync_asset_weights(paint_node, state.get("weights", []))

    # Ensure piece_attr and instancer have their standard attribute-transfer rows
    for _node_name in ("piece_attr", "instancer"):
        _n = geo.node(_node_name)
        if _n is not None:
            _p = _n.parm("numattr")
            if _p is not None and _p.eval() == 0:
                _reset_attrib_from_target(_n)

    # 6. Sync geometry offset
    sync_geo_offset(geo, state.get("geo_offset", 0.0))

    # 7. Sync clumping
    sync_clump_params(geo, state)

    # 8. Sync per-instance color variation
    sync_color_params(geo, state)

    # 9. Sync proximity exclusion
    sync_proximity_params(geo, state)

    # 10. Sync LOD
    sync_lod_params(geo, state)

    # 11. Sync placement rules
    sync_placement_rules(geo, state.get("placement_rules", []))

    # Ensure scatter_filecache is connected to instancer output after all network modifications
    ensure_scatter_filecache(geo)


def clear_points(paint_node):
    """
    Resets the attribute paint mask on the attribpaint SOP, clearing all
    scattered instances.  Tries every known parm name for the reset button
    across different Houdini versions.
    """
    if paint_node is None:
        return
    try:
        # Try all known names for the "Reset All Changes" button
        for parm_name in ("reset", "attribreset1", "resetattrib1"):
            btn = paint_node.parm(parm_name)
            if btn is not None:
                btn.pressButton()
                log(f"Pressed '{parm_name}' on {paint_node.path()}")
                return
        # Last resort: print available parms so user can report
        parm_names = [p.name() for p in paint_node.parms()]
        log(f"No reset parm found. Available: {parm_names}")
        print(f"[Magic Scatter World] Could not find reset button. Parms: {parm_names}")
    except Exception as e:
        log(f"Clear error: {e}")
        print(f"[Magic Scatter World] Clear error: {e}")


# ---------------------------------------------------------------------------
# Curve scatter network
# ---------------------------------------------------------------------------

def create_curve_scatter_network(geo_node, paint_node, resample_length=0.5,
                                 jitter=0.0, curve_sop=None, subdivide=False,
                                 rand_rot=0.0):
    """
    Builds / rebuilds the curve scatter branch and wires it into pscale_wrangle.

    Each drawcurve gets its own full processing chain (settings preserved on rebuild):

      drawcurve   ─ curve_resample   ─ curve_pointjitter   ─ curve_pscale   ─ curve_rot_wrangle   ─┐
      drawcurve_2 ─ curve_resample_2 ─ curve_pointjitter_2 ─ curve_pscale_2 ─ curve_rot_wrangle_2 ─┤
      drawcurve_N ─ curve_resample_N ─ curve_pointjitter_N ─ curve_pscale_N ─ curve_rot_wrangle_N ─┘
                                                                                                    │
                                                                                             curves_merge
                                                                                                    │
                                                                                              curve_ray ──────────────────┐
    scatter_logic → [cam_frustum_cull] → pscale_wrangle ──────────────────── curve_scatter_merge ─┘
                                                                                        │
                                                                                    geo_offset → ...
    """
    curve_nodes   = get_drawcurve_nodes(geo_node)
    scatter_logic = geo_node.node("scatter_logic")
    pscale_wr     = geo_node.node("pscale_wrangle")

    if not curve_nodes:
        raise RuntimeError("No curve node found. Click Draw Curve first.")
    if scatter_logic is None:
        raise RuntimeError("Could not find 'scatter_logic'. Re-create the scatter network.")
    if pscale_wr is None:
        raise RuntimeError("Could not find 'pscale_wrangle'. Re-create the scatter network.")

    # Remove stale scatter merge from any previous apply
    stale = geo_node.node("curve_scatter_merge")
    if stale:
        stale.destroy()

    # ── Build per-curve chain: resample → pointjitter → pscale → rot_wrangle
    rot_outputs = []
    for curve_node in curve_nodes:
        cn = curve_node.name()

        # resample
        rs_name = _resample_name_for_curve(cn)
        resample = geo_node.node(rs_name)
        if resample is not None:
            inp = resample.input(0)
            if inp is not None and inp.name() in ("curve_pscale", "curves_merge"):
                resample.destroy(); resample = None
        rs_new = resample is None
        if resample is None:
            resample = geo_node.createNode("resample", rs_name)
        resample.setInput(0, curve_node)
        if rs_new:
            resample.setParms({"length": max(0.001, resample_length),
                               "treatpolysas": 1 if subdivide else 0})

        # pointjitter
        pj_name = _pointjitter_name_for_curve(cn)
        pj = geo_node.node(pj_name)
        if pj is not None:
            inp = pj.input(0)
            if inp is not None and inp.name() in ("curve_pscale", "curve_resample"):
                pj.destroy(); pj = None
        pj_new = pj is None
        if pj is None:
            pj = geo_node.createNode("pointjitter", pj_name)
        pj.setInput(0, resample)
        if pj_new:
            pj.setParms({"scale": jitter})

        # pscale wrangle
        ps_name = _pscale_name_for_curve(cn)
        ps = geo_node.node(ps_name)
        ps_new = ps is None
        if ps is None:
            ps = geo_node.createNode("attribwrangle", ps_name)
        ps.setInput(0, pj)
        if ps_new:
            ps.setParms({"class": 2, "snippet": "f@pscale = 1.0;"})

        # rot wrangle
        rot_name = _rot_wrangle_name_for_curve(cn)
        rot_wr = geo_node.node(rot_name)
        rot_new = rot_wr is None
        if rot_wr is None:
            rot_wr = geo_node.createNode("attribwrangle", rot_name)
        rot_wr.setInput(0, ps)
        if rot_new:
            rot_wr.setParms({"class": 2, "snippet": _curve_rot_snippet(rand_rot)})

        rot_outputs.append(rot_wr)

    # ── Merge all per-curve rot_wrangle outputs ────────────────────────────
    if len(rot_outputs) > 1:
        curves_merge = geo_node.node("curves_merge")
        if curves_merge is None:
            curves_merge = geo_node.createNode("merge", "curves_merge")
        for i, ro in enumerate(rot_outputs):
            curves_merge.setInput(i, ro)
        upstream_of_ray = curves_merge
    else:
        old_cm = geo_node.node("curves_merge")
        if old_cm:
            old_cm.destroy()
        upstream_of_ray = rot_outputs[0]

    # ── ray ───────────────────────────────────────────────────────────────
    surface_node = geo_node.node("surface_merge") or geo_node.node("surface_input")
    ray = geo_node.node("curve_ray")
    if ray is None:
        ray = geo_node.createNode("ray", "curve_ray")
    ray.setInput(0, upstream_of_ray)
    if surface_node is not None:
        ray.setInput(1, surface_node)
    ray.setParms({"method": 0})

    # ── final merge ───────────────────────────────────────────────────────
    # pscale_wr stays in its current input position (scatter_logic / cam_frustum_cull).
    # curve_scatter_merge sits AFTER pscale_wr so regular scatter gets pscale applied;
    # curve scatter already has per-curve pscale and skips pscale_wr via ray input.
    geo_offset = geo_node.node("geo_offset")
    merge = geo_node.createNode("merge", "curve_scatter_merge")
    merge.setInput(0, pscale_wr)  # regular scatter — already pscale'd
    merge.setInput(1, ray)         # curve scatter — has per-curve pscale
    if geo_offset is not None:
        geo_offset.setInput(0, merge)

    geo_node.layoutChildren()
    return curve_nodes[0]


def wire_curve_surface(geo_node, surface_node):
    """No-op kept for API compatibility — surface wiring not needed in this chain."""
    pass


def update_curve_scatter_pieces(geo_node, num_assets):
    """No-op kept for API compatibility — piece assignment handled by attribfrompieces."""
    pass


def get_drawcurve_nodes(geo_node):
    """
    Return all drawcurve* nodes inside geo_node, sorted by index.

    Naming convention:
      - First curve  -> ``drawcurve``
      - Subsequent   -> ``drawcurve_2``, ``drawcurve_3``, ...
      - Renamed      -> ``drawcurve_<any_label>`` (non-numeric suffix also accepted)
    """
    nodes = []
    for child in geo_node.children():
        name = child.name()
        if name == "drawcurve":
            nodes.append((1, 0, child))
        elif name.startswith("drawcurve_"):
            suffix = name[len("drawcurve_"):]
            # Numeric suffix keeps its sort order; named suffixes sort alphabetically after
            if suffix.isdigit():
                nodes.append((2, int(suffix), child))
            else:
                nodes.append((3, suffix, child))
    nodes.sort(key=lambda t: (t[0], t[1]))
    return [node for _, _, node in nodes]


def _resample_name_for_curve(curve_name):
    if curve_name == "drawcurve":
        return "curve_resample"
    if curve_name.startswith("drawcurve_"):
        return "curve_resample_" + curve_name[len("drawcurve_"):]
    return "curve_resample"


def _pointjitter_name_for_curve(curve_name):
    if curve_name == "drawcurve":
        return "curve_pointjitter"
    if curve_name.startswith("drawcurve_"):
        return "curve_pointjitter_" + curve_name[len("drawcurve_"):]
    return "curve_pointjitter"


def _pscale_name_for_curve(curve_name):
    if curve_name == "drawcurve":
        return "curve_pscale"
    if curve_name.startswith("drawcurve_"):
        return "curve_pscale_" + curve_name[len("drawcurve_"):]
    return "curve_pscale"


def _rot_wrangle_name_for_curve(curve_name):
    if curve_name == "drawcurve":
        return "curve_rot_wrangle"
    if curve_name.startswith("drawcurve_"):
        return "curve_rot_wrangle_" + curve_name[len("drawcurve_"):]
    return "curve_rot_wrangle"


def get_curve_resample_params(geo_node, curve_name):
    """Return the current resample params for a specific curve, or defaults."""
    resample = geo_node.node(_resample_name_for_curve(curve_name))
    if resample is None:
        return {"length": 0.5, "treatpolysas": 0}
    length_p = resample.parm("length")
    poly_p   = resample.parm("treatpolysas")
    return {
        "length":       length_p.eval() if length_p else 0.5,
        "treatpolysas": poly_p.eval()   if poly_p   else 0,
    }


def get_curve_pointjitter_params(geo_node, curve_name):
    """Return the current pointjitter params for a specific curve, or defaults."""
    pj = geo_node.node(_pointjitter_name_for_curve(curve_name))
    if pj is None:
        return {"scale": 0.0}
    scale_p = pj.parm("scale")
    return {"scale": scale_p.eval() if scale_p else 0.0}


def get_curve_pscale_params(geo_node, curve_name):
    """Return the per-curve scale multiplier by parsing the pscale snippet."""
    node = geo_node.node(_pscale_name_for_curve(curve_name))
    if node is None:
        return {"curve_scale": 1.0}
    snippet_p = node.parm("snippet")
    if snippet_p is None:
        return {"curve_scale": 1.0}
    m = re.search(r'f@pscale\s*=\s*f@curve_rand\s*\*\s*([\d.]+)', snippet_p.eval())
    return {"curve_scale": float(m.group(1)) if m else 1.0}


def get_curve_rot_params(geo_node, curve_name):
    """Return the random rotation range by parsing the rot_wrangle snippet."""
    node = geo_node.node(_rot_wrangle_name_for_curve(curve_name))
    if node is None:
        return {"rand_rot": 0.0}
    snippet_p = node.parm("snippet")
    if snippet_p is None:
        return {"rand_rot": 0.0}
    m = re.search(r'radians\(([\d.]+)\)', snippet_p.eval())
    return {"rand_rot": float(m.group(1)) if m else 0.0}


def set_curve_resample_length(geo_node, length, curve_name=None):
    """Live-update point spacing on a specific curve's resample node. curve_name required."""
    if not curve_name:
        return
    resample = geo_node.node(_resample_name_for_curve(curve_name))
    if resample:
        resample.setParms({"length": max(0.001, length)})


def set_curve_jitter(geo_node, jitter, curve_name=None):
    """Live-update jitter on a specific curve's pointjitter node. curve_name required."""
    if not curve_name:
        return
    pointjitter = geo_node.node(_pointjitter_name_for_curve(curve_name))
    if pointjitter:
        pointjitter.setParms({"scale": jitter})


def set_curve_subdivide(geo_node, subdivide, curve_name=None):
    """Live-update treatpolysas on a specific curve's resample node. curve_name required."""
    if not curve_name:
        return
    resample = geo_node.node(_resample_name_for_curve(curve_name))
    if resample:
        resample.setParms({"treatpolysas": 1 if subdivide else 0})


def set_curve_pscale(geo_node, scl_min, scl_max, randomize, curve_scale=1.0, curve_name=None):
    """Live-update a per-curve pscale node. curve_name must be provided; no-ops otherwise."""
    if not curve_name:
        return
    node = geo_node.node(_pscale_name_for_curve(curve_name))
    if not node:
        return
    s_min = scl_min[0] if isinstance(scl_min, (list, tuple)) else scl_min
    s_max = scl_max[0] if isinstance(scl_max, (list, tuple)) else scl_max
    snippet = (
        f"float rand_val = fit01(rand(@ptnum + 666), {s_min:.5f}, {s_max:.5f});\n"
        f"f@curve_rand = lerp(1.0, rand_val, {randomize:.5f});\n"
        f"f@pscale = f@curve_rand * {curve_scale:.5f};"
    )
    node.setParms({"snippet": snippet})


def _curve_rot_snippet(rand_rot_deg):
    """Return VEX snippet that applies a random Y-axis rotation up to rand_rot_deg degrees."""
    return (
        f"float randAngle = fit01(rand(@ptnum + 7331), 0.0, radians({rand_rot_deg:.4f}));\n"
        f"vector rotAxis = {{0, 1, 0}};\n"
        f"@orient = quaternion(randAngle, rotAxis);"
    )


def delete_curve_node(geo_node, curve_node_name):
    """
    Delete a drawcurve* node and all its per-curve processing nodes
    (resample, pointjitter, pscale, rot_wrangle), then rebuild curves_merge.
    Returns True on success.
    """
    target = geo_node.node(curve_node_name)
    if target is None:
        return False

    # Destroy all four per-curve nodes for this curve
    for name_fn in (_rot_wrangle_name_for_curve, _pscale_name_for_curve,
                    _pointjitter_name_for_curve, _resample_name_for_curve):
        n = geo_node.node(name_fn(curve_node_name))
        if n:
            n.destroy()

    target.destroy()

    # Rebuild curves_merge using remaining curves' rot_wrangle outputs
    remaining = get_drawcurve_nodes(geo_node)
    old_cm  = geo_node.node("curves_merge")
    ray     = geo_node.node("curve_ray")

    if len(remaining) > 1:
        if old_cm:
            old_cm.destroy()
        new_cm = geo_node.createNode("merge", "curves_merge")
        for i, cn in enumerate(remaining):
            rot = geo_node.node(_rot_wrangle_name_for_curve(cn.name()))
            new_cm.setInput(i, rot if rot else cn)
        if ray:
            ray.setInput(0, new_cm)
    elif len(remaining) == 1:
        if old_cm:
            old_cm.destroy()
        if ray:
            rot = geo_node.node(_rot_wrangle_name_for_curve(remaining[0].name()))
            ray.setInput(0, rot if rot else remaining[0])
    else:
        # Last curve deleted — tear down the entire curve scatter branch
        if old_cm:
            old_cm.destroy()
        stale_merge = geo_node.node("curve_scatter_merge")
        if stale_merge:
            stale_merge.destroy()
        if ray:
            ray.destroy()
        # Restore geo_offset → pscale_wrangle direct connection
        pscale_wr  = geo_node.node("pscale_wrangle")
        geo_offset = geo_node.node("geo_offset")
        if pscale_wr and geo_offset:
            geo_offset.setInput(0, pscale_wr)

    try:
        geo_node.layoutChildren()
    except Exception:
        pass
    return True


def rename_curve_node(geo_node, old_name, new_name):
    """
    Rename a drawcurve* node and all its per-curve processing nodes.
    If new_name does not already start with 'drawcurve_' (or equal 'drawcurve'),
    it is automatically prefixed with 'drawcurve_' so the node remains
    discoverable by get_drawcurve_nodes.
    Returns (True, actual_name) on success, (False, None) on failure.
    """
    node = geo_node.node(old_name)
    if node is None:
        return False, None
    safe = new_name.strip()
    if safe != "drawcurve" and not safe.startswith("drawcurve_"):
        safe = "drawcurve_" + safe
    name_fns = (_resample_name_for_curve, _pointjitter_name_for_curve,
                _pscale_name_for_curve, _rot_wrangle_name_for_curve)
    old_companions = [(fn, geo_node.node(fn(old_name))) for fn in name_fns]
    try:
        node.setName(safe, unique_name=True)
        actual_name = node.name()
        for fn, companion in old_companions:
            if companion:
                try:
                    companion.setName(fn(actual_name), unique_name=True)
                except Exception:
                    pass
        return True, actual_name
    except Exception:
        return False, None


def set_curve_rand_rot(geo_node, rand_rot_deg, curve_name=None):
    """Live-update the random Y rotation range on a per-curve rot_wrangle node. curve_name required."""
    if not curve_name:
        return
    rot_wr = geo_node.node(_rot_wrangle_name_for_curve(curve_name))
    if rot_wr:
        rot_wr.setParms({"snippet": _curve_rot_snippet(rand_rot_deg)})



def sync_asset_weights(paint_node, weights):
    """
    Inserts (or updates) a 'weight_filter' attribwrangle between piece_attr
    and instancer that drops points whose asset weight is < 1.0.

    weights is a list of floats (0..1) indexed by the @piece attribute that
    piece_attr writes onto each scatter point. A weight of 1.0 keeps every
    point; 0.5 keeps roughly half; 0.0 drops all points for that asset.
    """
    if paint_node is None:
        return
    geo = paint_node.parent()
    if geo is None:
        return
    piece_attr = geo.node("piece_attr")
    inst       = geo.node("instancer")
    if piece_attr is None or inst is None:
        return

    wf = geo.node("weight_filter")
    if wf is None:
        wf = geo.createNode("attribwrangle", "weight_filter")
        wf.setParms({"class": 2})  # Run Over Points
        wf.setInput(0, piece_attr)
        # color_wrangle sits after weight_filter; only wire to instancer if it doesn't exist
        color_wr = geo.node("color_wrangle")
        if color_wr is not None:
            color_wr.setInput(0, wf)
        else:
            inst.setInput(1, wf)
        try:
            geo.layoutChildren()
        except Exception:
            pass

    if not weights:
        wf.bypass(True)
        return

    arr = ", ".join(f"{max(0.0, min(1.0, float(w))):.6f}" for w in weights)
    snippet = (
        f"float weights[] = array({arr});\n"
        f"int p = i@piece;\n"
        f"if (p >= 0 && p < len(weights)) {{\n"
        f"    float w = weights[p];\n"
        f"    if (w < 1.0 && rand(@ptnum * 13.7 + 9876.0) >= w) {{\n"
        f"        removepoint(0, @ptnum);\n"
        f"    }}\n"
        f"}}\n"
    )
    try:
        wf.setParms({"snippet": snippet})
        wf.bypass(False)
    except Exception as e:
        log(f"weight_filter sync error: {e}")

    # Ensure scatter_filecache stays connected after weight updates
    ensure_scatter_filecache(geo)


def _reset_attrib_from_target(node):
    """Press the 'Reset Attributes from Target' button on any SOP that has it.

    Works on both attribfrompieces (piece_attr) and copytopoints (instancer).
    Tries the built-in button first; falls back to setting the 3 standard rows.
    """
    if node is None:
        return
    # Try known button parameter names (varies by node type and Houdini version)
    for btn_name in ("resetnopointn", "resetattribs", "resettransferattribs", "resettargetattribs"):
        p = node.parm(btn_name)
        if p is not None:
            try:
                p.pressButton()
                return
            except Exception:
                pass
    # Fallback: set the 3 standard rows manually
    try:
        node.setParms({"numattr": 3})
        node.setParms({
            "applyto1": 0, "method1": 0,
            "attribs1": "*, ^v, ^Alpha, ^N, ^up, ^pscale, ^scale, ^orient, ^rot, ^pivot, ^trans, ^t",
            "applyto2": 0, "method2": 2, "attribs2": "Alpha",
            "applyto3": 0, "method3": 3, "attribs3": "v",
        })
    except Exception as e:
        log(f"_reset_attrib_from_target ({node.name()}): {e}")


def _init_piece_attr_defaults(piece_attr):
    _reset_attrib_from_target(piece_attr)


def _asset_group_name(path, used_names):
    """Return a Houdini-safe, unique group name based on the asset node name."""
    node = hou.node(path) if path else None
    raw_name = node.name() if node is not None else os.path.basename(str(path).rstrip("/\\"))
    base = re.sub(r"[^0-9A-Za-z_]+", "_", raw_name).strip("_") or "asset"
    if base[0].isdigit():
        base = f"asset_{base}"

    name = base
    suffix = 2
    while name in used_names:
        name = f"{base}_{suffix}"
        suffix += 1
    used_names.add(name)
    return name


def update_instancing_network(paint_node, asset_paths):
    """
    Creates Object Merge nodes for each asset path and connects them
    to the assets_merge node inside the scatter system.
    """
    geo = paint_node.parent()
    merge = geo.node("merge_assets") if geo.node("merge_assets") else geo.node("assets_merge")
    if not merge:
        return

    # Clear existing nodes connected to this merge.
    # Each slot holds a piece_aw (attribwrangle); its input is the object_merge.
    # Destroying piece_aw alone leaves the object_merge orphaned, so collect
    # both then destroy together.
    nodes_to_remove = []
    for conn in merge.inputs():
        if conn and conn not in nodes_to_remove:
            om = conn.input(0)
            nodes_to_remove.append(conn)
            if om is not None and om not in nodes_to_remove:
                nodes_to_remove.append(om)
    for node in nodes_to_remove:
        try:
            node.destroy()
        except Exception:
            pass

    # Create new object merges
    used_group_names = set()
    for i, path in enumerate(asset_paths):
        om = geo.createNode("object_merge", f"asset_{i}")
        om.setParms({"objpath1": path, "xformtype": 1}) # Into This Object
        # Add LOD path spare parms so they persist in the .hip file
        try:
            ptg = om.parmTemplateGroup()
            ptg.append(hou.StringParmTemplate(
                "lod1_path", "LOD 1 Path", 1,
                string_type=hou.stringParmType.NodeReference))
            ptg.append(hou.StringParmTemplate(
                "lod2_path", "LOD 2 Path", 1,
                string_type=hou.stringParmType.NodeReference))
            om.setParmTemplateGroup(ptg)
        except Exception as _e:
            log(f"update_instancing_network: lod spare parms: {_e}")

        group_name = _asset_group_name(path, used_group_names)
        piece_aw = geo.createNode("attribwrangle", f"asset_{i}_piece")
        piece_aw.setInput(0, om)
        piece_aw.setParms({
            "class": 1, # Primitives
            "snippet": (
                f"i@piece = {i};\n"
                f"setprimgroup(0, \"{group_name}\", @primnum, 1, \"set\");"
            )
        })
        
        merge.setInput(i, piece_aw)

    geo.layoutChildren()
    # Ensure scatter_filecache stays connected after asset updates
    ensure_scatter_filecache(geo)


def get_point_count(paint_node):
    """Returns how many scatter instances exist."""
    if paint_node is None:
        return 0
    try:
        geo_node = paint_node.parent()
        scatter = geo_node.node("scatter_logic")
        if scatter:
            return len(scatter.geometry().points())
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# Quaternion helper
# ---------------------------------------------------------------------------

def _euler_to_quaternion(rx_deg, ry_deg, rz_deg, align_normal=None):
    """
    Converts Euler XYZ (degrees) to a quaternion (x,y,z,w).
    If align_normal is a (nx,ny,nz) tuple the base orientation is first
    rotated so that local Y aligns with the surface normal.
    """
    def deg2rad(d): return d * math.pi / 180.0

    # Build rotation matrix from Euler XYZ
    rx, ry, rz = deg2rad(rx_deg), deg2rad(ry_deg), deg2rad(rz_deg)

    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)

    # If align_normal: find rotation from (0,1,0) to normal, then apply euler
    if align_normal is not None:
        n = hou.Vector3(align_normal).normalized()
        up = hou.Vector3(0, 1, 0)
        axis = up.cross(n)
        axis_len = axis.length()
        if axis_len > 1e-6:
            axis = axis / axis_len
            angle = math.acos(max(-1.0, min(1.0, up.dot(n))))
            # Rodrigues → quaternion
            s = math.sin(angle / 2.0)
            qn = (axis[0]*s, axis[1]*s, axis[2]*s, math.cos(angle / 2.0))
        else:
            qn = (0.0, 0.0, 0.0, 1.0)
    else:
        qn = (0.0, 0.0, 0.0, 1.0)

    # Euler XYZ → quaternion
    qx = (math.sin(rx/2), 0, 0, math.cos(rx/2))
    qy = (0, math.sin(ry/2), 0, math.cos(ry/2))
    qz = (0, 0, math.sin(rz/2), math.cos(rz/2))
    q_euler = _qmul(_qmul(qz, qy), qx)

    q = _qmul(qn, q_euler)
    return q   # (x, y, z, w)


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw*bx + ax*bw + ay*bz - az*by,
        aw*by - ax*bz + ay*bw + az*bx,
        aw*bz + ax*by - ay*bx + az*bw,
        aw*bw - ax*bx - ay*by - az*bz,
    )


# ---------------------------------------------------------------------------
# Raycasting (viewport intersection)
# ---------------------------------------------------------------------------

def raycast_geo_node(geo_node, origin, direction):
    """
    Intersect a ray with the visible geometry of `geo_node`.

    Args:
        geo_node  – hou.Node (object-level geo node to test against)
        origin    – hou.Vector3 ray origin (world space)
        direction – hou.Vector3 ray direction (world space, not normalised is ok)

    Returns:
        (hit_pos, hit_normal) as hou.Vector3 pair, or None on miss.
    """
    try:
        sop = geo_node.displayNode()
        if sop is None:
            return None
        geo = sop.geometry()
        if geo is None:
            return None

        d = direction.normalized()
        hit_pos    = hou.Vector3()
        hit_normal = hou.Vector3()
        hit_uvw    = hou.Vector3()

        prim_num = geo.intersect(origin, d, hit_pos, hit_normal, hit_uvw)
        if prim_num >= 0:
            return hit_pos, hit_normal
    except Exception as e:
        log(f"raycast error: {e}")
    return None


# ---------------------------------------------------------------------------
# Multi-surface support
# ---------------------------------------------------------------------------

def ensure_scatter_on_scatter_output(source_geo_node):
    """Create / ensure an unpacked output in a scatter network so another
    scatter network can use the instanced geometry as its surface.

    Creates:  OUT_scatter → scatter_unpack (unpack SOP) → OUT_scatter_unpack (null)

    Returns the full Houdini path to OUT_scatter_unpack, or None on failure.
    """
    if source_geo_node is None:
        return None
    out = source_geo_node.node("OUT_scatter")
    if out is None:
        return None

    unpack = source_geo_node.node("scatter_unpack")
    if unpack is None:
        unpack = source_geo_node.createNode("unpack", "scatter_unpack")
        unpack.setInput(0, out)

    out_unpack = source_geo_node.node("OUT_scatter_unpack")
    if out_unpack is None:
        out_unpack = source_geo_node.createNode("null", "OUT_scatter_unpack")
        out_unpack.setInput(0, unpack)

    try:
        source_geo_node.layoutChildren()
    except Exception:
        pass

    return out_unpack.path()


def ensure_surface_merge(geo_node):
    """Ensure surface_merge (merge SOP) exists and sits between surface_input
    and mesh_group.  Upgrades old single-surface networks transparently."""
    if geo_node is None:
        return None
    surf_input = geo_node.node("surface_input")
    if surf_input is None:
        return None
    surf_merge = geo_node.node("surface_merge")
    if surf_merge is None:
        surf_merge = geo_node.createNode("merge", "surface_merge")
        surf_merge.setInput(0, surf_input)
        mesh = geo_node.node("mesh")
        if mesh is not None and (mesh.input(0) is None or
                                  mesh.input(0).path() == surf_input.path()):
            mesh.setInput(0, surf_merge)
    return surf_merge


def update_surface_inputs(geo_node, paths):
    """Set the full list of scatter surfaces.

    paths[0] → surface_input (the primary object_merge, always exists).
    paths[1..] → surface_1, surface_2, … extra object_merges wired into
                 surface_merge at slots 1, 2, …
    Old extra nodes beyond len(paths)-1 are destroyed.
    """
    if geo_node is None or not paths:
        return
    surf_merge = ensure_surface_merge(geo_node)
    surf_input = geo_node.node("surface_input")
    if surf_input is None:
        return

    # Primary surface
    surf_input.setParms({"objpath1": paths[0], "numobj": 1})

    # Extra surfaces
    extra_paths = paths[1:]
    for i, path in enumerate(extra_paths):
        slot = i + 1
        name = f"surface_{slot}"
        node = geo_node.node(name)
        if node is None:
            node = geo_node.createNode("object_merge", name)
            node.setParms({"xformtype": 1})
        node.setParms({"objpath1": path, "numobj": 1})
        if surf_merge is not None:
            surf_merge.setInput(slot, node)

    # Remove stale extra nodes
    i = len(extra_paths) + 1
    while True:
        name = f"surface_{i}"
        node = geo_node.node(name)
        if node is None:
            break
        try:
            node.destroy()
        except Exception:
            pass
        i += 1


def get_surface_paths(geo_node):
    """Return the ordered list of surface paths currently wired in."""
    if geo_node is None:
        return []
    surf_input = geo_node.node("surface_input")
    if surf_input is None:
        return []
    primary = surf_input.parm("objpath1").eval() if surf_input.parm("objpath1") else ""
    paths = [primary] if primary else []
    i = 1
    while True:
        node = geo_node.node(f"surface_{i}")
        if node is None:
            break
        p = node.parm("objpath1").eval() if node.parm("objpath1") else ""
        if p:
            paths.append(p)
        i += 1
    return paths


# ---------------------------------------------------------------------------
# Metadata persistence
# ---------------------------------------------------------------------------

def save_meta(paint_node, **kwargs):
    """Serialise tool parameters into the SOP's user data."""
    if paint_node is None:
        return

    # We use kwargs to match existing UI logic structure
    meta = kwargs.copy()
    meta["ver"] = TOOL_VERSION

    # Preserve asset list and per-asset weights — those are managed by
    # save_asset_node_paths, not by sync_state/save_meta. Without this
    # preservation, every sync_state would clobber the weight array.
    existing = load_meta(paint_node)
    meta["assets"] = existing.get("assets", [])
    if "asset_weights" in existing:
        meta["asset_weights"] = existing["asset_weights"]

    paint_node.setUserData(META_KEY, json.dumps(meta))
    log(f"Meta saved to {paint_node.path()}")


def load_meta(paint_node):
    """Load and return the metadata dict, or {} on failure."""
    if paint_node is None:
        return {}
    raw = paint_node.userData(META_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Scene discovery
# ---------------------------------------------------------------------------

def get_scatter_nodes():
    """
    Return a list of (geo_node, scatter_sop) for every scatter system
    currently in the scene.
    """
    results = []
    obj = hou.node("/obj")
    if obj is None:
        return results
    for node in obj.children():
        if node.userData(SCATTER_TAG):
            sop = _find_scatter_sop(node)
            if sop:
                results.append((node, sop))
    return results


def _find_scatter_sop(geo_node):
    """Find the 'paint_mask' Attribute Paint SOP inside a geo node."""
    for child in geo_node.children():
        if child.type().name() == "attribpaint" and child.name() == "paint_mask":
            return child
    return None


def get_wire_sop(geo_node):
    """Return the wire-mesh output SOP for ivy/crawl networks, or None.

    Crawling Ivy exposes its wire mesh through a 'crawl_OUT' null;
    Ivy Generation uses 'OUT_wires'.  Regular scatter networks have neither.
    """
    if geo_node is None:
        return None
    node = geo_node.node("crawl_OUT")
    if node is not None:
        return node
    return geo_node.node("OUT_wires")


def get_asset_node_paths(paint_node):
    """
    Retrieve the list of asset node paths.
    First reads from meta; if meta has no assets, falls back to reading
    the objpath1 parms of the object_merge nodes wired into assets_merge/
    merge_assets in the SOP network.  This covers Ivy mode where save_meta
    is never called but the network nodes are authoritative.
    """
    meta = load_meta(paint_node)
    paths = meta.get("assets", [])
    log(f"[get_asset_node_paths] meta assets: {paths}")
    if paths:
        return paths

    # Fallback: reconstruct from live network nodes
    geo = paint_node.parent()
    merge = geo.node("merge_assets") if geo.node("merge_assets") else geo.node("assets_merge")
    log(f"[get_asset_node_paths] merge node: {merge}")
    if merge is None:
        return []
    result = []
    for piece_aw in merge.inputs():
        if piece_aw is None:
            continue
        # piece_aw is the attribwrangle; its input(0) is the object_merge
        om = piece_aw.input(0)
        if om is None:
            continue
        p = om.parm("objpath1")
        if p is not None:
            path = p.eval()
            log(f"[get_asset_node_paths] found path from network: {path!r}")
            if path:
                result.append(path)
    log(f"[get_asset_node_paths] network fallback result: {result}")
    return result


def get_lookdev_asset_paths(paint_node):
    """Same list as get_asset_node_paths, plus the wire SOP (for ivy/crawl)
    so artists can assign a material to the wire mesh from the Lookdev window."""
    paths = list(get_asset_node_paths(paint_node))
    if paint_node is None:
        return paths
    wire = get_wire_sop(paint_node.parent())
    if wire is not None and wire.path() not in paths:
        paths.append(wire.path())
    return paths


def save_asset_node_paths(paint_node, paths, weights=None):
    """
    Store asset paths back into meta. Optionally also persists per-asset
    weights (drop probabilities) — pass None to leave existing weights
    untouched, or a list parallel to ``paths`` to overwrite.
    """
    raw = paint_node.userData(META_KEY) or "{}"
    try:
        meta = json.loads(raw)
    except Exception:
        meta = {}
    meta["assets"] = paths
    if weights is not None:
        meta["asset_weights"] = list(weights)
    paint_node.setUserData(META_KEY, json.dumps(meta))


def get_asset_weights(paint_node):
    """Retrieve the per-asset weight list stored in meta, or [] if absent."""
    meta = load_meta(paint_node)
    return meta.get("asset_weights", [])


# ---------------------------------------------------------------------------
# Camera Frustum Culling
# ---------------------------------------------------------------------------

_FRUSTUM_SNIPPET = (
    'if (!chi("enable")) return;\n'
    'string cam = chs("cam_path");\n'
    'if (cam == "") return;\n'
    'float pad = chf("fov_padding");\n'
    'vector ndc = toNDC(cam, @P);\n'
    '// Houdini camera looks down -Z: ndc.z < 0 = in front, >= 0 = behind\n'
    'if (ndc.z >= 0 || ndc.x < -pad || ndc.x > 1+pad ||\n'
    '    ndc.y < -pad || ndc.y > 1+pad)\n'
    '    removepoint(0, @ptnum);\n'
)


# ---------------------------------------------------------------------------
# Altitude mask (elevation-as-temperature)
# ---------------------------------------------------------------------------
# Multiplies @mask by an elevation-band falloff so biomes only grow inside
# their preferred altitude range (e.g. tundra near the peaks, rainforest in
# the valleys). Uses the surface's runtime bbox so terrain edits auto-update.
_ALTITUDE_SNIPPET = (
    'if (!chi("enable")) return;\n'
    'vector bbmin = getbbox_min(0);\n'
    'vector bbmax = getbbox_max(0);\n'
    'float yrange = max(bbmax.y - bbmin.y, 1e-6);\n'
    'float t = (@P.y - bbmin.y) / yrange;\n'
    'float emin = chf("elev_min");\n'
    'float emax = chf("elev_max");\n'
    'float fall = chf("falloff");\n'
    'float lo = smooth(emin - fall, emin, t);\n'
    'float hi = 1.0 - smooth(emax, emax + fall, t);\n'
    'float f = clamp(lo * hi, 0.0, 1.0);\n'
    '// Slope mask: 0=flat, 1=vertical cliff\n'
    'float slope = 1.0 - clamp(@N.y, 0.0, 1.0);\n'
    'float smax  = chf("slope_max");\n'
    'float sfall = chf("slope_falloff");\n'
    'float sf = 1.0 - smooth(smax, smax + sfall, slope);\n'
    '@mask *= f * sf;\n'
)

# Visualization branch — colorizes the surface using the combined elevation+slope
# band so the user can preview where the biome will and won't scatter.
_ALTITUDE_VIS_SNIPPET = (
    'vector bbmin = getbbox_min(0);\n'
    'vector bbmax = getbbox_max(0);\n'
    'float yrange = max(bbmax.y - bbmin.y, 1e-6);\n'
    'float t = (@P.y - bbmin.y) / yrange;\n'
    'float emin = chf("elev_min");\n'
    'float emax = chf("elev_max");\n'
    'float fall = chf("falloff");\n'
    'float lo = smooth(emin - fall, emin, t);\n'
    'float hi = 1.0 - smooth(emax, emax + fall, t);\n'
    'float f = clamp(lo * hi, 0.0, 1.0);\n'
    'float slope = 1.0 - clamp(@N.y, 0.0, 1.0);\n'
    'float smax  = chf("slope_max");\n'
    'float sfall = chf("slope_falloff");\n'
    'float sf = 1.0 - smooth(smax, smax + sfall, slope);\n'
    'float combined = f * sf;\n'
    '// dim red (excluded) → bright green (in-band)\n'
    '@Cd = lerp(set(0.55, 0.05, 0.05), set(0.20, 0.95, 0.25), combined);\n'
)


def ensure_altitude_mask_wrangle(geo_node):
    """Create / ensure the `altitude_mask` wrangle between mask_post_apply and
    scatter_logic. Disabled by default; biome apply turns it on."""
    if geo_node is None:
        return None
    scatter = geo_node.node("scatter_logic")
    post    = geo_node.node("mask_post_apply")
    if scatter is None:
        return None
    # Ensure mask chain (creates mask_post_apply if missing).
    if post is None:
        ensure_scatter_mask_noise(geo_node)
        post = geo_node.node("mask_post_apply")
        if post is None:
            return None

    alt = geo_node.node("altitude_mask")
    if alt is None:
        alt = geo_node.createNode("attribwrangle", "altitude_mask")
        alt.setParms({"class": 2})  # run over Points
        ptg = alt.parmTemplateGroup()
        ptg.append(hou.ToggleParmTemplate(
            "enable", "Enable Altitude Mask", default_value=0))
        ptg.append(hou.FloatParmTemplate(
            "elev_min", "Elevation Min", 1,
            default_value=(0.0,), min=0.0, max=1.0,
            min_is_strict=True, max_is_strict=True))
        ptg.append(hou.FloatParmTemplate(
            "elev_max", "Elevation Max", 1,
            default_value=(1.0,), min=0.0, max=1.0,
            min_is_strict=True, max_is_strict=True))
        ptg.append(hou.FloatParmTemplate(
            "falloff", "Falloff Width", 1,
            default_value=(0.10,), min=0.0, max=1.0,
            min_is_strict=True, max_is_strict=True))
        ptg.append(hou.FloatParmTemplate(
            "slope_max", "Max Slope", 1,
            default_value=(0.60,), min=0.0, max=1.0,
            min_is_strict=True, max_is_strict=True))
        ptg.append(hou.FloatParmTemplate(
            "slope_falloff", "Slope Falloff", 1,
            default_value=(0.10,), min=0.0, max=1.0,
            min_is_strict=True, max_is_strict=True))
        alt.setParmTemplateGroup(ptg)
    # Always refresh the snippet so fixes propagate to existing scenes.
    alt.setParms({"snippet": _ALTITUDE_SNIPPET})

    # Re-wire: post → altitude_mask → scatter_logic
    if alt.input(0) is None or alt.input(0).path() != post.path():
        alt.setInput(0, post)
    if scatter.input(0) is None or scatter.input(0).path() != alt.path():
        scatter.setInput(0, alt)
    return alt


def ensure_altitude_vis_branch(geo_node):
    """Create / ensure the altitude visualization branch:
        surface_merge → altitude_vis_color → OUT_altitude_vis (null)
    Display flag is off by default. Toggled via set_altitude_vis_visible."""
    if geo_node is None:
        return None
    surf_in = geo_node.node("surface_merge") or geo_node.node("surface_input")
    if surf_in is None:
        return None

    color = geo_node.node("altitude_vis_color")
    if color is None:
        color = geo_node.createNode("attribwrangle", "altitude_vis_color")
        # Run over Points so @Cd is set per point and shaded smoothly across primitives.
        color.setParms({"class": 2})
        ptg = color.parmTemplateGroup()
        ptg.append(hou.FloatParmTemplate(
            "elev_min", "Elevation Min", 1, default_value=(0.0,)))
        ptg.append(hou.FloatParmTemplate(
            "elev_max", "Elevation Max", 1, default_value=(1.0,)))
        ptg.append(hou.FloatParmTemplate(
            "falloff", "Falloff Width", 1, default_value=(0.10,)))
        ptg.append(hou.FloatParmTemplate(
            "slope_max", "Max Slope", 1, default_value=(0.60,)))
        ptg.append(hou.FloatParmTemplate(
            "slope_falloff", "Slope Falloff", 1, default_value=(0.10,)))
        color.setParmTemplateGroup(ptg)
        color.setInput(0, surf_in)
    color.setParms({"snippet": _ALTITUDE_VIS_SNIPPET})

    out = geo_node.node("OUT_altitude_vis")
    if out is None:
        out = geo_node.createNode("null", "OUT_altitude_vis")
        out.setInput(0, color)
        try:
            out.setDisplayFlag(False)
        except Exception:
            pass
    if out.input(0) is None or out.input(0).path() != color.path():
        out.setInput(0, color)
    return out


def set_altitude_mask_params(geo_node, enabled, elev_min, elev_max, falloff,
                             slope_max=0.60, slope_falloff=0.10):
    """Push UI values onto both the mask wrangle and the visualization wrangle."""
    if geo_node is None:
        return
    mask = ensure_altitude_mask_wrangle(geo_node)
    ensure_altitude_vis_branch(geo_node)
    color_node = geo_node.node("altitude_vis_color")
    if mask is not None:
        try:
            mask.parm("enable").set(1 if enabled else 0)
            mask.parm("elev_min").set(float(elev_min))
            mask.parm("elev_max").set(float(elev_max))
            mask.parm("falloff").set(float(falloff))
            mask.parm("slope_max").set(float(slope_max))
            mask.parm("slope_falloff").set(float(slope_falloff))
        except Exception as e:
            log(f"set_altitude_mask_params (mask): {e}")
    if color_node is not None:
        try:
            color_node.parm("elev_min").set(float(elev_min))
            color_node.parm("elev_max").set(float(elev_max))
            color_node.parm("falloff").set(float(falloff))
            color_node.parm("slope_max").set(float(slope_max))
            color_node.parm("slope_falloff").set(float(slope_falloff))
        except Exception as e:
            log(f"set_altitude_mask_params (vis): {e}")


def set_altitude_vis_visible(geo_node, on):
    """Toggle the OUT_altitude_vis display flag. When on, the colored heat-map
    appears in the viewport. When off, restore display to OUT_scatter so the
    user sees the scatter result instead of an empty viewport."""
    if geo_node is None:
        return
    out = geo_node.node("OUT_altitude_vis")
    if out is None:
        out = ensure_altitude_vis_branch(geo_node)
    if out is None:
        return
    try:
        if on:
            # Display the heatmap. Houdini auto-clears other nodes' display flags.
            out.setDisplayFlag(True)
        else:
            # Hide the heatmap and restore display on the main scatter output.
            out.setDisplayFlag(False)
            scatter_out = geo_node.node("OUT_scatter")
            if scatter_out is not None:
                scatter_out.setDisplayFlag(True)
    except Exception as e:
        log(f"set_altitude_vis_visible: {e}")


def measure_surface_bbox(surface_node):
    """Return ((xmin,ymin,zmin),(xmax,ymax,zmax)) in WORLD space, or None."""
    if surface_node is None:
        return None
    try:
        geo = surface_node.geometry()
        if geo is None or not geo.iterPoints():
            return None
        bb = geo.boundingBox()
        # Transform local bbox into world space via the SOP's parent OBJ.
        try:
            xform = surface_node.parent().worldTransform()
            bb = bb.transform(xform)
        except Exception:
            pass
        return ((bb.minvec().x(), bb.minvec().y(), bb.minvec().z()),
                (bb.maxvec().x(), bb.maxvec().y(), bb.maxvec().z()))
    except Exception as e:
        log(f"measure_surface_bbox: {e}")
        return None


def _rebuild_scatter_point_chain(geo_node):
    """Rebuild the full scatter-point filter chain in canonical order:
    scatter_logic → [cam_frustum_cull] → [proximity_filter]
                  → [placement_rule_0 … N] → [clump_wrangle] → pscale_wrangle
    """
    scatter   = geo_node.node("scatter_logic")
    pscale_wr = geo_node.node("pscale_wrangle")
    if scatter is None or pscale_wr is None:
        return

    prev = scatter

    cull = geo_node.node("cam_frustum_cull")
    if cull is not None:
        if cull.input(0) is None or cull.input(0).path() != prev.path():
            cull.setInput(0, prev)
        prev = cull

    prox = geo_node.node("proximity_filter")
    if prox is not None:
        if prox.input(0) is None or prox.input(0).path() != prev.path():
            prox.setInput(0, prev)
        prev = prox

    i = 0
    while True:
        rule = geo_node.node(f"placement_rule_{i}")
        if rule is None:
            break
        if rule.input(0) is None or rule.input(0).path() != prev.path():
            rule.setInput(0, prev)
        prev = rule
        i += 1

    clump = geo_node.node("clump_wrangle")
    if clump is not None:
        if clump.input(0) is None or clump.input(0).path() != prev.path():
            clump.setInput(0, prev)
        prev = clump

    if pscale_wr.input(0) is None or pscale_wr.input(0).path() != prev.path():
        pscale_wr.setInput(0, prev)


def ensure_clump_wrangle(geo_node):
    """Create/ensure clump_wrangle between cam_frustum_cull (or scatter_logic) and pscale_wrangle.

    Bypassed by default (clump_enabled = 0). Pulls scatter points toward their
    neighbours within a radius, creating natural species-clustering behaviour.
    """
    if geo_node is None:
        return None
    pscale_wr = geo_node.node("pscale_wrangle")
    if pscale_wr is None:
        return None

    clump = geo_node.node("clump_wrangle")
    if clump is None:
        clump = geo_node.createNode("attribwrangle", "clump_wrangle")
        clump.setParms({"class": 2})

        ptg = clump.parmTemplateGroup()
        ptg.append(hou.ToggleParmTemplate(
            "clump_enabled", "Enable Clumping", default_value=0))
        ptg.append(hou.FloatParmTemplate(
            "clump_radius", "Radius", 1, default_value=(2.0,),
            min=0.1, max=50.0, min_is_strict=False, max_is_strict=False))
        ptg.append(hou.FloatParmTemplate(
            "clump_strength", "Strength", 1, default_value=(0.7,),
            min=0.0, max=1.0, min_is_strict=True, max_is_strict=True))
        ptg.append(hou.IntParmTemplate(
            "clump_min_count", "Min Neighbors", 1, default_value=(2,),
            min=0, max=50))
        ptg.append(hou.IntParmTemplate(
            "clump_seed", "Seed", 1, default_value=(42,)))
        clump.setParmTemplateGroup(ptg)
        clump.setParms({"snippet": _CLUMP_VEX})

    _rebuild_scatter_point_chain(geo_node)
    return clump


def sync_clump_params(geo_node, state):
    """Push clumping state to clump_wrangle (creates node if missing)."""
    if geo_node is None:
        return
    clump = ensure_clump_wrangle(geo_node)
    if clump is None:
        return
    try:
        clump.setParms({
            "clump_enabled":   1 if state.get("clump_enabled", False) else 0,
            "clump_radius":    float(state.get("clump_radius",    2.0)),
            "clump_strength":  float(state.get("clump_strength",  0.7)),
            "clump_min_count": int(state.get("clump_min_count",   2)),
            "clump_seed":      int(state.get("clump_seed",        42)),
            "snippet":         _CLUMP_VEX,
        })
    except Exception as e:
        log(f"sync_clump_params: {e}")


def ensure_proximity_filter(geo_node):
    """Create/ensure proximity_filter wrangle between cam_frustum_cull and clump_wrangle.

    Deletes scatter points within prox_radius of any point in the exclusion
    geometry fed from proximity_objmerge (input 1 of the wrangle).
    Disabled by default (prox_enabled = 0).
    """
    if geo_node is None:
        return None
    pscale_wr = geo_node.node("pscale_wrangle")
    if pscale_wr is None:
        return None

    cull    = geo_node.node("cam_frustum_cull")
    scatter = geo_node.node("scatter_logic")
    upstream = cull if cull is not None else scatter
    if upstream is None:
        return None

    prox_merge = geo_node.node("proximity_objmerge")
    if prox_merge is None:
        prox_merge = geo_node.createNode("object_merge", "proximity_objmerge")
        prox_merge.setParms({"numobj": 1, "xformtype": 0})

    prox = geo_node.node("proximity_filter")
    if prox is None:
        prox = geo_node.createNode("attribwrangle", "proximity_filter")
        prox.setParms({"class": 2})
        ptg = prox.parmTemplateGroup()
        ptg.append(hou.ToggleParmTemplate(
            "prox_enabled", "Enable Proximity Exclusion", default_value=0))
        ptg.append(hou.FloatParmTemplate(
            "prox_radius", "Exclusion Radius", 1, default_value=(2.0,),
            min=0.01, max=500.0, min_is_strict=False, max_is_strict=False))
        prox.setParmTemplateGroup(ptg)
        prox.setParms({"snippet": _PROXIMITY_VEX})

    if prox.input(1) is None or prox.input(1).path() != prox_merge.path():
        prox.setInput(1, prox_merge)

    _rebuild_scatter_point_chain(geo_node)
    return prox


def sync_proximity_params(geo_node, state):
    """Push proximity exclusion state to proximity_filter (creates nodes if missing)."""
    if geo_node is None:
        return
    prox = ensure_proximity_filter(geo_node)
    if prox is None:
        return
    prox_merge = geo_node.node("proximity_objmerge")
    try:
        prox.setParms({
            "prox_enabled": 1 if state.get("prox_enabled", False) else 0,
            "prox_radius":  float(state.get("prox_radius", 2.0)),
            "snippet":      _PROXIMITY_VEX,
        })
        if prox_merge is not None:
            prox_merge.setParms({"objpath1": state.get("prox_sop_path", "")})
    except Exception as e:
        log(f"sync_proximity_params: {e}")


def sync_placement_rules(geo_node, rules):
    """Create/update/remove placement_rule_N wrangles and rebuild scatter chain.

    rules — list of dicts, each with keys:
        type (str): one of RULE_TYPES keys
        enabled (bool)
        + type-specific param keys (see RULE_DEFAULTS)
    """
    if geo_node is None:
        return

    for i, rule in enumerate(rules):
        rtype = rule.get("type", "slope")
        name  = f"placement_rule_{i}"
        node  = geo_node.node(name)

        if node is None:
            node = geo_node.createNode("attribwrangle", name)
            node.setParms({"class": 2})
            ptg = node.parmTemplateGroup()
            ptg.append(hou.ToggleParmTemplate("enabled", "Enabled", default_value=1))

            if rtype == "slope":
                ptg.append(hou.FloatParmTemplate("max_slope", "Max Slope (°)", 1,
                    default_value=(30.0,), min=0.0, max=90.0))
            elif rtype == "altitude":
                ptg.append(hou.FloatParmTemplate("min_alt", "Min Altitude", 1,
                    default_value=(0.0,)))
                ptg.append(hou.FloatParmTemplate("max_alt", "Max Altitude", 1,
                    default_value=(100.0,)))
            elif rtype == "noise":
                ptg.append(hou.FloatParmTemplate("frequency", "Frequency", 1,
                    default_value=(0.5,), min=0.0, max=10.0))
                ptg.append(hou.FloatParmTemplate("threshold", "Threshold", 1,
                    default_value=(0.4,), min=0.0, max=1.0))
                ptg.append(hou.IntParmTemplate("seed", "Seed", 1, default_value=(0,)))
            elif rtype == "dist_path":
                ptg.append(hou.FloatParmTemplate("min_dist", "Min Distance", 1,
                    default_value=(0.0,), min=0.0, max=1000.0))
                ptg.append(hou.FloatParmTemplate("max_dist", "Max Distance", 1,
                    default_value=(10.0,), min=0.0, max=1000.0))
                # input 1 = reference geometry objmerge
                ref_om = geo_node.node(f"{name}_ref")
                if ref_om is None:
                    ref_om = geo_node.createNode("object_merge", f"{name}_ref")
                    ref_om.setParms({"xformtype": 1, "numobj": 1})
                node.setInput(1, ref_om)

            node.setParmTemplateGroup(ptg)

        node.setParms({"snippet": _RULE_VEX.get(rtype, "")})
        try:
            node.parm("enabled").set(1 if rule.get("enabled", True) else 0)
            if rtype == "slope":
                node.parm("max_slope").set(float(rule.get("max_slope", 30.0)))
            elif rtype == "altitude":
                node.parm("min_alt").set(float(rule.get("min_alt", 0.0)))
                node.parm("max_alt").set(float(rule.get("max_alt", 100.0)))
            elif rtype == "noise":
                node.parm("frequency").set(float(rule.get("frequency", 0.5)))
                node.parm("threshold").set(float(rule.get("threshold", 0.4)))
                node.parm("seed").set(int(rule.get("seed", 0)))
            elif rtype == "dist_path":
                node.parm("min_dist").set(float(rule.get("min_dist", 0.0)))
                node.parm("max_dist").set(float(rule.get("max_dist", 10.0)))
                ref_om = geo_node.node(f"{name}_ref")
                if ref_om is not None:
                    ref_om.setParms({"objpath1": rule.get("sop_path", "")})
        except Exception as e:
            log(f"sync_placement_rules rule {i}: {e}")

    # Remove stale rule nodes beyond current count
    i = len(rules)
    while True:
        name = f"placement_rule_{i}"
        node = geo_node.node(name)
        ref  = geo_node.node(f"{name}_ref")
        if node is None and ref is None:
            break
        for n in (node, ref):
            if n is not None:
                try:
                    n.destroy()
                except Exception:
                    pass
        i += 1

    _rebuild_scatter_point_chain(geo_node)


_MANUAL_PY_CODE = """\
import json
geo  = hou.pwd().geometry()
node = hou.pwd()
positions = json.loads(node.userData("_mpos") or "[]")
pieces    = json.loads(node.userData("_mpc")  or "[]")
if positions:
    geo.addAttrib(hou.attribType.Point, "piece", 0)
    for i, pos in enumerate(positions):
        pt = geo.createPoint()
        pt.setPosition(hou.Vector3(float(pos[0]), float(pos[1]), float(pos[2])))
        pt.setAttribValue("piece", int(pieces[i]) if i < len(pieces) else 0)
"""

# Projects each manual point onto the nearest surface polygon AND copies the
# surface normal.  Uses xyzdist/primuv — NEVER deletes points.
# Also sets @pscale + @orient: manual_merge fills these from the regular
# scatter stream with 0/zero-quat otherwise, making copytopoints render
# zero-scale (invisible) assets at manual points.
_MANUAL_NORMAL_VEX = """\
if (npoints(1) > 0) {
    int   prim = -1;
    vector uvw;
    xyzdist(1, @P, prim, uvw, 1e10);
    if (prim >= 0) {
        @P = primuv(1, "P", prim, uvw);
        vector sn = primuv(1, "N", prim, uvw);
        if (length(sn) > 0.001) @N = normalize(sn);
    }
}
if (length(@N) < 0.001) @N = {0, 1, 0};
f@pscale = 1.0;
p@orient = quaternion(dihedral({0, 1, 0}, @N));
"""


def ensure_manual_scatter(geo_node):
    """Create the manual placement SOP chain and wire it into the instancer.

    Chain: manual_points (python) → manual_normal_wr → manual_piece_wr (passthrough)
    These merge into the instancer-1 chain via manual_merge after lod_wrangle.
    Uses nearpoint VEX to copy surface normals — never deletes points.
    """
    if geo_node is None:
        return None

    mp = geo_node.node("manual_points")
    # Replace stale add SOP from old versions
    if mp is not None and mp.type().name() != "python":
        mp.destroy()
        mp = None
    if mp is None:
        mp = geo_node.createNode("python", "manual_points")
        mp.setUserData("_mpos", "[]")
        mp.setUserData("_mpc",  "[]")
    mp.setParms({"python": _MANUAL_PY_CODE})

    surf = geo_node.node("surface_merge") or geo_node.node("surface_input")

    # Remove old ray SOP if present (replaced by the nearpoint wrangle below)
    old_ray = geo_node.node("manual_ray")
    if old_ray is not None:
        try:
            old_ray.destroy()
        except Exception:
            pass

    nr = geo_node.node("manual_normal_wr")
    if nr is None:
        nr = geo_node.createNode("attribwrangle", "manual_normal_wr")
        nr.setParms({"class": 2})
    nr.setParms({"snippet": _MANUAL_NORMAL_VEX})
    nr.setInput(0, mp)
    if surf is not None:
        nr.setInput(1, surf)

    pw = geo_node.node("manual_piece_wr")
    if pw is None:
        pw = geo_node.createNode("attribwrangle", "manual_piece_wr")
        pw.setParms({"class": 2, "snippet": "// passthrough"})
    pw.setInput(0, nr)

    mm = geo_node.node("manual_merge")
    if mm is None:
        mm = geo_node.createNode("merge", "manual_merge")

    _rebuild_instancer1_chain(geo_node)
    return mp


def add_manual_point(geo_node, pos, piece_idx):
    """Append one manually placed point to the scatter network."""
    mp = ensure_manual_scatter(geo_node)
    if mp is None:
        return
    import json
    positions = json.loads(mp.userData("_mpos") or "[]")
    pieces    = json.loads(mp.userData("_mpc")  or "[]")
    positions.append([float(pos[0]), float(pos[1]), float(pos[2])])
    pieces.append(int(piece_idx))
    mp.setUserData("_mpos", json.dumps(positions))
    mp.setUserData("_mpc",  json.dumps(pieces))
    try:
        mp.cook(force=True)
    except Exception:
        pass


def _refresh_manual_piece_snippet(geo_node):
    # No longer needed — Python SOP handles piece assignment directly.
    pass


def set_manual_point_piece(geo_node, pt_idx, piece_idx):
    """Change the assigned asset for an existing manual point."""
    import json
    mp = geo_node.node("manual_points")
    if mp is None or mp.type().name() != "python":
        return
    pieces = json.loads(mp.userData("_mpc") or "[]")
    if pt_idx < len(pieces):
        pieces[pt_idx] = int(piece_idx)
        mp.setUserData("_mpc", json.dumps(pieces))
        try:
            mp.cook(force=True)
        except Exception:
            pass


def clear_manual_points(geo_node):
    """Remove all manually placed points."""
    import json
    mp = geo_node.node("manual_points")
    if mp is not None and mp.type().name() == "python":
        mp.setUserData("_mpos", "[]")
        mp.setUserData("_mpc",  "[]")
        try:
            mp.cook(force=True)
        except Exception:
            pass


def ensure_flip_wrangle(geo_node):
    """Bypass flip_wrangle if present in an existing network; wire orient_rand → add_keep directly."""
    if geo_node is None:
        return None
    orient_rand = geo_node.node("attribrandomize_orient")
    add_keep    = geo_node.node("add_keep")
    if orient_rand is None or add_keep is None:
        return None

    flip = geo_node.node("flip_wrangle")
    if flip is not None:
        flip.bypass(True)
    else:
        if add_keep.input(0) is None or add_keep.input(0).path() != orient_rand.path():
            add_keep.setInput(0, orient_rand)
    return flip


def _rebuild_instancer1_chain(geo_node):
    """Rebuild the chain feeding instancer input 1.

    Order: piece_attr → [weight_filter] → [color_wrangle] → [lod_wrangle]
                      → [manual_merge (merges in manual_piece_wr)] → instancer(1)
    Only wires nodes that already exist; does not create any new nodes.
    """
    piece_attr = geo_node.node("piece_attr")
    instancer  = geo_node.node("instancer")
    if piece_attr is None or instancer is None:
        return
    chain = [piece_attr]
    for name in ("weight_filter", "color_wrangle", "lod_wrangle"):
        n = geo_node.node(name)
        if n is not None:
            chain.append(n)
    for i in range(1, len(chain)):
        if chain[i].input(0) is None or chain[i].input(0).path() != chain[i - 1].path():
            chain[i].setInput(0, chain[i - 1])
    last = chain[-1]

    # manual_merge sits after lod_wrangle — merges manual_piece_wr (input 1) into chain
    mm = geo_node.node("manual_merge")
    pw = geo_node.node("manual_piece_wr")
    if mm is not None and pw is not None:
        if mm.input(0) is None or mm.input(0).path() != last.path():
            mm.setInput(0, last)
        if mm.input(1) is None or mm.input(1).path() != pw.path():
            mm.setInput(1, pw)
        last = mm

    if instancer.input(1) is None or instancer.input(1).path() != last.path():
        instancer.setInput(1, last)


def ensure_color_wrangle(geo_node):
    """Create/ensure color_wrangle between piece_attr and instancer (input 1).

    Must sit after piece_attr so prototype Cd attributes can't overwrite the
    per-instance variation we write.  Bypassed by default (color_enabled = 0).
    """
    if geo_node is None:
        return None
    piece_attr = geo_node.node("piece_attr")
    instancer  = geo_node.node("instancer")
    if piece_attr is None or instancer is None:
        return None

    color_wr = geo_node.node("color_wrangle")
    if color_wr is None:
        color_wr = geo_node.createNode("attribwrangle", "color_wrangle")
        color_wr.setParms({"class": 2})

        ptg = color_wr.parmTemplateGroup()
        ptg.append(hou.ToggleParmTemplate(
            "color_enabled", "Enable Color Variation", default_value=0))
        ptg.append(hou.FloatParmTemplate(
            "color_a", "Color A", 3,
            default_value=(0.22, 0.45, 0.10),
            look=hou.parmLook.ColorSquare,
            naming_scheme=hou.parmNamingScheme.RGBA))
        ptg.append(hou.FloatParmTemplate(
            "color_b", "Color B", 3,
            default_value=(0.38, 0.65, 0.18),
            look=hou.parmLook.ColorSquare,
            naming_scheme=hou.parmNamingScheme.RGBA))
        ptg.append(hou.IntParmTemplate(
            "color_seed", "Seed", 1, default_value=(0,)))
        color_wr.setParmTemplateGroup(ptg)
        color_wr.setParms({"snippet": _COLOR_VEX})

    # Fix legacy wiring: old versions inserted color_wrangle between pscale_wrangle
    # and geo_offset. Detect that and restore geo_offset's direct pscale_wr input.
    pscale_wr = geo_node.node("pscale_wrangle")
    geo_off   = geo_node.node("geo_offset")
    if (pscale_wr is not None and geo_off is not None
            and color_wr.input(0) is not None
            and color_wr.input(0).path() == pscale_wr.path()):
        geo_off.setInput(0, pscale_wr)

    _rebuild_instancer1_chain(geo_node)
    return color_wr


def sync_color_params(geo_node, state):
    """Push color-variation state to color_wrangle (creates node if missing)."""
    if geo_node is None:
        return
    color_wr = ensure_color_wrangle(geo_node)
    if color_wr is None:
        return
    col_a = state.get("color_variation_a", COLOR_VARIATION_DEFAULTS["color_variation_a"])
    col_b = state.get("color_variation_b", COLOR_VARIATION_DEFAULTS["color_variation_b"])
    try:
        color_wr.setParms({
            "color_enabled": 1 if state.get("color_variation_enabled", True) else 0,
            "color_seed":    int(state.get("color_variation_seed", 0)),
            "snippet":       _COLOR_VEX,
        })
        color_wr.parmTuple("color_a").set(tuple(col_a[:3]))
        color_wr.parmTuple("color_b").set(tuple(col_b[:3]))
    except Exception as e:
        log(f"sync_color_params: {e}")


def ensure_lod_wrangle(geo_node):
    """Create/ensure lod_wrangle after color_wrangle (last node before instancer input 1).

    Reads camera distance per scatter point.  Remaps i@piece to select a LOD
    variant prototype, or removes the point when beyond cull_dist.
    """
    if geo_node is None:
        return None
    instancer  = geo_node.node("instancer")
    piece_attr = geo_node.node("piece_attr")
    if instancer is None or piece_attr is None:
        return None

    lod = geo_node.node("lod_wrangle")
    if lod is None:
        lod = geo_node.createNode("attribwrangle", "lod_wrangle")
        lod.setParms({"class": 2})
        ptg = lod.parmTemplateGroup()
        ptg.append(hou.ToggleParmTemplate(
            "lod_enabled", "Enable LOD", default_value=0))
        ptg.append(hou.StringParmTemplate(
            "cam_path", "Camera", 1,
            string_type=hou.stringParmType.NodeReference))
        ptg.append(hou.IntParmTemplate(
            "asset_count", "Asset Count", 1, default_value=(1,)))
        ptg.append(hou.FloatParmTemplate(
            "lod1_dist", "LOD 1 Distance", 1, default_value=(20.0,),
            min=0.0, max=9999.0, min_is_strict=False, max_is_strict=False))
        ptg.append(hou.FloatParmTemplate(
            "lod2_dist", "LOD 2 Distance", 1, default_value=(50.0,),
            min=0.0, max=9999.0, min_is_strict=False, max_is_strict=False))
        ptg.append(hou.FloatParmTemplate(
            "cull_dist", "Cull Distance", 1, default_value=(100.0,),
            min=0.0, max=9999.0, min_is_strict=False, max_is_strict=False))
        lod.setParmTemplateGroup(ptg)
        lod.setParms({"snippet": _LOD_VEX})

    _rebuild_instancer1_chain(geo_node)
    return lod


def ensure_lod_assets(geo_node):
    """Create/update LOD1 and LOD2 prototype nodes in lod_assets_merge.

    Base assets stay in assets_merge (piece indices 0..N-1) so attribfrompieces
    only distributes base pieces.  LOD1 variants (N..2N-1) and LOD2 variants
    (2N..3N-1) live in lod_assets_merge alongside assets_merge at slot 0.
    Returns N (base asset count).
    """
    assets_merge = geo_node.node("assets_merge")
    if assets_merge is None:
        return 0
    merge = geo_node.node("lod_assets_merge")
    if merge is None:
        merge = geo_node.createNode("merge", "lod_assets_merge")
        merge.setInput(0, assets_merge)
        instancer = geo_node.node("instancer")
        if instancer is not None and (
            instancer.input(0) is None or instancer.input(0).path() != merge.path()
        ):
            instancer.setInput(0, merge)
    # Discover base assets in order
    base_pieces = []
    i = 0
    while True:
        aw = geo_node.node(f"asset_{i}_piece")
        if aw is None:
            break
        base_pieces.append((i, aw))
        i += 1
    n = len(base_pieces)
    if n == 0:
        return 0

    # Remove stale LOD inputs that the old architecture wired into assets_merge.
    # Only base assets (slots 0..n-1) should live there so attribfrompieces
    # distributes only piece indices 0..n-1 to scatter points.
    if assets_merge is not None:
        for slot in range(n, len(assets_merge.inputs())):
            if assets_merge.input(slot) is not None:
                assets_merge.setInput(slot, None)

    for idx, piece_aw in base_pieces:
        base_om = piece_aw.input(0)
        if base_om is None:
            continue
        base_path = base_om.parm("objpath1").eval() if base_om.parm("objpath1") else ""
        for level, suffix, piece_offset in (
            (1, "lod1", n),
            (2, "lod2", 2 * n),
        ):
            p_parm  = base_om.parm(f"lod{level}_path")
            lod_path = p_parm.eval() if p_parm else ""
            eff_path = lod_path if lod_path else base_path  # fallback

            om_name = f"asset_{idx}_{suffix}"
            aw_name = f"asset_{idx}_{suffix}_piece"

            lod_om = geo_node.node(om_name)
            if lod_om is None:
                lod_om = geo_node.createNode("object_merge", om_name)
                lod_om.setParms({"xformtype": 1})
            lod_om.setParms({"objpath1": eff_path, "numobj": 1})

            lod_aw = geo_node.node(aw_name)
            if lod_aw is None:
                lod_aw = geo_node.createNode("attribwrangle", aw_name)
                lod_aw.setParms({"class": 1})
            lod_aw.setInput(0, lod_om)
            lod_aw.setParms({"snippet": f"i@piece = {piece_offset + idx};"})

            merge.setInput(piece_offset + idx, lod_aw)

    return n


def _remove_lod_assets(geo_node):
    """Destroy LOD variant nodes (lod1 + lod2) and disconnect them from lod_assets_merge."""
    for suffix in ("lod1", "lod2"):
        i = 0
        while True:
            aw = geo_node.node(f"asset_{i}_{suffix}_piece")
            om = geo_node.node(f"asset_{i}_{suffix}")
            if aw is None and om is None:
                break
            for node in (aw, om):
                if node is not None:
                    try:
                        node.destroy()
                    except Exception:
                        pass
            i += 1


def sync_lod_params(geo_node, state):
    """Push LOD state: create/update LOD asset nodes and lod_wrangle parameters."""
    if geo_node is None:
        return
    lod = ensure_lod_wrangle(geo_node)
    if lod is None:
        return

    enabled     = state.get("lod_enabled", False)
    lod1_map    = state.get("lod1_path_map", {})
    lod2_map    = state.get("lod2_path_map", {})

    # Apply LOD paths to base asset nodes
    i = 0
    while True:
        om = geo_node.node(f"asset_{i}")
        if om is None:
            break
        base_path = om.parm("objpath1").eval() if om.parm("objpath1") else ""
        try:
            p1 = om.parm("lod1_path")
            p2 = om.parm("lod2_path")
            if p1:
                p1.set(lod1_map.get(base_path, ""))
            if p2:
                p2.set(lod2_map.get(base_path, ""))
        except Exception as _e:
            log(f"sync_lod_params set spare parm: {_e}")
        i += 1

    if enabled:
        n = ensure_lod_assets(geo_node)
    else:
        _remove_lod_assets(geo_node)
        n = i  # base asset count (still valid for param)

    try:
        lod.setParms({
            "lod_enabled": 1 if enabled else 0,
            "cam_path":    state.get("lod_cam_path", ""),
            "asset_count": n,
            "lod1_dist":   float(state.get("lod1_dist", 20.0)),
            "lod2_dist":   float(state.get("lod2_dist", 50.0)),
            "cull_dist":   float(state.get("lod_cull_dist", 100.0)),
            "snippet":     _LOD_VEX,
        })
    except Exception as e:
        log(f"sync_lod_params: {e}")


def ensure_camera_frustum_wrangle(geo_node):
    """Create/ensure cam_frustum_cull wrangle between scatter_logic and pscale_wrangle.

    Disabled by default. When enabled, removes scatter points that fall outside
    the selected camera's view frustum. FOV padding expands the visible region.
    """
    if geo_node is None:
        return None
    scatter   = geo_node.node("scatter_logic")
    pscale_wr = geo_node.node("pscale_wrangle")
    if scatter is None or pscale_wr is None:
        return None

    cull = geo_node.node("cam_frustum_cull")
    if cull is None:
        cull = geo_node.createNode("attribwrangle", "cam_frustum_cull")
        cull.setParms({"class": 2})  # run over Points

        ptg = cull.parmTemplateGroup()
        ptg.append(hou.ToggleParmTemplate(
            "enable", "Enable Frustum Cull", default_value=0))
        ptg.append(hou.StringParmTemplate(
            "cam_path", "Camera", 1,
            string_type=hou.stringParmType.NodeReference))
        ptg.append(hou.FloatParmTemplate(
            "fov_padding", "FOV Padding", 1,
            default_value=(0.0,),
            min=0.0, max=1.0,
            min_is_strict=False, max_is_strict=False))
        cull.setParmTemplateGroup(ptg)
        cull.setParms({"snippet": _FRUSTUM_SNIPPET})

    _rebuild_scatter_point_chain(geo_node)
    return cull


def sync_camera_frustum(geo_node, enabled, camera_path, fov_padding):
    """Update cam_frustum_cull wrangle parameters (creates node if missing)."""
    if geo_node is None:
        return
    cull = ensure_camera_frustum_wrangle(geo_node)
    if cull is None:
        return
    try:
        # Always refresh snippet so fixes propagate to existing scenes
        cull.setParms({"snippet": _FRUSTUM_SNIPPET})
        cull.parm("enable").set(1 if enabled else 0)
        cull.parm("cam_path").set(camera_path or "")
        cull.parm("fov_padding").set(float(fov_padding))
    except Exception as e:
        log(f"sync_camera_frustum: {e}")


# ---------------------------------------------------------------------------
# Icon helper
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ivy generator network
# ---------------------------------------------------------------------------

IVY_CURVE_CODE = '''
import hou, math, random

node = hou.pwd()
geo  = node.geometry()

# ── helpers ──────────────────────────────────────────────────────────────────
def parm(name, default):
    p = node.parm(name)
    return p.eval() if p else default

def lerp(a, b, t):
    return a + (b - a) * t

def v_add(a, b):
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])

def v_scale(v, s):
    return (v[0]*s, v[1]*s, v[2]*s)

def v_normalize(v):
    l = math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
    if l < 1e-8:
        return (0.0, -1.0, 0.0)
    return (v[0]/l, v[1]/l, v[2]/l)

def v_lerp(a, b, t):
    return (lerp(a[0],b[0],t), lerp(a[1],b[1],t), lerp(a[2],b[2],t))

# ── parameters ───────────────────────────────────────────────────────────────
seed             = int(parm("ivy_seed",            2789))
strand_length    = parm("ivy_strand_length",       9.182)
step_size        = parm("ivy_step_size",           0.888)
gravity_str      = parm("ivy_gravity",             0.0)
droop_bias       = parm("ivy_droop_bias",          0.4)
curl_amount      = parm("ivy_curl",                0.0)
randomness       = parm("ivy_randomness",          0.0)
mask_threshold   = parm("ivy_mask_threshold",      0.504)
inertia          = parm("ivy_inertia",             0.0)   # how quickly gravity takes over (0=instant, 1=never)
max_strands      = int(parm("ivy_max_strands",     333))
jitter_scale     = parm("ivy_jitter_scale",        0.0)   # world-space offset applied to each strand root
jitter_seed      = int(parm("ivy_jitter_seed",     0))

# ── read painted mask points from input 0 (paint_mask SOP) ──────────────────
input_geo = node.inputGeometry(0)
if input_geo is None:
    raise RuntimeError("[Ivy] No input geometry — wire scatter_logic into ivy_curve_gen input 0.")

# Collect candidate root points where mask > threshold
mask_attrib = input_geo.findPointAttrib("mask")
norm_attrib  = input_geo.findPointAttrib("N")

roots = []   # list of (pos_tuple, normal_tuple)
for pt in input_geo.points():
    mask_val = pt.attribValue(mask_attrib) if mask_attrib else 1.0
    if mask_val < mask_threshold:
        continue
    pos = tuple(pt.position())
    if norm_attrib:
        n = tuple(pt.attribValue(norm_attrib))
        n = v_normalize(n)
    else:
        n = (0.0, 1.0, 0.0)   # fallback: world up
    roots.append((pos, n, mask_val))

if not roots:
    print("[Ivy] No painted points above threshold — paint the surface first.")

# Subsample if we have more roots than max_strands (deterministic, seed-driven)
rng_global = random.Random(seed)
if len(roots) > max_strands:
    roots = rng_global.sample(roots, max_strands)

# World-space gravity vector (always straight down)
GRAVITY = (0.0, -1.0, 0.0)

num_steps = max(2, int(strand_length / max(step_size, 0.001)))
strands_built = 0

for idx, (root_pos, surface_normal, mask_weight) in enumerate(roots):
    rng = random.Random(seed + idx * 1337)
    rng_jitter = random.Random(jitter_seed + idx * 7919)

    # Point jitter: displace the strand root in a random direction on the
    # tangent plane so roots spread out without lifting off the surface.
    if jitter_scale > 1e-6:
        jx = rng_jitter.uniform(-jitter_scale, jitter_scale)
        jy = rng_jitter.uniform(-jitter_scale, jitter_scale)
        jz = rng_jitter.uniform(-jitter_scale, jitter_scale)
        root_pos = (root_pos[0] + jx, root_pos[1] + jy, root_pos[2] + jz)

    # Initial grow direction: along the surface normal, away from the surface.
    # A small random tangential nudge breaks symmetry so strands fan out.
    # Pick two arbitrary tangent vectors from the normal.
    nx, ny, nz = surface_normal
    if abs(nx) < 0.9:
        tx = v_normalize((0.0,  nz, -ny))
    else:
        tx = v_normalize((nz,  0.0, -nx))
    tz = (ny*tx[2]-nz*tx[1], nz*tx[0]-nx*tx[2], nx*tx[1]-ny*tx[0])  # cross(n, tx)

    nudge_x = rng.uniform(-0.25, 0.25)
    nudge_z = rng.uniform(-0.25, 0.25)
    start_dir = v_normalize(v_add(
        surface_normal,
        v_add(v_scale(tx, nudge_x), v_scale(tz, nudge_z))
    ))

    pos       = list(root_pos)
    direction = list(start_dir)
    points    = [tuple(pos)]

    for step in range(num_steps):
        t = step / max(num_steps - 1, 1)   # 0..1 along strand

        # Gravity contribution: grows stronger toward the tip (droop_bias)
        grav_strength = gravity_str * (1.0 + droop_bias * t)
        grav_v = v_scale(GRAVITY, grav_strength)

        # Random lateral perturbation (small, in tangent space)
        rand_v = (
            rng.uniform(-randomness, randomness),
            rng.uniform(-randomness * 0.1, randomness * 0.1),
            rng.uniform(-randomness, randomness),
        )

        # Sinusoidal curl along the strand
        phase_x = rng.uniform(0.0, math.pi)
        phase_z = rng.uniform(0.0, math.pi)
        curl_v  = (
            math.sin(t * math.pi * 4.0 + phase_x) * curl_amount,
            0.0,
            math.cos(t * math.pi * 3.0 + phase_z) * curl_amount * 0.5,
        )

        # Blend all forces into a new candidate direction
        new_dir = tuple(direction)
        new_dir = v_add(new_dir, v_scale(grav_v,  step_size))
        new_dir = v_add(new_dir, v_scale(rand_v,  step_size))
        new_dir = v_add(new_dir, v_scale(curl_v,  step_size))
        new_dir = list(v_normalize(new_dir))

        # Inertia: smoothly blend toward the new direction (higher = straighter start)
        blend = lerp(0.35, 0.05, inertia)   # low inertia = snappy, high = smooth
        direction = list(v_normalize(v_lerp(tuple(direction), tuple(new_dir), blend)))

        # Advance position
        pos = [pos[k] + direction[k] * step_size for k in range(3)]
        points.append(tuple(pos))

    if len(points) < 2:
        continue

    # Write the open polygon curve into the output geo
    poly = geo.createPolygon(is_closed=False)
    for pt_pos in points:
        pt = geo.createPoint()
        pt.setPosition(hou.Vector3(*pt_pos))
        poly.addVertex(pt)
    strands_built += 1

print(f"[Ivy Curve Gen] Grew {strands_built} strand(s) from {len(roots)} masked point(s).")
'''

IVY_WRANGLE_CODE = """\
// Per-strand colour (green palette) and width, driven by primitive number
float t = rand(@primnum * 0.71 + 0.3);
@Cd    = set(lerp(0.08, 0.22, t), lerp(0.35, 0.65, t), lerp(0.04, 0.12, t));
@width = fit01(rand(@primnum + 0.5), 0.006, 0.014);
"""

IVY_PARM_SPECS = [
    # (name,                label,               default,  min,   max,   is_int)
    ("ivy_seed",            "Random Seed",        937,      0,     9999,  True),
    ("ivy_max_strands",     "Max Strands",        100,      1,     2000,  True),
    ("ivy_mask_threshold",  "Mask Threshold",     0.372,    0.0,   1.0,   False),
    ("ivy_strand_length",   "Strand Length",      5.000,    0.1,   100.0,   False),
    ("ivy_step_size",       "Step Size",          1.000,    0.01,  10.0,  False),
    ("ivy_gravity",         "Gravity Strength",   0.300,    0.0,   2.0,   False),
    ("ivy_droop_bias",      "Droop Bias",         0.500,    0.0,   3.0,   False),
    ("ivy_inertia",         "Inertia",            0.0,      0.0,   1.0,   False),
    ("ivy_curl",            "Curl Amount",        0.150,    0.0,   2.0,   False),
    ("ivy_randomness",      "Randomness",         0.100,    0.0,   1.0,   False),
    # Point jitter applied to strand root positions
    ("ivy_jitter_scale",    "Jitter Scale",       0.0,      0.0,   2.0,   False),
    ("ivy_jitter_seed",     "Jitter Seed",        0,        0,     9999,  True),
    # Wire (tube) appearance — pushed to ivy_wire SOP
    ("ivy_wire_radius",     "Wire Radius",        0.008,    0.001, 0.2,   False),
    ("ivy_wire_segs",       "Wire Segments",      5,        3,     24,    True),
    ("ivy_wire_divisions",  "Wire Divisions",     8,        3,     32,    True),
]


def create_ivy_network(geo_node):
    """
    Builds the ivy SOP chain inside an existing scatter geo node.

    Topology changes made to the existing scatter network:
      - scatter_logic is bypassed (disabled)
      - ivy_curve_gen input 0 → scatter_logic   (grows strands from scatter pts)
      - ivy_blast input 0 → ivy_curve_gen       (strips "mesh" group downstream)
      - pscale_wrangle rewired → ivy_blast       (branch feeds copy-to-points)
      - ivy_attr_randomise → ivy_blast output
      - ivy_wire merged with instancer via ivy_scatter_merge
      - OUT_scatter rewired → ivy_scatter_merge

    Nodes are prefixed with 'ivy_' to avoid collisions.
    Returns the ivy_curve_gen Python SOP.
    """
    scatter_logic = geo_node.node("scatter_logic")
    if scatter_logic is None:
        raise RuntimeError(
            "No 'scatter_logic' node found in this geo node. "
            "Create a scatter network first."
        )

    instancer = geo_node.node("instancer")
    out       = geo_node.node("OUT_wires") or geo_node.node("OUT_scatter")

    # ── Bypass scatter_logic — only runs when Create Ivy Network is clicked ──
    scatter_logic.bypass(True)

    # ── ivy_curve_gen: input 0 → scatter_logic ───────────────────────────────
    py_sop = geo_node.createNode("python", "ivy_curve_gen")
    py_sop.setInput(0, scatter_logic)

    # Add spare parameters BEFORE setting the Python code so the parms
    # already exist when the SOP cooks for the first time.
    _add_ivy_spare_parms(py_sop)
    py_sop.setParms({"python": IVY_CURVE_CODE})

    # ── ivy_sim_length_scale — scale each strand length randomly ─────────────
    # Placed between ivy_curve_gen and ivy_blast so length filtering happens
    # before the mesh group is blasted away and before the copy-to-points branch.
    length_scale = geo_node.createNode("attribwrangle", "ivy_sim_length_scale")
    length_scale.setParms({"class": 1, "snippet": _IVY_SIM_LENGTH_SCALE_CODE})
    length_scale.setInput(0, py_sop)
    for pname, label, default in (
        ("min_length", "Min Length", 0.100),
        ("max_length", "Max Length", 1.000),
    ):
        try:
            ptg = length_scale.parmTemplateGroup()
            if ptg.find(pname) is None:
                pt = hou.FloatParmTemplate(pname, label, 1, default_value=(default,))
                ptg.append(pt)
                length_scale.setParmTemplateGroup(ptg)
            p = length_scale.parm(pname)
            if p is not None:
                p.set(default)
        except Exception as e:
            log(f"ivy_sim_length_scale init {pname}: {e}")

    # ── ivy_blast: input 0 → ivy_sim_length_scale ────────────────────────────
    blast = geo_node.createNode("blast", "ivy_blast")
    blast.setParms({"group": "mesh", "negate": 0})  # negate=0: delete the named group
    blast.setInput(0, length_scale)

    # ── Rewire pscale_wrangle → fed from ivy_blast (branch to copy-to-points) ─
    pscale_wr = geo_node.node("pscale_wrangle")
    if pscale_wr is not None:
        pscale_wr.setInput(0, blast)

    # ── orient_wrangle — replace attribrandomize_orient with VEX random rotation ─
    orient_curve = geo_node.node("orientalongcurve1")
    add_keep     = geo_node.node("add_keep")

    orient_rand = geo_node.node("attribrandomize_orient")
    if orient_rand is not None:
        orient_rand.destroy()

    orient_wr = geo_node.createNode("attribwrangle", "orient_wrangle")
    orient_wr.setParms({"class": 2, "snippet": _ORIENT_WRANGLE_CODE})
    _add_orient_wrangle_spare_parms(orient_wr)
    if orient_curve is not None:
        orient_wr.setInput(0, orient_curve)

    # ── ivy_pscale_ramp — scale @pscale along curve length (root→tip) ─────────
    ramp_node = geo_node.createNode("attribwrangle", "ivy_pscale_ramp")
    ramp_node.setParms({"class": 2, "snippet": _IVY_PSCALE_RAMP_CODE})
    _add_pscale_ramp_spare_parm(ramp_node)
    ramp_node.setInput(0, orient_wr)
    if add_keep is not None:
        add_keep.setInput(0, ramp_node)

    # ── ivy_attr_randomise connected directly to blast output ─────────────────
    wrangle = geo_node.createNode("attribwrangle", "ivy_attr_randomise")
    wrangle.setInput(0, blast)
    wrangle.setParms({"class": 1, "snippet": IVY_WRANGLE_CODE})

    # ── Resample — smooth curves to uniform segment length ───────────────────
    resample = geo_node.createNode("resample", "ivy_resample")
    resample.setInput(0, wrangle)
    resample.setParms({"dolength": 1, "length": 0.200})

    # ── Attribute Noise — displaces the P attribute of the resampled curves ──
    # attribtype = "P" per spec; attribs="P" targets the position attribute
    noise = geo_node.createNode("attribnoise", "ivy_attribnoise")
    for pname, val in (
        ("attribtype", "P"),
        ("attribs", "P"),
        ("attribname", "P"),
        ("amplitudev", 0.0),
        ("elementsize", 0.0),
        ("rough", 0.0),
        ("lac", 0),
    ):
        p = noise.parm(pname)
        if p is not None:
            try:
                p.set(val)
            except Exception as e:
                log(f"ivy_attribnoise init parm {pname}: {e}")
    noise.setInput(0, resample)

    # ── PolyWire — convert curves to tube geometry ───────────────────────────
    # NOTE: using 'polywire' (not 'wire'/Wireframe) because we need Segments
    # and Divisions controls. The Wireframe SOP only exposes Radius.
    wire = geo_node.createNode("polywire", "ivy_wire")
    for pname, val in (("radius", 0.008), ("segs", 5), ("div", 8)):
        p = wire.parm(pname)
        if p is not None:
            try:
                p.set(val)
            except Exception as e:
                log(f"ivy_wire init parm {pname}: {e}")
    wire.setInput(0, noise)

    # ── ivy_uv_normalize — remap polywire u from arc-length to 0-1 ───────────
    # Polywire sets u = arc_length / circumference (≈ 20 for a 1 m wire at the
    # default 0.008 radius), causing heavy texture tiling in Karma and Arnold.
    uv_norm = geo_node.node("ivy_uv_normalize")
    if uv_norm is None:
        uv_norm = geo_node.createNode("attribwrangle", "ivy_uv_normalize")
    for pname, val in (("class", 3), ("snippet",
        'float mx=0.0;\n'
        'for(int i=0;i<@numvtx;i++){\n'
        '    vector uv_i=vertex(0,"uv",i);\n'
        '    if(uv_i.x>mx) mx=uv_i.x;\n'
        '}\n'
        'if(mx>0.001) @uv.x=@uv.x/mx;\n'
    )):
        p = uv_norm.parm(pname)
        if p is not None:
            try:
                p.set(val)
            except Exception as e:
                log(f"ivy_uv_normalize parm {pname}: {e}")
    uv_norm.setInput(0, wire)

    # ── leaves_grp — group node wrapping instancer output ────────────────────
    leaves_grp = geo_node.node("leaves_grp")
    if leaves_grp is None:
        leaves_grp = geo_node.createNode("groupcreate", "leaves_grp")
        p = leaves_grp.parm("groupname")
        if p is not None:
            p.set("leaves_grp")
    if instancer is not None:
        leaves_grp.setInput(0, instancer)

    # ── trunk_grp — group node wrapping ivy_wire output ──────────────────────
    trunk_grp = geo_node.node("trunk_grp")
    if trunk_grp is None:
        trunk_grp = geo_node.createNode("groupcreate", "trunk_grp")
        p = trunk_grp.parm("groupname")
        if p is not None:
            p.set("trunk_grp")
    trunk_grp.setInput(0, uv_norm)

    # ── Rename nodes for Ivy Scatter UI clarity ─────────────────────────────
    # Rename scatter_filecache → scatter_leaves
    scatter_cache = geo_node.node("scatter_filecache")
    if scatter_cache is not None:
        scatter_cache.setName("scatter_leaves")
    else:
        scatter_cache = geo_node.node("scatter_leaves")

    # ── scatter_leaves ← leaves_grp (caches leaves separately) ───────────────
    if scatter_cache is not None and leaves_grp is not None:
        scatter_cache.setInput(0, leaves_grp)
        for pname, val in (("loadfromdisk", 0), ("trange", 0), ("timedependent", 0)):
            p = scatter_cache.parm(pname)
            if p is not None:
                try:
                    p.set(val)
                except Exception:
                    pass

    # Rename OUT_scatter → OUT_wires
    if out is not None and out.name() == "OUT_scatter":
        out.setName("OUT_wires")
    
    # ── ivy_wires_filecache ← trunk_grp (caches wires separately) ───────────
    ivy_cache = _create_node_with_fallback(
        geo_node,
        ["filecache::2.0", "filecache", "filecache::1.0"],
        "ivy_wires_filecache",
    )
    # If an old ivy_filecache exists, we could migrate it, but here we just ensure 
    # the new name is used.
    old_ivy_cache = geo_node.node("ivy_filecache")
    if old_ivy_cache is not None:
        old_ivy_cache.setName("ivy_wires_filecache")
        ivy_cache = old_ivy_cache

    ivy_cache.setInput(0, trunk_grp)
    for pname, val in (("loadfromdisk", 0), ("trange", 0), ("timedependent", 0)):
        p = ivy_cache.parm(pname)
        if p is not None:
            try:
                p.set(val)
            except Exception as e:
                log(f"ivy_wires_filecache init parm {pname}: {e}")

    # ── OUT_wires ← ivy_wires_filecache (wires output) ───────────────────────
    if out is not None:
        out.setInput(0, ivy_cache)
        out.setDisplayFlag(True)
        out.setRenderFlag(True)

    # ── OUT_leaves ← scatter_leaves (leaves output) ───────────────────────
    out_leaves = geo_node.node("OUT_leaves")
    if out_leaves is None:
        out_leaves = geo_node.createNode("null", "OUT_leaves")
    out_leaves.setInput(0, geo_node.node("scatter_leaves") or scatter_cache)

    # ── Top-level output geo nodes with wildcard object_merge paths ────────────
    try:
        obj_context = hou.node("/obj")

        def _make_output_geo(name, target_path):
            geo = obj_context.node(name)
            if geo is None:
                geo = obj_context.createNode("geo", name)
            for child in geo.children():
                child.destroy()
            om = geo.createNode("object_merge", "object_merge1")
            om.parm("objpath1").set(target_path)
            om.setDisplayFlag(True)
            om.setRenderFlag(True)

        _make_output_geo("wires_ivy_fall",  "/obj/MSW_*/OUT_wires")
        _make_output_geo("leaves_ivy_fall", "/obj/MSW_*/OUT_leaves")

        log("[Ivy] Created wires_ivy_fall and leaves_ivy_fall output containers.")
    except Exception as e:
        log(f"[Ivy] Failed to create output geo nodes: {e}")

    geo_node.layoutChildren()
    log("[Ivy] Network created — scatter_logic bypassed, ivy merged with instancer.")
    return py_sop


def _add_ivy_spare_parms(py_sop_node):
    """Add spare parameters (int or float) to the ivy Python SOP."""
    ptg    = py_sop_node.parmTemplateGroup()
    folder = hou.FolderParmTemplate(
        "ivy_folder", "Ivy Controls",
        folder_type=hou.folderType.Simple
    )
    for spec in IVY_PARM_SPECS:
        name, label, default, mn, mx, is_int = spec
        if is_int:
            tmpl = hou.IntParmTemplate(
                name, label, 1,
                default_value=(int(default),),
                min=int(mn), max=int(mx),
                min_is_strict=False, max_is_strict=False,
                naming_scheme=hou.parmNamingScheme.Base1,
            )
        else:
            tmpl = hou.FloatParmTemplate(
                name, label, 1,
                default_value=(float(default),),
                min=float(mn), max=float(mx),
                min_is_strict=False, max_is_strict=False,
                naming_scheme=hou.parmNamingScheme.Base1,
            )
        folder.addParmTemplate(tmpl)

    # Nested Lookdev sub-tab inside the Ivy folder.
    # Houdini has no single documented tag for folder-tab colouring on spare
    # parms, so we set every tag name that has been seen to work in one
    # Houdini version or another; unrecognised tags are silently ignored.
    lookdev = hou.FolderParmTemplate(
        "ivy_lookdev", "Lookdev",
        folder_type=hou.folderType.Simple,
        tags={
            "sidefx::tab_color":        "#ff0000",
            "sidefx::folder_tab_color": "#ff0000",
            "tab_color":                "#ff0000",
        },
    )
    folder.addParmTemplate(lookdev)

    ptg.append(folder)
    py_sop_node.setParmTemplateGroup(ptg)


def sync_ivy_params(geo_node, ivy_state, cook=True):
    """
    Push ivy_state dict values onto the ivy_curve_gen Python SOP spare parms
    and the matching native parms on ivy_wire.
    Pass cook=False to defer the recook when batching multiple changes.
    """
    py_sop = geo_node.node("ivy_curve_gen")
    if py_sop is None:
        return
    for spec in IVY_PARM_SPECS:
        name = spec[0]
        if name not in ivy_state:
            continue
        p = py_sop.parm(name)
        if p is not None:
            try:
                p.set(ivy_state[name])
            except Exception as e:
                log(f"ivy parm sync error ({name}): {e}")

    # Push wire appearance parms directly onto the Wire SOP
    _sync_ivy_wire_parms(geo_node, ivy_state)

    if cook:
        cook_ivy(geo_node)


# PolyWire SOP parm name mapping: spare parm name → native PolyWire SOP parm name
_WIRE_PARM_MAP = {
    "ivy_wire_radius":    "radius",
    "ivy_wire_segs":      "segs",
    "ivy_wire_divisions": "div",
}


def _get_ivy_filecache(geo_node):
    """Return the ivy_wires_filecache (or legacy ivy_filecache) node."""
    if geo_node is None: return None
    return geo_node.node("ivy_wires_filecache") or geo_node.node("ivy_filecache")


def _sync_ivy_wire_parms(geo_node, ivy_state):
    """Push wire-appearance values from ivy_state onto the ivy_wire PolyWire SOP."""
    wire = geo_node.node("ivy_wire")
    if wire is None:
        return
    for spare_name, wire_parm in _WIRE_PARM_MAP.items():
        if spare_name in ivy_state:
            p = wire.parm(wire_parm)
            if p is not None:
                try:
                    p.set(ivy_state[spare_name])
                except Exception as e:
                    log(f"ivy wire parm error ({wire_parm}): {e}")


# Attribute Noise SOP parm name mapping: UI state key → native SOP parm name
_NOISE_SCALAR_PARMS = {
    "ivy_noise_amp":    "amplitudev",
    "ivy_noise_freq":   "elementsize",
    "ivy_noise_rough":  "rough",
    "ivy_noise_turb":   "lac",
}
_NOISE_VECTOR_PARMS = {}


def sync_ivy_noise_parms(geo_node, noise_state):
    """Push noise values from noise_state dict onto the ivy_attribnoise SOP.

    Uses defensive parm() None-checks so unknown parm names on this build of
    Houdini simply no-op instead of raising.
    """
    noise = geo_node.node("ivy_attribnoise")
    if noise is None:
        return
    for state_key, parm_name in _NOISE_SCALAR_PARMS.items():
        if state_key not in noise_state:
            continue
        p = noise.parm(parm_name)
        if p is not None:
            try:
                p.set(noise_state[state_key])
            except Exception as e:
                log(f"ivy noise parm error ({parm_name}): {e}")
    for state_key, comp_parms in _NOISE_VECTOR_PARMS.items():
        if state_key not in noise_state:
            continue
        val = noise_state[state_key]
        for cp in comp_parms:
            p = noise.parm(cp)
            if p is not None:
                try:
                    p.set(val)
                except Exception as e:
                    log(f"ivy noise parm error ({cp}): {e}")


def get_ivy_noise_params(geo_node):
    """Read Ivy Attribute Noise values into a UI state dict."""
    noise = geo_node.node("ivy_attribnoise") if geo_node is not None else None
    result = {}
    if noise is None:
        return result
    for state_key, parm_name in _NOISE_SCALAR_PARMS.items():
        p = noise.parm(parm_name)
        if p is not None:
            try:
                result[state_key] = p.eval()
            except Exception:
                pass
    return result


def get_ivy_resample_settings(geo_node):
    """Read ivy_resample length/subdivide settings."""
    resample = geo_node.node("ivy_resample") if geo_node is not None else None
    result = {"length": 0.2, "subdivide": False}
    if resample is None:
        return result
    p = resample.parm("length")
    if p is not None:
        try:
            result["length"] = p.eval()
        except Exception:
            pass
    p = resample.parm("treatpolysas")
    if p is not None:
        try:
            result["subdivide"] = bool(p.eval())
        except Exception:
            pass
    return result


def cook_ivy(geo_node):
    """Force-cook ivy_curve_gen so the viewport updates immediately."""
    py_sop = geo_node.node("ivy_curve_gen")
    if py_sop is None:
        return
    try:
        py_sop.cook(force=True)
    except Exception as e:
        log(f"ivy cook error: {e}")


def get_ivy_params(geo_node):
    """Read current ivy parm values from the SOP into a dict."""
    py_sop = geo_node.node("ivy_curve_gen") if geo_node else None
    result = {}
    for spec in IVY_PARM_SPECS:
        name, _label, default, _mn, _mx, _is_int = spec
        if py_sop:
            p = py_sop.parm(name)
            result[name] = p.eval() if p is not None else default
        else:
            result[name] = default
    return result


def ivy_network_exists(geo_node):
    """Return True if the ivy chain is already present in geo_node."""
    return geo_node is not None and geo_node.node("ivy_curve_gen") is not None


# ---------------------------------------------------------------------------
# Crawling Ivy — surface-creeping growth (independent of the strand ivy chain)
# ---------------------------------------------------------------------------
# Inspired by Streit, Federl & Sousa, "Modelling Plant Variation Through
# Growth" (Eurographics 2005). Each strand walks the surface step-by-step;
# heading is updated by a delayed proportional controller (lag + gain) with
# Gaussian sensor noise; surface adherence is enforced via ray-intersect, and
# when the surface is lost the strand drops under gravity until it reattaches.

CRAWL_PARM_SPECS = [
    # (name,                  label,              default, min,    max,    is_int)
    ("crawl_seed",            "Random Seed",        7,      0,      99999,  True),
    ("crawl_n_seeds",         "Seed Count",         60,     1,      5000,   True),
    ("crawl_strand_length",   "Strand Length",      8.0,    0.1,    500.0,  False),
    ("crawl_step_size",       "Step Size",          0.1,    0.005,  5.0,    False),
    ("crawl_adherence",       "Surface Adherence",  0.25,   0.001,  10.0,   False),
    ("crawl_gravity",         "Gravity Drop",       0.5,    0.0,    5.0,    False),
    ("crawl_upward_bias",     "Upward Bias",        0.6,    0.0,    1.0,    False),
    ("crawl_lag",             "Lag (steps)",        6,      0,      200,    True),
    ("crawl_gain",            "Adjustment Gain",    0.25,   0.0,    1.5,    False),
    ("crawl_noise",           "Sensor Noise",       0.05,   0.0,    1.0,    False),
    ("crawl_branch_prob",     "Branch Probability", 0.015,  0.0,    0.5,    False),
    ("crawl_branch_angle",    "Branch Angle",       45.0,   0.0,    179.0,  False),
    ("crawl_max_depth",       "Max Branch Depth",   3,      0,      10,     True),
    ("crawl_min_strands",     "Min Strand Length",  0.3,    0.0,    50.0,   False),
    # Wire (tube) appearance
    ("crawl_wire_radius",     "Wire Radius",        0.02,   0.001,  1.0,    False),
    ("crawl_wire_segs",       "Wire Segments",      1,      1,      32,     True),
    ("crawl_wire_divisions",  "Wire Divisions",     5,      1,      32,     True),
]


# Python SOP code that runs the actual growth simulation.
# input 0 = surface mesh (object_merge of the painted surface)
# input 1 = seed points (scatter SOP on that surface)
# Output: polyline curves representing crawling-ivy strands.
CRAWL_IVY_CODE = r'''
import hou
import numpy as np
from collections import deque
import random as _pyrand


def _crawl_run():
    node = hou.pwd()
    geo  = node.geometry()
    geo.clear()

    ins = node.inputs()
    if len(ins) < 2 or ins[0] is None or ins[1] is None:
        return

    surf_geo = ins[0].geometry()
    seed_geo = ins[1].geometry()
    if len(surf_geo.iterPoints()) == 0 or len(seed_geo.iterPoints()) == 0:
        return

    # ── parameters ────────────────────────────────────────────────────────
    seed_val      = int(node.parm("crawl_seed").eval())
    strand_len    = float(node.parm("crawl_strand_length").eval())
    step_size     = max(1e-4, float(node.parm("crawl_step_size").eval()))
    adhere        = max(1e-4, float(node.parm("crawl_adherence").eval()))
    gravity       = float(node.parm("crawl_gravity").eval())
    upward_bias   = float(node.parm("crawl_upward_bias").eval())
    lag_steps     = int(node.parm("crawl_lag").eval())
    gain          = float(node.parm("crawl_gain").eval())
    noise_amt     = float(node.parm("crawl_noise").eval())
    branch_prob   = float(node.parm("crawl_branch_prob").eval())
    branch_angle  = float(node.parm("crawl_branch_angle").eval())
    max_depth     = int(node.parm("crawl_max_depth").eval())
    min_len       = float(node.parm("crawl_min_strands").eval())

    rng = np.random.default_rng(seed_val)
    _pyrand.seed(seed_val)

    WORLD_UP   = np.array([0.0, 1.0, 0.0])
    WORLD_DOWN = -WORLD_UP

    def _norm(v):
        n = np.linalg.norm(v)
        return v / n if n > 1e-9 else v

    def _project_tangent(v, n):
        return _norm(v - np.dot(v, n) * n)

    def _rotate(v, axis, angle):
        if abs(angle) < 1e-9:
            return v
        c, s = np.cos(angle), np.sin(angle)
        return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1.0 - c)

    def _random_perp(n):
        a = rng.normal(size=3)
        a = _project_tangent(a, n)
        if np.linalg.norm(a) < 1e-6:
            ref = np.array([1.0, 0.0, 0.0])
            if abs(np.dot(ref, n)) > 0.95:
                ref = np.array([0.0, 0.0, 1.0])
            a = _project_tangent(ref, n)
        return _norm(a)

    def _project_to_surface(pos, last_n):
        origin = hou.Vector3(*(pos + last_n * adhere).tolist())
        direction = hou.Vector3(*(-last_n * (2.0 * adhere)).tolist())
        out_pos = hou.Vector3()
        out_n   = hou.Vector3()
        out_uvw = hou.Vector3()
        prim = surf_geo.intersect(origin, direction, out_pos, out_n, out_uvw)
        if prim < 0:
            return None
        return (np.array([out_pos[0], out_pos[1], out_pos[2]]),
                _norm(np.array([out_n[0], out_n[1], out_n[2]])))

    def _signed_angle(a, b, axis):
        a = _norm(a); b = _norm(b)
        cos_e = np.clip(np.dot(a, b), -1.0, 1.0)
        sign  = np.sign(np.dot(np.cross(a, b), axis))
        if sign == 0:
            sign = 1.0
        return np.arccos(cos_e) * sign

    # ── seed extraction ───────────────────────────────────────────────────
    seeds = []
    has_N = seed_geo.findPointAttrib("N") is not None
    for p in seed_geo.iterPoints():
        pos = np.array(p.position())
        if has_N:
            n = np.array(p.attribValue("N"))
        else:
            proj = _project_to_surface(pos, np.array([0.0, 1.0, 0.0]))
            if proj is None:
                continue
            pos, n = proj
        n = _norm(n)
        if np.linalg.norm(n) < 1e-6:
            continue
        seeds.append((pos, n))

    def _grow(start_pos, start_n, start_h, depth, length_cap):
        pts = [start_pos.copy()]
        P, N, H = start_pos.copy(), start_n.copy(), start_h.copy()
        pending = deque()
        off_count = 0
        grown = 0.0
        max_steps = int(length_cap / step_size) + 4
        new_branches = []

        for _ in range(max_steps):
            if grown >= length_cap:
                break

            # target heading: project world-up onto current tangent plane
            T = _project_tangent(WORLD_UP, N)
            if np.linalg.norm(T) < 1e-6:
                T = H

            # error → adjustment (proportional controller, paper §4.1)
            e = _signed_angle(H, T, N)
            u = gain * e * upward_bias

            # delayed signal model (paper §4.2.1)
            pending.append([lag_steps, u])
            applied = 0.0
            kept = deque()
            for entry in pending:
                entry[0] -= 1
                if entry[0] <= 0:
                    applied += entry[1]
                else:
                    kept.append(entry)
            pending = kept

            # apply rotation about surface normal + sensor noise
            noise_rad = float(rng.normal(0.0, noise_amt))
            H = _rotate(H, N, applied + noise_rad)
            H = _project_tangent(H, N)

            # forward Euler step
            P_new = P + step_size * H
            hit = _project_to_surface(P_new, N)
            if hit is not None:
                P_new, N = hit
                off_count = 0
            else:
                off_count += 1
                P_new = P_new + WORLD_DOWN * (gravity * step_size)
                if off_count > 8:
                    break

            # re-tangentialize H to (possibly new) N
            H = _project_tangent(H, N)

            # branching
            if depth < max_depth and _pyrand.random() < branch_prob:
                ang = _pyrand.uniform(-branch_angle, branch_angle) * np.pi / 180.0
                bH  = _project_tangent(_rotate(H, N, ang), N)
                new_branches.append(
                    (P_new.copy(), N.copy(), bH, depth + 1, (length_cap - grown) * 0.6))

            pts.append(P_new.copy())
            grown += float(np.linalg.norm(P_new - P))
            P = P_new

        return pts, new_branches

    # ── grow all strands (BFS over branches) ──────────────────────────────
    all_strands = []
    for seed_pos, seed_n in seeds:
        queue = [(seed_pos, seed_n, _random_perp(seed_n), 0, strand_len)]
        while queue:
            spos, sn, sh, sd, slen = queue.pop()
            pts, branches = _grow(spos, sn, sh, sd, slen)
            total = 0.0
            for i in range(1, len(pts)):
                total += float(np.linalg.norm(pts[i] - pts[i - 1]))
            if len(pts) >= 2 and total >= min_len:
                all_strands.append(pts)
            queue.extend(branches)

    # ── write polyline curves ─────────────────────────────────────────────
    for strand in all_strands:
        poly = geo.createPolygon()
        poly.setIsClosed(False)
        for v in strand:
            pt = geo.createPoint()
            pt.setPosition(hou.Vector3(float(v[0]), float(v[1]), float(v[2])))
            poly.addVertex(pt)


_crawl_run()
'''


def create_crawl_ivy_network(geo_node):
    """
    Build the Crawling Ivy SOP chain inside `geo_node` and splice it into the
    main scatter chain. The Crawling Ivy curves (resampled) become the new
    point source feeding pscale_wrangle, replacing scatter_logic which is
    removed.

    Topology:
        paint_mask ──► crawl_seed_scatter ──┐
                                            ├─► crawl_ivy_gen ─► crawl_resample ──► pscale_wrangle ──► (existing chain → instancer → OUT_scatter)
        paint_mask ────────────────────────┘                            │
                                                                         ▼
                                                                  crawl_wire (PolyWire)
                                                                         │
                                                                         ▼
                                                                     crawl_OUT
    Returns the crawl_ivy_gen Python SOP.
    """
    # Ensure scatter_filecache is connected to instancer output before creating crawl network
    ensure_scatter_filecache(geo_node)

    paint_mask = geo_node.node("paint_mask")
    if paint_mask is None:
        raise RuntimeError(
            "No 'paint_mask' node found. Create the scatter network first "
            "(Set a Surface and click Create Network) so paint_mask exists."
        )

    # ── seed scatter (driven by painted mask) ────────────────────────────
    seed_scatter = geo_node.createNode("scatter", "crawl_seed_scatter")
    seed_scatter.setInput(0, paint_mask)
    # Native Scatter parm names vary slightly across builds — set defensively.
    # densityattrib="mask" makes the painted mask attribute drive seed density.
    for pname, val in (("forcetotalcount", 1), ("npts", 60),
                       ("seed", 7), ("ptseed", 7),
                       ("densityattrib", "mask"), ("usedensityattrib", 1)):
        p = seed_scatter.parm(pname)
        if p is not None:
            try:
                p.set(val)
            except Exception:
                pass

    # ── growth Python SOP (surface = paint_mask, seeds = scatter) ────────
    py_sop = geo_node.createNode("python", "crawl_ivy_gen")
    py_sop.setInput(0, paint_mask)
    py_sop.setInput(1, seed_scatter)
    _add_crawl_ivy_spare_parms(py_sop)
    py_sop.setParms({"python": CRAWL_IVY_CODE})

    # ── geometry offset — move crawl points along normals ──────────────────────
    crawl_geo_off = geo_node.createNode("attribwrangle", "crawl_geo_offset")
    crawl_geo_off.setInput(0, py_sop)
    crawl_geo_off.setParms({"class": 2, "snippet": '@P += normalize(@N) * chf("offset");'})
    try:
        cls_p = crawl_geo_off.parm("class")
        if cls_p is not None and cls_p.eval() != 2:
            cls_p.set(2)
    except Exception:
        pass
    try:
        ptg = crawl_geo_off.parmTemplateGroup()
        if ptg.find("offset") is None:
            ptg.append(hou.FloatParmTemplate(
                "offset", "Offset", 1, default_value=(0.0,),
                min=-5.0, max=5.0, min_is_strict=False, max_is_strict=False,
            ))
            crawl_geo_off.setParmTemplateGroup(ptg)
        p = crawl_geo_off.parm("offset")
        if p is not None:
            p.set(0.0)
    except Exception as _e:
        log(f"crawl_geo_offset spare parm: {_e}")

    # ── resample for even segments ───────────────────────────────────────
    resample = geo_node.createNode("resample", "crawl_resample")
    resample.setInput(0, crawl_geo_off)
    resample.setParms({"dolength": 1, "length": 0.05})

    # ── polywire to thicken the strands ──────────────────────────────────
    wire = geo_node.createNode("polywire", "crawl_wire")
    wire.setInput(0, resample)
    for pname, val in (("radius", 0.01), ("segs", 1), ("div", 5)):
        p = wire.parm(pname)
        if p is not None:
            try:
                p.set(val)
            except Exception:
                pass

    # ── trunk_grp — group node wrapping crawl_wire output ────────────────
    trunk_grp = geo_node.node("trunk_grp")
    if trunk_grp is None:
        trunk_grp = geo_node.createNode("groupcreate", "trunk_grp")
        p = trunk_grp.parm("groupname")
        if p is not None:
            p.set("trunk_grp")
        trunk_grp.setInput(0, wire)

    # ── splice into main chain: pscale_wrangle ← crawl_resample ─────────
    pscale_wr = geo_node.node("pscale_wrangle")
    if pscale_wr is not None:
        try:
            pscale_wr.setInput(0, resample)
        except Exception as e:
            log(f"[Crawl] pscale_wrangle setInput error: {e}")

    # ── replace attribrandomize_orient with orient_wrangle ───────────────
    orient_curve = geo_node.node("orientalongcurve1")
    add_keep     = geo_node.node("add_keep")

    orient_rand = geo_node.node("attribrandomize_orient")
    if orient_rand is not None:
        try:
            orient_rand.destroy()
        except Exception as e:
            log(f"[Crawl] attribrandomize_orient destroy error: {e}")

    existing_wr = geo_node.node("orient_wrangle")
    if existing_wr is None:
        orient_wr = geo_node.createNode("attribwrangle", "orient_wrangle")
        orient_wr.setParms({"class": 2, "snippet": _ORIENT_WRANGLE_CODE})
        _add_orient_wrangle_spare_parms(orient_wr)
    else:
        orient_wr = existing_wr
    if orient_curve is not None:
        orient_wr.setInput(0, orient_curve)

    # ── insert crawl_pscale_ramp between orient_wrangle and add_keep ─────
    if orient_wr is not None and add_keep is not None:
        crawl_ramp = geo_node.createNode("attribwrangle", "crawl_pscale_ramp")
        crawl_ramp.setParms({"class": 2, "snippet": _IVY_PSCALE_RAMP_CODE})
        crawl_ramp.setInput(0, orient_wr)
        _add_pscale_ramp_spare_parm(crawl_ramp)
        add_keep.setInput(0, crawl_ramp)
        log("[Crawl] crawl_pscale_ramp inserted between orient_wrangle and add_keep.")

    # ── remove scatter_logic (now superseded by the crawl chain) ─────────
    scatter_logic = geo_node.node("scatter_logic")
    if scatter_logic is not None:
        try:
            scatter_logic.destroy()
        except Exception as e:
            log(f"[Crawl] scatter_logic destroy error: {e}")

    # ── instancer → leaves_grp → crawl_leaves_filecache → OUT_Scatter_ivy_leaves ──
    out_scatter    = geo_node.node("OUT_Scatter_ivy_leaves") or geo_node.node("OUT_scatter")
    instancer_node = geo_node.node("instancer")
    leaves_grp     = geo_node.node("leaves_grp")

    if leaves_grp is None and instancer_node is not None:
        leaves_grp = geo_node.createNode("groupcreate", "leaves_grp")
        p = leaves_grp.parm("groupname")
        if p is not None:
            p.set("leaves_grp")
    if leaves_grp is not None and instancer_node is not None:
        leaves_grp.setInput(0, instancer_node)

    # Rename legacy scatter_filecache → crawl_leaves_filecache if it exists
    legacy_scatter_cache = geo_node.node("scatter_filecache")
    if legacy_scatter_cache is not None:
        try:
            legacy_scatter_cache.setName("crawl_leaves_filecache", unique_name=True)
        except Exception:
            pass

    # Create or reuse crawl_leaves_filecache
    leaves_cache = geo_node.node("crawl_leaves_filecache")
    if leaves_cache is None:
        leaves_cache = _create_node_with_fallback(
            geo_node,
            ["filecache::2.0", "filecache", "filecache::1.0"],
            "crawl_leaves_filecache",
        )
    if leaves_grp is not None:
        leaves_cache.setInput(0, leaves_grp)

    if out_scatter is not None:
        out_scatter.setInput(0, leaves_cache)
        out_scatter.setRenderFlag(True)
        out_scatter.setDisplayFlag(True)
        if out_scatter.name() != "OUT_Scatter_ivy_leaves":
            out_scatter.setName("OUT_Scatter_ivy_leaves")

    # ── crawl_filecache between trunk_grp and crawl_OUT ──────────────────
    crawl_cache = _create_node_with_fallback(
        geo_node,
        ["filecache::2.0", "filecache", "filecache::1.0"],
        "crawl_filecache",
    )
    crawl_cache.setInput(0, trunk_grp if trunk_grp is not None else wire)

    # Initialise both cache nodes with CRAWL_CACHE_DEFAULTS
    defaults = CRAWL_CACHE_DEFAULTS
    for cache_node in (crawl_cache, leaves_cache):
        for pname, val in (("loadfromdisk", int(bool(defaults["crawl_cache_loadfromdisk"]))),
                           ("trange", int(defaults["crawl_cache_trange"])),
                           ("timedependent", int(bool(defaults["crawl_cache_timedependent"])))):
            p = cache_node.parm(pname)
            if p is not None:
                try:
                    p.set(val)
                except Exception as e:
                    log(f"{cache_node.name()} init parm {pname}: {e}")
        _set_parm(cache_node, "basedir", defaults["crawl_cache_basedir"])
    # Give each cache a distinct default basename so they write to separate files
    _set_parm(crawl_cache,  "basename", "$HIPNAME.crawl_curves")
    _set_parm(leaves_cache, "basename", "$HIPNAME.crawl_leaves")

    # ── crawl_OUT null after crawl_filecache ──────────────────────────────
    crawl_out = geo_node.createNode("null", "crawl_OUT")
    crawl_out.setInput(0, crawl_cache)
    crawl_out.setRenderFlag(True)
    crawl_out.setDisplayFlag(True)

    # ── /obj output geo nodes ─────────────────────────────────────────────
    try:
        obj_context = hou.node("/obj")

        def _make_crawl_output_geo(name, target_path):
            geo = obj_context.node(name)
            if geo is None:
                geo = obj_context.createNode("geo", name)
            for child in geo.children():
                child.destroy()
            om = geo.createNode("object_merge", "object_merge1")
            om.parm("objpath1").set(target_path)
            om.setDisplayFlag(True)
            om.setRenderFlag(True)

        _make_crawl_output_geo("wires_geo",  "/obj/MSW_*/crawl_OUT")
        _make_crawl_output_geo("leaves_geo", "/obj/MSW_*/OUT_Scatter_ivy_leaves")

        log("[Crawl] Created wires_geo and leaves_geo output containers.")
    except Exception as e:
        log(f"[Crawl] Failed to create output geo nodes: {e}")

    geo_node.layoutChildren()
    log("[Crawl] Network created — trunk_grp → crawl_filecache → crawl_OUT, "
        "crawl_leaves_filecache → OUT_Scatter_ivy_leaves is leaves output.")
    return py_sop


def _add_crawl_ivy_spare_parms(py_sop_node):
    """Add spare parameters to the crawl_ivy_gen Python SOP."""
    ptg    = py_sop_node.parmTemplateGroup()
    folder = hou.FolderParmTemplate(
        "crawl_folder", "Crawling Ivy",
        folder_type=hou.folderType.Simple,
    )
    for spec in CRAWL_PARM_SPECS:
        name, label, default, mn, mx, is_int = spec
        if is_int:
            tmpl = hou.IntParmTemplate(
                name, label, 1,
                default_value=(int(default),),
                min=int(mn), max=int(mx),
                min_is_strict=False, max_is_strict=False,
                naming_scheme=hou.parmNamingScheme.Base1,
            )
        else:
            tmpl = hou.FloatParmTemplate(
                name, label, 1,
                default_value=(float(default),),
                min=float(mn), max=float(mx),
                min_is_strict=False, max_is_strict=False,
                naming_scheme=hou.parmNamingScheme.Base1,
            )
        folder.addParmTemplate(tmpl)
    ptg.append(folder)
    py_sop_node.setParmTemplateGroup(ptg)


_CRAWL_WIRE_PARM_MAP = {
    "crawl_wire_radius":    "radius",
    "crawl_wire_segs":      "segs",
    "crawl_wire_divisions": "div",
}


def sync_crawl_ivy_params(geo_node, crawl_state, cook=True):
    """Push crawl_state values onto crawl_ivy_gen + crawl_wire, then optionally cook."""
    py_sop = geo_node.node("crawl_ivy_gen")
    if py_sop is None:
        return
    for spec in CRAWL_PARM_SPECS:
        name = spec[0]
        if name not in crawl_state:
            continue
        p = py_sop.parm(name)
        if p is not None:
            try:
                p.set(crawl_state[name])
            except Exception as e:
                log(f"crawl parm sync error ({name}): {e}")

    # Push wire-appearance values onto crawl_wire
    wire = geo_node.node("crawl_wire")
    if wire is not None:
        for spare_name, wire_parm in _CRAWL_WIRE_PARM_MAP.items():
            if spare_name in crawl_state:
                p = wire.parm(wire_parm)
                if p is not None:
                    try:
                        p.set(crawl_state[spare_name])
                    except Exception as e:
                        log(f"crawl wire parm error ({wire_parm}): {e}")

    # Push n_seeds onto the scatter SOP so density updates live
    if "crawl_n_seeds" in crawl_state:
        scat = geo_node.node("crawl_seed_scatter")
        if scat is not None:
            for pname in ("npts", "ptn"):
                p = scat.parm(pname)
                if p is not None:
                    try:
                        p.set(int(crawl_state["crawl_n_seeds"]))
                    except Exception:
                        pass
    if "crawl_seed" in crawl_state:
        scat = geo_node.node("crawl_seed_scatter")
        if scat is not None:
            for pname in ("seed", "ptseed"):
                p = scat.parm(pname)
                if p is not None:
                    try:
                        p.set(int(crawl_state["crawl_seed"]))
                    except Exception:
                        pass

    if cook:
        cook_crawl_ivy(geo_node)


def cook_crawl_ivy(geo_node):
    """Mark crawl_ivy_gen dirty so the viewport cooks it on its next refresh.

    parm.set() already flags the node dirty — calling cook(force=True) would
    block the main thread until the Python SOP finishes, freezing the UI.
    """
    pass


def crawl_ivy_network_exists(geo_node):
    return geo_node is not None and geo_node.node("crawl_ivy_gen") is not None


def remove_crawl_ivy_network(geo_node):
    """Tear down all crawl_* nodes inside geo_node."""
    if geo_node is None:
        return
    # Tear down the OUT_IVY_SETUP / merge_ivy_setup endpoint first so the
    # remaining display flag falls back onto OUT_Scatter_ivy_leaves cleanly.
    # Before destroying crawl_pscale_ramp, reconnect add_keep upstream so
    # the CTP chain is intact after teardown. Prefer orient_wrangle (the
    # crawl/ivy node), fall back to attribrandomize_orient for older networks.
    add_keep    = geo_node.node("add_keep")
    upstream    = geo_node.node("orient_wrangle") or geo_node.node("attribrandomize_orient")
    if add_keep is not None and upstream is not None:
        try:
            add_keep.setInput(0, upstream)
        except Exception as e:
            log(f"crawl remove — add_keep reconnect error: {e}")

    for name in ("crawl_OUT", "crawl_filecache", "crawl_wire",
                 "crawl_pscale_ramp", "crawl_resample", "crawl_geo_offset",
                 "crawl_ivy_gen", "crawl_seed_scatter"):
        n = geo_node.node(name)
        if n is not None:
            try:
                n.destroy()
            except Exception as e:
                log(f"crawl remove error ({name}): {e}")

    # Remove trunk_grp only if ivy_scatter_merge isn't using it as its wire input
    trunk_grp = geo_node.node("trunk_grp")
    if trunk_grp is not None:
        ivy_merge_nd = geo_node.node("ivy_scatter_merge")
        if ivy_merge_nd is None or ivy_merge_nd.input(1) is not trunk_grp:
            try:
                trunk_grp.destroy()
            except Exception as e:
                log(f"crawl remove error (trunk_grp): {e}")

    # Remove leaves_grp only if ivy_scatter_merge isn't using it; reconnect
    # OUT_Scatter_ivy_leaves to the node that was upstream of leaves_grp first.
    leaves_grp = geo_node.node("leaves_grp")
    if leaves_grp is not None:
        ivy_merge_nd = geo_node.node("ivy_scatter_merge")
        if ivy_merge_nd is None or ivy_merge_nd.input(0) is not leaves_grp:
            out_s = geo_node.node("OUT_Scatter_ivy_leaves") or geo_node.node("OUT_scatter")
            if out_s is not None:
                upstream = leaves_grp.input(0)
                if upstream is not None:
                    try:
                        out_s.setInput(0, upstream)
                    except Exception as e:
                        log(f"crawl remove — leaves_grp reconnect: {e}")
            try:
                leaves_grp.destroy()
            except Exception as e:
                log(f"crawl remove error (leaves_grp): {e}")

    # Restore display/render flags onto OUT_scatter (renamed back from
    # OUT_Scatter_ivy_leaves) so the network still has a final viewable node.
    out_scatter = geo_node.node("OUT_Scatter_ivy_leaves") or geo_node.node("OUT_scatter")
    if out_scatter is not None:
        try:
            if out_scatter.name() == "OUT_Scatter_ivy_leaves":
                out_scatter.setName("OUT_scatter")
            out_scatter.setRenderFlag(True)
            out_scatter.setDisplayFlag(True)
        except Exception:
            pass
    geo_node.layoutChildren()
    log("[Crawl] Network removed.")


def get_crawl_ivy_params(geo_node):
    """Read crawl parm values into a dict (returning defaults if not present)."""
    py_sop = geo_node.node("crawl_ivy_gen") if geo_node else None
    out = {}
    for spec in CRAWL_PARM_SPECS:
        name, _label, default, _mn, _mx, _is_int = spec
        if py_sop:
            p = py_sop.parm(name)
            out[name] = p.eval() if p is not None else default
        else:
            out[name] = default
    return out


# ---------------------------------------------------------------------------
# Vellum wire simulation
# ---------------------------------------------------------------------------

IVY_SIM_PARM_SPECS = [
    # (name,                 label,            default, min,    max,   is_int)
    ("ivy_sim_gravity",      "Gravity",        -9.8,    -30.0,  30.0,  False),
    ("ivy_sim_substeps",     "Substeps",        2,      1,      20,    True),
    ("ivy_sim_stiffness",    "Stiffness",       0.5,    0.0,    1.0,   False),
    ("ivy_sim_bend",         "Bend Stiffness",  0.3,    0.0,    1.0,   False),
    ("ivy_sim_damping",      "Damping",         0.1,    0.0,    1.0,   False),
    ("ivy_sim_start_frame",  "Start Frame",     1,     -10000,  10000, True),
    ("ivy_sim_end_frame",    "End Frame",       100,   -10000,  10000, True),
]


# VEX — mark first point of each primitive as pinned (root of each strand).
# Vellum treats i@stopped=1 points as kinematically frozen, so the curve base
# stays anchored while the rest of the strand is free to fall under gravity.
_IVY_SIM_LENGTH_SCALE_CODE = """
float minLen = chf("min_length");
float maxLen = chf("max_length");

float randVal = rand(@primnum);
float scale = lerp(minLen, maxLen, randVal);

int pts[] = primpoints(0, @primnum);
vector root = point(0, "P", pts[0]);

foreach (int pt; pts) {
    vector pos = point(0, "P", pt);
    vector offset = pos - root;
    vector newPos = root + (offset * scale);
    setpointattrib(0, "P", pt, newPos);
}
"""

_IVY_SIM_PIN_CODE = """
int prim  = pointprims(0, @ptnum)[0];
int first = primpoint(0, prim, 0);
i@stopped = (@ptnum == first) ? 1 : 0;
f@mass    = 1.0;
"""

# VEX — scales @pscale and the width (XY) components of @scale along the curve
# from root (U=0) to tip (U=1).  Width axes assume orientalongcurve aligns +Z
# with the tangent (Houdini default), so X/Y are perpendicular to curve length.
# Guards against non-curve points with pointprims().
# Multiplies (rather than overwrites) v@scale so Global Scale set upstream by
# pscale_wrangle in non-uniform XYZ mode survives the ramp pass.
_IVY_PSCALE_RAMP_CODE = """
int prims[] = pointprims(0, @ptnum);
if (len(prims) == 0) return;
int prim = prims[0];
int pts[] = primpoints(0, prim);
int idx = find(pts, @ptnum);
if (idx < 0) return;
float u = (len(pts) > 1) ? float(idx) / float(len(pts) - 1) : 0.0;
@pscale *= chramp("scale_ramp", u);
float w = chramp("width_ramp", u) * chf("width_scale");
vector cur = haspointattrib(0, "scale") ? v@scale : set(1, 1, 1);
v@scale = set(cur.x * w, cur.y * w, cur.z);
"""


def _add_pscale_ramp_spare_parm(node):
    """Add spare parms on ivy_pscale_ramp:
       - scale_ramp  : float ramp, defaults U=0→1.0, U=1→0.3 (length scaling)
       - width_ramp  : float ramp, defaults U=0→1.0, U=1→1.0 (flat = no-op)
       - width_scale : float,      default 1.0 (global multiplier on width_ramp)
    """
    try:
        ptg = node.parmTemplateGroup()

        if ptg.find("scale_ramp") is None:
            ptg.append(hou.RampParmTemplate(
                "scale_ramp", "Scale Ramp",
                hou.rampParmType.Float,
                default_basis=hou.rampBasis.Linear,
            ))
        if ptg.find("width_ramp") is None:
            ptg.append(hou.RampParmTemplate(
                "width_ramp", "Width Ramp",
                hou.rampParmType.Float,
                default_basis=hou.rampBasis.Linear,
            ))
        if ptg.find("width_scale") is None:
            ptg.append(hou.FloatParmTemplate(
                "width_scale", "Width Scale", 1,
                default_value=(1.0,),
                min=0.0, max=5.0,
                min_is_strict=True, max_is_strict=False,
            ))

        node.setParmTemplateGroup(ptg)

        scale_p = node.parm("scale_ramp")
        if scale_p is not None:
            scale_p.set(hou.Ramp(
                (hou.rampBasis.Linear, hou.rampBasis.Linear),
                (0.0, 1.0),
                (1.0, 0.3),
            ))
        width_p = node.parm("width_ramp")
        if width_p is not None:
            width_p.set(hou.Ramp(
                (hou.rampBasis.Linear, hou.rampBasis.Linear),
                (0.0, 1.0),
                (1.0, 1.0),
            ))
    except Exception as e:
        log(f"ivy_pscale_ramp spare parm: {e}")


def _set_vellum_constraint_type(node, tokens, menu_keywords=()):
    """
    Set `node`'s constrainttype parm.  The parm accepts either string tokens
    or integer menu indices depending on the Houdini build, so we try tokens
    first then fall back to menu-label substring matching.
    """
    ct = node.parm("constrainttype")
    if ct is None:
        return
    for tok in tokens:
        try:
            ct.set(tok)
            return
        except Exception:
            pass
    try:
        labels = ct.menuLabels()
    except Exception as e:
        log(f"vellum constraint type menu lookup: {e}")
        return
    for i, lbl in enumerate(labels):
        ll = lbl.lower()
        if any(kw in ll for kw in menu_keywords):
            try:
                ct.set(i)
                return
            except Exception as e:
                log(f"vellum constraint type set index {i}: {e}")
    log(f"[Ivy Sim] Could not set constraint type {tokens} on {node.name()}.")


def _create_node_with_fallback(parent, candidates, node_name):
    """
    Try each type name in `candidates` (list of strings) in order and return
    the first successfully-created node. If none work, raise a clear error
    listing what was attempted — helps debug Houdini-version name drift.
    """
    tried = []
    sop_cat = hou.sopNodeTypeCategory()
    for tname in candidates:
        # Only attempt if the type actually exists in this build
        if hou.nodeType(sop_cat, tname) is None:
            tried.append(f"{tname} (not registered)")
            continue
        try:
            return parent.createNode(tname, node_name)
        except hou.OperationFailed as e:
            tried.append(f"{tname} (failed: {e})")
    raise RuntimeError(
        "Could not create '{}' — tried: {}".format(node_name, "; ".join(tried))
    )


def create_ivy_sim_network(geo_node):
    """
    Insert a Vellum Hair simulation chain between ivy_attribnoise and ivy_wire.
    Layout:
        ivy_attribnoise → ivy_sim_pin → ivy_vellum_constraints
                        → ivy_vellum_solver → ivy_sim_cache → ivy_wire
        ivy_sim_collision (object_merge) → ivy_vellum_solver input 2
    Note: ivy_sim_length_scale lives between ivy_curve_gen and ivy_blast (base network).
    """
    if not ivy_network_exists(geo_node):
        raise RuntimeError("Create the ivy network first.")
    if ivy_sim_network_exists(geo_node):
        log("[Ivy Sim] Network already exists.")
        return

    noise = geo_node.node("ivy_attribnoise")
    wire  = geo_node.node("ivy_wire")
    if noise is None or wire is None:
        raise RuntimeError("Required ivy nodes (attribnoise/wire) are missing.")

    # ── ivy_sim_pin — wrangle that marks root points as stopped ──────────────
    pin = geo_node.createNode("attribwrangle", "ivy_sim_pin")
    pin.setParms({"class": 2, "snippet": _IVY_SIM_PIN_CODE})  # class=2 → run over points
    pin.setInput(0, noise)

    # ── ivy_vellum_constraints — build Hair constraints on the curves ───────
    # In Houdini 19.5 there is no `vellumconfigurehair` SOP — we use the
    # generic `vellumconstraints` and set its type menu to "Hair", which
    # builds stretch + bend constraints along each curve.
    constraints = _create_node_with_fallback(
        geo_node,
        ["vellumconstraints", "vellumconstraints::2.0"],
        "ivy_vellum_constraints",
    )
    # Wire pin into all 3 constraint inputs (Source / Constraint / Rest)
    for idx in (0, 1, 2):
        try:
            constraints.setInput(idx, pin)
        except Exception as e:
            log(f"ivy_vellum_constraints setInput({idx}): {e}")

    _set_vellum_constraint_type(constraints, ("hair",), menu_keywords=("hair",))

    # ── ivy_sim_collision — object_merge that pulls an external collision mesh
    # Initially has no object path; the user picks one via the UI.
    collision = geo_node.createNode("object_merge", "ivy_sim_collision")
    for pname, val in (("xformtype", 1),):  # 1 = "Into This Object" (world-space)
        p = collision.parm(pname)
        if p is not None:
            try:
                p.set(val)
            except Exception as e:
                log(f"ivy_sim_collision init parm {pname}: {e}")

    # ── ivy_sim_glue_constraints — Attach strand points to collision surface ──
    # Chained after the hair constraints: any strand point within `maxdist`
    # of the collision mesh gets pinned to its nearest target point.  Starts
    # bypassed so it has no effect until the user enables it in the UI.
    glue = _create_node_with_fallback(
        geo_node,
        ["vellumconstraints", "vellumconstraints::2.0"],
        "ivy_sim_glue_constraints",
    )
    glue.setInput(0, constraints, 0)
    try:
        glue.setInput(1, constraints, 1)
    except Exception as e:
        log(f"ivy_sim_glue_constraints setInput(1): {e}")
    try:
        glue.setInput(2, collision)
    except Exception as e:
        log(f"ivy_sim_glue_constraints setInput(2): {e}")
    _set_vellum_constraint_type(glue, ("attachtogeometry", "glueToSurface", "pinToTarget"),
                                menu_keywords=("attach", "glue"))
    for pname, val in (
        ("maxdistcheck", 1),
        ("maxdist", 0.2),
        ("stretchstiffness", 1.0),
        ("stiffness", 1.0),
    ):
        p = glue.parm(pname)
        if p is not None:
            try:
                p.set(val)
            except Exception as e:
                log(f"ivy_sim_glue_constraints init parm {pname}: {e}")
    glue.bypass(True)  # disabled until user enables in the Glue UI

    # ── ivy_vellum_solver — simulates the hair ───────────────────────────────
    solver = _create_node_with_fallback(
        geo_node,
        ["vellumsolver", "vellumsolver::2.0", "vellumsolver::1.0"],
        "ivy_vellum_solver",
    )
    # Input 0: geometry (glue out 0), Input 1: constraints (glue out 1).
    # When glue is bypassed, its outputs pass through from the hair
    # constraints, so the solver still gets the hair-only chain.
    solver.setInput(0, glue, 0)
    try:
        solver.setInput(1, glue, 1)
    except Exception as e:
        log(f"ivy_vellum_solver setInput(1): {e}")
    # Input 2: collision geometry
    try:
        solver.setInput(2, collision)
    except Exception as e:
        log(f"ivy_vellum_solver setInput(2): {e}")

    # ── ivy_sim_cache — filecache for "Render to Disk" ───────────────────────
    cache = _create_node_with_fallback(
        geo_node,
        ["filecache::2.0", "filecache", "filecache::1.0"],
        "ivy_sim_cache",
    )
    cache.setInput(0, solver)
    # Default: pass-through (no disk IO) until user hits Render to Disk.
    for pname, val in (("loadfromdisk", 0), ("timedependent", 1)):
        p = cache.parm(pname)
        if p is not None:
            try:
                p.set(val)
            except Exception as e:
                log(f"ivy_sim_cache init parm {pname}: {e}")

    # ── Geometry Offset — move ivy points along normals after sim cache ──────────
    ivy_geo_off = geo_node.createNode("attribwrangle", "ivy_geo_offset")
    ivy_geo_off.setInput(0, cache)
    ivy_geo_off.setParms({"class": 2, "snippet": '@P += normalize(@N) * chf("offset");'})
    try:
        _ptg = ivy_geo_off.parmTemplateGroup()
        _ptg.append(hou.FloatParmTemplate(
            "offset", "Offset", 1, default_value=(0.0,),
            min=-5.0, max=5.0, min_is_strict=False, max_is_strict=False,
        ))
        ivy_geo_off.setParmTemplateGroup(_ptg)
    except Exception as _e:
        log(f"ivy_geo_offset spare parm: {_e}")

    # ── Rewire: ivy_sim_cache → ivy_geo_offset → ivy_wire ──────────────────────
    wire.setInput(0, ivy_geo_off)

    # ── Strip vellum-generated @pscale before it reaches pscale_wrangle ─────────
    # Vellum Hair solver writes wire-radius values into @pscale (~0.008).
    # pscale_wrangle would read this as base_pscale, making leaves microscopic.
    # Deleting @pscale here forces pscale_wrangle to start from base_pscale=1.0.
    pscale_reset = geo_node.createNode("attribdelete", "ivy_sim_pscale_reset")
    pscale_reset.setInput(0, ivy_geo_off)
    p = pscale_reset.parm("ptdel")
    if p is not None:
        p.set("pscale")

    # ── Rewire: pscale_wrangle input 0 ← ivy_sim_pscale_reset ───────────────
    pscale_wr = geo_node.node("pscale_wrangle")
    if pscale_wr is not None:
        try:
            pscale_wr.setInput(0, pscale_reset)
        except Exception as e:
            log(f"pscale_wrangle setInput(0, ivy_sim_pscale_reset): {e}")

    geo_node.layoutChildren()
    log("[Ivy Sim] Vellum wire-sim network created.")


def remove_ivy_sim_network(geo_node):
    """Destroy all sim nodes and reconnect ivy_attribnoise → ivy_wire."""
    if geo_node is None:
        return
    if not ivy_sim_network_exists(geo_node):
        return

    # Reconnect ivy_wire back to ivy_attribnoise (ivy_sim_length_scale is now
    # between ivy_curve_gen and ivy_blast, not upstream of ivy_wire).
    noise = geo_node.node("ivy_attribnoise")
    wire  = geo_node.node("ivy_wire")
    if wire is not None and noise is not None:
        wire.setInput(0, noise)

    # Restore pscale_wrangle input 0 ← ivy_blast (its pre-sim source)
    pscale_wr = geo_node.node("pscale_wrangle")
    blast     = geo_node.node("ivy_blast")
    if pscale_wr is not None and blast is not None:
        try:
            pscale_wr.setInput(0, blast)
        except Exception as e:
            log(f"pscale_wrangle restore setInput(0, ivy_blast): {e}")

    # Destroy sim nodes (but keep ivy_sim_length_scale — it's part of the
    # base ivy network, not the Vellum sim).
    for name in ("ivy_sim_cache", "ivy_geo_offset", "ivy_sim_pscale_reset",
                 "ivy_vellum_solver", "ivy_sim_glue_constraints",
                 "ivy_sim_collision", "ivy_vellum_constraints", "ivy_sim_pin"):
        n = geo_node.node(name)
        if n:
            try:
                n.destroy()
            except Exception as e:
                log(f"ivy sim destroy {name}: {e}")

    geo_node.layoutChildren()
    log("[Ivy Sim] Network removed.")


def ivy_sim_network_exists(geo_node):
    """Return True if the vellum sim chain is present."""
    return geo_node is not None and geo_node.node("ivy_vellum_solver") is not None


# UI state key → (node name, parm name, value transform)
# Vector parms (gravity) use component-suffixed setters.
_SIM_CONFIG_PARMS = {
    "ivy_sim_stiffness":        ("ivy_vellum_constraints", "stretchstiffness"),
    "ivy_sim_bend_stiffness":   ("ivy_vellum_constraints", "bendstiffness"),
    "ivy_sim_bend_damping":     ("ivy_vellum_constraints", "benddampingratio"),
    "ivy_sim_bend_rest_scale":  ("ivy_vellum_constraints", "bendrestscale"),
}
_SIM_SOLVER_SCALAR_PARMS = {
    "ivy_sim_substeps":  ("ivy_vellum_solver", "substeps"),
    "ivy_sim_damping":   ("ivy_vellum_solver", "normaldrag"),
    "ivy_sim_start_frame": ("ivy_vellum_solver", "startframe"),
}


def sync_ivy_sim_parms(geo_node, sim_state):
    """Push sim-state values onto the Vellum config/solver SOPs."""
    if not ivy_sim_network_exists(geo_node):
        return

    for state_key, (node_name, parm_name) in _SIM_CONFIG_PARMS.items():
        if state_key not in sim_state:
            continue
        n = geo_node.node(node_name)
        if n is None:
            continue
        p = n.parm(parm_name)
        if p is not None:
            try:
                p.set(sim_state[state_key])
            except Exception as e:
                log(f"ivy sim config parm {parm_name}: {e}")

    for state_key, (node_name, parm_name) in _SIM_SOLVER_SCALAR_PARMS.items():
        if state_key not in sim_state:
            continue
        n = geo_node.node(node_name)
        if n is None:
            continue
        p = n.parm(parm_name)
        if p is not None:
            try:
                p.set(sim_state[state_key])
            except Exception as e:
                log(f"ivy sim solver parm {parm_name}: {e}")

    # Gravity on the vellum solver is a vec3; write Y component
    solver = geo_node.node("ivy_vellum_solver")
    if solver is not None and "ivy_sim_gravity" in sim_state:
        gval = sim_state["ivy_sim_gravity"]
        for comp, val in (("gravityx", 0.0), ("gravityy", gval), ("gravityz", 0.0)):
            p = solver.parm(comp)
            if p is not None:
                try:
                    p.set(val)
                except Exception as e:
                    log(f"ivy sim gravity {comp}: {e}")


def get_ivy_sim_params(geo_node):
    """Read current Vellum sim parm values from the network into a UI state dict."""
    result = {}
    if not ivy_sim_network_exists(geo_node):
        return result

    for state_key, (node_name, parm_name) in _SIM_CONFIG_PARMS.items():
        n = geo_node.node(node_name)
        p = n.parm(parm_name) if n is not None else None
        if p is not None:
            try:
                result[state_key] = p.eval()
            except Exception:
                pass

    for state_key, (node_name, parm_name) in _SIM_SOLVER_SCALAR_PARMS.items():
        n = geo_node.node(node_name)
        p = n.parm(parm_name) if n is not None else None
        if p is not None:
            try:
                result[state_key] = p.eval()
            except Exception:
                pass

    solver = geo_node.node("ivy_vellum_solver")
    p = solver.parm("gravityy") if solver is not None else None
    if p is not None:
        try:
            result["ivy_sim_gravity"] = p.eval()
        except Exception:
            pass
    return result


def get_ivy_sim_collision_object(geo_node):
    """Return ivy_sim_collision.objpath1, or an empty string."""
    col = geo_node.node("ivy_sim_collision") if geo_node is not None else None
    return _get_raw_parm(col, "objpath1", "") if col is not None else ""


def get_ivy_glue_params(geo_node):
    """Read glue-on-collision settings from ivy_sim_glue_constraints."""
    result = {
        "ivy_glue_enabled": False,
        "ivy_glue_distance": 0.2,
        "ivy_glue_strength": 1.0,
    }
    glue = geo_node.node("ivy_sim_glue_constraints") if geo_node is not None else None
    if glue is None:
        return result
    try:
        result["ivy_glue_enabled"] = not bool(glue.isBypassed())
    except Exception:
        pass
    p = glue.parm("maxdist")
    if p is not None:
        try:
            result["ivy_glue_distance"] = p.eval()
        except Exception:
            pass
    for pname in ("stretchstiffness", "stiffness"):
        p = glue.parm(pname)
        if p is not None:
            try:
                result["ivy_glue_strength"] = p.eval()
                break
            except Exception:
                pass
    return result


def get_ivy_sim_length_scale(geo_node):
    """Return the min/max strand length scale values."""
    node = geo_node.node("ivy_sim_length_scale") if geo_node is not None else None
    vals = {"min_length": 0.1, "max_length": 1.0}
    if node is None:
        return vals
    for key in ("min_length", "max_length"):
        p = node.parm(key)
        if p is not None:
            try:
                vals[key] = p.eval()
            except Exception:
                pass
    return vals


def get_ivy_transform_params(geo_node):
    """Best-effort restore of shared Ivy transform widgets from live nodes."""
    result = {}
    if geo_node is None:
        return result

    orient = geo_node.node("attribrandomize_orient") or geo_node.node("orient_wrangle")
    if orient is not None:
        for key in ("rot_min", "rot_max", "rot_randomize", "full_rand"):
            p = orient.parm(key)
            if p is not None:
                try:
                    result[key] = bool(p.eval()) if key == "full_rand" else p.eval()
                except Exception:
                    pass

    scatter = geo_node.node("scatter_logic")
    if scatter is not None:
        for key, pname in (
            ("density", "densityscale"),
            ("spacing", "coverage"),
            ("max_points", "emergencylimit"),
            ("relax_iter", "relaxiterations"),
        ):
            p = scatter.parm(pname)
            if p is not None:
                try:
                    result[key] = p.eval()
                except Exception:
                    pass

    paint = geo_node.node("paint_mask")
    if paint is not None:
        for key, pname in (
            ("radius", "stroke_radius"),
            ("falloff_amount", "stroke_opacity"),
            ("falloff_softness", "stroke_softedge"),
        ):
            p = paint.parm(pname)
            if p is not None:
                try:
                    result[key] = p.eval()
                except Exception:
                    pass

    wrangle = geo_node.node("pscale_wrangle")
    if wrangle is not None:
        p = wrangle.parm("global_scale")
        if p is not None:
            try:
                result["global_scale"] = p.eval()
            except Exception:
                pass
        p = wrangle.parm("snippet")
        snippet = ""
        if p is not None:
            try:
                snippet = p.eval()
            except Exception:
                snippet = ""
        if snippet:
            result["uniform_xyz"] = "v@scale" not in snippet
            mins = re.findall(r"fit01\(rand\(@ptnum \+ \d+\), ([0-9.+-]+), ([0-9.+-]+)\)", snippet)
            if mins:
                result["scl_min"] = [float(v[0]) for v in mins[:3]]
                result["scl_max"] = [float(v[1]) for v in mins[:3]]
                if len(result["scl_min"]) == 1:
                    result["scl_min"] *= 3
                    result["scl_max"] *= 3
            m = re.search(r"lerp\(.*?rand_scale,\s*([0-9.+-]+)\)", snippet, re.S)
            if m:
                try:
                    result["pscale_randomize"] = float(m.group(1))
                except Exception:
                    pass
    return result


def simulate_ivy(geo_node, start_frame, end_frame, progress_cb=None):
    """
    Step the timeline from start to end_frame, cooking the sim each frame.
    progress_cb(frame, total) is invoked after each frame if provided.
    """
    if not ivy_sim_network_exists(geo_node):
        raise RuntimeError("No ivy sim network. Create it first.")

    cache = geo_node.node("ivy_sim_cache")
    # Make sure the cache is in pass-through / write mode for live sim
    if cache is not None:
        p = cache.parm("loadfromdisk")
        if p is not None:
            try:
                p.set(0)
            except Exception:
                pass

    start = int(start_frame)
    end   = int(end_frame)
    total = max(1, end - start + 1)

    hou.setFrame(start)
    for i, f in enumerate(range(start, end + 1)):
        hou.setFrame(f)
        try:
            cache.cook(force=True)
        except Exception as e:
            log(f"ivy sim cook frame {f}: {e}")
        if progress_cb is not None:
            try:
                progress_cb(f, total)
            except Exception:
                pass
    log(f"[Ivy Sim] Simulated frames {start}-{end}.")


def get_sim_cache_frame_range(geo_node):
    """Read frame range from ivy_sim_cache. Returns (start, end, inc, substeps)."""
    cache = geo_node.node("ivy_sim_cache") if geo_node else None
    start, end, inc, substeps = 1, 100, 1, 1
    if cache is None:
        return start, end, inc, substeps
    pt = cache.parmTuple("f")
    if pt is not None:
        try:
            vals = pt.eval()
            start = int(vals[0])
            end   = int(vals[1])
            inc   = int(vals[2]) if len(vals) > 2 else 1
        except Exception:
            pass
    else:
        for pname, attr in (("f1", "start"), ("f2", "end"), ("f3", "inc")):
            p = cache.parm(pname)
            if p is not None:
                try:
                    locals()[attr]  # noqa
                except Exception:
                    pass
        p1 = cache.parm("f1")
        p2 = cache.parm("f2")
        p3 = cache.parm("f3")
        if p1: start = int(p1.eval())
        if p2: end   = int(p2.eval())
        if p3: inc   = int(p3.eval())
    p = cache.parm("substeps")
    if p is not None:
        try:
            substeps = int(p.eval())
        except Exception:
            pass
    return start, end, inc, substeps


def set_sim_cache_frame_range(geo_node, start, end, inc=1, substeps=1):
    """Write frame range to ivy_sim_cache."""
    cache = geo_node.node("ivy_sim_cache") if geo_node else None
    if cache is None:
        return
    p = cache.parm("trange")
    if p is not None:
        try:
            p.set(1)
        except Exception:
            pass
    pt = cache.parmTuple("f")
    if pt is not None:
        try:
            for comp in pt:
                try:
                    comp.deleteAllKeyframes()
                except Exception:
                    pass
            pt.set((int(start), int(end), int(inc)))
        except Exception as e:
            log(f"ivy_sim_cache f tuple set: {e}")
    else:
        for pname, val in (("f1", start), ("f2", end), ("f3", inc)):
            p = cache.parm(pname)
            if p is not None:
                try:
                    p.deleteAllKeyframes()
                    p.set(int(val))
                except Exception as e:
                    log(f"ivy_sim_cache parm {pname}: {e}")
    p = cache.parm("substeps")
    if p is not None:
        try:
            p.set(int(substeps))
        except Exception as e:
            log(f"ivy_sim_cache substeps: {e}")


def render_ivy_sim_to_disk(geo_node, start_frame, end_frame, inc=1, substeps=1):
    """
    Write the Vellum sim to a File Cache on disk for fast playback.
    Uses $HIP/geo/ivy_sim_$F4.bgeo.sc by default.
    """
    if not ivy_sim_network_exists(geo_node):
        raise RuntimeError("No ivy sim network. Create it first.")

    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        raise RuntimeError("ivy_sim_cache SOP is missing.")

    # Set frame range via the shared helper so keyframes are cleared first.
    set_sim_cache_frame_range(geo_node, start_frame, end_frame, inc, substeps)

    p = cache.parm("loadfromdisk")
    if p is not None:
        try:
            p.set(0)
        except Exception:
            pass

    p = cache.parm("timedependent")
    if p is not None:
        try:
            p.set(1)
        except Exception as e:
            log(f"ivy_sim_cache timedependent: {e}")

    # Trigger the cache save. Houdini 18/19/20 use "execute" on filecache SOPs.
    executed = False
    for btn_name in ("execute", "render", "savetodisk"):
        p = cache.parm(btn_name)
        if p is not None:
            try:
                p.pressButton()
                executed = True
                break
            except Exception as e:
                log(f"ivy sim cache {btn_name}: {e}")
    if not executed:
        raise RuntimeError("Could not find an execute button on the File Cache SOP.")

    # Switch to read-from-disk so playback is instant
    p = cache.parm("loadfromdisk")
    if p is not None:
        try:
            p.set(1)
        except Exception:
            pass

    log(f"[Ivy Sim] Cached frames {start_frame}-{end_frame} to disk.")


def set_sim_cache_basedir(geo_node, value):
    """Set the Base Folder (basedir) parm on ivy_sim_cache."""
    if geo_node is None:
        return
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        return
    p = cache.parm("basedir")
    if p is not None:
        try:
            p.set(value or "")
        except Exception as e:
            log(f"ivy_sim_cache basedir set: {e}")


def set_sim_cache_basename(geo_node, value):
    """Set the Base Name (basename) parm on ivy_sim_cache."""
    if geo_node is None:
        return
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        return
    p = cache.parm("basename")
    if p is not None:
        try:
            p.set(value or "")
        except Exception as e:
            log(f"ivy_sim_cache basename set: {e}")


def get_sim_cache_basedir(geo_node):
    """Read the Base Folder (basedir) parm from ivy_sim_cache (raw, unevaluated)."""
    if geo_node is None:
        return ""
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        return ""
    p = cache.parm("basedir")
    if p is None:
        return ""
    try:
        return p.unexpandedString()
    except Exception:
        try:
            return p.evalAsString()
        except Exception:
            return ""


def get_sim_cache_basename(geo_node):
    """Read the Base Name (basename) parm from ivy_sim_cache (raw, unevaluated)."""
    if geo_node is None:
        return ""
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        return ""
    p = cache.parm("basename")
    if p is None:
        return ""
    try:
        return p.unexpandedString()
    except Exception:
        try:
            return p.evalAsString()
        except Exception:
            return ""


def set_sim_cache_basedir(geo_node, value):
    """Set the Base Folder (basedir) parm on ivy_sim_cache."""
    if geo_node is None:
        return
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        return
    p = cache.parm("basedir")
    if p is not None:
        try:
            p.set(value or "")
        except Exception as e:
            log(f"ivy_sim_cache basedir set: {e}")


def set_sim_cache_basename(geo_node, value):
    """Set the Base Name (basename) parm on ivy_sim_cache."""
    if geo_node is None:
        return
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        return
    p = cache.parm("basename")
    if p is not None:
        try:
            p.set(value or "")
        except Exception as e:
            log(f"ivy_sim_cache basename set: {e}")


def set_sim_cache_loadfromdisk(geo_node, enabled):
    """Toggle the Load from Disk flag on ivy_sim_cache."""
    if geo_node is None:
        return
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        raise RuntimeError("ivy_sim_cache not found — create the sim network first.")
    p = cache.parm("loadfromdisk")
    if p is None:
        raise RuntimeError("ivy_sim_cache has no 'loadfromdisk' parm.")
    p.set(1 if enabled else 0)
    log(f"[Ivy Sim] Load from Disk: {bool(enabled)}")


def get_sim_cache_loadfromdisk(geo_node):
    """Return the current loadfromdisk flag on ivy_sim_cache (or False)."""
    if geo_node is None:
        return False
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        return False
    p = cache.parm("loadfromdisk")
    return bool(p.eval()) if p is not None else False


# ---------------------------------------------------------------------------
# Ivy Generation filecache bake
# ---------------------------------------------------------------------------

def bake_ivy(geo_node):
    """
    Save the ivy generation to disk via ivy_wires_filecache, then flip it to
    Load-from-Disk so subsequent cooks read the cache instead of re-running
    the ivy Python SOP.
    Returns the file path that was written, or None.
    """
    if geo_node is None:
        raise RuntimeError("No geo node.")
    cache = _get_ivy_filecache(geo_node)
    if cache is None:
        raise RuntimeError(
            "ivy_wires_filecache not found — create the Ivy network first."
        )

    # Only disable load-from-disk; trange/f1/f2 are pushed by the UI before calling.
    p = cache.parm("loadfromdisk")
    if p is not None:
        try:
            p.set(0)
        except Exception as e:
            log(f"ivy bake parm loadfromdisk: {e}")

    executed = False
    p = cache.parm("execute")
    if p is not None:
        try:
            p.pressButton()
            executed = True
        except Exception as e:
            log(f"ivy bake execute: {e}")
    if not executed:
        for btn_name in ("render", "savetodisk", "saveall"):
            p = cache.parm(btn_name)
            if p is not None:
                try:
                    p.pressButton()
                    executed = True
                    break
                except Exception as e:
                    log(f"ivy bake {btn_name}: {e}")
    if not executed:
        raise RuntimeError("Could not find an execute button on ivy_wires_filecache.")

    p = cache.parm("loadfromdisk")
    if p is not None:
        try:
            p.set(1)
        except Exception:
            pass

    file_path = ""
    p = cache.parm("file") or cache.parm("sopoutput")
    if p is not None:
        try:
            file_path = p.evalAsString()
        except Exception:
            try:
                file_path = p.eval()
            except Exception:
                pass

    log(f"[Ivy] Baked ivy generation to disk: {file_path or '(unknown path)'}")
    return file_path


def bake_crawl_ivy(geo_node):
    """
    Save the crawling ivy output to disk via crawl_filecache, then flip it to
    Load-from-Disk so subsequent cooks read the cache instead of re-running
    the expensive Python SOP.
    Returns the file path that was written, or None.
    """
    if geo_node is None:
        raise RuntimeError("No geo node.")
    cache = geo_node.node("crawl_filecache")
    if cache is None:
        raise RuntimeError(
            "crawl_filecache not found — create the Crawling Ivy network first."
        )

    # Only disable load-from-disk; trange/f1/f2 are pushed by the UI before calling.
    p = cache.parm("loadfromdisk")
    if p is not None:
        try:
            p.set(0)
        except Exception as e:
            log(f"crawl bake parm loadfromdisk: {e}")

    executed = False
    p = cache.parm("execute")
    if p is not None:
        try:
            p.pressButton()
            executed = True
        except Exception as e:
            log(f"crawl bake execute: {e}")
    if not executed:
        for btn_name in ("render", "savetodisk", "saveall"):
            p = cache.parm(btn_name)
            if p is not None:
                try:
                    p.pressButton()
                    executed = True
                    break
                except Exception as e:
                    log(f"crawl bake {btn_name}: {e}")
    if not executed:
        raise RuntimeError("Could not find an execute button on crawl_filecache.")

    p = cache.parm("loadfromdisk")
    if p is not None:
        try:
            p.set(1)
        except Exception:
            pass

    # ── also bake crawl_leaves_filecache and enable load-from-disk ────
    leaves_cache = _get_crawl_leaves_filecache(geo_node)
    if leaves_cache is not None:
        p = leaves_cache.parm("loadfromdisk")
        if p is not None:
            try:
                p.set(0)
            except Exception:
                pass
        lc_executed = False
        for btn_name in ("execute", "render", "savetodisk", "saveall"):
            p = leaves_cache.parm(btn_name)
            if p is not None:
                try:
                    p.pressButton()
                    lc_executed = True
                    break
                except Exception as e:
                    log(f"crawl_leaves_filecache bake {btn_name}: {e}")
        if lc_executed:
            p = leaves_cache.parm("loadfromdisk")
            if p is not None:
                try:
                    p.set(1)
                except Exception:
                    pass
            log("[Crawl] crawl_leaves_filecache baked and set to Load from Disk.")
        else:
            log("[Crawl] Warning: could not execute crawl_leaves_filecache bake.")

    file_path = ""
    p = cache.parm("file") or cache.parm("sopoutput")
    if p is not None:
        try:
            file_path = p.evalAsString()
        except Exception:
            try:
                file_path = p.eval()
            except Exception:
                pass

    log(f"[Crawl] Baked crawling ivy output to disk: {file_path or '(unknown path)'}")
    return file_path


def _get_crawl_filecache(geo_node):
    """Return the crawl_filecache (wires cache) node, or None."""
    return geo_node.node("crawl_filecache") if geo_node is not None else None


def _get_crawl_leaves_filecache(geo_node):
    """Return the crawl_leaves_filecache (leaves cache) node.

    Falls back to scatter_filecache for backwards compatibility with
    networks created before the rename.
    """
    if geo_node is None:
        return None
    node = geo_node.node("crawl_leaves_filecache")
    if node is not None:
        return node
    # Legacy fallback — older crawl networks still use scatter_filecache
    return geo_node.node("scatter_filecache")


def _get_crawl_cache_nodes(geo_node):
    """Return a list of all crawl-owned file cache nodes (wires + leaves)."""
    nodes = []
    c = _get_crawl_filecache(geo_node)
    if c is not None:
        nodes.append(c)
    c = _get_crawl_leaves_filecache(geo_node)
    if c is not None:
        nodes.append(c)
    return nodes


def set_crawl_cache_basedir(geo_node, value):
    """Set the Base Folder (basedir) parm on all crawl cache nodes."""
    if geo_node is None:
        return
    for cache in _get_crawl_cache_nodes(geo_node):
        _set_parm(cache, "basedir", value or "")


def set_crawl_cache_basename(geo_node, value):
    """Set the Base Name (basename) parm on all crawl cache nodes."""
    if geo_node is None:
        return
    for cache in _get_crawl_cache_nodes(geo_node):
        _set_parm(cache, "basename", value or "")


def get_crawl_cache_basedir(geo_node):
    """Read the Base Folder (basedir) parm from crawl_filecache (raw, unevaluated)."""
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        return CRAWL_CACHE_DEFAULTS["crawl_cache_basedir"]
    return _get_raw_parm(cache, "basedir", CRAWL_CACHE_DEFAULTS["crawl_cache_basedir"])


def get_crawl_cache_basename(geo_node):
    """Read the Base Name (basename) parm from crawl_filecache (raw, unevaluated)."""
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        return CRAWL_CACHE_DEFAULTS["crawl_cache_basename"]
    return _get_raw_parm(cache, "basename", CRAWL_CACHE_DEFAULTS["crawl_cache_basename"])


def get_crawl_loadfromdisk(geo_node):
    """Return the current loadfromdisk flag on crawl_filecache (or False)."""
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        return False
    p = cache.parm("loadfromdisk")
    return bool(p.eval()) if p is not None else False


def set_crawl_loadfromdisk(geo_node, enabled):
    """Toggle Load from Disk on all crawl cache nodes."""
    if geo_node is None:
        return
    nodes = _get_crawl_cache_nodes(geo_node)
    if not nodes:
        raise RuntimeError("No crawl cache nodes found — create the crawling ivy network first.")
    for cache in nodes:
        _set_parm(cache, "loadfromdisk", 1 if enabled else 0)
    log(f"[Crawl] Load from Disk: {bool(enabled)}")


def set_crawl_filecache_basedir(geo_node, value):
    """Set basedir only on crawl_filecache (curves)."""
    if geo_node is None:
        return
    cache = _get_crawl_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "basedir", value or "")


def set_crawl_filecache_basename(geo_node, value):
    """Set basename only on crawl_filecache (curves)."""
    if geo_node is None:
        return
    cache = _get_crawl_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "basename", value or "")


def set_crawl_filecache_loadfromdisk(geo_node, enabled):
    """Toggle Load from Disk only on crawl_filecache (curves)."""
    if geo_node is None:
        return
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        raise RuntimeError("No crawl cache node found — create the crawling ivy network first.")
    _set_parm(cache, "loadfromdisk", 1 if enabled else 0)


def get_crawl_leaves_cache_basedir(geo_node):
    """Read basedir from crawl_leaves_filecache."""
    cache = _get_crawl_leaves_filecache(geo_node)
    if cache is None:
        return CRAWL_CACHE_DEFAULTS["crawl_cache_basedir"]
    return _get_raw_parm(cache, "basedir", CRAWL_CACHE_DEFAULTS["crawl_cache_basedir"])


def get_crawl_leaves_cache_basename(geo_node):
    """Read basename from crawl_leaves_filecache."""
    cache = _get_crawl_leaves_filecache(geo_node)
    if cache is None:
        return CRAWL_CACHE_DEFAULTS["crawl_cache_basename"]
    return _get_raw_parm(cache, "basename", CRAWL_CACHE_DEFAULTS["crawl_cache_basename"])


def get_crawl_leaves_loadfromdisk(geo_node):
    """Return loadfromdisk flag from crawl_leaves_filecache."""
    cache = _get_crawl_leaves_filecache(geo_node)
    if cache is None:
        return False
    p = cache.parm("loadfromdisk")
    return bool(p.eval()) if p is not None else False


def set_crawl_leaves_cache_basedir(geo_node, value):
    """Set basedir only on crawl_leaves_filecache."""
    if geo_node is None:
        return
    cache = _get_crawl_leaves_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "basedir", value or "")


def set_crawl_leaves_cache_basename(geo_node, value):
    """Set basename only on crawl_leaves_filecache."""
    if geo_node is None:
        return
    cache = _get_crawl_leaves_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "basename", value or "")


def set_crawl_leaves_loadfromdisk(geo_node, enabled):
    """Toggle Load from Disk only on crawl_leaves_filecache."""
    if geo_node is None:
        return
    cache = _get_crawl_leaves_filecache(geo_node)
    if cache is None:
        return
    _set_parm(cache, "loadfromdisk", 1 if enabled else 0)


def set_crawl_cache_version(geo_node, value):
    """Set the Version parm on all crawl cache nodes."""
    if geo_node is None:
        return
    for cache in _get_crawl_cache_nodes(geo_node):
        _set_parm(cache, "version", int(value))


def get_crawl_cache_version(geo_node):
    """Read the Version parm from crawl_filecache."""
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        return CRAWL_CACHE_DEFAULTS["crawl_cache_version"]
    p = cache.parm("version")
    if p is not None:
        try:
            return int(p.eval())
        except Exception:
            pass
    return CRAWL_CACHE_DEFAULTS["crawl_cache_version"]


def set_crawl_cache_timedependent(geo_node, enabled):
    """Set the Time Dependent Cache parm on all crawl cache nodes."""
    if geo_node is None:
        return
    for cache in _get_crawl_cache_nodes(geo_node):
        _set_parm(cache, "timedependent", 1 if enabled else 0)


def get_crawl_cache_timedependent(geo_node):
    """Read the Time Dependent Cache parm from crawl_filecache."""
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        return CRAWL_CACHE_DEFAULTS["crawl_cache_timedependent"]
    p = cache.parm("timedependent")
    if p is not None:
        try:
            return bool(p.eval())
        except Exception:
            pass
    return CRAWL_CACHE_DEFAULTS["crawl_cache_timedependent"]


def set_crawl_cache_trange(geo_node, value):
    """Set the time range type (trange) parm on all crawl cache nodes."""
    if geo_node is None:
        return
    for cache in _get_crawl_cache_nodes(geo_node):
        _set_parm(cache, "trange", int(value))


def get_crawl_cache_trange(geo_node):
    """Read the trange parm from crawl_filecache."""
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        return CRAWL_CACHE_DEFAULTS["crawl_cache_trange"]
    p = cache.parm("trange")
    if p is not None:
        try:
            return int(p.eval())
        except Exception:
            pass
    return CRAWL_CACHE_DEFAULTS["crawl_cache_trange"]


def set_crawl_cache_simulation(geo_node, enabled):
    """Set the Simulation parm on all crawl cache nodes."""
    if geo_node is None:
        return
    for cache in _get_crawl_cache_nodes(geo_node):
        _set_parm(cache, ("simulation", "dosimulation"), 1 if enabled else 0)


def get_crawl_cache_simulation(geo_node):
    """Read the Simulation parm from crawl_filecache."""
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        return CRAWL_CACHE_DEFAULTS["crawl_cache_simulation"]
    for pname in ("simulation", "dosimulation"):
        p = cache.parm(pname)
        if p is not None:
            try:
                return bool(p.eval())
            except Exception:
                pass
    return CRAWL_CACHE_DEFAULTS["crawl_cache_simulation"]


def set_crawl_cache_frame_range(geo_node, start, end, inc=1, substeps=1):
    """Set the frame range (f1, f2, f3) and substeps on all crawl cache nodes."""
    if geo_node is None:
        return
    for cache in _get_crawl_cache_nodes(geo_node):
        for pname, val in (("f1", start), ("f2", end), ("f3", inc), ("substep", substeps)):
            _set_parm(cache, pname, int(val))


def get_crawl_cache_frame_range(geo_node):
    """Read frame range (f1, f2, f3, substep) from crawl_filecache."""
    defaults = CRAWL_CACHE_DEFAULTS
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        return (defaults["crawl_cache_start"], defaults["crawl_cache_end"],
                defaults["crawl_cache_inc"], defaults["crawl_cache_substeps"])
    f1, f2, f3, substep = (defaults["crawl_cache_start"], defaults["crawl_cache_end"],
                           defaults["crawl_cache_inc"], defaults["crawl_cache_substeps"])
    for pname, idx in (("f1", 0), ("f2", 1), ("f3", 2)):
        p = cache.parm(pname)
        if p is not None:
            try:
                val = int(p.eval())
                if idx == 0:
                    f1 = val
                elif idx == 1:
                    f2 = val
                elif idx == 2:
                    f3 = val
            except Exception:
                pass
    p = cache.parm("substep")
    if p is not None:
        try:
            substep = int(p.eval())
        except Exception:
            pass
    return f1, f2, f3, substep


def get_crawl_cache_values(geo_node):
    """Read all crawl cache parm values into a dict (for UI restore)."""
    defaults = dict(CRAWL_CACHE_DEFAULTS)
    if geo_node is None:
        return defaults
    cache = _get_crawl_filecache(geo_node)
    if cache is None:
        return defaults
    defaults["crawl_cache_basedir"] = _get_raw_parm(
        cache, "basedir", defaults["crawl_cache_basedir"])
    defaults["crawl_cache_basename"] = _get_raw_parm(
        cache, "basename", defaults["crawl_cache_basename"])
    for key, pname in (
        ("crawl_cache_version", "version"),
        ("crawl_cache_loadfromdisk", "loadfromdisk"),
        ("crawl_cache_timedependent", "timedependent"),
        ("crawl_cache_trange", "trange"),
    ):
        p = cache.parm(pname)
        if p is not None:
            try:
                defaults[key] = p.eval()
            except Exception:
                pass
    for pname in ("simulation", "dosimulation"):
        p = cache.parm(pname)
        if p is not None:
            try:
                defaults["crawl_cache_simulation"] = p.eval()
                break
            except Exception:
                pass
    for key, pname in (
        ("crawl_cache_start", "f1"),
        ("crawl_cache_end", "f2"),
        ("crawl_cache_inc", "f3"),
        ("crawl_cache_substeps", "substep"),
    ):
        p = cache.parm(pname)
        if p is not None:
            try:
                defaults[key] = int(p.eval())
            except Exception:
                pass
    return defaults


def set_ivy_cache_basedir(geo_node, value):
    """Set the Base Folder (basedir) parm on ivy_wires_filecache."""
    cache = _get_ivy_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "basedir", value or "")


def set_ivy_cache_basename(geo_node, value):
    """Set the Base Name (basename) parm on ivy_wires_filecache."""
    cache = _get_ivy_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "basename", value or "")


def get_ivy_cache_basedir(geo_node):
    """Read the Base Folder (basedir) parm from ivy_wires_filecache (raw, unevaluated)."""
    cache = _get_ivy_filecache(geo_node)
    if cache is None:
        return ""
    p = cache.parm("basedir")
    if p is None:
        return ""
    try:
        return p.unexpandedString()
    except Exception:
        try:
            return p.evalAsString()
        except Exception:
            return ""


def get_ivy_cache_basename(geo_node):
    """Read the Base Name (basename) parm from ivy_wires_filecache (raw, unevaluated)."""
    cache = _get_ivy_filecache(geo_node)
    if cache is None:
        return ""
    p = cache.parm("basename")
    if p is None:
        return ""
    try:
        return p.unexpandedString()
    except Exception:
        try:
            return p.evalAsString()
        except Exception:
            return ""


def set_ivy_timedependent(geo_node, enabled):
    """Toggle the File Cache SOP's Time Dependent Cache flag on ivy_wires_filecache."""
    cache = _get_ivy_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "timedependent", 1 if enabled else 0)


def get_ivy_timedependent(geo_node):
    """Return the current timedependent flag on ivy_wires_filecache (or False)."""
    cache = _get_ivy_filecache(geo_node)
    if cache is None:
        return False
    p = cache.parm("timedependent")
    return bool(p.eval()) if p is not None else False


def set_ivy_trange(geo_node, val):
    """Set trange parm on ivy_wires_filecache (0=Single Frame, 1=Frame Range)."""
    cache = _get_ivy_filecache(geo_node)
    if cache is not None:
        _set_parm(cache, "trange", int(val))


def get_ivy_trange(geo_node):
    """Return the trange parm value on ivy_wires_filecache (0 or 1)."""
    cache = _get_ivy_filecache(geo_node)
    if cache is None:
        return 0
    p = cache.parm("trange")
    return int(p.eval()) if p is not None else 0


def set_ivy_cache_frame_range(geo_node, start, end, inc=1, substeps=1):
    """Set frame range parms on ivy_wires_filecache."""
    cache = _get_ivy_filecache(geo_node)
    if cache is None:
        return
    s, e, i = int(start), int(end), int(max(1, inc))
    substeps = int(max(1, substeps))

    # f triplet (Start / End / Inc) — clear any $FSTART/$FEND expressions first
    pt = cache.parmTuple("f")
    if pt is not None:
        try:
            for comp in pt:
                try:
                    comp.deleteAllKeyframes()
                except Exception:
                    pass
            pt.set((s, e, i))
        except Exception as ex:
            log(f"ivy_wires_filecache f tuple set: {ex}")
    else:
        for pname, val in (("f1", s), ("f2", e), ("f3", i)):
            p = cache.parm(pname)
            if p is not None:
                try:
                    p.deleteAllKeyframes()
                    p.set(val)
                except Exception as ex:
                    log(f"ivy_wires_filecache {pname} set: {ex}")

    # substep/substeps parm name differs between File Cache versions.
    _set_all_existing_parms(cache, ("substep", "substeps"), int(substeps))


def get_ivy_cache_frame_range(geo_node):
    """Return (start, end, inc, substeps) from ivy_wires_filecache parms."""
    cache = _get_ivy_filecache(geo_node)
    if cache is None:
        return (1, 1, 1, 1)
    start = end = inc = substeps = 1
    # Read the f triplet via parmTuple first; fall back to individual parms.
    pt = cache.parmTuple("f")
    if pt is not None:
        try:
            vals = pt.eval()
            start    = int(vals[0]) if len(vals) > 0 else 1
            end      = int(vals[1]) if len(vals) > 1 else 1
            inc      = max(1, int(vals[2])) if len(vals) > 2 else 1
        except Exception:
            pass
    else:
        for attr, pname in (("start", "f1"), ("end", "f2"), ("inc", "f3")):
            p = cache.parm(pname)
            if p is not None:
                try:
                    val = int(p.eval())
                    if attr == "start":    start = val
                    elif attr == "end":    end   = val
                    else:                  inc   = max(1, val)
                except Exception:
                    pass
    val = _get_first_parm_value(cache, ("substep", "substeps"), None)
    if val is not None:
        substeps = int(val)
    return (start, end, inc, substeps)


def set_ivy_loadfromdisk(geo_node, enabled):
    """Toggle the File Cache SOP's Load from Disk flag on ivy_wires_filecache."""
    cache = _get_ivy_filecache(geo_node)
    if cache is None:
        raise RuntimeError("ivy_wires_filecache not found — create the ivy network first.")
    p = cache.parm("loadfromdisk")
    if p is None:
        raise RuntimeError("ivy_filecache has no 'loadfromdisk' parm.")
    p.set(1 if enabled else 0)
    log(f"[Ivy] Load from Disk: {bool(enabled)}")


def get_ivy_loadfromdisk(geo_node):
    """Return the current loadfromdisk flag on ivy_wires_filecache (or False)."""
    cache = _get_ivy_filecache(geo_node)
    if cache is None:
        return False
    p = cache.parm("loadfromdisk")
    return bool(p.eval()) if p is not None else False


def _get_ivy_leaves_filecache(geo_node):
    """Return the Ivy leaves filecache node."""
    if geo_node is None:
        return None
    return geo_node.node("scatter_leaves")


def set_ivy_leaves_loadfromdisk(geo_node, enabled):
    """Toggle scatter_leaves.loadfromdisk for the Ivy Output/Bake leaves control."""
    cache = _get_ivy_leaves_filecache(geo_node)
    if cache is None:
        raise RuntimeError("scatter_leaves not found - create the ivy network first.")
    p = cache.parm("loadfromdisk")
    if p is None:
        raise RuntimeError("scatter_leaves has no 'loadfromdisk' parm.")
    p.set(1 if enabled else 0)
    log(f"[Ivy Leaves] Load from Disk: {bool(enabled)}")


def bake_ivy_leaves(geo_node):
    """Press scatter_leaves.execute and enable scatter_leaves.loadfromdisk after baking."""
    cache = _get_ivy_leaves_filecache(geo_node)
    if cache is None:
        raise RuntimeError("scatter_leaves not found - create the ivy network first.")
    _set_parm(cache, "loadfromdisk", 0)
    p = cache.parm("execute")
    if p is None:
        raise RuntimeError("scatter_leaves has no 'execute' parm.")
    p.pressButton()
    _set_parm(cache, "loadfromdisk", 1)
    out = cache.parm("file") or cache.parm("sopoutput")
    if out is not None:
        try:
            return out.eval()
        except Exception:
            return _get_raw_parm(cache, out.name(), "")
    return ""


def get_ivy_leaves_loadfromdisk(geo_node):
    """Return scatter_leaves.loadfromdisk for the Ivy Output/Bake leaves control."""
    cache = _get_ivy_leaves_filecache(geo_node)
    if cache is None:
        return False
    p = cache.parm("loadfromdisk")
    return bool(p.eval()) if p is not None else False


def set_ivy_sim_collision_object(geo_node, obj_path):
    """Point ivy_sim_collision (object_merge) at an external SOP/OBJ path."""
    if geo_node is None:
        return
    col = geo_node.node("ivy_sim_collision")
    if col is None:
        raise RuntimeError("ivy_sim_collision SOP is missing — create the sim network first.")
    p = col.parm("objpath1")
    if p is None:
        raise RuntimeError("ivy_sim_collision has no 'objpath1' parm.")
    p.set(obj_path or "")
    log(f"[Ivy Sim] Collision object set to: {obj_path!r}")


def reset_ivy_sim(geo_node):
    """Press the 'resimulate' button on ivy_vellum_solver so the sim rewinds."""
    if not ivy_sim_network_exists(geo_node):
        raise RuntimeError("No ivy sim network. Create it first.")
    solver = geo_node.node("ivy_vellum_solver")
    if solver is None:
        raise RuntimeError("ivy_vellum_solver SOP is missing.")
    p = solver.parm("resimulate")
    if p is None:
        raise RuntimeError("ivy_vellum_solver has no 'resimulate' parm.")
    p.pressButton()
    log("[Ivy Sim] Simulation reset (resimulate).")


def set_ivy_sim_loadfromdisk(geo_node, enabled):
    """Toggle the File Cache SOP's Load from Disk flag on ivy_sim_cache."""
    if geo_node is None:
        return
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        raise RuntimeError("ivy_sim_cache not found — create the sim network first.")
    p = cache.parm("loadfromdisk")
    if p is None:
        raise RuntimeError("ivy_sim_cache has no 'loadfromdisk' parm.")
    p.set(1 if enabled else 0)
    log(f"[Ivy Sim] Load from Disk: {bool(enabled)}")


def get_ivy_sim_loadfromdisk(geo_node):
    """Return the current loadfromdisk flag on ivy_sim_cache (or False)."""
    if geo_node is None:
        return False
    cache = geo_node.node("ivy_sim_cache")
    if cache is None:
        return False
    p = cache.parm("loadfromdisk")
    return bool(p.eval()) if p is not None else False


def set_ivy_wire_bypass(geo_node, bypassed):
    """Bypass / un-bypass the ivy_wire (PolyWire) node."""
    if geo_node is None:
        return
    wire = geo_node.node("ivy_wire")
    if wire is None:
        raise RuntimeError("ivy_wire SOP is missing.")
    wire.bypass(bool(bypassed))
    log(f"[Ivy] ivy_wire bypass: {bool(bypassed)}")


def get_ivy_wire_bypass(geo_node):
    """Return True if ivy_wire is currently bypassed."""
    if geo_node is None:
        return False
    wire = geo_node.node("ivy_wire")
    if wire is None:
        return False
    return bool(wire.isBypassed())


def set_crawl_wire_bypass(geo_node, bypassed):
    """
    Bypass / un-bypass the crawl_wire (PolyWire) node. No-op when the
    crawling-ivy network has not been created — the UI's wire toggle calls
    both this and set_ivy_wire_bypass to keep the two wire SOPs in sync.
    """
    if geo_node is None:
        return False
    wire = geo_node.node("crawl_wire")
    if wire is None:
        return False
    wire.bypass(bool(bypassed))
    log(f"[Crawl] crawl_wire bypass: {bool(bypassed)}")
    return True


def set_instancer_bypass(geo_node, bypassed):
    """Bypass / un-bypass the instancer (CopyToPoints) node — hides/shows scattered geometry."""
    if geo_node is None:
        return
    inst = geo_node.node("instancer")
    if inst is None:
        raise RuntimeError("instancer SOP is missing.")
    inst.bypass(bool(bypassed))
    log(f"[Scatter] instancer bypass: {bool(bypassed)}")


def get_instancer_bypass(geo_node):
    """Return True if instancer is currently bypassed."""
    if geo_node is None:
        return False
    inst = geo_node.node("instancer")
    if inst is None:
        return False
    return bool(inst.isBypassed())


_DISPLAY_AS_MAP = {
    "Full Geometry": "full",
    "Point Cloud":   "points",
    "Bounding Box":  "box",
    "Centroid":      "centroid",
    "Hidden":        "hidden",
}
_DISPLAY_AS_RMAP = {v: k for k, v in _DISPLAY_AS_MAP.items()}


def set_instancer_display_as(geo_node, display_str):
    """Set the viewport display mode on the instancer (CopyToPoints) node."""
    if geo_node is None:
        return
    inst = geo_node.node("instancer")
    if inst is None:
        return
    token = _DISPLAY_AS_MAP.get(display_str, "box")
    _set_parm(inst, "viewportlod", token)


def get_instancer_display_as(geo_node):
    """Return the UI display string for the current viewportlod of the instancer."""
    if geo_node is None:
        return "Bounding Box"
    inst = geo_node.node("instancer")
    if inst is None:
        return "Bounding Box"
    p = inst.parm("viewportlod")
    if p is None:
        return "Bounding Box"
    try:
        return _DISPLAY_AS_RMAP.get(p.eval(), "Bounding Box")
    except Exception:
        return "Bounding Box"


def set_instancer_pack(geo_node, pack_on):
    """Set the Pack and Instance toggle on the instancer (CopyToPoints) node."""
    if geo_node is None:
        return
    inst = geo_node.node("instancer")
    if inst is None:
        return
    _set_parm(inst, "pack", 1 if pack_on else 0)


def get_instancer_pack(geo_node):
    """Return True if Pack and Instance is enabled on the instancer node."""
    if geo_node is None:
        return True
    inst = geo_node.node("instancer")
    if inst is None:
        return True
    p = inst.parm("pack")
    if p is None:
        return True
    try:
        return bool(p.eval())
    except Exception:
        return True


def sync_ivy_sim_length_scale(geo_node, min_len, max_len):
    """Push min/max strand length values onto the ivy_sim_length_scale wrangle."""
    if geo_node is None:
        return
    node = geo_node.node("ivy_sim_length_scale")
    if node is None:
        return
    for pname, val in (("min_length", min_len), ("max_length", max_len)):
        p = node.parm(pname)
        if p is None:
            continue
        try:
            p.set(val)
        except Exception as e:
            log(f"ivy_sim_length_scale {pname}: {e}")


def sync_ivy_glue_parms(geo_node, glue_state):
    """
    Push glue state onto ivy_sim_glue_constraints.  Expected keys:
        ivy_glue_enabled  : bool  → bypass flag
        ivy_glue_distance : float → maxdist (world-space threshold)
        ivy_glue_strength : float → stretchstiffness (fallback: stiffness)
    Silently no-ops if the node is missing (sim not yet created).
    """
    if geo_node is None:
        return
    glue = geo_node.node("ivy_sim_glue_constraints")
    if glue is None:
        return
    if "ivy_glue_enabled" in glue_state:
        try:
            glue.bypass(not bool(glue_state["ivy_glue_enabled"]))
        except Exception as e:
            log(f"ivy_sim_glue_constraints bypass: {e}")
    if "ivy_glue_distance" in glue_state:
        p = glue.parm("maxdist")
        if p is not None:
            try:
                p.set(float(glue_state["ivy_glue_distance"]))
            except Exception as e:
                log(f"ivy_sim_glue_constraints maxdist: {e}")
    if "ivy_glue_strength" in glue_state:
        val = float(glue_state["ivy_glue_strength"])
        for pname in ("stretchstiffness", "stiffness"):
            p = glue.parm(pname)
            if p is not None:
                try:
                    p.set(val)
                except Exception as e:
                    log(f"ivy_sim_glue_constraints {pname}: {e}")


def sync_ivy_pscale_ramp(geo_node, enabled):
    """Bypass / un-bypass the ivy_pscale_ramp wrangle."""
    if geo_node is None:
        return
    node = geo_node.node("ivy_pscale_ramp")
    if node is None:
        return
    try:
        node.bypass(not bool(enabled))
    except Exception as e:
        log(f"ivy_pscale_ramp bypass: {e}")


# ---------------------------------------------------------------------------

def get_icon_path():
    """Return absolute path to sp_brush.png next to this package."""
    script_dir  = os.path.dirname(os.path.abspath(__file__))         # .../scripts/scatter_tool
    scripts_dir = os.path.dirname(script_dir)                         # .../scripts
    package_dir = os.path.dirname(scripts_dir)                        # package root
    for ext in [".png", ".svg"]:
        p = os.path.join(package_dir, "icons", "sp_brush" + ext)
        if os.path.exists(p):
            return p
    return ""
