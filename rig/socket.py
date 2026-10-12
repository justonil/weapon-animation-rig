"""Hand socket bones for engine-side placement (plan: socket workflow).

A socket bone is a plain, keyless, constraint-free leaf parented under a
hand, its head exactly at the mesh-origin-when-held point (the Pommel
reference when the grip sits on the hand). Attaching the sword mesh to
it in-engine (origin snap) reproduces the Blender hold bit-exactly, in
every blend, with zero runtime cost -- because the offset lives in the
bind hierarchy, not in numbers.

Why static and NOT a live weapon-copy: a live copy (Child Of the weapon,
or baked world tracks) re-expresses the authoring hand pose per frame,
so a blended hand times a varying local wobbles mid-blend. A static
socket holds a CONSTANT grip offset: blended_hand x const is exact at
every blend weight, always. (When attached, the hand already tracks the
weapon, so the static socket tracks authored weapon motion transitively
-- pivots and spins included. Detached flight (throw) is a state switch
in game code: hand socket while held, weapon bone while thrown.)

Baked follow (bake_socket_follow) extends the static seat across a
range: per-frame local keys reproduce the authored weapon motion
EXACTLY while the parent stays the hand, so blends carry the sword
with the hand side. Static seat = the bind frame; baked keys = every
other frame. A static hand-child socket provably cannot reproduce
weapon motion under wrist articulation (hand^-1 @ weapon must be
constant, and it is not) -- keys are the only exact carrier.
"""
import bpy

from ..constants import HAND_BONES
from ..constants import POMMEL_PROP
from ..constants import TIP_PROP
from ..constants import GUARD_PROP_L
from ..constants import GUARD_PROP_R
from ..constants import TOL_ROTATION_DEG
from ..constants import TOL_TRANSLATION
from ..constants import WeaponRigError
from ..utils import constraints as con_util
from ..utils import transforms


def socket_name(side):
    """Dedicated socket bone name (never collides with the rig)."""
    return "socket_%s" % side.lower()


def _socket_frame(armature, weapon, name):
    """Weapon-local socket rotation (columns X/Y/Z), orthonormal.

    Pure mesh mapping, no negations: X along the tuned guard direction
    (Gram-Schmidt orthogonalized vs the blade), Y along the blade
    (Tip direction, after the 90 deg X rotation), Z = Y x X completing
    right-handed. Determinant
    (blade_axis prop), Y = Z x X completing right-handed. Determinant
    +1 by construction; mesh +X/+Y/+Z land on socket X/Y/Z exactly.
    """
    from mathutils import Matrix, Vector
    bone = armature.data.bones.get(weapon)
    axis_prop = "+Y"
    guard_l = guard_r = None
    try:
        if bone is not None:
            axis_prop = bone.get("blade_axis", "+Y")
            guard_l = bone.get(GUARD_PROP_L)
            guard_r = bone.get(GUARD_PROP_R)
    except Exception:
        pass
    axes = {"+X": Vector((1.0, 0.0, 0.0)),
            "-X": Vector((-1.0, 0.0, 0.0)),
            "+Y": Vector((0.0, 1.0, 0.0)),
            "-Y": Vector((0.0, -1.0, 0.0)),
            "+Z": Vector((0.0, 0.0, 1.0)),
            "-Z": Vector((0.0, 0.0, -1.0))}
    blade = axes.get(axis_prop, Vector((0.0, 1.0, 0.0))).normalized()
    guard = None
    try:
        if guard_l is not None and guard_r is not None:
            guard = Vector(tuple(guard_r)) - Vector(tuple(guard_l))
    except Exception:
        guard = None
    if guard is None or guard.length < 1e-6:
        guard = Vector((1.0, 0.0, 0.0))
        if abs(blade.dot(guard)) > 0.9:
            guard = Vector((0.0, 0.0, 1.0))
    z_s = blade
    x_s = guard - guard.dot(blade) * blade
    if x_s.length < 1e-6:
        raise WeaponRigError(
            "Socket '%s': guard direction parallel to blade." % name)
    x_s = x_s.normalized()
    y_s = z_s.cross(x_s).normalized()
    # Rotate the mapping 90 deg about X so the socket's +Y points to the
    # Tip (along the blade): Unreal's socket attach and the user's
    # pipeline expect the bone to LOOK along the blade (verified in
    # engine). Guard (+X) is preserved; blade moves Z->Y. Right-handed
    # by construction: new cols = [x_s, z_s, -y_s], det +1.
    cols = [tuple(x_s), tuple(z_s), tuple(-y_s)]
    return Matrix(cols).transposed()


