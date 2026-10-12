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
from ..constants import WeaponRigError
from ..utils import constraints as con_util
from ..utils import transforms


def socket_name(side):
    """Dedicated socket bone name (never collides with the rig)."""
    return "socket_%s" % side.lower()


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
        from mathutils import Vector
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
        # Socket frame = weapon frame translated to the seat point:
        # the bone LOOKS along the blade (tail toward the tip, as
        # expected) and MUST be used with Keep-Relative attach rules
        # (rigid offset follow, never full re-snap: a full snap would
        # map mesh +Z (blade) onto socket Z (perp to blade) -- 90 deg
        # off by construction, for ANY tail direction but this one's
        # correct rigid follow. See module docstring.
        wrot = (mw_inv @ weapon_world).to_3x3()
        try:
            _axis_prop = armature.data.bones[weapon].get(
                "blade_axis", "+Y")
        except Exception:
            _axis_prop = "+Y"
        _axes = {"+X": Vector((1.0, 0.0, 0.0)),
                 "-X": Vector((-1.0, 0.0, 0.0)),
                 "+Y": Vector((0.0, 1.0, 0.0)),
                 "-Y": Vector((0.0, -1.0, 0.0)),
                 "+Z": Vector((0.0, 0.0, 1.0)),
                 "-Z": Vector((0.0, 0.0, -1.0))}
        tail_arm = head_arm + (wrot @ _axes.get(
            _axis_prop, Vector((0.0, 1.0, 0.0)))) * 0.02
        rig_create.bpy_set_mode(armature, 'EDIT')
        ebones = armature.data.edit_bones
        eb = ebones.get(name)
        created = eb is None
        if created:
            eb = ebones.new(name)
        # Parent FIRST, then head/tail: assigning a parent can shift
        # explicitly-set heads otherwise (bisected 0.72 seat miss).
        eb.parent = ebones.get(hand_bone)
        eb.use_connect = False
        eb.use_deform = False
        eb.head = head_arm
        eb.tail = tail_arm
        rig_create.bpy_set_mode(armature, 'POSE')
        # Verify full matrices (strict): pose-space head/tail reads
        # carry parent-relative semantics, so only whole-matrix
        # comparison is meaningful. Rollback = remove the bone we just
        # created; pose/keys of weapon and hand are untouched otherwise.
        from mathutils import Matrix
        transforms.update_view_layer()
        dg2 = transforms.evaluated_depsgraph()
        eval2 = armature.evaluated_get(dg2)
        sock_pb = eval2.pose.bones.get(name)
        hand_pb = eval2.pose.bones.get(hand_bone)
        err = 1e9
        if sock_pb is not None and hand_pb is not None:
            # Rigid-child model: socket rides the hand from bind head.
            # Translation only: rest orientation is the bone's own and
            # is not part of the seat contract (roll is user-tweaked).
            hand_rest2 = armature.data.bones[
                hand_bone].matrix_local.copy()
            exp = eval2.matrix_world @ hand_pb.matrix @ \
                hand_rest2.inverted() @ \
                Matrix.Translation(head_arm)
            got = eval2.matrix_world @ sock_pb.matrix
            err = (exp.translation - got.translation).length
        if err > 1e-4:
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
