"""Weapon animation baking (plan §44, §45) -- Milestone 5.

WHAT BAKE DOES: converts the control-rig result (ARP IK + attach Child Of
+ weapon animation + aim track, all evaluated) into plain channel keys on
the export bones, so Unreal reproduces the shot from the FBX alone with
the weapon as a plain Static Mesh on the weapon bone (plan §46).

SCOPE (plan §44-45 MVP, reworked): the single weapon bone.
Character+hand baking is explicitly deferred by plan §45 ("eventually"):
hands are constraint-driven followers, and the plan accepts weapon-only
baking as the first production-ready step.

CONSTRAINT CORRECTNESS (probe-verified on Blender 5.2):
The pb.matrix setter does NOT invert active constraints -- writing the
evaluated matrix as channels and re-evaluating applies the constraint a
second time. For our Damped Track (WPN_Aim) this is harmless at BINARY
influence: channels already point at the target, so the tracker's minimal
rotation is ~identity and playback reproduces the sampled matrices. It is
NOT harmless for blended (partial) influence, so bake refuses those frames
with a clear error instead of silently corrupting (plan §30, §54).
Any OTHER live constraint on the bake bones is likewise refused.

HOW (plan §44):
    1. for each frame in [start-1 .. end+1]: frame_set -> read final
       pose-space (armature-space) matrices of the bake bones. The ±1 guard
       frames pin the source pose so frames OUTSIDE the baked range keep
       evaluating exactly as before (plan §30).
    2. target action: NEW = full copy of the source action (all character
       animation survives intact, plan §29); CURRENT = bake into source.
    3. for each sampled frame: set channels from the sample, keyframe
       location + rotation + scale at that frame.
    4. verification (plan §52): re-evaluate every few frames with the baked
       action assigned and compare to the samples.

PARENT-RELATIVE KEYING: the weapon's channels are solved by Blender's
pose-matrix setter, which accounts for the parent's CURRENT pose -- so each
frame's write happens with that frame evaluated (frame_set stays on the
sampled frame during its write). Writing a whole range from memory against
a single parent pose would corrupt root-motion shots.
"""
import bpy

from ..constants import (
    WeaponRigError,
    missing_weapon_bone,
)
from ..utils import transforms
from ..weapon.aim import AIM_CONSTRAINT



def _bind_action(armature, action):
    """Assign action and bind its corresponding slot (slotted API, 5.2)."""
    ad = armature.animation_data
    if ad is None:
        armature.animation_data_create()
        ad = armature.animation_data
    prev = getattr(ad, "action_slot", None)
    want_id = prev.identifier if prev is not None else None
    slot = None
    if want_id is not None:
        try:
            slot = action.slots.get(want_id)
        except Exception:
            slot = None
    if slot is None and len(action.slots) > 0:
        slot = action.slots[0]
    ad.action = action
    if slot is not None:
        ad.action_slot = slot
    transforms.update_view_layer()


def _active_constraint_influences(armature, bone_name):
    """{constraint_name: influence} for constraints on this bone.

    Called with the desired frame evaluated, so the property values are
    the frame's animated values (probe-verified: RNA reads give the
    evaluated influence, not the static one)."""
    pbone = armature.pose.bones.get(bone_name)
    if pbone is None:
        return {}
    return {c.name: c.influence for c in pbone.constraints}


def bake_weapon_animation(armature, frame_start, frame_end,
                          mode='NEW_ACTION'):
    """Bake the weapon bone over [frame_start, frame_end].

    mode: 'NEW_ACTION' (default, plan §44: never overwrite by default) or
    'CURRENT_ACTION' (bake into the source action -- explicit choice).
    The weapon bone is resolved (legacy weapon_root works too).
    Returns {"action": name, "created": bool, "frames": n,
             "max_error": (t, r)}.
    """
    from ..utils import constraints as con_util
    bake_bones = (con_util.get_weapon_bone(armature),)
    if frame_end < frame_start:
        raise WeaponRigError("Bake range invalid: end < start.")

    scene = bpy.context.scene
    saved_frame = scene.frame_current

    ad = armature.animation_data
    source = ad.action if ad is not None else None
    if mode == 'CURRENT_ACTION' and source is None:
        raise WeaponRigError(
            "Bake into current action requested, but the armature has no "
            "action.")

    # Target action: full copy (character animation survives intact) or the
    # source itself for CURRENT_ACTION.
    if mode == 'NEW_ACTION':
        if source is not None:
            target = source.copy()
            target.name = "%s_Baked" % source.name
        else:
            target = bpy.data.actions.new("WeaponBaked")
        _bind_action(armature, target)
        created = True
    else:
        target = source
        created = False

    # Guard frames pin the pre-bake pose outside the range (plan §30).
    sample_frames = [frame_start - 1] + \
        list(range(frame_start, frame_end + 1)) + [frame_end + 1]

    from ..animation import keyframes
    samples = {}
    try:
        # --- 1. sample -------------------------------------------------
        for frame in sample_frames:
            scene.frame_set(frame)
            dg = transforms.evaluated_depsgraph()
            per_bone = {}
            for name in bake_bones:
                matrix = transforms.get_pose_bone_arm_matrix(
                    armature, name, dg)
                if matrix is None:
                    raise missing_weapon_bone(name)
                per_bone[name] = matrix
                # Constraint audit: anything but binary WPN_Aim influence
                # cannot be reproduced by channel keys (probe-verified).
                for con_name, infl in \
                        _active_constraint_influences(armature, name).items():
                    if con_name == AIM_CONSTRAINT:
                        if not (infl <= 1e-4 or abs(infl - 1.0) <= 1e-4):
                            raise WeaponRigError(
                                "Bake failed: %s has blended aim influence "
                                "%.3f at frame %d (keyframe the aim switch "
                                "with stepped values first)." % (
                                    name, infl, frame))
                    elif infl > 1e-4:
                        raise WeaponRigError(
                            "Bake failed: unexpected live constraint %s "
                            "(influence %.3f) on %s at frame %d -- disable "
                            "it before baking." % (con_name, infl, name,
                                                   frame))
            samples[frame] = per_bone

        # --- 3. write keys ---------------------------------------------
        for frame in sample_frames:
            scene.frame_set(frame)
            for name in bake_bones:
                transforms.set_pose_bone_arm_matrix(
                    armature, name, samples[frame][name])
                pbone = armature.pose.bones[name]
                for path in keyframes.channel_data_paths(pbone):
                    armature.keyframe_insert(path, frame=frame)
        transforms.update_view_layer()

        # --- 4. verification (plan §52) ----------------------------------
        worst_t = worst_r = 0.0
        stride = max(1, len(sample_frames) // 20)
        for frame in sample_frames[::stride]:
            scene.frame_set(frame)
            dg = transforms.evaluated_depsgraph()
            for name in bake_bones:
                got = transforms.get_pose_bone_arm_matrix(
                    armature, name, dg)
                t, r = transforms.matrix_difference(samples[frame][name], got)
                worst_t = max(worst_t, t)
                worst_r = max(worst_r, r)
        if worst_t > transforms.TOL_TRANSLATION:
            raise WeaponRigError(
                "Bake verification failed: translation drift %.6f." % worst_t)
    finally:
        scene.frame_set(saved_frame)

    return {
        "action": target.name,
        "created": created,
        "frames": len(sample_frames),
        "max_error": (worst_t, worst_r),
    }
