"""
Prototype cache.

For each scatter asset SOP, write its cooked geometry to a USD file on disk
under  $HIP/usd/prototypes/<system>/asset_<i>.usd .  The PointInstancer's
Prototypes relationship then targets a Reference LOP that loads that file.

SOP → USD is delegated to Houdini's native `sopimport` + `usd_rop` LOP
pipeline, so packed primitives — including Redshift Proxy and Arnold
Standin packed prims — are preserved end-to-end rather than collapsed
to a 1-vertex polymesh.

Hash-based invalidation
-----------------------
Before re-exporting we compute a content digest of the SOP geometry that
includes both point positions (for regular geo) AND per-prim intrinsic
values (so changing a `.rs` proxy file path invalidates the cache too).
The digest is stamped onto the cached layer's `customLayerData` so we can
read it back via Sdf-only access without putting a Stage into USD's
in-process registry (which would block overwrites).
"""

import hashlib
import os
import struct
import uuid

import hou
from pxr import Sdf, Usd

DIGEST_KEY = "msw_proto_digest"
DEFAULT_PRIM_NAME = "asset"


# ── Paths ───────────────────────────────────────────────────────────────────
def cache_dir_for(system_name):
    """Return the on-disk directory holding all cached prototypes for one
    scatter system. Honours $HIP via hou.expandString."""
    return hou.expandString(f"$HIP/usd/prototypes/MSW_{system_name}")


def cache_path_for(system_name, asset_index, asset_node_name):
    safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in asset_node_name)
    path = os.path.join(
        cache_dir_for(system_name),
        f"asset_{asset_index:02d}_{safe_name}.usd",
    )
    return path.replace("\\", "/")


# ── Digesting ───────────────────────────────────────────────────────────────
def _geometry_digest(geo):
    """Content hash that captures both regular geometry (positions + topology)
    AND packed-prim metadata (intrinsics including filename/transform). The
    latter is what invalidates the cache when a Redshift Proxy `.rs` path
    changes inside an otherwise-identical SOP chain."""
    h = hashlib.sha1()

    for pt in geo.points():
        p = pt.position()
        h.update(struct.pack("3f", p[0], p[1], p[2]))

    for prim in geo.prims():
        h.update(struct.pack("i", prim.numVertices()))
        for v in prim.vertices():
            h.update(struct.pack("i", v.point().number()))
        try:
            intrinsics = prim.intrinsicValueDict()
        except Exception:
            intrinsics = {}
        for k in sorted(intrinsics):
            h.update(f"{k}={intrinsics[k]!r}".encode("utf-8", errors="replace"))

    return h.hexdigest()


def _read_cached_digest(cache_path):
    """Return the digest stored on the cached layer, or '' if missing /
    corrupt / unstamped. Uses Sdf-level access so we don't put a Stage
    into USD's registry (which would block overwrites)."""
    if not os.path.exists(cache_path):
        return ""
    try:
        layer = Sdf.Layer.FindOrOpen(cache_path)
        if layer is None:
            return ""
        return str(layer.customLayerData.get(DIGEST_KEY, ""))
    except Exception:
        return ""


# ── Houdini-native SOP → USD export ────────────────────────────────────────
def _ensure_stage_net():
    stage_net = hou.node("/stage")
    if stage_net is None:
        stage_net = hou.node("/").createNode("lopnet", "stage")
    return stage_net


def _set_parm(node, parm_names, value):
    """Set the first parm matching any name in `parm_names`. Exact match
    first (fast path); if that fails, fall back to a case-insensitive
    substring search across the node's parm names. Substring matching is
    needed because some plugins (e.g. Redshift LOPs) encode parm names
    via punycode with a version-dependent hash suffix — the only stable
    fragment is a substring of the logical name."""
    for pname in parm_names:
        p = node.parm(pname)
        if p is not None:
            try:
                p.set(value)
                return True
            except Exception:
                continue
    for p in node.parms():
        lowered = p.name().lower()
        for pname in parm_names:
            if pname.lower() in lowered:
                try:
                    p.set(value)
                    return True
                except Exception:
                    continue
    return False


