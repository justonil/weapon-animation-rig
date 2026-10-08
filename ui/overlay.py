"""Viewport overlay: grip/tip/pivot markers + labels (grip-config UX).

WHY this exists instead of bones: the rework deliberately keeps ONE export
bone; grips live on as custom-prop vectors. Numbers alone are uneditable
blind -- this overlay shows WHERE each point is (and where the pivot
presets resolve), with zero scene pollution: no objects, no bones, nothing
exported, nothing animated. Pure view layer (plan §34 spirit).

Structure (for headless testability):
- ``collect_markers(armature)`` is PURE (no GL, no context.window): returns
  [(world_pos, label, rgba, size)] and is fully unit-tested.
- ``_draw_3d`` / ``_draw_2d`` only render that list; every failure path
  returns silently -- a draw callback must NEVER break the viewport.
- Handler installation is skipped in background mode (``bpy.app.background``,
  where no GL context exists); registration itself always succeeds so the
  headless test suites keep passing.
"""
import bpy

MARKER_3D = "POST_VIEW"
MARKER_2D = "POST_PIXEL"

_handle_3d = None
_handle_2d = None


def collect_markers(armature):
    """World-space markers for the weapon configuration.

    Returns a list of (position: Vector, label: str, color: 4-tuple,
    size: float). Stored points (grips/tip) are large; derived pivot
    points (guard/pommel/center) are smaller and dimmer.
    Raises WeaponRigError when no rig exists (callers: except -> skip).
    """
    from ..utils import constraints as con_util
    from ..weapon import pivot as pivot_mod
    from ..utils import transforms

    weapon = con_util.get_weapon_bone(armature)
    if weapon not in armature.data.bones:
        from ..constants import WeaponRigError
        raise WeaponRigError("no weapon rig")
    dg = transforms.evaluated_depsgraph()
    markers = []

    def add(preset, label, color, size):
        pos = pivot_mod.compute_pivot_world(armature, preset, dg=dg)
        markers.append((pos.copy(), label, color, size))

    add('GRIP_R', "Grip R", (1.0, 0.35, 0.3, 1.0), 0.025)
    add('GRIP_L', "Grip L", (0.35, 1.0, 0.45, 1.0), 0.025)
    add('TIP', "Tip", (1.0, 0.85, 0.25, 1.0), 0.025)
    add('GUARD_L', "Guard L", (0.4, 0.8, 1.0, 0.85), 0.016)
    add('GUARD_R', "Guard R", (0.4, 0.8, 1.0, 0.85), 0.016)
    add('POMMEL', "Pommel", (0.4, 0.8, 1.0, 0.85), 0.016)
    add('CENTER', "Center", (0.7, 0.7, 0.9, 0.8), 0.014)
    # The single Guard PIVOT (midpoint of the quillon ends): drawn
    # explicitly so Set Pivot -> Guard lands on a visible point.
    gl = _by_label(markers, "Guard L")
    gr = _by_label(markers, "Guard R")
    if gl is not None and gr is not None:
        markers.append(((gl + gr) * 0.5, "Guard",
                        (0.55, 0.95, 1.0, 1.0), 0.022))
    return markers


def _by_label(markers, label):
    for pos, name, _color, _size in markers:
        if name == label:
            return pos
    return None


def _resolve_armature():
    scene = bpy.context.scene
    if scene is None:
        return None
    arm = getattr(scene, "wpn_armature", None)
    if arm is not None:
        try:
            if arm.type == 'ARMATURE':
                return arm
        except ReferenceError:
            return None
    active = bpy.context.view_layer.objects.active
    if active is not None and active.type == 'ARMATURE':
        return active
    return None


def _draw_3d():
    try:
        scene = bpy.context.scene
        if scene is None or not getattr(scene, "wpn_show_grips", True):
            return
        arm = _resolve_armature()
        if arm is None:
            return
        markers = collect_markers(arm)
        if not markers:
            return
        import gpu
        from gpu_extras.batch import batch_for_shader
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        lines = []
        for pos, _label, _color, size in markers:
            s = size
            # 3D cross (orientation-independent, no billboarding needed).
            lines.extend([
                (pos.x - s, pos.y, pos.z), (pos.x + s, pos.y, pos.z),
                (pos.x, pos.y - s, pos.z), (pos.x, pos.y + s, pos.z),
                (pos.x, pos.y, pos.z - s), (pos.x, pos.y, pos.z + s),
            ])
        # One batch per color group keeps state changes minimal.
        offset = 0
        for _pos, _label, color, _size in markers:
            shader.uniform_float("color", color)
            sub = batch_for_shader(shader, 'LINES',
                                   {"pos": lines[offset:offset + 6]})
            sub.draw(shader)
            offset += 6
        # Handle axis (grip R -> grip L), blade axis (grip L -> tip)
        # and crossguard bar (guard L -> guard R), by label.
        by_label = {label: pos for pos, label, _, _ in markers}
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.45))
        for chain in (("Grip R", "Grip L", "Tip"),
                      ("Guard L", "Guard R")):
            if all(label in by_label for label in chain):
                batch_for_shader(shader, 'LINE_STRIP',
                                 {"pos": [tuple(by_label[label])
                                          for label in chain]}).draw(shader)
    except Exception:
        return


def _draw_2d():
    try:
        import blf
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        scene = bpy.context.scene
        if scene is None or not getattr(scene, "wpn_show_grips", True):
            return
        region = bpy.context.region
        rv3d = bpy.context.region_data
        if region is None or rv3d is None:
            return
        arm = _resolve_armature()
        if arm is None:
            return
        markers = collect_markers(arm)
        font_id = 0
        blf.size(font_id, 13)
        for pos, label, color, _size in markers:
            xy = location_3d_to_region_2d(region, rv3d, pos)
            if xy is None:  # behind the camera
                continue
            blf.color(font_id, color[0], color[1], color[2], 1.0)
            blf.position(font_id, xy.x + 10, xy.y + 6, 0)
            blf.draw(font_id, label)
    except Exception:
        return


def register():
    global _handle_3d, _handle_2d
    if bpy.app.background:
        return  # no GL context headless; pure logic still importable
    try:
        _handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            _draw_3d, (), 'WINDOW', MARKER_3D)
        _handle_2d = bpy.types.SpaceView3D.draw_handler_add(
            _draw_2d, (), 'WINDOW', MARKER_2D)
    except Exception:
        _handle_3d = _handle_2d = None


def unregister():
    global _handle_3d, _handle_2d
    for handle in (_handle_3d, _handle_2d):
        if handle is None:
            continue
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
        except (ValueError, ReferenceError, RuntimeError):
            pass
    _handle_3d = _handle_2d = None
