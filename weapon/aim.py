"""Aim system (plan §25, §26, §27) -- Milestone 4.

DESIGN (probe-verified on Blender 5.2):
- ``weapon_aim`` is an INDEPENDENT target bone, parented to the character
  ``root`` (NOT to the weapon bone). Aiming at a bone that is itself a child of
  the aiming bone would be a dependency cycle (weapon rotation moves the
  target, which moves the weapon...). Plan §2 explicitly allows adjusting
  the exact hierarchy; the mandatory part is the *role*: a target the
  animator moves and the weapon orients toward.
- Live aim = Damped Track on the weapon bone -> weapon_aim (track axis from the
  weapon's blade_axis config). Influence is animatable (plan §25).
- Roll (plan §27): Blender's Damped Track has no roll parameter, but the
  probe proved its output = f(direction) composed with the owner's current
  channels -- so pre-rotating the weapon's channels about the LOCAL blade
  axis changes the roll by EXACTLY that angle (40.0000 deg measured) while
  the tracked direction stays fixed (1e-8). This is the "manual
  roll/offset" of plan §25's conceptual system, and it works identically
  with or without the live constraint active.
- Point Blade At (plan §26) = one-shot solve: minimal-arc alignment of the
  blade axis to the aim direction, then absolute roll about it.

BLADE AXIS (plan §47): bone-local axis pointing toward the tip, stored as
the ``blade_axis`` custom property on the weapon bone ('+Y' = Blender bone
axis, default matches the creation layout where the tip sits along the
bone's +Y). Exposed but never hardcoded -- different weapon meshes get
different values.

ATTACH INTERACTION: aim/point ops act on the weapon's channels and are
compatible with attached hands (hands keep following the grips).
Point Blade At sets aim influence to 0 first if live aim is active, since
a live tracker would override the solved orientation on next eval.
"""
import math

import bpy
from mathutils import Matrix, Vector

from ..constants import (
    BLADE_AXES,
    TOL_TRANSLATION,
    WeaponRigError,
    missing_weapon_bone,
)
from ..utils import transforms

BONE_AIM = "weapon_aim"
AIM_CONSTRAINT = "WPN_Aim"

# Near-parallel / anti-parallel guard (plan §55: vector alignment must not
# produce unstable quaternions).
_EPS_DIR = 1e-6


def get_blade_axis(armature):
    """(local_vector, track_axis_enum) from the weapon config."""
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    tag = armature.data.bones.get(weapon, {}).get("blade_axis", "+Y")
    if tag not in BLADE_AXES:
        raise WeaponRigError(
            "Invalid blade_axis %r on %s (must be one of %s)."
            % (tag, weapon, ", ".join(sorted(BLADE_AXES))))
    return BLADE_AXES[tag]


def set_blade_axis(armature, tag):
    if tag not in BLADE_AXES:
        raise WeaponRigError("Invalid blade axis %r." % tag)
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    bone = armature.data.bones.get(weapon)
    if bone is None:
        raise missing_weapon_bone(weapon)
    bone["blade_axis"] = tag


def _aim_target_world(armature, dg=None):
    m = transforms.get_pose_bone_world_matrix(armature, BONE_AIM, dg)
    if m is None:
        raise missing_weapon_bone(BONE_AIM)
    return m


def _apply_channels(armature, world_matrix):
    """Write the weapon bone's world matrix; returns nothing (verify separately)."""
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    transforms.set_pose_bone_arm_matrix(
        armature, weapon,
        armature.matrix_world.inverted() @ world_matrix)
    transforms.update_view_layer()


def _blade_dir_world(armature, axis_local, dg=None):
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    m = transforms.get_pose_bone_world_matrix(armature, weapon, dg)
    if m is None:
        raise missing_weapon_bone(weapon)
    return (m.to_3x3() @ axis_local).normalized(), m


