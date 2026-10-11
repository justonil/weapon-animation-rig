"""Reparent the weapon rig under another bone, keeping the world pose.

Moving the weapon (or aim) bone to a new parent changes what every
local channel value MEANS, so a bare reparent would displace all keyed
frames. This re-bases pose channels AND fcurve keys onto the new parent
(new_local = new_parent_world^-1 @ recorded_world per frame) and then
verifies evaluated worlds match, rolling everything back on mismatch.

Grip/tip custom props are bone-LOCAL offsets resolved through the bone
matrix (grip_world = bone_world @ offset): with the world transform
preserved they ride along untouched, hands stay glued, inverses and
influence keys stay valid (all parent-independent).
"""
import bpy

from ..constants import BONE_AIM
from ..constants import BONE_WEAPON
from ..constants import TOL_ROTATION_DEG
from ..constants import TOL_TRANSLATION
from ..constants import WeaponRigError
from ..animation import keyframes
from ..utils import armature as arm_util
from ..utils import transforms

WPN_PARENT_PROP = "wpn_parent"

_GROUPS_BY_MODE = {
    "QUATERNION": ("location", "rotation_quaternion", "scale"),
    "AXIS_ANGLE": ("location", "rotation_axis_angle", "scale"),
}


def _channel_groups(pbone):
    """(location, rotation, scale) group names for the bone's mode."""
    mode = pbone.rotation_mode
    if mode in _GROUPS_BY_MODE:
        return _GROUPS_BY_MODE[mode]
    return ("location", "rotation_euler", "scale")


def _keyed_frames(armature, bone_name, groups):
    """{group: sorted key frames} for groups that actually have keys."""
    frames = {}
    for group in groups:
        path = 'pose.bones["%s"].%s' % (bone_name, group)
        have = set()
        for index in range(4):
            fc = keyframes._find_fcurve_index(armature, path, index)
            if fc is None:
                if index >= 3:
                    break
                continue
            for key in fc.keyframe_points:
                have.add(float(key.co[0]))
        if have:
            frames[group] = sorted(have)
    return frames


def _group_keyed_at(armature, bone_name, group, frame):
    """True if any index of the group has a key at the frame."""
    path = 'pose.bones["%s"].%s' % (bone_name, group)
    for index in range(4):
        fc = keyframes._find_fcurve_index(armature, path, index)
        if fc is None:
            if index >= 3:
                break
            continue
        if keyframes.find_key_at(fc, float(frame)) is not None:
            return True
    return False


def _check_cycle(armature, bone_name, new_parent):
    """Refuse reparenting that would create an evaluation cycle."""
    if new_parent is None:
        return
    seen = set()
    node = new_parent
    while node is not None:
        if node == bone_name:
            raise WeaponRigError(
                "Cannot parent '%s' under '%s': cycle."
                % (bone_name, new_parent))
        if node in seen:
            break
        seen.add(node)
        parent = armature.data.bones.get(node)
        node = parent.parent.name if parent is not None \
            and parent.parent is not None else None


def _goto_frame(scene, f):
    """frame_set accepting float frames (int + subframe)."""
    import math
    whole = math.floor(float(f))
    scene.frame_set(int(whole), subframe=float(f) - whole)


def _key_frame(f):
    """keyframe_insert needs int frames (floats fail silently)."""
    whole = round(float(f))
    if abs(float(f) - whole) > 1e-4:
        raise WeaponRigError(
            "Cannot rebase subframe key at %s: re-key it on a whole "
            "frame first." % (f,))
    return int(whole)


def _bone_world(armature, bone_name):
    dg = transforms.evaluated_depsgraph()
    eval_arm = armature.evaluated_get(dg)
    pbone = eval_arm.pose.bones.get(bone_name)
    if pbone is None:
        return None
    return (eval_arm.matrix_world @ pbone.matrix).copy()


