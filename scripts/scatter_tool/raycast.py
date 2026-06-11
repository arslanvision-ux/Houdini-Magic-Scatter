"""
SP Scatter for Houdini – Viewport Raycasting / Python Viewer State
===================================================================
Provides a lightweight Houdini Python Viewer State that intercepts
mouse events and fires on_press / on_drag / on_release callbacks on
the active ScatterWindow.

Usage (called from ui.py):
    from scatter_tool.raycast import ScatterViewerState, register_state
    register_state()
    viewer.setCurrentState("scatter_tool.paint")

The state is registered once at tool launch time.
"""

import hou
import viewerstate.utils as state_utils

# Name used to register / activate this state
STATE_NAME = "scatter_tool.paint"


# ---------------------------------------------------------------------------
# Viewer State implementation
# ---------------------------------------------------------------------------

class ScatterViewerState(object):
    """
    Houdini Python Viewer State that intercepts LMB drag events and fires
    scatter paint / erase callbacks on the currently open ScatterWindow.

    The state is a minimal wrapper:
        press  → calls window.on_press(hit_pos, hit_normal)
        drag   → calls window.on_drag(hit_pos, hit_normal)
        release→ calls window.on_release()
    """

    MSG = "LMB: Paint | Shift+LMB: Erase | Esc: Exit brush"

    def __init__(self, state_view):
        self.state_view = state_view
        self.scene_viewer = state_view.sceneViewer()
        
        # Get UI window instance to fetch current settings. Resolved through
        # get_active_painter() so the right window is picked when both
        # SP Scatter and Ivy Scatter are open.
        from . import ui
        self.win = ui.get_active_painter()
        self._window = self.win
        
        self.is_dragging = False
        self._pressing = False
        self.last_mouse_pos = (0, 0)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _get_window(self):
        """
        Resolve the ScatterWindow that owns the live paint session. Always
        checks fresh — the active window may switch between calls (e.g.
        user toggles paint off in one window and on in another).
        """
        try:
            import scatter_tool.ui as ui_mod
            active = ui_mod.get_active_painter()
            if active is not None:
                return active
        except Exception:
            pass
        return self._window

    def _raycast(self, ui_event):
        """
        Cast a ray from the cursor into the scene and return
        (hit_pos, hit_normal) or None on miss.
        """
        win = self._get_window()
        if win is None:
            return None

        surface_path = getattr(win, "surface_node_path", "")
        if not surface_path:
            return None

        surface_node = hou.node(surface_path)
        if surface_node is None:
            return None

        # Build ray from viewport
        try:
            viewport = self.scene_viewer.curViewport()
            ray_origin, ray_dir = viewport.mapToWorld(
                ui_event.device().mouseX(),
                ui_event.device().mouseY()
            )
        except Exception:
            return None

        from scatter_tool import logic
        return logic.raycast_geo_node(
            surface_node,
            hou.Vector3(ray_origin),
            hou.Vector3(ray_dir)
        )

    # ------------------------------------------------------------------
    # State callbacks
    # ------------------------------------------------------------------

    def onEnter(self, kwargs):
        self.scene_viewer.setPromptMessage(self.MSG)

    def onExit(self, kwargs):
        self.scene_viewer.clearPromptMessage()
        win = self._get_window()
        if win and hasattr(win, "_on_state_exit"):
            win._on_state_exit()

    def onMouseEvent(self, kwargs):
        ui_event = kwargs["ui_event"]
        dev       = ui_event.device()
        reason    = ui_event.reason()

        # Import inside to avoid circular
        import hou
        LMB_PRESS   = hou.uiEventReason.Start
        LMB_HOLD    = hou.uiEventReason.Active
        LMB_RELEASE = hou.uiEventReason.Changed

        if not dev.isLeftButton() and reason != LMB_RELEASE:
            return False

        win = self._get_window()
        if win is None:
            return False

        hit = self._raycast(ui_event)
        
        if reason == LMB_PRESS:
            self._pressing = True
            if hit:
                if hasattr(win, "on_press"):
                    win.on_press(hit[0], hit[1])
            else:
                print("[Magic Scatter World] No surface hit at mouse press")

        elif reason == LMB_HOLD and self._pressing:
            if hit:
                if hasattr(win, "on_drag"):
                    win.on_drag(hit[0], hit[1])

        elif reason in (LMB_RELEASE, hou.uiEventReason.NoReason) and self._pressing:
            self._pressing = False
            if hasattr(win, "on_release"):
                win.on_release()

        return True   # consumed

    def onDraw(self, kwargs):
        """Draw the brush circle in the viewport."""
        # Simple visual feedback: circles are harder in native GL without a lot of code,
        # but we can at least show the prompt. 
        # For a real brush, we should use hou.GeometryDrawable.
        pass

    def onKeyEvent(self, kwargs):
        key = kwargs["ui_event"].device().keyString()
        if key == "Escape":
            self.scene_viewer.setCurrentState("select")
            return True
        return False


# ---------------------------------------------------------------------------
# State template & registration
# ---------------------------------------------------------------------------

def _build_template():
    """Build the ViewerStateTemplate for ScatterViewerState."""
    template = hou.ViewerStateTemplate(
        STATE_NAME,
        "Magic Scatter World Paint",
        hou.sopNodeTypeCategory()
    )
    template.bindFactory(ScatterViewerState)
    # Note: in Houdini 20+ the state class methods (onDraw, onMouseEvent, …)
    # are discovered automatically — no explicit bindHandler call is needed.

    icon = ""
    try:
        from scatter_tool import logic
        icon = logic.get_icon_path()
    except Exception:
        pass

    if icon:
        template.bindIcon(icon)

    return template


def register():
    """Register the viewer state with Houdini (safe to call multiple times)."""
    try:
        # Check if already registered
        hou.ui.unregisterViewerState(STATE_NAME)
    except Exception:
        pass
    try:
        hou.ui.registerViewerState(_build_template())
    except Exception as e:
        print(f"[Magic Scatter World] Failed to register viewer state: {e}")


def activate_state(scene_viewer):
    """Switch the given viewport to the scatter paint state."""
    try:
        register()
        scene_viewer.setCurrentState(STATE_NAME)
    except Exception as e:
        print(f"[Magic Scatter World] Could not activate paint state: {e}")


def deactivate_state(scene_viewer):
    """Return the viewport to the default Select state."""
    try:
        scene_viewer.setCurrentState("select")
    except Exception:
        pass