def _pommel_world(armature, weapon):
    """Mesh-origin-when-held world: pommel prop through the weapon."""
    from mathutils import Vector
    dg = transforms.evaluated_depsgraph()
    eval_arm = armature.evaluated_get(dg)
    pbone = eval_arm.pose.bones.get(weapon)
    if pbone is None:
        raise WeaponRigError("Bone '%s' missing." % weapon)
    weapon_world = eval_arm.matrix_world @ pbone.matrix
    bone = armature.data.bones.get(weapon)
    pommel = tuple(bone.get(POMMEL_PROP, (0.0, 0.0, 0.0)))
    return (weapon_world @ Vector(pommel)).copy(), weapon_world.copy()


def create_hand_socket(armature, side, hand_bone=None):
    """Create/update the static hand socket for ``side`` (R/L).

    Head lands exactly on the mesh-origin-when-held point at the CURRENT
    frame (scrub to a correct hold first); tail runs along the weapon
    blade axis (roll is free for the user to tweak once in-engine).
    Idempotent: an existing socket is re-seated (never duplicated).
    Returns (report_lines, socket_name).
    """
    from ..rig import create as rig_create
    weapon = con_util.get_weapon_bone(armature)
    if hand_bone is None:
        hand_bone = HAND_BONES.get(side, HAND_BONES["R"])
    if hand_bone not in armature.data.bones:
        raise WeaponRigError(
            "Cannot seat socket: hand bone '%s' missing." % hand_bone)
    name = socket_name(side)
    context = bpy.context
    prev_object_mode = armature.mode
    rig_create._make_active(context, armature)
    try:
        pommel_world, weapon_world = _pommel_world(armature, weapon)
        mw_inv = armature.matrix_world.inverted()
        # Rest-expressed seat: the head is stored as REST (edit-bone
        # head/tail are armature-space rest), but the target is a POSED
        # world (hand posed at bind). Storing posed coords as rest
        # double-counts the hand pose on evaluation (bisected 0.72
        # miss) -- strip it: head_rest = handRest @ handPose^-1 @ target.
        dg = transforms.evaluated_depsgraph()
        eval_arm = armature.evaluated_get(dg)
        hand_pose = eval_arm.pose.bones[hand_bone].matrix.copy()
        hand_rest = armature.data.bones[hand_bone].matrix_local.copy()
        head_arm = hand_rest @ hand_pose.inverted() @ (
            mw_inv @ pommel_world)
        # Full rest matrix (NOT head/tail: head/tail leave roll at its
        # default, so the bone orientation never equals the mesh frame
        # (bisected 3.35 m tip miss on an exact head seat). The rest
        # matrix carries position AND the mesh-mapped orientation:
        # socket +Y along blade_axis (Tip), socket +X on the tuned guard
        # direction, Z completing right-handed (verified on the
        # reference origin-to-origin bind and matching prop/geometry
        # extents). EditBone.matrix assignment decomposes
        # it into head/tail/roll automatically.
        from mathutils import Matrix
        wrot = (mw_inv @ weapon_world).to_3x3()
        m = _socket_frame(armature, weapon, name)
        # Full 4x4 chain (never to_3x3 mid-chain: that drops the
        # translational coupling): REST is what the hand carries back
        # to exactly desired_world at bind. Verifiable by algebra:
        # mw @ hand_pose @ hand_rest^-1 @ REST == desired_world.
        desired_world = Matrix.Translation(pommel_world) @ \
            (armature.matrix_world.to_3x3() @ wrot @ m).to_4x4()
        rest_mat = hand_rest @ hand_pose.inverted() @ mw_inv @ \
            desired_world
        # Rest orientation columns (armature space) for explicit roll.
        rest_rot = rest_mat.to_3x3()
        _rx = rest_rot.col[0].normalized()
        _ry = rest_rot.col[1].normalized()
        rig_create.bpy_set_mode(armature, 'EDIT')
        ebones = armature.data.edit_bones
        eb = ebones.get(name)
        created = eb is None
        if created:
            eb = ebones.new(name)
        import math as _math
        eb.parent = ebones.get(hand_bone)
        eb.use_connect = False
        eb.use_deform = False
        eb.head = head_arm
        eb.tail = head_arm + _ry * 0.02
        # Closed-loop roll: head/tail fix Y; rotate X toward desired
        # about Y until it matches. No assumptions about Blender's
        # roll-0 convention or sign: each pass measures the ACTUAL
        # frame and corrects the residual (roll is 1-DOF additive
        # about bone Y, so this converges in ~2 passes).
        for _it in range(3):
            try:
                armature.update_from_editmode()
            except Exception:
                pass
            _cur = eb.matrix.to_3x3()
            _cx = _cur.col[0].normalized()
            _cy = _cur.col[1].normalized()
            _cross = _cx.cross(_rx)
            _ang = _math.atan2(_cross.dot(_cy), _cx.dot(_rx))
            if abs(_ang) < 1e-6:
                break
            try:
                _cur_roll = float(eb.roll)
            except Exception:
                _cur_roll = 0.0
            eb.roll = _cur_roll + _ang
        try:
            armature.update_from_editmode()
        except Exception:
            pass
        rig_create.bpy_set_mode(armature, 'POSE')
        # Verify full matrices (strict, translation AND rotation):
        # pose-space head/tail reads carry parent-relative semantics,
        # so only whole-matrix comparison is meaningful. Rollback =
        # remove the bone we just created; pose/keys of weapon and hand
        # are untouched otherwise.
        from mathutils import Matrix
        transforms.update_view_layer()
        dg2 = transforms.evaluated_depsgraph()
        eval2 = armature.evaluated_get(dg2)
        sock_pb = eval2.pose.bones.get(name)
        hand_pb = eval2.pose.bones.get(hand_bone)
        err = 1e9
        if sock_pb is not None and hand_pb is not None:
            # Rigid-child model: socket rides the hand from bind matrix.
            hand_rest2 = armature.data.bones[
                hand_bone].matrix_local.copy()
            exp = eval2.matrix_world @ hand_pb.matrix @ \
                hand_rest2.inverted() @ rest_mat
            got = eval2.matrix_world @ sock_pb.matrix
            trans, rot = transforms.matrix_difference(exp, got)
            if rot > TOL_ROTATION_DEG:
                raise WeaponRigError(
                    "Socket '%s' orientation off by %.4f deg "
                    "(rolled back)." % (name, rot))
            err = trans
        if err > TOL_TRANSLATION:
            if created:
                rig_create.bpy_set_mode(armature, 'EDIT')
                doomed = armature.data.edit_bones.get(name)
                if doomed is not None:
                    armature.data.edit_bones.remove(doomed)
                rig_create.bpy_set_mode(armature, 'POSE')
            raise WeaponRigError(
                "Socket '%s' missed its seat by %.6f (rolled back)."
                % (name, err))
        lines = ["Socket '%s' %s under '%s' at mesh origin "
                 "(grip on hand, verified %.6f)." %
                 (name, "created" if created else "re-seated",
                  hand_bone, err)]
        # Hold sanity (warning only): grip far from the hand means the
        # bind frame is not a correct hold -- re-seat on one that is.
        try:
            grip_w = con_util.grip_world(armature, "R").translation
            hand_w = transforms.get_pose_bone_world_matrix(
                armature, hand_bone).translation
            gap = (grip_w - hand_w).length
            if gap > 0.30:
                lines.append("WARNING: grip %.3f m from hand -- seat "
                             "on a correct hold frame." % gap)
        except Exception:
            pass
        return lines, name
    finally:
        try:
            if armature.mode != prev_object_mode:
                rig_create.bpy_set_mode(armature, prev_object_mode)
        except Exception:
            pass


