"""Interactive weapon rotation about an arbitrary pivot (user request).

WHAT THIS DOES: rotates the single ``weapon`` bone about a FIXED pivot
point so the pivot->drag vector aligns with a target direction. The pivot
never moves; the weapon never translates -- pure rotation (plan §56:
matrices/quaternions only).

SEMANTICS vs snap/pivot (deliberate difference, documented here because it
is easy to get wrong):
- snap/pivot REPOSITION the weapon (or its origin) and therefore re-glue
  attached hands in place -- the hands are the reference/target there.
- rotate only ORIENTS: attached hands follow rigidly through their
  constraints (that's the entire point of rotating a held sword), detached
  hands are untouched (constraint off -- nothing to follow with).

MATH (all world space):
    P  = pivot world position (fixed for the whole gesture)
    D  = drag-point world position (a named weapon point)
    T  = desired target world position (cursor, mouse ray hit, ...)
    u  = normalize(D - P)            (current drag direction)
    v  = normalize(T - P)            (desired drag direction)
    R  = _align_rotation(u, v)       (minimal arc; own implementation
                                      because mathutils
                                      rotation_difference is unstable
                                      for EXACTLY anti-parallel vectors
                                      -- verified: 0.78 deg error)
    W_new = Translate(P) @ R @ Translate(-P) @ W_old

VERIFICATION (plan §30): pivot world unchanged, |drag - pivot| radius
unchanged (rigid rotation), angle between new drag direction and desired
direction ~0. On failure the previous weapon matrix is restored and a
clear error raised -- never a half-applied rotation.

EDGE CASES (plan §54/§55 style -- explicit errors, no silent garbage):
- drag point coincides with pivot  -> rotation undefined, refuse;
- target coincides with pivot     -> desired direction undefined, refuse.

KEYFRAME POLICY (plan §31): viewport interaction -- no keys unless
requested (explicit [Key] / Auto Key). Keying covers changed weapon
channels with the usual frame-1 guard.
"""
import math

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from ..constants import (
    TOL_TRANSLATION,
    WeaponRigError,
)
from ..utils import transforms

# Degenerate geometry threshold (world units).
_EPS_DIR = 1e-6
# Sin(angle) below this -> u/v (anti-)parallel: Rodrigues axis becomes
# noise-dominated, switch to an exact branch.
_EPS_SIN = 1e-6
# Direction-alignment tolerance, degrees (same bar as aim, plan §51).
_TOL_ALIGN_DEG = 0.5


def _align_rotation(u, v):
    """Minimal 3x3 rotation taking unit vector ``u`` onto ``v``.

    Stable everywhere, including the degenerate cases:
    - u ==  v -> identity (no rotation needed);
    - u == -v -> exactly 180 deg about an axis perpendicular to u
      (deterministic: the world axis least aligned with u), so u maps
      to -u == v to full precision.
    mathutils' Vector.rotation_difference picks an unstable axis in the
    exactly-antiparallel case (measured 0.78 deg misalignment), which is
    why this helper exists.
    """
    w = u.cross(v)
    s = w.length
    c = max(-1.0, min(1.0, u.dot(v)))
    if s >= _EPS_SIN:
        # Rodrigues: stable for every non-degenerate pair.
        return Matrix.Rotation(math.atan2(s, c), 3, w / s)
    if c > 0.0:
        return Matrix.Rotation(0.0, 3, Vector((0.0, 0.0, 1.0)))
    # Anti-parallel: any axis perpendicular to u works and is exact.
    basis = (Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)),
             Vector((0.0, 0.0, 1.0)))
    helper = min(basis, key=lambda a: abs(a.dot(u)))
    axis = u.cross(helper)
    axis.normalize()
    return Matrix.Rotation(math.pi, 3, axis)


