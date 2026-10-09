"""Keyframe helpers (plan §10 step 8, §11 steps 6-7, §12, §31).

STEPPED INFLUENCE (plan §12):
Attachment states must never interpolate. All keys on an influence fcurve are
forced to CONSTANT interpolation. A guard key is inserted at ``frame-1``
holding the pre-operation value whenever the fcurve has no earlier key --
otherwise Blender's constant extrapolation would apply the new value to ALL
earlier frames (e.g. first attach at frame 30 would make the hand attached
on frames 1-29 too, corrupting existing poses -- plan §30).

KEYFRAME PATHS (probe-verified Blender 5.2):
- ``PoseBone.keyframe_insert`` does NOT accept constraint data paths; key via
  ``armature.keyframe_insert('pose.bones[...].constraints[...].influence')``.
- Actions are slotted: legacy ``action.fcurves`` is gone. Use
  ``action.layers[*].strips[*].channelbag(action_slot).fcurves`` with a
  legacy fallback.
- Setting an animated property + ``view_layer.update()`` does NOT get
  reverted by fcurve evaluation (only frame changes do) -- so operations may
  set influence, verify, and only then key it.
- ``keyframe_insert`` returns False instead of raising when it cannot
  insert: every insert here is CHECKED and raises WeaponRigError (plan
  §54 -- a silently missing key would corrupt later frames).
- After keying at a frame other than the current one, RNA properties are
  restored to their fcurve-evaluated values at the current frame.
  Background: inserting keys dirties animation data, so the next
  depsgraph read re-applies fcurves AT THE CURRENT frame -- leaving the
  just-set RNA values stale would mislead every later read in the
  session (found via a re-attach-at-another-frame test failure).
"""
import bpy

from ..constants import WeaponRigError


# ---------------------------------------------------------------------------
# Slotted-action fcurve access (Blender 4.4+/5.2)
# ---------------------------------------------------------------------------

def find_key_at(fcurve, frame, tol=1e-6):
    """The keyframe point at exactly ``frame``, or None."""
    if fcurve is None:
        return None
    for key in fcurve.keyframe_points:
        if abs(key.co[0] - frame) <= tol:
            return key
    return None


def _iter_channelbags(action, slot):
    """Yield channelbags for lookup: slot-bound first, fallback after.

    keyframe_insert always writes through the bound slot, and so does the
    evaluator. Reading any other bag (e.g. bags[0] of a multi-bag strip)
    yields stale values while the live data sits elsewhere -- verified
    post-key misreads in tests. So the bound slot wins whenever it
    resolves; the single-bag fallback only covers freshly assigned
    actions (action_slot None, one bag).
    """
    strips = []
    try:
        for layer in action.layers:
            for strip in layer.strips:
                if strip.type == 'KEYFRAME':
                    strips.append(strip)
    except Exception:
        return
    if slot is not None:
        for strip in strips:
            try:
                cb = strip.channelbag(slot)
            except Exception:
                cb = None
            if cb is not None:
                yield cb
        return
    for strip in strips:
        cb = None
        try:
            cb = strip.channelbag(None)
        except Exception:
            cb = None
        if cb is None:
            try:
                bags = list(strip.channelbags)
            except Exception:
                bags = []
            if len(bags) == 1:
                cb = bags[0]
        if cb is not None:
            yield cb


def find_fcurve(armature, data_path):
    """Find the fcurve driving ``data_path`` on this armature, or None."""
    ad = armature.animation_data
    if ad is None or ad.action is None:
        return None
    action = ad.action

    # Legacy single-timeline API (older Blenders).
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        fc = legacy.find(data_path)
        if fc is not None:
            return fc

    # Slotted actions (Blender 4.4+, the only API in 5.2).
    slot = getattr(ad, "action_slot", None)
    for cb in _iter_channelbags(action, slot):
        fc = cb.fcurves.find(data_path)
        if fc is not None:
            return fc
    return None


def influence_data_path(bone_name, constraint_name):
    return 'pose.bones["%s"].constraints["%s"].influence' % (
        bone_name, constraint_name)