def _channel_key_frames(armature, bone_name, groups):
    """Sorted key frames over channel groups (floats, any index)."""
    from ..animation import keyframes
    frames = set()
    for group in groups:
        path = 'pose.bones["%s"].%s' % (bone_name, group)
        for index in range(4):
            fc = keyframes._find_fcurve_index(armature, path, index)
            if fc is None:
                if index >= 3:
                    break
                continue
            for key in fc.keyframe_points:
                frames.add(float(key.co[0]))
    return sorted(frames)


def _baked_groups(pbone):
    """Channel groups the bake reads (location/rotation/scale)."""
    mode = pbone.rotation_mode
    rot = {"QUATERNION": "rotation_quaternion",
           "AXIS_ANGLE": "rotation_axis_angle"}.get(
               mode, "rotation_euler")
    return ("location", rot, "scale")


def _bake_span(armature, weapon, hand):
    """Integer (start, end) covering weapon+hand channel keys."""
    frames = set()
    for bone_name in (weapon, hand):
        pbone = armature.pose.bones.get(bone_name)
        if pbone is None:
            continue
        for f in _channel_key_frames(armature, bone_name,
                                     _baked_groups(pbone)):
            frames.add(f)
    if not frames:
        raise WeaponRigError(
            "Nothing to bake: no weapon/hand keys in this action.")
    for f in sorted(frames):
        if abs(f - round(f)) > 1e-4:
            raise WeaponRigError(
                "Cannot bake: subframe key at %s (re-key it on a whole "
                "frame first; keyframe_insert drops subframes silently)."
                % (f,))
    return int(round(min(frames))), int(round(max(frames)))