def rotate_toward(armature, pivot, drag, target_world, key=False,
                  frame=None, custom=(0.0, 0.0, 0.0)):
    """Rotate the weapon about ``pivot`` so pivot->``drag`` points along
    pivot->``target_world``.

    ``pivot``/``drag`` are pivot-preset names resolving to weapon points
    ('TIP', 'GUARD_L', 'POMMEL', ... -- CURSOR/CUSTOM allowed for pivot).
    ``target_world`` is a world-space Vector (e.g. 3D cursor or a mouse-ray
    hit on the view plane through the pivot).

    Returns diagnostics {angle_error_deg, pivot_shift, keyed}.
    """
    from ..utils import constraints as con_util
    from ..weapon import pivot as pivot_mod

    weapon = con_util.get_weapon_bone(armature)
    if frame is None:
        frame = bpy.context.scene.frame_current

    dg = transforms.evaluated_depsgraph()
    w_before = transforms.get_pose_bone_world_matrix(armature, weapon, dg)
    hands_before = {
        side: transforms.get_pose_bone_world_matrix(armature, name, dg)
        for side, name in (("R", "c_hand_ik.r"), ("L", "c_hand_ik.l"))
        if name in armature.data.bones}

    pivot_w = pivot_mod.compute_pivot_world(armature, pivot, custom, dg)
    drag_w = pivot_mod.compute_pivot_world(armature, drag, dg=dg)

    u = drag_w - pivot_w
    v = target_world - pivot_w
    if u.length < _EPS_DIR:
        raise WeaponRigError(
            "Rotate failed: drag point '%s' coincides with pivot '%s' -- "
            "rotation axis is undefined. Pick different points."
            % (drag, pivot))
    if v.length < _EPS_DIR:
        raise WeaponRigError(
            "Rotate failed: target coincides with the pivot -- desired "
            "direction is undefined. Move the target away from %s." % pivot)
    u.normalize()
    v.normalize()

    radius = (drag_w - pivot_w).length
    rot = _align_rotation(u, v)
    w_new = (Matrix.Translation(pivot_w) @ rot.to_4x4()
             @ Matrix.Translation(-pivot_w) @ w_before)

    from ..animation import keyframes
    old_channels = keyframes.capture_channels(armature, weapon)
    transforms.set_pose_bone_arm_matrix(
        armature, weapon, armature.matrix_world.inverted() @ w_new)
    transforms.update_view_layer()

    # --- verification (plan §30) ----------------------------------------
    dg = transforms.evaluated_depsgraph()
    w_after = transforms.get_pose_bone_world_matrix(armature, weapon, dg)
    problems = []
    angle_error = 0.0
    # 1. Pivot locked.
    pw_now = _pivot_now(armature, pivot, custom, dg)
    if (pw_now - pivot_w).length > TOL_TRANSLATION:
        problems.append("pivot moved %.6f (must stay locked)"
                        % (pw_now - pivot_w).length)
    # 2. Radius preserved (rigid rotation, no drift/scale).
    drag_now = pivot_mod.compute_pivot_world(armature, drag, dg)
    if abs((drag_now - pw_now).length - radius) > TOL_TRANSLATION:
        problems.append("drag radius changed (not a pure rotation)")
    # 3. Direction aligned with the target.
    got_dir = (drag_now - pw_now)
    if got_dir.length < _EPS_DIR:
        problems.append("drag point collapsed onto pivot")
    else:
        ang = math.degrees(got_dir.normalized().angle(v))
        if ang > _TOL_ALIGN_DEG:
            problems.append("direction off by %.4f deg" % ang)
        angle_error = ang
    # 4. Attached hands followed rigidly == same world delta as weapon.
    w_delta = w_after @ w_before.inverted()
    for sname, hb in (("R", "c_hand_ik.r"), ("L", "c_hand_ik.l")):
        if sname not in hands_before:
            continue
        con = con_util.find_attach_constraint(armature, sname)
        now = transforms.get_pose_bone_world_matrix(armature, hb, dg)
        if con is not None and con.influence > 0.0:
            want = w_delta @ hands_before[sname]
            t_err, _ = transforms.matrix_difference(want, now)
            if t_err > 1e-3:
                problems.append("attached hand %s did not follow rigidly "
                                "(%.6f)" % (sname, t_err))
        else:
            t_err, _ = transforms.matrix_difference(hands_before[sname],
                                                    now)
            if t_err > TOL_TRANSLATION:
                problems.append("detached hand %s moved %.6f (must not)"
                                % (sname, t_err))

    if problems:
        transforms.set_pose_bone_arm_matrix(
            armature, weapon,
            armature.matrix_world.inverted() @ w_before)
        transforms.update_view_layer()
        raise WeaponRigError("Rotate failed: %s." % "; ".join(problems))

    if key:
        _key_weapon(armature, frame, old_channels)

    return {
        "angle_error_deg": angle_error,
        "pivot_shift": (pw_now - pivot_w).length,
        "keyed": bool(key),
    }