def channel_data_paths(pbone):
    """Data paths for the transform channel groups of a pose bone."""
    paths = ['pose.bones["%s"].location' % pbone.name]
    mode = pbone.rotation_mode
    if mode == 'QUATERNION':
        paths.append('pose.bones["%s"].rotation_quaternion' % pbone.name)
    elif mode == 'AXIS_ANGLE':
        paths.append('pose.bones["%s"].rotation_axis_angle' % pbone.name)
    else:
        paths.append('pose.bones["%s"].rotation_euler' % pbone.name)
    paths.append('pose.bones["%s"].scale' % pbone.name)
    return paths


# ---------------------------------------------------------------------------
# Influence keying (attachment state)
# ---------------------------------------------------------------------------

def _checked_insert(armature, data_path, frame):
    """keyframe_insert that raises instead of silently failing.

    ``bpy_struct.keyframe_insert`` returns False (no exception) when it
    cannot insert -- a silently missing key corrupts later frames, so this
    is a hard error (plan §54).
    """
    if not armature.keyframe_insert(data_path, frame=frame):
        raise WeaponRigError(
            "Failed to insert keyframe '%s' at frame %s." % (data_path,
                                                             frame))


def _find_fcurve_index(armature, data_path, index):
    """Find the fcurve for one array index (location has 3 fcurves)."""
    ad = armature.animation_data
    if ad is None or ad.action is None:
        return None
    action = ad.action
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        try:
            return legacy.find(data_path, index=index)
        except Exception:
            return None
    slot = getattr(ad, "action_slot", None)
    for cb in _iter_channelbags(action, slot):
        try:
            fc = cb.fcurves.find(data_path, index=index)
        except Exception:
            continue
        if fc is not None:
            return fc
    return None


def _restore_influence(armature, bone_name, constraint_name):
    """Re-sync the RNA property with the fcurve value at current frame.

    Keyframing dirties animation data, so the next depsgraph read
    re-applies fcurves AT THE CURRENT frame. When keys were written at
    another frame, the just-set RNA value would otherwise stay stale and
    mislead every later read in the session.
    """
    current = bpy.context.scene.frame_current
    fc = find_fcurve(armature,
                       influence_data_path(bone_name, constraint_name))
    if fc is None:
        return
    try:
        value = fc.evaluate(current)
    except Exception:
        return
    armature.pose.bones[bone_name].constraints[constraint_name].influence = \
        value


def keyframe_influence(armature, bone_name, constraint_name, frame, value,
                       pre_value=None):
    """Key ``value`` at ``frame`` with a guard at frame-1 when needed.

    The guard value is read from the fcurve itself (evaluated at
    frame-1) when one exists, else ``pre_value`` when given, else the
    current static property value -- in all cases it is exactly what
    frames before the transition showed (plan §12: stepped adjacent
    transitions, no leaking into the past). ``pre_value`` is the
    operation's entry RNA value: callers that already rewrote the live
    property (attach sets 1.0 before keying) must pass it, otherwise the
    guard would capture the NEW value and leak it backwards.

    All keys on the fcurve are set to CONSTANT (plan §12).
    """
    path = influence_data_path(bone_name, constraint_name)
    fc = find_fcurve(armature, path)

    has_earlier = (
        fc is not None and
        any(k.co[0] < frame - 1e-6 for k in fc.keyframe_points)
    )
    pbone = armature.pose.bones[bone_name]
    con = pbone.constraints[constraint_name]

    if not has_earlier:
        # Guard: pin the pre-operation value just before the transition so
        # constant extrapolation cannot leak the new value into the past.
        if fc is not None:
            try:
                prev_value = fc.evaluate(frame - 1)
            except Exception:
                prev_value = (pre_value if pre_value is not None
                              else con.influence)
        else:
            prev_value = (pre_value if pre_value is not None
                          else con.influence)
        con.influence = prev_value
        _checked_insert(armature, path, frame - 1)

    con.influence = value
    _checked_insert(armature, path, frame)

    # Re-fetch (keyframe_insert may have created the fcurve just now) and
    # force stepped interpolation on every key of OUR fcurve.
    fc = find_fcurve(armature, path)
    if fc is not None:
        for k in fc.keyframe_points:
            k.interpolation = 'CONSTANT'
        fc.update()
    # NOTE: no _restore_influence (RNA already holds the just-keyed value;
    # re-reading risks stale-bag clobber, see pin_hold_channels).


# ---------------------------------------------------------------------------
# Transform channel keying (detach compensation)
# ---------------------------------------------------------------------------