def _socket_has_keys(armature, name):
    """True if the socket already carries any transform keys."""
    from ..animation import keyframes
    for group in ("location", "rotation_euler", "rotation_quaternion",
                  "rotation_axis_angle", "scale"):
        path = 'pose.bones["%s"].%s' % (name, group)
        for index in range(4):
            fc = keyframes._find_fcurve_index(armature, path, index)
            if fc is not None and len(fc.keyframe_points):
                return True
    return False


def _remove_socket_keys(armature, name):
    """Best-effort rollback: drop the socket's transform keys."""
    from ..animation import keyframes
    for group in ("location", "rotation_euler", "rotation_quaternion",
                  "rotation_axis_angle", "scale"):
        path = 'pose.bones["%s"].%s' % (name, group)
        for index in range(4):
            fc = keyframes._find_fcurve_index(armature, path, index)
            if fc is None:
                if index >= 3:
                    break
                continue
            try:
                for key in reversed(list(fc.keyframe_points)):
                    try:
                        fc.keyframe_points.remove(key)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                fc.update()
            except Exception:
                pass


def _mesh_frame(armature, weapon, name):
    """Constant weapon-local mesh frame: Translation(pommel) @ map."""
    from mathutils import Matrix, Vector
    bone = armature.data.bones.get(weapon)
    pommel = Vector(tuple(bone.get(POMMEL_PROP, (0.0, 0.0, 0.0))))
    return (Matrix.Translation(pommel)
            @ _socket_frame(armature, weapon, name).to_4x4())


def _tip_distance(armature, weapon):
    """Pommel->tip distance along the blade (mesh tip lever)."""
    from mathutils import Vector
    bone = armature.data.bones.get(weapon)
    tip = Vector(tuple(bone.get(TIP_PROP, (0.0, 1.10, 0.0))))
    pommel = Vector(tuple(bone.get(POMMEL_PROP, (0.0, 0.0, 0.0))))
    return (tip - pommel).length


