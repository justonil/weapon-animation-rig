"""Dynamic pivot system (plan §21, §22, §23, §24) -- reworked single bone.

WHAT SET PIVOT DOES (plan §22):
    1. Resolve the desired pivot world position (preset).
    2. Translate the weapon bone so its head sits ON the pivot point --
       the head IS the rotation origin, so plain Blender rotation (R key,
       single bone selected -> median == head) afterwards orbits the pivot.
       Pose-space only: no mesh origin touched, no rest-pose change (§23).
    3. Keep everything else visually frozen:
       - preview mesh (if assigned): restore its world transform;
       - attached hands: re-solve their Child Of inverses to their
         captured worlds (moving the weapon bone would otherwise drag
         them along -- same treatment as snap).
    3.5 Re-anchor the grip/tip local offsets so every reference point
       stays frozen in world space (without this the tip would swing
       away the moment the origin lands on it -- offsets are config data
       describing the same physical weapon from the new origin).
    4. Optionally key the changed weapon channels (plan §31: no keys
       unless asked).

    Repeated use at different frames is safe: each call works purely from
    evaluated world transforms, which are invariant under previous pivot
    changes (only local channels differ), so presets resolve to the same
    physical points (plan §22 "must not corrupt the weapon's transform
    when switching pivot modes").

PRESET GEOMETRY (world space, from current evaluated grip/tip points):
    guard   = 2*grip_l - grip_r   (mirror grip_r over grip_l: just above
                                   the upper hand -- geometric default,
                                   presets §17 may store explicit points)
    pommel  = 2*grip_r - grip_l   (mirror grip_l over grip_r: below the
                                   lower hand)
    center  = midpoint(pommel, tip)
    tip     = blade-tip reference point
    grip_*  = grip reference points
    cursor  = scene 3D cursor (plan §24)
    custom  = stored scene vector (plan §21)

SPACES: preset resolution and the root translation work in WORLD space; the
final writes go through the arm-space pose-matrix setter (probe-verified,
handles parents/rest/rotation-mode).
"""
import bpy
from mathutils import Matrix, Vector

from ..constants import (
    CENTER_PROP,
    GRIP_PROP_L,
    GRIP_PROP_R,
    GUARD_PROP_L,
    GUARD_PROP_R,
    POMMEL_PROP,
    TIP_PROP,
    WeaponRigError,
)
from ..utils import transforms

PIVOT_ITEMS = (
    ('CENTER', "Center", "Configured weapon center"),
    ('GRIP_R', "Grip R", "Right hand grip point"),
    ('GRIP_L', "Grip L", "Left hand grip point"),
    ('GUARD', "Guard", "Crossguard center (midpoint of quillon ends)"),
    ('GUARD_L', "Guard L", "Left quillon end"),
    ('GUARD_R', "Guard R", "Right quillon end"),
    ('TIP', "Tip", "Blade tip -- plan §53 Test G"),
    ('POMMEL', "Pommel", "Configured pommel point"),
    ('CURSOR', "3D Cursor", "Current 3D cursor position -- plan §24"),
    ('CUSTOM', "Custom", "Stored custom pivot position"),
)

# Config prop -> pivot preset resolving exactly that point (GUARD itself
# is derived = midpoint, so it has no direct prop).
_PRESET_FOR_PROP = {
    GRIP_PROP_R: 'GRIP_R',
    GRIP_PROP_L: 'GRIP_L',
    GUARD_PROP_L: 'GUARD_L',
    GUARD_PROP_R: 'GUARD_R',
    POMMEL_PROP: 'POMMEL',
    CENTER_PROP: 'CENTER',
    TIP_PROP: 'TIP',
}


def _config_points(armature, dg=None):
    """All configured weapon points, world positions (pure read).

    Returns {preset_name: Vector} for GRIP_R/GRIP_L/GUARD_L/GUARD_R/
    POMMEL/CENTER/TIP using the bone-local custom props.
    """
    from mathutils import Vector as _V
    from ..constants import DEFAULT_GRIP_OFFSETS
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    dg = dg or transforms.evaluated_depsgraph()
    eval_arm = armature.evaluated_get(dg)
    world = eval_arm.matrix_world @ eval_arm.pose.bones[weapon].matrix
    wbone = armature.data.bones.get(weapon)

    def at(prop):
        if wbone is not None and prop in wbone:
            local = _V(tuple(wbone[prop]))
        else:
            local = _V(DEFAULT_GRIP_OFFSETS[prop])
        return (world @ local)

    return {
        'GRIP_R': at(GRIP_PROP_R),
        'GRIP_L': at(GRIP_PROP_L),
        'GUARD_L': at(GUARD_PROP_L),
        'GUARD_R': at(GUARD_PROP_R),
        'POMMEL': at(POMMEL_PROP),
        'CENTER': at(CENTER_PROP),
        'TIP': at(TIP_PROP),
    }