def capture_channels(armature, bone_name):
    """Snapshot location/rotation/scale of a pose bone (old values)."""
    pbone = armature.pose.bones[bone_name]
    snap = {"location": tuple(pbone.location),
            "scale": tuple(pbone.scale)}
    mode = pbone.rotation_mode
    if mode == 'QUATERNION':
        snap["rotation_quaternion"] = tuple(pbone.rotation_quaternion)
    elif mode == 'AXIS_ANGLE':
        snap["rotation_axis_angle"] = tuple(pbone.rotation_axis_angle)
    else:
        snap["rotation_euler"] = tuple(pbone.rotation_euler)
    snap["_mode"] = mode
    return snap


def _restore_channels(armature, bone_name, groups):
    """Re-sync channel properties with fcurve values at current frame.

    Same staleness hazard as _restore_influence, per channel group.
    Groups without fcurves keep their (just-written, static) values.
    """
    current = bpy.context.scene.frame_current
    pbone = armature.pose.bones[bone_name]
    sizes = {"location": 3, "scale": 3, "rotation_quaternion": 4,
             "rotation_axis_angle": 4, "rotation_euler": 3}
    for group in groups:
        path = 'pose.bones["%s"].%s' % (bone_name, group)
        values = []
        complete = True
        for index in range(sizes[group]):
            fc = _find_fcurve_index(armature, path, index)
            if fc is None:
                complete = False
                break
            try:
                values.append(fc.evaluate(current))
            except Exception:
                complete = False
                break
        if complete:
            _set_channel_group(pbone, group, tuple(values))


def key_changed_channels(armature, bone_name, frame, old_snapshot):
    """Persist the compensation written by the pb.matrix setter (plan §11
    step 6: "write the appropriate location/rotation/scale keys").

    Called AFTER the new values are in the channels and verified. For each
    channel group that actually changed:
    - if the group has no fcurves yet, first insert a guard key at frame-1
      holding the OLD value (so frames before the detach keep their pose --
      plan §30), then key the NEW value at ``frame``;
    - if the group already has fcurves, just key at ``frame`` (normal
      animation workflow -- existing keys elsewhere are untouched).

    Returns {group: guard_written} for post-key verification. RNA
    properties are restored to their fcurve-evaluated values at the current
    frame afterwards (same staleness hazard as influence keying).
    """
    pbone = armature.pose.bones[bone_name]
    mode = pbone.rotation_mode
    new_values = {"location": tuple(pbone.location),
                  "scale": tuple(pbone.scale)}
    if mode == 'QUATERNION':
        new_values["rotation_quaternion"] = tuple(pbone.rotation_quaternion)
    elif mode == 'AXIS_ANGLE':
        new_values["rotation_axis_angle"] = tuple(pbone.rotation_axis_angle)
    else:
        new_values["rotation_euler"] = tuple(pbone.rotation_euler)

    keyed = {}
    for group, new in new_values.items():
        old = old_snapshot.get(group)
        if old is None:
            continue
        if all(abs(a - b) <= 1e-6 for a, b in zip(old, new)):
            continue  # channel group unchanged -> no keys, no noise (§31)

        path = 'pose.bones["%s"].%s' % (bone_name, group)
        has_fcurve = find_fcurve(armature, path) is not None

        guard = False
        if not has_fcurve:
            # Guard with OLD values at frame-1: write old back, key, restore.
            _set_channel_group(pbone, group, old)
            _checked_insert(armature, path, frame - 1)
            _set_channel_group(pbone, group, new)
            guard = True
        _checked_insert(armature, path, frame)
        keyed[group] = guard
    # NOTE: no _restore_channels (see pin_hold_channels): RNA already
    # holds the just-keyed values; re-reading risks stale-bag clobber.
    return keyed