def _detect_redshift_proxy_path(geo):
    """Return the `.rs` archive path this asset references, or None.

    Houdini's instance-file workflow stores the proxy path on a point
    attribute named `instancefile` (sopimport then promotes it to
    `primvars:instancefile`). We check that first; as a fallback we also
    scan packed-prim intrinsics in case a native Redshift Proxy packed
    primitive ever carries the path there directly."""
    inst_attr = geo.findPointAttrib("instancefile")
    if inst_attr is not None and len(geo.points()) > 0:
        try:
            val = geo.points()[0].attribValue(inst_attr)
            if isinstance(val, str) and val.lower().endswith(".rs"):
                return val.replace("\\", "/")
        except Exception:
            pass

    if len(geo.prims()) == 1:
        prim = geo.prims()[0]
        try:
            intrinsics = prim.intrinsicValueDict()
        except Exception:
            intrinsics = {}
        for v in intrinsics.values():
            if isinstance(v, str) and v.lower().endswith(".rs"):
                return v.replace("\\", "/")

    return None


def _export_via_sopimport(sop_node, cache_path, frame_range=None):
    """Standard SOP → USD: `sopimport` + `usd_rop`. Handles polymesh and
    other geometry Houdini's stock translator knows about.

    frame_range — optional (start, end, inc) tuple.  When provided the
    usd_rop bakes that frame range as USD time samples into a single file.
    When None (default) only the current frame is written.
    """
    stage_net = _ensure_stage_net()
    suffix = uuid.uuid4().hex[:8]
    sopimp = None
    usdrop = None
    try:
        sopimp = stage_net.createNode("sopimport", f"_msw_tmp_imp_{suffix}")
        sopimp.parm("soppath").set(sop_node.path())
        sopimp.parm("pathprefix").set(f"/{DEFAULT_PRIM_NAME}")

        usdrop = stage_net.createNode("usd_rop", f"_msw_tmp_rop_{suffix}")
        usdrop.setInput(0, sopimp)
        usdrop.parm("lopoutput").set(cache_path)

        if frame_range is not None:
            start, end, inc = frame_range
            p_trange = usdrop.parm("trange")
            if p_trange is not None:
                try:
                    p_trange.set(1)
                except Exception:
                    pass
            for pname, val in (("f1", float(start)), ("f2", float(end)), ("f3", float(inc))):
                p = usdrop.parm(pname)
                if p is not None:
                    try:
                        p.set(val)
                    except Exception:
                        pass

        btn = usdrop.parm("execute") or usdrop.parm("render")
        if btn is None:
            raise hou.NodeError(
                "usd_rop LOP has no 'execute' or 'render' button — "
                "unexpected Houdini build"
            )
        btn.pressButton()
    finally:
        for n in (usdrop, sopimp):
            if n is not None:
                try:
                    n.destroy()
                except Exception:
                    pass


def classify_asset(sop_node):
    """Inspect the asset SOP and return a dict describing how its prototype
    prim should be authored on the USD stage.

    Returns one of:
      {"kind": "regular"}                            – cache geometry to disk
      {"kind": "redshift_proxy", "path": "<.rs>"}    – author via RS_Proxy LOP
    """
    if sop_node is None:
        return {"kind": "regular"}
    try:
        sop_node.cook(force=True)
    except Exception:
        return {"kind": "regular"}
    geo = sop_node.geometry()
    if geo is None:
        return {"kind": "regular"}
    rs_path = _detect_redshift_proxy_path(geo)
    if rs_path:
        return {"kind": "redshift_proxy", "path": rs_path}
    return {"kind": "regular"}


# Candidate type-name chain for the Redshift Proxy LOP — Houdini build /
# Redshift version drift makes a single literal unreliable. Order: newest
# canonical first, older / alternate spellings as fallbacks.
_RS_PROXY_LOP_TYPES = (
    "RS_Proxy::1.0", "RS_Proxy",
    "Redshift::Proxy", "redshift::Proxy",
    "redshift_proxy", "redshift::proxy",
)