def compute_pivot_world(armature, pivot, custom=(0.0, 0.0, 0.0), dg=None):
    """Resolve a pivot preset to a world-space point (pure read)."""
    from ..utils import constraints as con_util
    con_util.get_weapon_bone(armature)  # raises with a clear error
    if pivot == 'CURSOR':
        return bpy.context.scene.cursor.location.copy()
    if pivot == 'CUSTOM':
        return Vector(custom)

    pts = _config_points(armature, dg)
    if pivot == 'GUARD':
        # Crossguard center: midpoint of the two configured quillon ends.
        return (pts['GUARD_L'] + pts['GUARD_R']) * 0.5
    if pivot in pts:
        return pts[pivot]
    raise WeaponRigError("Unknown pivot preset: %s" % pivot)


def set_pivot(armature, pivot, custom=(0.0, 0.0, 0.0), key=False,
              frame=None):
    """Move the weapon origin onto ``pivot`` without any visible jump.

    Attached hands and the preview mesh are held in place (inverse
    re-solve / world restore). Returns diagnostics.
    Raises WeaponRigError on missing bones or failed verification.
    """
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    if frame is None:
        frame = bpy.context.scene.frame_current

    from ..weapon.preview import get_preview_object

    dg = transforms.evaluated_depsgraph()
    pivot_world = compute_pivot_world(armature, pivot, custom, dg)

    root_before = transforms.get_pose_bone_world_matrix(
        armature, weapon, dg)
    # Reference worlds BEFORE the move -- the local offsets get
    # re-anchored to these afterwards (step 3.5). ALL configured points
    # (a partial set would let guard/pommel/center drift silently).
    from ..constants import CONFIG_PROPS
    refs_before = {
        prop: compute_pivot_world(armature, _PRESET_FOR_PROP[prop],
                                  custom, dg)
        for prop in CONFIG_PROPS
    }
    hands_before = {
        side: transforms.get_pose_bone_world_matrix(
            armature, name, dg)
        for side, name in (("R", "c_hand_ik.r"), ("L", "c_hand_ik.l"))
        if name in armature.data.bones}
    preview = get_preview_object(armature)
    preview_before = preview.matrix_world.copy() if preview else None

    from ..animation import keyframes
    old_channels = keyframes.capture_channels(armature, weapon)

    # 3. Translate the weapon so its head == pivot (keep orientation).
    #    Work fully in WORLD space, then convert once for the setter.
    root_after_world = root_before.copy()
    root_after_world.translation = pivot_world
    root_after_arm = armature.matrix_world.inverted() @ root_after_world
    # 3-4b. Land the head on the pivot, converging against setter
    # imprecision (scaled parents, custom-prop float truncation, solver
    # residuals): re-aim the target by the measured miss until the head is
    # on the pivot (max 4 passes; usually 1-2). Offsets always re-anchor
    # to the INTENDED frame so geometry stays exact; preview/hands re-glue
    # to their captured worlds each pass (idempotent). If a constraint
    # genuinely fights the placement the loop will not converge and the
    # verification below raises loudly instead of accepting a pop.
    wbone = armature.data.bones.get(weapon)
    mw_inv = armature.matrix_world.inverted()
    attached = {s: hands_before[s] for s in ("R", "L")
                if s in hands_before
                and con_util.find_attach_constraint(armature, s) is not None
                and con_util.find_attach_constraint(
                    armature, s).influence > 0.0}
    target_arm = root_after_arm
    for _attempt in range(4):
        transforms.set_pose_bone_arm_matrix(armature, weapon, target_arm)
        transforms.update_view_layer()
        # 3.5 Re-anchor grip/tip offsets so every reference point stays
        # frozen in world space. The bone origin relocates but the weapon
        # GEOMETRY (as the solver/pivots see it) must not move -- otherwise
        # the tip would swing away the moment the origin lands on it.
        # (Pure translation keeps the grip axis direction identical.)
        for prop, world_pos in refs_before.items():
            arm_pos = mw_inv @ world_pos
            wbone[prop] = tuple((target_arm.inverted() @ arm_pos)[:])
        # 4a. Preview mesh: restore world (it rigidly followed the bone).
        if preview is not None:
            preview.matrix_world = preview_before
            transforms.update_view_layer()
        # 4b. Attached hands: re-glue (would otherwise chase the weapon).
        if attached:
            con_util.preserve_attached_hands(armature, attached)
        head_now = transforms.get_pose_bone_world_matrix(
            armature, weapon).translation
        residual = pivot_world - head_now
        if residual.length <= transforms.TOL_TRANSLATION:
            break
        # Re-aim the setter target by the miss (world space).
        target_world = (armature.matrix_world @ target_arm).copy()
        target_world.translation = target_world.translation + residual
        target_arm = armature.matrix_world.inverted() @ target_world
    transforms.update_view_layer()

    # 4c. Preserve EXISTING animation: the re-anchor above is a pure
    # translation (orientation kept by construction), so every already-keyed
    # location must move by the same pose-space delta -- otherwise keyed
    # frames authored for the old origin swing the weapon elsewhere and the
    # animation breaks. Rotation/scale must be bit-identical; anything else
    # is a loud error, never a silent corruption (undo with Ctrl+Z).
    new_channels = keyframes.capture_channels(armature, weapon)
    # Bone-space origin shift S: Pose_new = Pose_old @ T(S). Single matrix
    # capturing the re-anchor exactly; MUST be pure translation (rotation
    # and scale bit-identical) -- anything else is a loud error, never a
    # silent corruption (undo with Ctrl+Z). Per-key compensation then uses
    # each frame's own R(F)/Scl(F), so rotation animation keeps orbiting
    # the ORIGINAL points after the origin moves.
    pose_old = keyframes.compose_channel_matrix(old_channels)
    pose_new = keyframes.compose_channel_matrix(new_channels)
    T_bone = pose_old.inverted() @ pose_new
    _r3 = T_bone.to_3x3()
    _eye3 = Matrix.Identity(3)
    if max(abs(v) for row in (_r3 - _eye3) for v in row) > 1e-6:
        raise WeaponRigError(
            "Set Pivot (%s) is not translation-only (rotation/scale "
            "changed); refusing to shift keys to avoid corrupting "
            "animation. Undo (Ctrl+Z) to restore." % pivot)
    S_bone = T_bone.translation
    shifted_keys = keyframes.shift_location_keys(armature, weapon, S_bone)
    # Editing keys dirties animation data: on the next update, location
    # fcurves (if any) re-apply at the current frame over our manual
    # placement. So re-assert the target pose and -- while RNA still holds
    # the manual value, BEFORE any update -- pin it with a compensation
    # location key if (and only if) location is animated. Static poses need
    # no key (re-apply holds, plan §31 respected).
    transforms.set_pose_bone_arm_matrix(armature, weapon, target_arm)
    loc_path = 'pose.bones["%s"].location' % weapon
    pinned = False
    if keyframes.find_fcurve(armature, loc_path) is not None:
        if not armature.keyframe_insert(loc_path, frame=frame):
            raise WeaponRigError(
                "Set Pivot (%s) could not pin the corrected pose "
                "(keyframe insert failed). Undo (Ctrl+Z) to restore."
                % pivot)
        pinned = True
    transforms.update_view_layer()

    # --- verification (plan §30) ----------------------------------------
    dg = transforms.evaluated_depsgraph()
    problems = []
    root_now = transforms.get_pose_bone_world_matrix(
        armature, weapon, dg)
    if (root_now.translation - pivot_world).length > \
            transforms.TOL_TRANSLATION:
        problems.append("weapon head off pivot by %.6f"
                        % (root_now.translation - pivot_world).length)
    for sname, hb in (("R", "c_hand_ik.r"), ("L", "c_hand_ik.l")):
        if sname not in hands_before:
            continue
        now = transforms.get_pose_bone_world_matrix(armature, hb, dg)
        t_err, r_err = transforms.matrix_difference(hands_before[sname],
                                                    now)
        if t_err > transforms.TOL_TRANSLATION:
            problems.append("hand %s jumped %.6f" % (sname, t_err))
        if r_err > transforms.TOL_ROTATION_DEG:
            problems.append("hand %s rotated %.4f deg" % (sname, r_err))
    # Reference points must be frozen too (re-anchored offsets working).
    for prop, want in refs_before.items():
        got = compute_pivot_world(armature, _PRESET_FOR_PROP[prop],
                                  custom, dg)
        if (got - want).length > transforms.TOL_TRANSLATION:
            problems.append("reference %s moved %.6f"
                            % (prop, (got - want).length))
    if preview is not None:
        t_err, _ = transforms.matrix_difference(
            preview_before, preview.matrix_world.copy())
        if t_err > transforms.TOL_TRANSLATION:
            problems.append("preview mesh jumped %.6f" % t_err)
    if problems:
        raise WeaponRigError("Set Pivot (%s) failed: %s."
                             % (pivot, "; ".join(problems)))

    # 5. Optional keys (plan §31): weapon channels only (hands/preview
    #    untouched -- their pose did not change).
    keyed = []
    if key:
        changed = keyframes.key_changed_channels(armature, weapon,
                                                 frame, old_channels)
        keyed = list(changed.keys())
    return {
        "pivot": pivot,
        "pivot_world": pivot_world,
        "keyed": bool(key),
        "keyed_groups": keyed,
        "shifted_keys": shifted_keys,
        "pinned_frame": frame if pinned else None,
    }