def point_blade_at(armature, roll_degrees=0.0, key=False, frame=None):
    """One-shot: orient the blade axis at weapon_aim + absolute roll (§26).

    Position is never touched. Never keys unless ``key=True`` (plan §31).
    Disables live aim first (it would override the solved orientation).
    """
    weapon = _require_rig(armature)
    axis_local, _track = get_blade_axis(armature)
    if frame is None:
        frame = bpy.context.scene.frame_current

    aim = _aim_target_world(armature)
    dg = transforms.evaluated_depsgraph()
    root_w = transforms.get_pose_bone_world_matrix(armature, weapon, dg)

    to_target = aim.translation - root_w.translation
    if to_target.length < _EPS_DIR:
        raise WeaponRigError(
            "Point Blade At failed: weapon_aim coincides with the weapon bone "
            "(aim direction is undefined).")
    want_dir = (to_target / to_target.length)

    blade_dir, _ = _blade_dir_world(armature, axis_local, dg)
    # Shortest-arc alignment (explicitly rolls NOTHING; roll comes next).
    if (blade_dir - want_dir).length < _EPS_DIR:
        align = Matrix.Identity(3)
    elif (blade_dir + want_dir).length < _EPS_DIR:
        # Anti-parallel: rotate 180 deg about any perpendicular axis.
        perp = blade_dir.cross(Vector((1, 0, 0)))
        if perp.length < _EPS_DIR:
            perp = blade_dir.cross(Vector((0, 1, 0)))
        align = Matrix.Rotation(math.pi, 3, perp.normalized())
    else:
        align = blade_dir.rotation_difference(want_dir).to_matrix()

    check = (align @ blade_dir - want_dir).length
    if check > 1e-4:
        raise WeaponRigError(
            "Point Blade At failed: alignment unstable (residual %.6f)."
            % check)

    roll = Matrix.Rotation(math.radians(roll_degrees), 3, want_dir)
    new_rot = roll @ align @ root_w.to_3x3()
    new_world = Matrix.Translation(root_w.translation) @ new_rot.to_4x4()

    from ..animation import keyframes
    old_channels = keyframes.capture_channels(armature, weapon)

    aim_con = _find_aim_constraint(armature)

    _set_aim_influence(armature, 0.0)  # manual mode: live aim must not fight
    _apply_channels(armature, new_world)

    # Verify: blade direction points at the target (plan §30, §51).
    dg = transforms.evaluated_depsgraph()
    got, final_w = _blade_dir_world(armature, axis_local, dg)
    ang = math.degrees(got.angle(want_dir)) if got.length and want_dir.length else 0.0
    # Position must be untouched (§26: orientation only).
    trans, _rot = transforms.matrix_difference(
        Matrix.Translation(root_w.translation),
        Matrix.Translation(final_w.translation))
    if ang > 0.5 or trans > TOL_TRANSLATION:
        raise WeaponRigError(
            "Point Blade At failed verification (off %.4f deg, %.6f). "
            % (ang, trans))
    if key:
        _key_weapon(armature, frame, old_channels)
        if aim_con is not None and _aim_differs(armature, 0.0):
            # Persist the manual-mode switch (plan §31).
            keyframes.keyframe_influence(armature, weapon,
                                         AIM_CONSTRAINT, frame, 0.0)
    return {"angle_error_deg": ang, "roll_degrees": roll_degrees}


def aim_weapon(armature, roll_degrees=0.0, key=False, frame=None):
    """Enable live aim (Damped Track) then apply absolute roll (plan §25/27).

    Ensures the WPN_Aim constraint exists (never duplicated), sets
    influence to 1, then solves channels exactly like point_blade_at so the
    roll value is ABSOLUTE (re-running with 30 deg gives 30 deg, never
    compounds). Never keys unless ``key=True``.
    """
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)  # validates rig
    if frame is None:
        frame = bpy.context.scene.frame_current

    con = _ensure_aim_constraint(armature)

    # One-shot solve carries the absolute roll; the live tracker then
    # maintains direction while the channel roll survives (probe-verified).
    result = point_blade_at(armature, roll_degrees=roll_degrees, key=key,
                            frame=frame)
    con.influence = 1.0
    transforms.update_view_layer()

    # Verify tracking holds with the constraint active.
    axis_local, _t = get_blade_axis(armature)
    dg = transforms.evaluated_depsgraph()
    aim = _aim_target_world(armature, dg)
    root_w = transforms.get_pose_bone_world_matrix(armature, weapon, dg)
    want = (aim.translation - root_w.translation).normalized()
    got, _ = _blade_dir_world(armature, axis_local, dg)
    ang = math.degrees(got.angle(want))
    if ang > 0.5:
        raise WeaponRigError(
            "Aim Weapon failed verification (off %.4f deg)." % ang)

    if key:
        from ..animation import keyframes
        keyframes.keyframe_influence(armature, weapon, AIM_CONSTRAINT,
                                     frame, 1.0)
    result["aimed"] = True
    return result


def _aim_owner(armature):
    """Bone name carrying WPN_Aim, or None."""
    con = _find_aim_constraint(armature)
    if con is None:
        return None
    for pb in armature.pose.bones:
        if pb.constraints.get(AIM_CONSTRAINT) is con:
            return pb.name
    return None