def bake_socket_follow(armature, side, hand_bone=None):
    """Key the socket so a snapped sword reproduces weapon motion exactly.

    Per integer frame of the weapon+hand key span: desired socket world
    = weapon_world @ M (M = constant weapon-local mesh frame), written
    into the socket's local channels (the matrix setter accounts for
    the hand parent) and keyed (location + euler rotation, LINEAR).
    The parent stays the hand: blends carry the sword with the hand
    side, while at weight 1 the placement is bit-exact authoring.

    Touches NOTHING but the socket bone (its channels + its keys): no
    weapon/hand RNA writes, no other keys, no rest edits. Strict verify
    (socket world vs desired, plus tip GAP) with key rollback on
    mismatch. Refuses pre-keyed sockets (double-bake would corrupt).
    Returns (report_lines, max_tip_gap).
    """
    from ..rig import create as rig_create
    from ..animation import keyframes
    weapon = con_util.get_weapon_bone(armature)
    if hand_bone is None:
        hand_bone = HAND_BONES.get(side, HAND_BONES["R"])
    name = socket_name(side)
    if name not in armature.data.bones:
        raise WeaponRigError(
            "Cannot bake: no '%s' -- create the socket first." % name)
    if hand_bone not in armature.data.bones:
        raise WeaponRigError(
            "Cannot bake: hand bone '%s' missing." % hand_bone)
    parent = armature.data.bones[name].parent
    if parent is None or parent.name != hand_bone:
        raise WeaponRigError(
            "Cannot bake: '%s' is not under '%s' (re-seat the socket)."
            % (name, hand_bone))
    if _socket_has_keys(armature, name):
        raise WeaponRigError(
            "Cannot bake: '%s' already has keys (delete them first -- "
            "double-bake would corrupt the follow)." % name)
    start, end = _bake_span(armature, weapon, hand_bone)
    from mathutils import Vector
    mesh_frame = _mesh_frame(armature, weapon, name)
    tip_dist = _tip_distance(armature, weapon)
    bone = armature.data.bones.get(weapon)
    tip_local = Vector(tuple(bone.get(TIP_PROP, (0.0, 1.10, 0.0))))
    mw = armature.matrix_world.copy()
    mw_inv = mw.inverted()
    context = bpy.context
    cur_frame = int(context.scene.frame_current)
    prev_object_mode = armature.mode
    rig_create._make_active(context, armature)
    sock = armature.pose.bones.get(name)
    prev_rot_mode = sock.rotation_mode
    lpath = 'pose.bones["%s"].location' % name
    rpath = 'pose.bones["%s"].rotation_euler' % name
    try:
        rig_create.bpy_set_mode(armature, 'POSE')
        sock.rotation_mode = 'XYZ'
        for f in range(start, end + 1):
            context.scene.frame_set(f)
            transforms.update_view_layer()
            want = transforms.get_pose_bone_world_matrix(
                armature, weapon) @ mesh_frame
            transforms.set_pose_bone_arm_matrix(
                armature, name, mw_inv @ want)
            if not armature.keyframe_insert(lpath, frame=f):
                raise WeaponRigError(
                    "Failed to bake key '%s' at frame %d." % (lpath, f))
            if not armature.keyframe_insert(rpath, frame=f):
                raise WeaponRigError(
                    "Failed to bake key '%s' at frame %d." % (rpath, f))
        # LINEAR: predictable, no overshoot between dense keys.
        for group, size in ((lpath, 3), (rpath, 3)):
            for index in range(size):
                fc = keyframes._find_fcurve_index(armature, group, index)
                if fc is None:
                    raise WeaponRigError(
                        "Bake lost fcurve '%s'[%d]." % (group, index))
                for key in fc.keyframe_points:
                    key.interpolation = 'LINEAR'
                try:
                    fc.update()
                except Exception:
                    pass
        # Verify every frame: socket world vs desired + tip GAP.
        max_gap = 0.0
        max_solve = 0.0
        for f in range(start, end + 1):
            context.scene.frame_set(f)
            transforms.update_view_layer()
            want = transforms.get_pose_bone_world_matrix(
                armature, weapon) @ mesh_frame
            got = transforms.get_pose_bone_world_matrix(armature, name)
            trans, rot = transforms.matrix_difference(want, got)
            max_solve = max(max_solve, trans)
            if trans > TOL_TRANSLATION or rot > TOL_ROTATION_DEG:
                raise WeaponRigError(
                    "Bake verify failed at frame %d (d-trans %.6f, "
                    "d-rot %.4f deg) -- keys rolled back."
                    % (f, trans, rot))
            tip_want = transforms.get_pose_bone_world_matrix(
                armature, weapon) @ tip_local
            tip_got = got @ Vector((0.0, tip_dist, 0.0))
            gap = (tip_want - tip_got).length
            max_gap = max(max_gap, gap)
            if gap > TOL_TRANSLATION:
                raise WeaponRigError(
                    "Bake tip GAP %.6f at frame %d -- keys rolled back."
                    % (gap, f))
        context.scene.frame_set(cur_frame)
        transforms.update_view_layer()
        n = end - start + 1
        lines = ["Socket '%s' baked %d..%d (%d frames): sword on socket "
                 "== authored weapon motion (max tip GAP %.6f, max "
                 "solve d-trans %.6f). Parent still '%s'; weapon/hand "
                 "untouched." %
                 (name, start, end, n, max_gap, max_solve, hand_bone)]
        return lines, max_gap
    except Exception:
        try:
            sock.rotation_mode = prev_rot_mode
        except Exception:
            pass
        _remove_socket_keys(armature, name)
        try:
            context.scene.frame_set(cur_frame)
            transforms.update_view_layer()
        except Exception:
            pass
        raise
    finally:
        # NOTE: rotation mode stays XYZ on success (the keys are euler;
        # restoring anything else would misread them). Only the object
        # mode is restored here; failure path restores rotation above.
        try:
            if armature.mode != prev_object_mode:
                rig_create.bpy_set_mode(armature, prev_object_mode)
        except Exception:
            pass