def pin_hold_channels(armature, bone_name, frame):
    """Pin the hand's current channels flat at ``frame`` (attached hold).

    A Child Of composes the owner's channels on top of the follow
    (world = target @ inverse @ channels), so swinging hand keys inside
    an attached range would slide the hand off the grip. This keys the
    current channel values at ``frame`` with CONSTANT interpolation (the
    hold stays glued until the next key) plus a guard at frame-1 holding
    the evaluated values (pre-existing free motion into the hold is
    untouched). Pins are ALWAYS written (even for static values): the
    CONSTANT key at the attach frame is what keeps later swing keys from
    blending the hold away, and the guard shields all earlier frames from
    single-future-key backward leaks. Motion-neutral by construction
    (guard holds evaluated history, flat holds the current pose). Only
    the new key is forced CONSTANT; every other key keeps its
    interpolation.
    Returns the list of pinned channel groups.
    """
    pbone = armature.pose.bones[bone_name]
    mode = pbone.rotation_mode
    rot_group = {"QUATERNION": "rotation_quaternion",
                 "AXIS_ANGLE": "rotation_axis_angle"}.get(
                     mode, "rotation_euler")
    new_values = {"location": tuple(pbone.location),
                  "scale": tuple(pbone.scale),
                  rot_group: tuple(getattr(pbone, rot_group))}
    pinned = []
    for group, new in new_values.items():
        path = 'pose.bones["%s"].%s' % (bone_name, group)
        size = len(new)
        guard = []
        for index in range(size):
            fc = _find_fcurve_index(armature, path, index)
            if fc is None:
                guard.append(float(new[index]))
            else:
                try:
                    guard.append(float(fc.evaluate(frame - 1)))
                except Exception:
                    guard.append(float(new[index]))
        guard = tuple(guard)
        # No history yet (first keys ever: also shields all earlier frames
        # from single-future-key backward leaks) or diverged values.
        _set_channel_group(pbone, group, guard)
        _checked_insert(armature, path, frame - 1)
        _set_channel_group(pbone, group, new)
        _checked_insert(armature, path, frame)
        # Force CONSTANT on the frame key of EVERY index fcurve:
        # find_fcurve() alone returns only the first index.
        for index in range(size):
            fc_i = _find_fcurve_index(armature, path, index)
            if fc_i is None:
                continue
            key = find_key_at(fc_i, frame)
            if key is not None:
                key.interpolation = 'CONSTANT'
            try:
                fc_i.update()
            except Exception:
                pass
        pinned.append(group)
    # NOTE: deliberately no _restore_channels here: RNA already holds the
    # just-keyed values, and re-reading fcurves at this point has returned
    # stale-bag values in multi-key histories (verified post-key misread).
    return pinned


def _set_channel_group(pbone, group, values):
    if group == "location":
        pbone.location = values
    elif group == "scale":
        pbone.scale = values
    elif group == "rotation_quaternion":
        pbone.rotation_quaternion = values
    elif group == "rotation_axis_angle":
        pbone.rotation_axis_angle = values
    elif group == "rotation_euler":
        pbone.rotation_euler = values


def apply_channels(armature, bone_name, snap):
    """Write a capture_channels() snapshot back to RNA (all groups).

    Plain channel writes tag transforms only (never animation), so this
    can never trigger an fcurve resync itself -- it is the repair
    primitive for update-induced resync (see constraints._assert_hand).
    """
    pbone = armature.pose.bones[bone_name]
    for group, values in snap.items():
        if group.startswith("_"):
            continue
        _set_channel_group(pbone, group, values)


# ---------------------------------------------------------------------------
# Location-key compensation (Set Pivot re-anchor)
# ---------------------------------------------------------------------------

def _rotation_to_matrix_4x4(rot_values, mode):
    """Rotation channel values -> 4x4 matrix (no translation/scale)."""
    from mathutils import Euler, Matrix, Quaternion, Vector
    if mode == 'QUATERNION':
        # Fcurve-interpolated quats are often non-unit (component-wise
        # lerp, not slerp); Blender normalizes internally, so must we.
        q = Quaternion(
            (rot_values[0], rot_values[1],
             rot_values[2], rot_values[3]))
        if q.magnitude < 1e-9:
            return Matrix.Identity(4)
        return q.normalized().to_matrix().to_4x4()
    if mode == 'AXIS_ANGLE':
        angle = float(rot_values[0])
        axis = Vector((float(rot_values[1]), float(rot_values[2]),
                       float(rot_values[3])))
        if axis.length < 1e-9 or abs(angle) < 1e-9:
            return Matrix.Identity(4)
        return Matrix.Rotation(angle, 4, axis.normalized())
    order = mode if mode in ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX') \
        else 'XYZ'
    return Euler((float(rot_values[0]), float(rot_values[1]),
                  float(rot_values[2])), order).to_matrix().to_4x4()


