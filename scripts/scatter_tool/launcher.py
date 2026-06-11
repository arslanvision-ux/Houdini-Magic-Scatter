"""
SP Scatter for Houdini – Launcher
===================================
Entry points
------------
  launch()           → open as a floating window (shelf button)
  createInterface()  → return widget for Houdini Python Panel (forwards to ui)

The shelf .xml calls launch().
The Python Panel registration calls createInterface() directly on scatter_tool.ui.
"""

import importlib


def launch():
    """
    Import (and hot-reload for live dev) all modules, then show the
    SP Scatter panel as a floating window.  Called by the shelf button.
    """
    try:
        from scatter_tool.usd_io import prototypes as _up; importlib.reload(_up)
        from scatter_tool.usd_io import materials_mtlx as _um; importlib.reload(_um)
        import scatter_tool.logic     as _l;  importlib.reload(_l)
        import scatter_tool.thumbnail as _t;  importlib.reload(_t)
        import scatter_tool.raycast   as _r;  importlib.reload(_r)
        # Lookdev subsystem — reload in dependency order
        from scatter_tool.lookdev import conventions as _lc; importlib.reload(_lc)
        from scatter_tool.lookdev.engines import base   as _lb; importlib.reload(_lb)
        from scatter_tool.lookdev.engines import arnold as _la; importlib.reload(_la)
        from scatter_tool.lookdev.engines import redshift as _lr; importlib.reload(_lr)
        from scatter_tool.lookdev import engines as _le; importlib.reload(_le)
        from scatter_tool.lookdev import assign as _las; importlib.reload(_las)
        from scatter_tool.lookdev import preview as _lpv; importlib.reload(_lpv)
        from scatter_tool.lookdev import ui     as _lu;  importlib.reload(_lu)
        import scatter_tool.ui        as ui;  importlib.reload(ui)
        ui.show()
    except Exception as e:
        try:
            import hou
            hou.ui.displayMessage(
                f"Magic Scatter World failed to launch:\n{e}",
                severity=hou.severityType.Error,
            )
        except Exception:
            print(f"[Magic Scatter World] Launch error: {e}")
            raise


def createInterface():
    """
    Houdini Python Panel factory.  Houdini calls this when the pane tab opens.
    Hot-reloads all modules so edits take effect without restarting Houdini.
    """
    from scatter_tool.usd_io import prototypes as _up; importlib.reload(_up)
    from scatter_tool.usd_io import materials_mtlx as _um; importlib.reload(_um)
    import scatter_tool.logic     as _l;  importlib.reload(_l)
    import scatter_tool.thumbnail as _t;  importlib.reload(_t)
    import scatter_tool.raycast   as _r;  importlib.reload(_r)
    # Lookdev subsystem — reload in dependency order
    from scatter_tool.lookdev import conventions as _lc; importlib.reload(_lc)
    from scatter_tool.lookdev.engines import base   as _lb; importlib.reload(_lb)
    from scatter_tool.lookdev.engines import arnold as _la; importlib.reload(_la)
    from scatter_tool.lookdev.engines import redshift as _lr; importlib.reload(_lr)
    from scatter_tool.lookdev import engines as _le; importlib.reload(_le)
    from scatter_tool.lookdev import assign as _las; importlib.reload(_las)
    from scatter_tool.lookdev import ui     as _lu;  importlib.reload(_lu)
    import scatter_tool.ui        as ui;  importlib.reload(ui)
    return ui.createInterface()


def launch_ivy():
    """
    Open the Ivy Scatter floating window (Transformation + Ivy Generation
    tabs only).  Independent from the SP Scatter window — its own state,
    its own target network.
    """
    try:
        from scatter_tool.usd_io import prototypes as _up; importlib.reload(_up)
        from scatter_tool.usd_io import materials_mtlx as _um; importlib.reload(_um)
        import scatter_tool.logic     as _l;  importlib.reload(_l)
        import scatter_tool.thumbnail as _t;  importlib.reload(_t)
        import scatter_tool.raycast   as _r;  importlib.reload(_r)
        # Lookdev subsystem — reload in dependency order
        from scatter_tool.lookdev import conventions as _lc; importlib.reload(_lc)
        from scatter_tool.lookdev.engines import base   as _lb; importlib.reload(_lb)
        from scatter_tool.lookdev.engines import arnold as _la; importlib.reload(_la)
        from scatter_tool.lookdev.engines import redshift as _lr; importlib.reload(_lr)
        from scatter_tool.lookdev import engines as _le; importlib.reload(_le)
        from scatter_tool.lookdev import assign as _las; importlib.reload(_las)
        from scatter_tool.lookdev import preview as _lpv; importlib.reload(_lpv)
        from scatter_tool.lookdev import ui     as _lu;  importlib.reload(_lu)
        import scatter_tool.ui        as ui;  importlib.reload(ui)
        ui.show_ivy()
    except Exception as e:
        try:
            import hou
            hou.ui.displayMessage(
                f"Ivy Scatter failed to launch:\n{e}",
                severity=hou.severityType.Error,
            )
        except Exception:
            print(f"[Ivy Scatter] Launch error: {e}")
            raise


def createInterfaceIvy():
    """Python Panel factory for the Ivy Scatter pane tab."""
    from scatter_tool.usd_io import prototypes as _up; importlib.reload(_up)
    from scatter_tool.usd_io import materials_mtlx as _um; importlib.reload(_um)
    import scatter_tool.logic     as _l;  importlib.reload(_l)
    import scatter_tool.thumbnail as _t;  importlib.reload(_t)
    import scatter_tool.raycast   as _r;  importlib.reload(_r)
    import scatter_tool.ui        as ui;  importlib.reload(ui)
    return ui.createInterfaceIvy()


def launch_crawling_ivy():
    """Open the Ivy Scatter window focused on the Crawling Ivy tab."""
    try:
        from scatter_tool.usd_io import prototypes as _up; importlib.reload(_up)
        from scatter_tool.usd_io import materials_mtlx as _um; importlib.reload(_um)
        import scatter_tool.logic     as _l;  importlib.reload(_l)
        import scatter_tool.thumbnail as _t;  importlib.reload(_t)
        import scatter_tool.raycast   as _r;  importlib.reload(_r)
        # Lookdev subsystem — reload in dependency order
        from scatter_tool.lookdev import conventions as _lc; importlib.reload(_lc)
        from scatter_tool.lookdev.engines import base   as _lb; importlib.reload(_lb)
        from scatter_tool.lookdev.engines import arnold as _la; importlib.reload(_la)
        from scatter_tool.lookdev.engines import redshift as _lr; importlib.reload(_lr)
        from scatter_tool.lookdev import engines as _le; importlib.reload(_le)
        from scatter_tool.lookdev import assign as _las; importlib.reload(_las)
        from scatter_tool.lookdev import preview as _lpv; importlib.reload(_lpv)
        from scatter_tool.lookdev import ui     as _lu;  importlib.reload(_lu)
        import scatter_tool.ui        as ui;  importlib.reload(ui)
        ui.show_crawling_ivy()
    except Exception as e:
        try:
            import hou
            hou.ui.displayMessage(
                f"Crawling Ivy failed to launch:\n{e}",
                severity=hou.severityType.Error,
            )
        except Exception:
            print(f"[Crawling Ivy] Launch error: {e}")
            raise


if __name__ == "__main__":
    launch()