def _pivot_now(armature, pivot, custom, dg):
    """Re-resolve the pivot preset after the move (fresh read)."""
    from ..weapon import pivot as pivot_mod
    return pivot_mod.compute_pivot_world(armature, pivot, custom, dg)


def _key_weapon(armature, frame, old_channels):
    from ..animation import keyframes
    from ..utils import constraints as con_util
    return keyframes.key_changed_channels(armature,
                                          con_util.get_weapon_bone(armature),
                                          frame, old_channels)


def ray_plane_target(origin, direction, plane_point, plane_normal):
    """Intersect a view ray with the plane through the pivot.

    Returns the world hit point, or None when the ray is (near-)parallel
    to the plane (caller keeps the last good target then).
    """
    denom = direction.dot(plane_normal)
    if abs(denom) < 1e-9:
        return None
    t = (plane_point - origin).dot(plane_normal) / denom
    if t < 0:
        return None
    return origin + direction * t


# ======================================================================
# Empty handle mode (user request: an Empty you move with Blender's own
# tools; the weapon rotates to aim at it live).
# ======================================================================
#
# WHY A HANDLER AND NOT A MODAL/DRIVER:
# - the modal drag operator requires holding the operator; the user
#   rejected it as inconvenient -- the Empty must work with G/R, gizmos,
#   numeric inputs, snapping, N-panel coords, all for free;
# - a driver cannot express "rotate about an arbitrary world pivot"
#   (constraints/drivers track from the bone origin, which would
#   translate the pivot -- breaking the locked-pivot guarantee);
# - depsgraph_update_post gives true live response to ANY change of the
#   Empty, guarded so it can never loop or spam.
#
# Semantics: Empty position == desired target for the drag point. It is
# created ON the drag point, so creating it never jumps. Pivot and drag
# point are read from the scene on EVERY application -- changing the
# dropdown mid-gesture takes effect immediately.

HANDLE_NAME = "WPN_RotateTarget"

_handle_state = {"matrix": None, "last_error": None}
_in_handle_update = False


def _matrix_signature(mat):
    """Flatten a Matrix to plain floats for change detection.

    CRITICAL (probe-verified): ``tuple(Matrix)`` yields row Vectors that
    ALIAS the source buffer -- a later ``obj.matrix_world`` write
    MUTATES the stored "snapshot", so equality would always match and
    the live-follow handler would never fire. Floats are immune.
    """
    return tuple(float(v) for row in mat for v in row)


def handle_object(scene):
    """The live handle Empty for this scene, or None (removed cleanly)."""
    name = getattr(scene, "wpn_rot_handle", "") or ""
    if not name:
        return None
    obj = bpy.data.objects.get(name)
    if obj is None:
        # Deleted behind our back -- heal the pointer.
        try:
            scene.wpn_rot_handle = ""
        except (AttributeError, ReferenceError):
            pass
        return None
    return obj


def create_handle(armature, pivot, drag, custom=(0.0, 0.0, 0.0)):
    """Create (or re-place) the aim Empty exactly on the drag point.

    Sitting on the drag point means aim == current state: creating the
    handle never moves the weapon. Returns the Empty.
    """
    from ..weapon import pivot as pivot_mod
    scene = bpy.context.scene
    drag_w = pivot_mod.compute_pivot_world(armature, drag, dg=None)
    obj = handle_object(scene)
    if obj is None:
        obj = bpy.data.objects.new(HANDLE_NAME, None)
        obj.empty_display_type = 'PLAIN_AXES'
        obj.empty_display_size = 0.12
        obj.show_in_front = True
        obj.hide_render = True
        scene.collection.objects.link(obj)
    obj.matrix_world = Matrix.Translation(drag_w)
    scene.wpn_rot_handle = obj.name
    _handle_state["matrix"] = _matrix_signature(obj.matrix_world)
    _handle_state["last_error"] = None
    start_handler()
    return obj


