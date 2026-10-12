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
"""
import bpy

from ..constants import HAND_BONES
from ..constants import POMMEL_PROP
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
    (Gram-Schmidt orthogonalized vs the blade), Z along the blade
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
    cols = [tuple(x_s), tuple(y_s), tuple(z_s)]
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
        # mesh +Z (blade) lands on blade_axis, mesh +X (guard bar) on
        # the tuned guard direction, Y completes right-handed (verified
        # on the reference origin-to-origin bind and matching
        # prop/geometry extents). EditBone.matrix assignment decomposes
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