def stop_aim(armature, key=False, frame=None):
    """Disable live aim (influence 0), pose untouched."""
    con = _find_aim_constraint(armature)
    if con is None:
        return {"stopped": False}
    owner = _aim_owner(armature)
    con.influence = 0.0
    transforms.update_view_layer()
    if key:
        if frame is None:
            frame = bpy.context.scene.frame_current
        from ..animation import keyframes
        if owner is not None and _aim_differs(armature, 0.0):
            keyframes.keyframe_influence(armature, owner,
                                         AIM_CONSTRAINT, frame, 0.0)
    return {"stopped": True}


def _aim_differs(armature, value, tol=1e-9):
    """True unless aim influence is statically ``value`` with no fcurve.

    The no-fcurve case is the only one where the RNA read is exact (no
    fcurve exists that could override it); otherwise assume a key is
    needed. Avoids gratuitous keys when aim was never animated (§31).
    """
    from ..animation import keyframes
    owner = _aim_owner(armature)
    con = _find_aim_constraint(armature)
    if con is None or owner is None:
        return False
    fc = keyframes.find_fcurve(
        armature, keyframes.influence_data_path(owner,
                                                AIM_CONSTRAINT))
    if fc is None:
        return abs(con.influence - value) > tol
    return True


def set_roll(armature, roll_degrees, key=False, frame=None):
    """Relative roll: rotate weapon_root about its CURRENT blade axis.

    With live aim active the tracked direction is preserved (rolling about
    the track axis cannot change where it points -- probe-verified exact);
    without aim it just spins the weapon about its own blade axis (§27).
    """
    weapon = _require_rig(armature)
    axis_local, _t = get_blade_axis(armature)
    if frame is None:
        frame = bpy.context.scene.frame_current

    dg = transforms.evaluated_depsgraph()
    root_w = transforms.get_pose_bone_world_matrix(armature, weapon, dg)
    blade_dir = (root_w.to_3x3() @ axis_local).normalized()

    from ..animation import keyframes
    old_channels = keyframes.capture_channels(armature, weapon)

    # Roll ABOUT THE BONE HEAD: T(head) @ R @ T(-head). A plain
    # pre-multiplication (R @ W) would swing the head around the world
    # origin instead.
    head = root_w.translation.copy()
    rot_new = (Matrix.Rotation(math.radians(roll_degrees), 3, blade_dir)
               @ root_w.to_3x3())
    _apply_channels(armature, Matrix.Translation(head) @ rot_new.to_4x4())
    if key:
        _key_weapon(armature, frame, old_channels)

    # Verify direction unchanged and roll applied (plan §27).
    dg = transforms.evaluated_depsgraph()
    new_w = transforms.get_pose_bone_world_matrix(armature, weapon, dg)
    new_dir = (new_w.to_3x3() @ axis_local).normalized()
    if (new_dir - blade_dir).length > 1e-3:
        raise WeaponRigError(
            "Set Roll failed: blade direction changed (%.6f)."
            % (new_dir - blade_dir).length)
    return {"roll_degrees": roll_degrees}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _require_rig(armature):
    """Returns the resolved weapon bone name; raises if rig incomplete."""
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    if BONE_AIM not in armature.data.bones:
        raise missing_weapon_bone(BONE_AIM)
    return weapon


def _find_aim_constraint(armature):
    for pbone in armature.pose.bones:
        con = pbone.constraints.get(AIM_CONSTRAINT)
        if con is None:
            continue
        if con.type != 'DAMPED_TRACK':
            raise WeaponRigError(
                "Constraint %s exists but is not a Damped Track "
                "(found %s) -- refusing to reuse it."
                % (AIM_CONSTRAINT, con.type))
        return con
    return None


def _ensure_aim_constraint(armature):
    """Find or create the WPN_Aim Damped Track (never duplicated)."""
    from ..utils import constraints as con_util
    existing = _find_aim_constraint(armature)
    axis_local, track_axis = get_blade_axis(armature)
    if existing is not None:
        existing.target = armature
        existing.subtarget = BONE_AIM
        existing.track_axis = track_axis
        return existing
    weapon = con_util.get_weapon_bone(armature)
    pbone = armature.pose.bones.get(weapon)
    if pbone is None:
        raise missing_weapon_bone(weapon)
    con = pbone.constraints.new('DAMPED_TRACK')
    con.name = AIM_CONSTRAINT
    con.target = armature
    con.subtarget = BONE_AIM
    con.track_axis = track_axis
    con.influence = 0.0
    return con


def _set_aim_influence(armature, value):
    con = _find_aim_constraint(armature)
    if con is not None:
        con.influence = value
        transforms.update_view_layer()


def _key_weapon(armature, frame, old_channels):
    from ..animation import keyframes
    from ..utils import constraints as con_util
    return keyframes.key_changed_channels(armature,
                                          con_util.get_weapon_bone(armature),
                                          frame, old_channels)