def remove_handle(scene):
    """Delete the handle Empty and forget it (weapon keeps its pose)."""
    obj = handle_object(scene)
    if obj is not None:
        bpy.data.objects.remove(obj, do_unlink=True)
    try:
        scene.wpn_rot_handle = ""
    except (AttributeError, ReferenceError):
        pass
    _handle_state["matrix"] = None
    _handle_state["last_error"] = None


def apply_handle(armature, scene, target=None):
    """One sync: aim the drag point at the Empty (same core as all the
    other rotate entry points). Raises WeaponRigError when degenerate.

    ``target`` lets callers pass an already-evaluated world position
    (the depsgraph handler does -- see _on_depsgraph_update).
    """
    obj = handle_object(scene)
    if obj is None:
        raise WeaponRigError(
            "Rotate handle not found -- press 'Create Rotate Handle'.")
    if target is None:
        target = obj.matrix_world.translation.copy()
    return rotate_toward(
        armature, scene.wpn_pivot, scene.wpn_drag, target,
        key=False, frame=scene.frame_current,
        custom=getattr(scene, "wpn_pivot_custom", (0.0, 0.0, 0.0)))


@persistent
def _on_depsgraph_update(scene, _dg):
    """Live follow: when (and only when) the Empty moved, re-aim.

    Guards: never re-entrant (our own writes re-enter this handler),
    no-op without a handle/armature, matrix-equality short-circuit so
    arbitrary scene churn costs one tuple compare. Errors are de-duped
    (one console line per distinct message, never a spam loop) and never
    propagate -- a depsgraph handler must not crash Blender.
    """
    global _in_handle_update
    if _in_handle_update:
        return
    obj = handle_object(scene)
    if obj is None:
        return
    arm = getattr(scene, "wpn_armature", None)
    if arm is None:
        return
    # Prefer the EVALUATED copy: frame_change_post can run before the
    # original object's obmat reflects the new frame's animation.
    try:
        src = (obj.evaluated_get(_dg)
               if (_dg is not None
                   and hasattr(_dg, "evaluated_get"))
               else obj)
        mw = src.matrix_world
    except (AttributeError, ReferenceError, RuntimeError):
        mw = obj.matrix_world
    m = _matrix_signature(mw)
    if m == _handle_state["matrix"]:
        return
    _in_handle_update = True
    try:
        apply_handle(arm, scene, target=mw.translation.copy())
        _handle_state["last_error"] = None
    except WeaponRigError as exc:
        if str(exc) != _handle_state["last_error"]:
            _handle_state["last_error"] = str(exc)
            print("WeaponRig (rotate handle): %s" % exc)
    except Exception as exc:  # noqa: BLE001 -- handler must never crash
        msg = "handle sync failed: %s" % exc
        if msg != _handle_state["last_error"]:
            _handle_state["last_error"] = msg
            print("WeaponRig (rotate handle): %s" % msg)
    finally:
        _in_handle_update = False
        _handle_state["matrix"] = m


def start_handler():
    """Idempotent install (addon register / handle create).

    TWO hooks on purpose (probe-verified behavior in 5.2):
    - depsgraph_update_post: fires for tagged RNA writes (dragging an
      un-animated Empty, N-panel edits) -- but NOT on frame changes;
    - frame_change_post: fires on frame changes (animated Empty,
      playback/scrub) -- which depsgraph_update_post misses when the
      only change came from animation evaluation.
    Both call the same guarded sync.
    """
    for bucket in (bpy.app.handlers.depsgraph_update_post,
                   bpy.app.handlers.frame_change_post):
        if _on_depsgraph_update not in bucket:
            bucket.append(_on_depsgraph_update)


def stop_handler():
    """Idempotent removal (addon unregister). Handle object stays."""
    for bucket in (bpy.app.handlers.depsgraph_update_post,
                   bpy.app.handlers.frame_change_post):
        if _on_depsgraph_update in bucket:
            bucket.remove(_on_depsgraph_update)