def create_redshift_proxy_lop(parent, name, rs_path, primpath):
    """Create a Redshift Proxy LOP under `parent` authoring a Redshift-
    typed proxy prim at `primpath` that references `rs_path`. Caller is
    responsible for wiring inputs/outputs.

    Returns the created LOP node. Raises hou.NodeError if the Redshift
    Houdini plugin isn't providing a recognised LOP node-type."""
    rs_lop = None
    for type_name in _RS_PROXY_LOP_TYPES:
        try:
            rs_lop = parent.createNode(type_name, name)
            break
        except hou.OperationFailed:
            continue
    if rs_lop is None:
        raise hou.NodeError(
            "Could not create Redshift Proxy LOP — none of "
            f"{_RS_PROXY_LOP_TYPES} are registered. Is the Redshift "
            "Houdini plugin loaded with Solaris support?"
        )

    if not _set_parm(
        rs_lop,
        ("primpath", "primpath1", "primitivepath", "primitivepaths"),
        primpath,
    ):
        raise hou.NodeError(
            f"Redshift Proxy LOP ({rs_lop.type().name()}) has no "
            "recognised primpath parm."
        )
    if not _set_parm(
        rs_lop,
        ("filepath", "filepath1", "file", "proxyfile",
         "proxy_file", "proxy_filepath"),
        rs_path,
    ):
        raise hou.NodeError(
            f"Redshift Proxy LOP ({rs_lop.type().name()}) has no "
            "recognised proxy-file parm."
        )
    return rs_lop


def _stamp_layer_metadata(cache_path, digest):
    """Post-process the cached layer: set defaultPrim so references resolve
    without an explicit prim path, and stash the content digest in
    customLayerData for next-call cache-skip."""
    layer = Sdf.Layer.FindOrOpen(cache_path)
    if layer is None:
        raise hou.NodeError(
            f"cache_asset: USD ROP completed but {cache_path} could not be "
            "opened — check ROP output for errors."
        )
    if not layer.defaultPrim:
        layer.defaultPrim = DEFAULT_PRIM_NAME
    layer.customLayerData = {DIGEST_KEY: digest}
    layer.Save()


# ── Curves post-processing ─────────────────────────────────────────────────
def ensure_curves_widths(cache_path, default_width=0.005):
    """Add a constant 'widths' value to any BasisCurves prims that lack one.

    Arnold requires explicit widths on BasisCurves to render them — zero or
    missing widths produce invisible curves.  Karma has a built-in default so
    the absence only matters for Arnold.
    """
    if not os.path.exists(cache_path):
        return
    try:
        from pxr import UsdGeom, Vt
        stage = Usd.Stage.Open(cache_path)
        edited = False
        for prim in stage.Traverse():
            if prim.GetTypeName() != "BasisCurves":
                continue
            curves = UsdGeom.BasisCurves(prim)
            widths_attr = curves.GetWidthsAttr()
            if widths_attr and widths_attr.HasValue():
                continue
            curves.CreateWidthsAttr(Vt.FloatArray([default_width]))
            curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)
            edited = True
        if edited:
            stage.GetRootLayer().Save()
    except Exception as e:
        print(f"[MSW/USD] ensure_curves_widths: {e}")


# ── Public entry point ─────────────────────────────────────────────────────
def cache_asset(sop_node, cache_path, force=False, frame_range=None):
    """Cache `sop_node`'s cooked geometry to `cache_path` as USD.

    Returns True if the file was (re)written, False if skipped via digest match.
    Raises hou.NodeError if the SOP cannot be cooked or has no geometry.

    frame_range — optional (start, end, inc) tuple passed to the usd_rop.
    When provided the digest check is skipped (the single-frame digest is
    not representative of the full baked range) and the USD is always written.
    """
    if sop_node is None:
        raise hou.NodeError("cache_asset: sop_node is None")

    try:
        sop_node.cook(force=True)
    except hou.OperationFailed as e:
        raise hou.NodeError(f"cache_asset: cook failed for {sop_node.path()}: {e}")

    geo = sop_node.geometry()
    if geo is None:
        raise hou.NodeError(f"cache_asset: {sop_node.path()} has no geometry")

    n_pts = len(geo.points())
    n_prims = len(geo.prims())
    if n_pts == 0 and n_prims == 0:
        raise hou.NodeError(
            f"cache_asset: {sop_node.path()} cooked to empty geometry "
            "(no points, no prims). Check upstream asset SOP."
        )

    cache_path = cache_path.replace("\\", "/")
    digest = _geometry_digest(geo)
    # Sequence export always re-writes (digest covers only a single frame).
    if not force and frame_range is None and digest == _read_cached_digest(cache_path):
        return False

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    _export_via_sopimport(sop_node, cache_path, frame_range=frame_range)
    _stamp_layer_metadata(cache_path, digest)
    return True