def compose_channel_matrix(snapshot):
    """Pose-space 4x4 from a capture_channels() dict (loc/rot/scale+mode)."""
    from mathutils import Matrix, Vector
    mode = snapshot.get("_mode", "XYZ")
    loc = snapshot.get("location", (0.0, 0.0, 0.0))
    rot_group = {"QUATERNION": "rotation_quaternion",
                 "AXIS_ANGLE": "rotation_axis_angle"}.get(mode,
                                                             "rotation_euler")
    rot = snapshot.get(rot_group)
    if rot is None:
        rot = (1.0, 0.0, 0.0, 0.0) if mode == 'QUATERNION' else (0.0,) * (
            4 if mode == 'AXIS_ANGLE' else 3)
    scl = snapshot.get("scale", (1.0, 1.0, 1.0))
    m = Matrix.Translation(Vector((float(loc[0]), float(loc[1]),
                                   float(loc[2]))))
    m = m @ _rotation_to_matrix_4x4(rot, mode)
    m = m @ Matrix.Diagonal(Vector((float(scl[0]), float(scl[1]),
                                    float(scl[2]), 1.0)))
    return m


def _eval_group_at(armature, bone_name, group, size, static, frame):
    """Channel values at ``frame`` (fcurve eval, static fallback per index)."""
    path = 'pose.bones["%s"].%s' % (bone_name, group)
    out = []
    for index in range(size):
        fc = _find_fcurve_index(armature, path, index)
        if fc is None:
            out.append(float(static[index]))
        else:
            try:
                out.append(float(fc.evaluate(frame)))
            except Exception:
                out.append(float(static[index]))
    return tuple(out)


def shift_location_keys(armature, bone_name, bone_space_delta):
    """Shift location keys so world motion survives a pure-translation
    re-anchor of the bone origin (Set Pivot).

    ``bone_space_delta`` (S) is the origin shift in bone/channel space:
    every pose matrix becomes ``Pose_old @ T(S)``. Rotation/scale keys are
    untouched (post-multiplying by a translation preserves them), but each
    location key moves by ``R(F) @ Scl(F) @ S`` where R/Scl are that
    frame's rotation/scale -- so rotation animation keeps orbiting the
    ORIGINAL points instead of swinging around the new origin. Handles are
    evaluated at their own frames so BEZIER shape stays exact.
    Returns the number of keyframe points shifted.
    """
    from mathutils import Vector
    S = Vector((float(bone_space_delta[0]), float(bone_space_delta[1]),
                float(bone_space_delta[2])))
    if S.length < 1e-9:
        return 0
    pbone = armature.pose.bones[bone_name]
    mode = pbone.rotation_mode
    rot_group, rot_size = {
        "QUATERNION": ("rotation_quaternion", 4),
        "AXIS_ANGLE": ("rotation_axis_angle", 4),
    }.get(mode, ("rotation_euler", 3))
    rot_static = capture_channels(armature, bone_name).get(
        rot_group, (1.0, 0.0, 0.0, 0.0) if rot_size == 4 else (0.0, 0.0, 0.0))
    scl_static = tuple(pbone.scale)

    def offset_at(frame):
        rot = _eval_group_at(armature, bone_name, rot_group, rot_size,
                             rot_static, frame)
        scl = _eval_group_at(armature, bone_name, "scale", 3,
                             scl_static, frame)
        r3 = _rotation_to_matrix_4x4(rot, mode).to_3x3()
        sv = Vector((float(scl[0]), float(scl[1]), float(scl[2])))
        scaled = Vector((S[0] * sv[0], S[1] * sv[1], S[2] * sv[2]))
        return r3 @ scaled

    loc_path = 'pose.bones["%s"].location' % bone_name
    shifted = 0
    for index in range(3):
        fc = _find_fcurve_index(armature, loc_path, index)
        if fc is None:
            continue
        for key in fc.keyframe_points:
            off = offset_at(key.co[0])
            key.co[1] += float(off[index])
            try:
                off_l = offset_at(key.handle_left[0])
                key.handle_left[1] += float(off_l[index])
            except Exception:
                pass
            try:
                off_r = offset_at(key.handle_right[0])
                key.handle_right[1] += float(off_r[index])
            except Exception:
                pass
        try:
            fc.update()
        except Exception:
            pass
        shifted += len(fc.keyframe_points)
    return shifted
