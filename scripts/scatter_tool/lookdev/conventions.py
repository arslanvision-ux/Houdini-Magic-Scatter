"""
Per-engine texture / color conventions.

Each renderer disagrees about:
  - colorspace string  (sRGB vs Raw / linear)
  - UDIM token         (<udim> vs <UDIM>)
  - normal-map flavor  (OpenGL Y+ vs DirectX Y-)
  - displacement mid   (0 vs 0.5)

Keeping these in one table makes it trivial to add a new engine later.
"""

import os
import re

UDIM_RE = re.compile(r"(?<!\d)(10\d{2})(?!\d)")


def detect_udim(path):
    """If the file path contains a '1001'-style UDIM tag, return a glob
    pattern using <UDIM>; otherwise return the path unchanged."""
    if not path:
        return path
    base = os.path.basename(path)
    m = UDIM_RE.search(base)
    if not m:
        return path
    new_base = base[:m.start()] + "<UDIM>" + base[m.end():]
    return os.path.join(os.path.dirname(path), new_base)


def replace_udim_token(path, token):
    """Swap the canonical <UDIM> placeholder for an engine-specific token."""
    if not path or "<UDIM>" not in path:
        return path
    return path.replace("<UDIM>", token)


# ── Per-engine conventions ──────────────────────────────────────────────────
ARNOLD = {
    "udim_token": "<udim>",
    "cs_color":   "sRGB",
    "cs_raw":     "Raw",
}

REDSHIFT = {
    "udim_token": "<UDIM>",
    "cs_color":   "sRGB",
    "cs_raw":     "Raw",
}


# ── Default exposed-parm values ────────────────────────────────────────────
DEFAULT_PARMS = {
    "basecolor_tint":     (1.0, 1.0, 1.0),
    "roughness_mult":     1.0,
    "metallic_mult":      1.0,
    "normal_strength":    1.0,
    "displace_scale":     0.05,
    "displace_mid":       0.5,
    "emission_color":     (1.0, 1.0, 1.0),
    "emission_intensity": 0.0,
}

TEXTURE_SLOTS = ("diffuse", "roughness", "metallic", "normal", "displacement")
