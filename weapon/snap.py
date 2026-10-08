"""Weapon snapping (plan §18, §19, §20) -- reworked: grips are bone-local
reference POINTS in custom properties, not bones.

WHAT THIS DOES: solves a new transform for the single ``weapon`` bone so
its grip points land on the character's hand IK controllers. It writes ONLY
the weapon bone -- hands, character and hand animation are never touched
(plan §18: "do not move the character, do not alter the hand animation").

ATTACHED HANDS STAY PUT: if a hand is attached when the weapon moves, its
Child Of would chase the weapon by the full delta and end up OFF its grip.
Instead we capture attached hands' worlds first and re-solve their
constraint inverses afterwards (preserve_attached_hands) -- the weapon
lands where it should AND the hands never move. No channels touched, no
keys written for this. Detached hands never move anyway (constraint off).

SPACES: all solving happens with mathutils matrices/quaternions in WORLD
space (plan §20, §56 -- no manual atan2, no Euler math). The final write
converts to armature space and goes through Blender's ``PoseBone.matrix``
setter, which solves the underlying channels (probe-verified: residual
~5e-7 including parents/rest pose).

KEYFRAME POLICY (plan §31): snapping creates NO keys unless requested
(``key=True``, driven from the UI by the [Key] toggle or Blender's Auto
Key). When keys ARE requested and the channel had no fcurves yet, a guard
key at frame-1 pins the pre-snap value so other frames do not shift
(same discipline as detach, plan §30).

--------------------------------------------------------------------------
TWO-HAND SOLVER (plan §20) -- derivation, because this is high-risk (§57):
--------------------------------------------------------------------------
Given (all world space, evaluated at the current frame):
    Hr, Hl   = right/left hand IK world matrices (targets)
    W        = weapon world matrix (current)
    lr, ll   = grip offsets in weapon space (rigid config constants)

We must find W_new (rotation R + translation t) such that:
    (1) direction:  R @ (ll - lr)  ||  (Hl.t - Hr.t)   [same sense]
    (2) translation: t anchors grip_r onto the right hand (plan §20 step 6)

Step 1+5 -- rotation. Aligning one vector leaves one rotational DOF (roll
about the grip axis). We resolve it by building two orthonormal FRAMES:
    F_local  : columns = grip axis u (weapon local), weapon reference axis
               (weapon local X projected perpendicular to u, fallback Z/Y
               -- the implicit "blade flat" config, plan §47)
    F_target : columns = grip axis u_t (hand spacing), RIGHT-hand reference
               axis (hand local X projected perpendicular to u_t, fallback
               Z then Y -- plan §20: preferred roll reference is the right
               hand orientation)
    R = F_target @ F_local^-1        (F^-1 == transpose, orthonormal)

Frame construction instead of shortest-arc quaternions is deliberate:
it is immune to the near-180-degree ambiguity of ``rotation_difference``
(plan §55) and degrades gracefully for mirrored/crossed hands, because the
reference axes are always projected and re-orthonormalized.

Step 6 -- translation:  t = Hr.t - R @ lr (grip_r exactly on Hr).

Step 7 -- errors: grip_r is exact by construction; grip_l can only match
if |hand spacing| == |grip spacing| (the weapon is rigid, no scaling).
We report both errors (plan §20 step 7) and warn when the spacing
mismatch -- rather than the solver -- is responsible for the left error.

DEGENERATE INPUT (plan §55): if |Hl.t - Hr.t| < epsilon the orientation is
mathematically ambiguous. Fallback: position-grip_r onto the right hand and
use the RIGHT-HAND aim (bone Y) with minimal-arc (geodesic) alignment of
the weapon's blade axis -- i.e. right-hand orientation while keeping the
weapon's current roll -- and REPORT A WARNING. No unstable quaternion is
ever produced.
"""
from mathutils import Matrix, Vector

import bpy

from ..constants import (
    HAND_BONES,
    TOL_TRANSLATION,
    WeaponRigError,
    missing_bone,
    missing_weapon_bone,
)
from ..utils import transforms

# Degenerate hand-spacing threshold (plan §55).
EPS_HAND_DISTANCE = 1e-6
# Frame fallback: projection considered degenerate below this fraction.
_EPS_PROJ = 1e-4

