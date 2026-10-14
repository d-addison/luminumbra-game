"""Declaration of the future host boundary, not an installed lifecycle hook.

G3 supplies the adapter and a paired engine integration. Registration in G1 is
deliberately inert: it installs no handlers, timers, operators or listeners.
"""

SURFACE_VERSION = 1
IMPLEMENTATION_STATUS = "skeleton"
EXECUTION_FEATURES = ()
REQUIRED_SERVICE_FEATURES = ("meshgen_configuration", "meshgen_script_pins")
BUDGETED_BUILD_FEATURE = "max_tris_setting"

# Pending import plans are invalidated by every event below. Scene edits do
# not cancel inference; document/session changes prevent staging. Ownership,
# cancellation and process-tree termination remain with the engine broker.
INVALIDATION_EVENTS = (
    "edit", "undo", "redo", "load", "unload", "scope_changed",
    "config_changed", "project_changed", "session_changed",
)

# Future paired host calls; these names declare a seam, not engine APIs that
# already exist. Import mutation runs in one main-thread undoable operator.
INTEGRATION_POINTS = (
    "invalidate_import_plans", "prevent_staging_after_context_change",
    "review_import_plan", "apply_reviewed_import", "propagate_derivation_origins",
    "validate_origins_at_mark", "validate_origins_at_build",
)


def register():
    """Blender extension entry point, reserved for G3 integration."""


def unregister():
    """Blender extension exit point, reserved for G3 integration."""