def _new_local(armature, bone_name, new_parent, want_world):
    """Recorded world as an armature-space matrix setter target.

    The matrix setter takes armature-space matrices and accounts for
    the (new) parent itself -- passing parent-relative values would
    apply the parent twice. Parent reads are not needed at all.
    """
    mw_inv = armature.matrix_world.inverted()
    return mw_inv @ want_world


def reparent_weapon_bones(armature, new_parent):
    """Move weapon (+aim) under ``new_parent`` (name or None), keeping pose.

    Returns (report_lines, moved) where moved maps bone -> (old, new).
    Raises WeaponRigError with rollback on any verification mismatch.
    """
    from ..rig import create as rig_create
    for need in (BONE_WEAPON, BONE_AIM):
        if need not in armature.data.bones:
            raise WeaponRigError(
                "Cannot reparent: bone '%s' missing -- run Create first."
                % need)
    if new_parent is not None and new_parent not in armature.data.bones:
        hint = ""
        if "root" in new_parent.lower():
            hint = " (root-like: %s)" % ", ".join(
                arm_util.root_like_candidates(armature))
        raise WeaponRigError(
            "Cannot reparent under '%s': no such bone%s."
            % (new_parent, hint))
    for bone_name in (BONE_WEAPON, BONE_AIM):
        _check_cycle(armature, bone_name, new_parent)
    moved = {}
    for bone_name in (BONE_WEAPON, BONE_AIM):
        cur = armature.data.bones[bone_name].parent
        cur = cur.name if cur is not None else None
        if cur != new_parent:
            moved[bone_name] = (cur, new_parent)
    lines = ["Current parents: %s" % ", ".join(
        "%s->%s" % (b, armature.data.bones[b].parent.name
                    if armature.data.bones[b].parent is not None
                    else "(armature)")
        for b in (BONE_WEAPON, BONE_AIM))]
    if not moved:
        lines.append("Already there: nothing to do.")
        return lines, moved

    context = bpy.context
    prev_object_mode = armature.mode
    rig_create._make_active(context, armature)
    cur_frame = float(context.scene.frame_current)
    old_keys = {}
    worlds = {}
    # Live statics (rollback can only re-derive keyed state).
    live = {b: keyframes.capture_channels(armature, b) for b in moved}
    try:
        # Phase 1: record worlds + old key values (POSE level).
        rig_create.bpy_set_mode(armature, 'POSE')
        per_bone = {}
        frames = {cur_frame}
        for bone_name in moved:
            pbone = armature.pose.bones[bone_name]
            groups = _channel_groups(pbone)
            keyed = _keyed_frames(armature, bone_name, groups)
            per_bone[bone_name] = (groups, keyed)
            for group, fs in keyed.items():
                frames.update(float(f) for f in fs)
                path = 'pose.bones["%s"].%s' % (bone_name, group)
                for f in fs:
                    for index in range(4):
                        fc = keyframes._find_fcurve_index(
                            armature, path, index)
                        if fc is None:
                            if index >= 3:
                                break
                            continue
                        key = keyframes.find_key_at(fc, float(f))
                        if key is not None:
                            old_keys[(bone_name, group, index,
                                      float(f))] = float(key.co[1])
        frames = sorted(frames)
        for f in frames:
            _goto_frame(context.scene, f)
            transforms.update_view_layer()
            for bone_name in moved:
                worlds[(bone_name, float(f))] = _bone_world(
                    armature, bone_name)
        # Phase 2: relink parents (EDIT; rest head/tail are armature-space
        # and stay put -- only the hierarchy link changes).
        rig_create.bpy_set_mode(armature, 'EDIT')
        for bone_name, (_old, _new) in moved.items():
            eb = armature.data.edit_bones.get(bone_name)
            eb.parent = armature.data.edit_bones.get(_new) \
                if _new is not None else None
        rig_create.bpy_set_mode(armature, 'POSE')
        # Phase 3: rebase channels onto the new parent; overwrite only
        # frames that already have keys (never create new ones).
        for f in frames:
            _goto_frame(context.scene, f)
            transforms.update_view_layer()
            for bone_name, (_old, _new) in moved.items():
                groups, keyed = per_bone[bone_name]
                want = worlds[(bone_name, float(f))]
                transforms.set_pose_bone_arm_matrix(
                    armature, bone_name,
                    _new_local(armature, bone_name, _new, want))
                for group in groups:
                    if group not in keyed:
                        continue
                    if not _group_keyed_at(armature, bone_name, group, f):
                        continue
                    path = 'pose.bones["%s"].%s' % (bone_name, group)
                    if not armature.keyframe_insert(path,
                                                     frame=_key_frame(f)):
                        raise WeaponRigError(
                            "Failed to rebase key '%s' at frame %s."
                            % (path, f))
        # Phase 4: verify a spread of frames incl. current, then restore.
        check = sorted({frames[0], frames[len(frames) // 2], frames[-1],
                        cur_frame})
        for f in check:
            _goto_frame(context.scene, f)
            transforms.update_view_layer()
            for bone_name in moved:
                got = _bone_world(armature, bone_name)
                want = worlds[(bone_name, float(f))]
                trans, rot = transforms.matrix_difference(want, got)
                if trans > TOL_TRANSLATION or rot > TOL_ROTATION_DEG:
                    raise WeaponRigError(
                        "Reparent moved '%s' at frame %s (d-trans %.6f, "
                        "d-rot %.4f deg) -- rolled back."
                        % (bone_name, f, trans, rot))
        _goto_frame(context.scene, cur_frame)
        transforms.update_view_layer()
        for bone_name, (_old, _new) in moved.items():
            want = worlds[(bone_name, cur_frame)]
            transforms.set_pose_bone_arm_matrix(
                armature, bone_name,
                _new_local(armature, bone_name, _new, want))
        # Phase 5: record the override so validation accepts the parent.
        for bone_name, (_old, _new) in moved.items():
            armature.data.bones[bone_name][WPN_PARENT_PROP] = _new or ""
        for bone_name, (old, new) in sorted(moved.items()):
            n_keys = sum(1 for k in old_keys if k[0] == bone_name)
            lines.append("'%s': %s -> %s (%d keys rebased, verified)"
                         % (bone_name, old or "(armature)",
                            new or "(armature)", n_keys))
        return lines, moved
    except Exception:
        # Rollback: parents back, old key values back, timeline restored.
        try:
            rig_create.bpy_set_mode(armature, 'EDIT')
            for bone_name, (old, _new) in moved.items():
                eb = armature.data.edit_bones.get(bone_name)
                if eb is not None:
                    eb.parent = armature.data.edit_bones.get(old) \
                        if old is not None else None
            rig_create.bpy_set_mode(armature, 'POSE')
            touched = []
            for (bone_name, group, index, f), value in old_keys.items():
                path = 'pose.bones["%s"].%s' % (bone_name, group)
                fc = keyframes._find_fcurve_index(armature, path, index)
                if fc is not None:
                    key = keyframes.find_key_at(fc, f)
                    if key is not None:
                        key.co[1] = value
                        if fc not in touched:
                            touched.append(fc)
            for fc in touched:
                try:
                    fc.update()
                except Exception:
                    pass
            _goto_frame(context.scene, cur_frame)
            transforms.update_view_layer()
            for bone_name in moved:
                keyframes.apply_channels(
                    armature, bone_name, live[bone_name])
        except Exception:
            pass
        raise
    finally:
        try:
            if armature.mode != prev_object_mode:
                rig_create.bpy_set_mode(armature, prev_object_mode)
        except Exception:
            pass


def expected_parent(armature):
    """Parent name validation should expect (override or resolved root)."""
    bone = armature.data.bones.get(BONE_WEAPON)
    override = None
    if bone is not None:
        try:
            override = bone.get(WPN_PARENT_PROP)
        except Exception:
            override = None
    if override is not None:
        return (str(override) or None), "override"
    char_root, status = arm_util.resolve_character_root(armature)
    return char_root, status