# Home-pose slots: weapon transform relative to a hand (H^-1 @ W),
# stored as 16 row-major floats in weapon-bone custom props. Relative
# storage follows the hand: recall restores the recorded spatial
# relationship against the hand's CURRENT pose. Re-record after editing
# grip offsets (they change what the stored relationship means).
HOME_PROP = {"R": "snap_home_r", "L": "snap_home_l"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _require_bone(armature, bone_name, kind):
    if bone_name not in armature.data.bones:
        raise (missing_bone(bone_name) if kind == "arp"
               else missing_weapon_bone(bone_name))


def _world(armature, bone_name, dg=None):
    matrix = transforms.get_pose_bone_world_matrix(armature, bone_name, dg)
    if matrix is None:
        raise missing_weapon_bone(bone_name)
    return matrix


def _apply_weapon(armature, world_matrix):
    """Write the weapon bone's world matrix via the pose-matrix setter."""
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    arm_space = armature.matrix_world.inverted() @ world_matrix
    transforms.set_pose_bone_arm_matrix(armature, weapon, arm_space)
    transforms.update_view_layer()


def _key_weapon(armature, frame, old_channels):
    """Key changed weapon channels (only when requested, plan §31)."""
    from ..animation import keyframes
    from ..utils import constraints as con_util
    return keyframes.key_changed_channels(armature,
                                          con_util.get_weapon_bone(armature),
                                          frame, old_channels)


def _grip_offsets(armature):
    """(grip_r, grip_l) local offsets as Vectors (rework: custom props)."""
    from ..utils import constraints as con_util
    return (con_util.grip_offset(armature, "R"),
            con_util.grip_offset(armature, "L"))


def _preserve_hands(armature, captured):
    """Re-glue attached hands after the weapon moved (no channels, no keys).

    ``captured``: {side: world Matrix} read BEFORE the weapon move.
    Detached hands need nothing (constraint off -- they never moved).
    """
    if not captured:
        return
    from ..utils import constraints as con_util
    con_util.preserve_attached_hands(armature, captured)


def _capture_hands(armature, dg=None):
    """Current world matrices of both hand IK bones."""
    return {side: _world(armature, HAND_BONES[side], dg)
            for side in ("R", "L")}


def _make_frame(axis, *candidates):
    """Orthonormal rotation matrix with column 0 == normalized ``axis`` and
    column 1 == the first candidate projected perpendicular to the axis.

    Returns None only if the axis itself is degenerate. Falls back through
    the given candidates, then through the global axes (plan §55 robustness:
    weapon pointing along the chosen reference axis must not blow up).
    """
    u = Vector(axis)
    if u.length < _EPS_PROJ:
        return None
    u.normalize()

    v = None
    for cand in list(candidates) + [Vector((1, 0, 0)),
                                    Vector((0, 0, 1)),
                                    Vector((0, 1, 0))]:
        c = Vector(cand)
        proj = c - u * c.dot(u)
        if proj.length > _EPS_PROJ:
            v = proj
            break
    if v is None:
        return None
    v.normalize()
    w = u.cross(v)
    # Matrix(rows=...) then transpose -> columns are the basis vectors.
    return Matrix((u, v, w)).transposed()


# ---------------------------------------------------------------------------
# Single-hand snap (plan §18, §19)
# ---------------------------------------------------------------------------

def snap_weapon_to_hand(armature, side, align_orientation=False,
                        key=False, frame=None):
    """Snap the weapon so the grip point lands on the hand IK bone.

    Default: position only -- the weapon orientation is preserved
    (plan §18). With ``align_orientation=True`` the weapon's full frame
    is matched to the hand's frame.

    Attached hands are re-glued in place afterwards (they must not chase
    the weapon here -- the hand IS the target). Never keys unless
    ``key=True`` (plan §31). Never moves the hand.
    Returns diagnostics dict.
    """
    hand = HAND_BONES[side]
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    _require_bone(armature, hand, "arp")

    if frame is None:
        frame = bpy.context.scene.frame_current

    lr, ll = _grip_offsets(armature)
    grip_local = lr if side == "R" else ll

    dg = transforms.evaluated_depsgraph()
    w_before = _world(armature, weapon, dg)
    h_target = _world(armature, hand, dg)
    hands_before = _capture_hands(armature, dg)

    # Rigid grip offset in weapon space: local = translation only (grip is
    # a point now, not a bone -- orientation comes from the weapon frame).
    if align_orientation:
        # Full 6-DOF: weapon frame == hand frame, positioned so the grip
        # point lands on the hand.
        w_new = h_target.copy()
        w_new.translation = (h_target.translation
                             - h_target.to_3x3() @ grip_local)
    else:
        # Position only: keep weapon rotation, shift translation so the
        # grip point lands on the hand.
        w_new = w_before.copy()
        w_new.translation = (h_target.translation
                             - w_before.to_3x3() @ grip_local)

    from ..animation import keyframes
    old_channels = keyframes.capture_channels(armature, weapon)
    _apply_weapon(armature, w_new)
    _preserve_hands(armature, hands_before)

    # --- verification (plan §30) ----------------------------------------
    grip_after = _world(armature, weapon) @ grip_local
    err = (grip_after - h_target.translation).length
    problems = []
    if err > TOL_TRANSLATION:
        problems.append("grip missed hand by %.6f" % err)
    if align_orientation:
        got = _world(armature, weapon)
        trans, rot = transforms.matrix_difference(got, h_target)
        # NOTE: translation differs by design (grip point, not origin, is
        # on the hand); only rotation must match.
        if rot > transforms.TOL_ROTATION_DEG:
            problems.append("weapon rotation off by %.4f deg" % rot)
    for sname, hb in (("R", HAND_BONES["R"]), ("L", HAND_BONES["L"])):
        now = _world(armature, hb)
        t_err = (now.translation - hands_before[sname].translation).length
        if t_err > TOL_TRANSLATION:
            problems.append("hand %s moved %.6f (must not)" % (sname, t_err))

    if problems:
        _apply_weapon(armature, w_before)  # rollback
        raise WeaponRigError(
            "Snap weapon -> %s failed: %s." % (hand, "; ".join(problems)))

    if key:
        _key_weapon(armature, frame, old_channels)

    return {
        "mode": "single",
        "side": side,
        "grip_error_r": err,
        "grip_error_l": 0.0,
        "keyed": bool(key),
        "warning": None,
    }


# ---------------------------------------------------------------------------
# Two-hand solver (plan §20, edge cases §55)
# ---------------------------------------------------------------------------

def snap_weapon_to_both(armature, key=False, frame=None):
    """Solve weapon_root from BOTH hand positions (plan §20).

    See module docstring for the full derivation. Returns diagnostics with
    both grip errors; ``warning`` is set for degenerate input or spacing
    mismatch. Attached hands are re-glued in place (never chase).
    """
    from ..utils import constraints as _con_resolve
    weapon = _con_resolve.get_weapon_bone(armature)
    for side in ("R", "L"):
        _require_bone(armature, HAND_BONES[side], "arp")

    if frame is None:
        frame = bpy.context.scene.frame_current

    lr, ll = _grip_offsets(armature)

    dg = transforms.evaluated_depsgraph()
    w_before = _world(armature, weapon, dg)
    hr = _world(armature, HAND_BONES["R"], dg)
    hl = _world(armature, HAND_BONES["L"], dg)
    hands_before = {"R": hr.copy(), "L": hl.copy()}

    d_local = ll - lr                       # grip vector, weapon local
    d_target = hl.translation - hr.translation  # hand vector, world

    if d_local.length < EPS_HAND_DISTANCE:
        raise WeaponRigError(
            "Both-hand solve failed: grip points coincide "
            "(weapon misconfigured).")

    # --- plan §55: degenerate hand distance -> fallback, no unstable math
    if d_target.length < EPS_HAND_DISTANCE:
        result = _fallback_right_hand_only(
            armature, hr, d_local, lr, w_before, hands_before, key, frame)
        result["warning"] = (
            "Hand distance %.6f is below epsilon -- two-hand orientation "
            "is ambiguous; used right-hand orientation + current weapon "
            "roll (plan §55 fallback)." % d_target.length)
        return result

    # --- step 3-5: rotation via explicit frames -------------------------
    # Weapon reference axis: weapon local X (blade flat), fallback Z/Y.
    f_local = _make_frame(d_local, Vector((1, 0, 0)), Vector((0, 0, 1)),
                          Vector((0, 1, 0)))
    # Right-hand roll reference: hand local X, fallback Z then Y (plan §20).
    f_target = _make_frame(d_target, Vector(hr.to_3x3().col[0]),
                           Vector(hr.to_3x3().col[2]),
                           Vector(hr.to_3x3().col[1]))
    if f_local is None or f_target is None:
        raise WeaponRigError(
            "Both-hand solve failed: degenerate weapon grip axis.")

    rot_new = f_target @ f_local.inverted()
    # --- step 6: translation anchors grip_r onto the right hand ---------
    w_new = Matrix.Translation(hr.translation - rot_new @ lr)
    w_new = w_new @ rot_new.to_4x4()

    from ..animation import keyframes
    old_channels = keyframes.capture_channels(armature, weapon)
    _apply_weapon(armature, w_new)
    _preserve_hands(armature, hands_before)

    # --- step 7: evaluate BOTH grip errors (plan §20 step 7) ------------
    w_after = _world(armature, weapon)
    gr_after = w_after.translation + w_after.to_3x3() @ lr
    gl_after = w_after.translation + w_after.to_3x3() @ ll
    err_r = (gr_after - hr.translation).length
    err_l = (gl_after - hl.translation).length
    spacing_gap = abs(d_target.length - d_local.length)

    problems = []
    if err_r > TOL_TRANSLATION:
        problems.append("grip_r missed right hand by %.6f" % err_r)
    # grip_l may miss by at most the rigid-spacing mismatch (plus tolerance).
    if err_l > spacing_gap + TOL_TRANSLATION:
        problems.append("grip_l error %.6f exceeds spacing gap %.6f"
                        % (err_l, spacing_gap))
    for sname, hb, hb_before in (
            ("R", HAND_BONES["R"], hands_before["R"]),
            ("L", HAND_BONES["L"], hands_before["L"])):
        now = _world(armature, hb)
        t_err = (now.translation - hb_before.translation).length
        if t_err > TOL_TRANSLATION:
            problems.append("hand %s moved %.6f (must not)"
                            % (sname, t_err))

    if problems:
        _apply_weapon(armature, w_before)  # rollback
        raise WeaponRigError(
            "Snap weapon -> both hands failed: %s."
            % "; ".join(problems))

    if key:
        _key_weapon(armature, frame, old_channels)

    warning = None
    if err_l > TOL_TRANSLATION:
        warning = (
            "Left grip off by %.4f: hand spacing (%.4f) differs from "
            "weapon grip spacing (%.4f) -- weapon is rigid, cannot match "
            "both positions exactly."
            % (err_l, d_target.length, d_local.length))

    return {
        "mode": "both",
        "grip_error_r": err_r,
        "grip_error_l": err_l,
        "keyed": bool(key),
        "warning": warning,
    }


# ---------------------------------------------------------------------------
# Home pose slots: record a relative pose, snap back to it later
# ---------------------------------------------------------------------------

def _home_prop_name(side):
    try:
        return HOME_PROP[side]
    except KeyError:
        raise WeaponRigError("Unknown hand side: %s." % side)


def has_home_pose(armature, side):
    """True when a home slot is stored for ``side`` (pure read)."""
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    wbone = armature.data.bones.get(weapon)
    return wbone is not None and _home_prop_name(side) in wbone


def record_home_pose(armature, side):
    """Store the weapon transform relative to the hand (H^-1 @ W).

    Arrange the weapon by hand first (any pose: angled in the palm,
    resting on fingers, ...) then record. Recall reproduces exactly this
    relative pose against the hand's pose at recall time. No keys, no
    animation touched -- pure data write. Returns diagnostics.
    """
    hand = HAND_BONES[side]
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    _require_bone(armature, hand, "arp")

    dg = transforms.evaluated_depsgraph()
    h_world = _world(armature, hand, dg)
    w_world = _world(armature, weapon, dg)
    rel = h_world.inverted() @ w_world
    wbone = armature.data.bones.get(weapon)
    if wbone is None:
        raise missing_weapon_bone(weapon)
    wbone[_home_prop_name(side)] = [float(v) for row in rel
                                     for v in row]
    return {"mode": "record", "side": side, "stored": True}


def _read_home_rel(armature, side):
    """Stored relative matrix or a loud error telling how to record it."""
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    wbone = armature.data.bones.get(weapon)
    prop = _home_prop_name(side)
    if wbone is None or prop not in wbone:
        raise WeaponRigError(
            "No home pose recorded for the %s hand. Arrange the weapon "
            "and press Record Home first."
            % ("right" if side == 'R' else "left"))
    try:
        vals = [float(v) for v in wbone[prop]]
    except Exception:
        vals = []
    if len(vals) != 16:
        raise WeaponRigError(
            "Home pose slot for the %s hand is corrupt (%d values, "
            "need 16). Re-record it."
            % (("right" if side == 'R' else "left"), len(vals)))
    return Matrix((vals[0:4], vals[4:8], vals[8:12], vals[12:16]))


def snap_weapon_to_home(armature, side, key=False, frame=None):
    """Return the weapon to its recorded home pose relative to the hand.

    Target = current hand world @ stored relative matrix: the exact
    recorded spatial relationship, reproduced against wherever the hand
    is now. Attached hands are re-glued in place (never chase), hands
    and hand animation are never touched. Rollback + loud error on any
    mismatch; keys only when ``key=True`` (plan §31).
    """
    hand = HAND_BONES[side]
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    _require_bone(armature, hand, "arp")
    rel = _read_home_rel(armature, side)

    if frame is None:
        frame = bpy.context.scene.frame_current

    dg = transforms.evaluated_depsgraph()
    w_before = _world(armature, weapon, dg)
    h_now = _world(armature, hand, dg)
    hands_before = _capture_hands(armature, dg)
    w_target = h_now @ rel

    from ..animation import keyframes
    old_channels = keyframes.capture_channels(armature, weapon)
    _apply_weapon(armature, w_target)
    _preserve_hands(armature, hands_before)

    # --- verification (plan §30) ----------------------------------------
    w_after = _world(armature, weapon)
    t_err, r_err = transforms.matrix_difference(w_after, w_target)
    problems = []
    if t_err > TOL_TRANSLATION:
        problems.append("weapon missed home pose by %.6f" % t_err)
    if r_err > transforms.TOL_ROTATION_DEG:
        problems.append("weapon rotation off home by %.4f deg" % r_err)
    for sname, hb in (("R", HAND_BONES["R"]),
                       ("L", HAND_BONES["L"])):
        now = _world(armature, hb)
        moved = (now.translation
                 - hands_before[sname].translation).length
        if moved > TOL_TRANSLATION:
            problems.append("hand %s moved %.6f (must not)"
                            % (sname, moved))

    if problems:
        _apply_weapon(armature, w_before)  # rollback
        raise WeaponRigError(
            "Snap weapon -> home pose (%s) failed: %s."
            % (hand, "; ".join(problems)))

    if key:
        _key_weapon(armature, frame, old_channels)

    return {
        "mode": "home",
        "side": side,
        "error_t": t_err,
        "error_r": r_err,
        "keyed": bool(key),
        "warning": None,
    }


def _fallback_right_hand_only(armature, hr, d_local, lr, w_before,
                              hands_before, key, frame):
    """plan §55 fallback: right-hand orientation + current weapon roll.

    Position: grip_r anchored to the right hand. Orientation: minimal-arc
    (geodesic) rotation aligning the weapon's blade axis (weapon -> tip
    point) to the right hand's aim (bone local Y). A minimal rotation
    changes no twist about the aligned axis, which is exactly "keep the
    current roll". Never returns an unstable quaternion: rotation_difference
    is only used between two non-coincident, normalized directions and the
    blade axis is checked for degeneracy first. Attached hands re-glued.
    """
    from ..utils import constraints as con_util
    tip_local = con_util.tip_offset(armature)
    blade = (w_before.to_3x3() @ (tip_local - lr)).copy()
    # Note: blade direction from grip_r toward tip, in world.
    if blade.length < EPS_HAND_DISTANCE:
        raise WeaponRigError(
            "Snap fallback failed: tip coincides with grip_r.")
    blade.normalize()
    aim = Vector(hr.to_3x3().col[1])  # hand bone direction (local Y)
    if aim.length < EPS_HAND_DISTANCE:
        raise WeaponRigError(
            "Snap fallback failed: right hand aim axis is degenerate.")
    aim.normalize()

    rot_delta = blade.rotation_difference(aim)  # minimal arc, no added roll
    rot_new = rot_delta.to_matrix() @ w_before.to_3x3()
    w_new = Matrix.Translation(hr.translation - rot_new @ lr)
    w_new = w_new @ rot_new.to_4x4()

    from ..animation import keyframes
    from ..utils import constraints as _con_fb
    _fb_weapon = _con_fb.get_weapon_bone(armature)
    old_channels = keyframes.capture_channels(armature, _fb_weapon)
    _apply_weapon(armature, w_new)
    _preserve_hands(armature, hands_before)

    w_after = _world(armature, _fb_weapon)
    gr_after = w_after.translation + w_after.to_3x3() @ lr
    err = (gr_after - hr.translation).length
    if err > TOL_TRANSLATION:
        _apply_weapon(armature, w_before)
        raise WeaponRigError(
            "Snap fallback failed: grip_r missed right hand by %.6f." % err)

    if key:
        _key_weapon(armature, frame, old_channels)

    return {
        "mode": "fallback",
        "grip_error_r": err,
        "grip_error_l": float("inf"),
        "keyed": bool(key),
        "warning": None,  # set by caller
    }




# ---------------------------------------------------------------------------
# Hand -> weapon direction (+ hand home slots)
#
# Mirror of the weapon snaps: the WEAPON stays frozen, the detached hand
# travels onto the grip. Refuses attached hands loudly (moving one would
# fight its Child Of). Hand IK solvers are frozen for the write exactly
# like in attach (plan §53 lesson): if the solver disagrees with the
# target, verification catches it instead of a silent pop.
# ---------------------------------------------------------------------------

HAND_HOME_PROP = {"R": "hand_home_r", "L": "hand_home_l"}


def _apply_hand(armature, side, world_matrix):
    """Write a hand bone's world matrix via the pose-matrix setter."""
    arm_space = armature.matrix_world.inverted() @ world_matrix
    transforms.set_pose_bone_arm_matrix(
        armature, HAND_BONES[side], arm_space)
    transforms.update_view_layer()


def _freeze_hand_ik(armature, side):
    """Disable IK solvers on the hand; returns [(constraint, was_active)]."""
    pbone = armature.pose.bones[HAND_BONES[side]]
    saved = [(c, c.active) for c in pbone.constraints if c.type == 'IK']
    for c, _old in saved:
        c.active = False
    return saved


def _restore_hand_ik(saved):
    for c, old in saved:
        c.active = old


def _require_detached(armature, side):
    """Hands glued by Child Of must not be posed by hand-snap."""
    from ..utils import constraints as con_util
    con = con_util.find_attach_constraint(armature, side)
    if con is not None and con.influence > 0.0:
        raise WeaponRigError(
            "Hand %s is attached (influence %.2f) -- Detach it first, "
            "then snap the hand to the weapon." % (side, con.influence))


def _move_hand(armature, side, h_target, key, frame, label):
    """Shared hand-move pipeline: freeze IK, write, verify, rollback, key."""
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    other = "L" if side == "R" else "R"

    dg = transforms.evaluated_depsgraph()
    h_before = _world(armature, HAND_BONES[side], dg)
    w_before = _world(armature, weapon, dg)
    other_before = _world(armature, HAND_BONES[other], dg)

    frozen = _freeze_hand_ik(armature, side)
    try:
        from ..animation import keyframes
        old_channels = keyframes.capture_channels(
            armature, HAND_BONES[side])
        _apply_hand(armature, side, h_target)
    finally:
        _restore_hand_ik(frozen)
    transforms.update_view_layer()

    h_after = _world(armature, HAND_BONES[side])
    t_err, r_err = transforms.matrix_difference(h_after, h_target)
    w_after = _world(armature, weapon)
    wt_err, wr_err = transforms.matrix_difference(w_after, w_before)
    o_after = _world(armature, HAND_BONES[other])
    o_err = (o_after.translation - other_before.translation).length
    problems = []
    if t_err > TOL_TRANSLATION:
        problems.append("hand missed target by %.6f" % t_err)
    if r_err > transforms.TOL_ROTATION_DEG:
        problems.append("hand rotation off by %.4f deg" % r_err)
    if wt_err > TOL_TRANSLATION or wr_err > transforms.TOL_ROTATION_DEG:
        problems.append("weapon moved (must not)")
    if o_err > TOL_TRANSLATION:
        problems.append("other hand moved %.6f (must not)" % o_err)

    if problems:
        frozen = _freeze_hand_ik(armature, side)
        try:
            _apply_hand(armature, side, h_before)
        finally:
            _restore_hand_ik(frozen)
        transforms.update_view_layer()
        raise WeaponRigError(
            "Snap hand -> weapon (%s) failed: %s."
            % (label, "; ".join(problems)))

    if key:
        from ..animation import keyframes as _kf
        _kf.key_changed_channels(armature, HAND_BONES[side], frame,
                                 old_channels)

    return {
        "mode": label,
        "side": side,
        "error_t": t_err,
        "error_r": r_err,
        "keyed": bool(key),
        "warning": None,
    }


def snap_hand_to_weapon(armature, side, align_orientation=False,
                        key=False, frame=None):
    """Move the detached hand onto the weapon's grip point.

    Default: position only, hand orientation preserved. With
    ``align_orientation=True`` the hand frame matches the weapon frame.
    The weapon, the other hand and all animation are untouched; keys only
    when ``key=True`` (plan §31).
    """
    hand = HAND_BONES[side]
    from ..utils import constraints as con_util
    con_util.get_weapon_bone(armature)
    _require_bone(armature, hand, "arp")
    _require_detached(armature, side)

    if frame is None:
        frame = bpy.context.scene.frame_current

    dg = transforms.evaluated_depsgraph()
    h_before = _world(armature, hand, dg)
    grip = con_util.grip_world(armature, side)
    if align_orientation:
        w_now = _world(armature, con_util.get_weapon_bone(armature), dg)
        h_target = w_now.copy()
        h_target.translation = grip.translation.copy()
    else:
        h_target = h_before.copy()
        h_target.translation = grip.translation.copy()

    return _move_hand(armature, side, h_target, key, frame, "hand")


def _hand_home_prop_name(side):
    try:
        return HAND_HOME_PROP[side]
    except KeyError:
        raise WeaponRigError("Unknown hand side: %s." % side)


def has_hand_home(armature, side):
    """True when a hand home slot is stored for ``side`` (pure read)."""
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    wbone = armature.data.bones.get(weapon)
    return wbone is not None and _hand_home_prop_name(side) in wbone


def record_hand_home(armature, side):
    """Store the hand transform relative to the grip (G^-1 @ H).

    Arrange the hand by hand first, then record. Recall reproduces exactly
    this relative pose against the grip's pose at recall time. No keys, no
    animation touched -- pure data write.
    """
    hand = HAND_BONES[side]
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    _require_bone(armature, hand, "arp")

    dg = transforms.evaluated_depsgraph()
    grip = con_util.grip_world(armature, side)
    h_world = _world(armature, hand, dg)
    rel = grip.inverted() @ h_world
    wbone = armature.data.bones.get(weapon)
    if wbone is None:
        raise missing_weapon_bone(weapon)
    wbone[_hand_home_prop_name(side)] = [float(v) for row in rel
                                         for v in row]
    return {"mode": "record-hand", "side": side, "stored": True}


def _read_hand_home_rel(armature, side):
    from ..utils import constraints as con_util
    weapon = con_util.get_weapon_bone(armature)
    wbone = armature.data.bones.get(weapon)
    prop = _hand_home_prop_name(side)
    if wbone is None or prop not in wbone:
        raise WeaponRigError(
            "No hand home pose recorded for the %s hand. Arrange the "
            "hand and press Record Hand first."
            % ("right" if side == 'R' else "left"))
    try:
        vals = [float(v) for v in wbone[prop]]
    except Exception:
        vals = []
    if len(vals) != 16:
        raise WeaponRigError(
            "Hand home slot for the %s hand is corrupt (%d values, need "
            "16). Re-record it."
            % (("right" if side == 'R' else "left"), len(vals)))
    return Matrix((vals[0:4], vals[4:8], vals[8:12], vals[12:16]))


def snap_hand_to_home(armature, side, key=False, frame=None):
    """Return the hand to its recorded home pose relative to the grip.

    Target = current grip frame @ stored relative matrix. Attached hands
    are refused (detach first); weapon, other hand and animation are
    untouched; rollback + loud error on mismatch; keys only with key=True.
    """
    hand = HAND_BONES[side]
    from ..utils import constraints as con_util
    con_util.get_weapon_bone(armature)
    _require_bone(armature, hand, "arp")
    _require_detached(armature, side)
    rel = _read_hand_home_rel(armature, side)

    if frame is None:
        frame = bpy.context.scene.frame_current

    grip = con_util.grip_world(armature, side)
    return _move_hand(armature, side, grip @ rel, key, frame, "hand-home")
