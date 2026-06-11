"""
Material preview sphere.

Creates /obj/scatter_lookdev_preview — a self-contained geo with a sphere
that gets s@shop_materialpath set to whichever material the artist is
currently editing in the Lookdev window. The point isn't a real engine-
accurate preview (that requires an IPR render); it's that the artist
can keep a Render View or floating viewport docked on this single sphere
and see their changes against a known shape.
"""

import hou

PREVIEW_OBJ = "/obj/scatter_lookdev_preview"


def ensure_preview(mat_path):
    """Create or update the preview geo so its sphere gets `mat_path`
    assigned. Returns the /obj geo node."""
    obj = hou.node("/obj")
    if obj is None:
        return None
    geo = obj.node("scatter_lookdev_preview")
    if geo is None:
        geo = obj.createNode("geo", "scatter_lookdev_preview")

    sph = geo.node("preview_sphere")
    if sph is None:
        sph = geo.createNode("sphere", "preview_sphere")
        sph.parm("type").set(2)        # polygon mesh (renderable)
        sph.parm("rows").set(64)
        sph.parm("cols").set(64)

    norm = geo.node("preview_normals")
    if norm is None:
        norm = geo.createNode("normal", "preview_normals")
        norm.setInput(0, sph)

    uv = geo.node("preview_uv")
    if uv is None:
        uv = geo.createNode("uvunwrap", "preview_uv")
        uv.setInput(0, norm)

    aw = geo.node("assign_material")
    if aw is None:
        aw = geo.createNode("attribwrangle", "assign_material")
        aw.setInput(0, uv)
        aw.parm("class").set(1)        # primitives
    # Update the snippet on every call so material path stays in sync
    aw.parm("snippet").set(f's@shop_materialpath = "{mat_path}";')
    aw.setRenderFlag(True)
    aw.setDisplayFlag(True)

    try:
        geo.layoutChildren()
    except Exception:
        pass
    return geo


def show_preview_viewer():
    """Open a floating Scene Viewer focused on the preview sphere."""
    geo = hou.node(PREVIEW_OBJ)
    if geo is None:
        return None

    desktop = hou.ui.curDesktop()
    pane = desktop.createFloatingPaneTab(
        hou.paneTabType.SceneViewer,
        position=(900, 200),
        size=(500, 500),
    )
    try:
        # Frame on the preview object
        geo.setSelected(True, clear_all_selected=True)
        sv = pane
        sv.curViewport().frameSelected()
    except Exception:
        pass
    return pane


def destroy_preview():
    """Remove the preview geo if the artist wants to clean it up."""
    geo = hou.node(PREVIEW_OBJ)
    if geo is not None:
        try:
            geo.destroy()
        except Exception:
            pass
